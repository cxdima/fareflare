import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from fareflare.contracts import Reading
from fareflare.links import import_link
from fareflare.reidentify import MOVED, main, reidentify
from fareflare.service import COLLECTING, MonitoringService
from fareflare.store import SQLiteStore


def older_importer(url):
    """Read a link the way the previous release did: click tracking was kept."""
    target = import_link(url)
    tracking = {k: v for k, v in parse_qsl(urlsplit(url).query) if k in ("sa", "ved", "utm_x")}
    query = dict(sorted({**target["provider_query"], **tracking}.items()))
    identity = {k: v for k, v in query.items() if not k.startswith("utm_")}
    return {
        **target,
        "provider_query": query,
        "url": "https://www.google.com/travel/flights/booking?" + urlencode(query),
        "id": target["id"]
        if identity == target["provider_query"]
        else hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
    }


@pytest.fixture
def before(store, clock):
    """The service as it stored targets before, with a global capacity to keep in step."""
    return MonitoringService(
        store, lambda: clock[0], link_importer=older_importer, global_target_limit=20
    )


def watched(service, clock, tenant, url, key, prices=(30000,)):
    monitor = service.create_monitor(tenant, url, key)
    for number, amount in enumerate(prices):
        clock[0] += 60
        service.record(
            Reading(monitor["target_id"], amount, "USD", clock[0], "test-fixture"),
            f"{key}-{number}",
        )
    service.process_events()
    return monitor


def test_a_target_moves_to_its_new_identity_with_everything_that_names_it(
    before, store, clock, flight_url
):
    monitor = watched(
        before, clock, "alice", flight_url + "&sa=X&ved=abc", "alice-request", (30000, 29000)
    )
    old = monitor["target_id"]
    new = import_link(flight_url)["id"]
    assert old != new

    plan = reidentify(store, now=clock[0])
    assert [(c.target, c.outcome, c.to, c.watchers, c.history) for c in plan] == [
        (old, "moved", new, 1, 2)
    ]
    assert store.get("target:" + new) is None  # A plan writes nothing.

    reidentify(store, apply=True, now=clock[0])
    service = MonitoringService(store, lambda: clock[0], global_target_limit=20)
    moved = service.get_monitor("alice", monitor["id"])
    assert moved["target_id"] == new and moved["target"] == import_link(flight_url)
    assert moved["latest"]["target_id"] == new and moved["latest"]["amount_minor"] == 29000
    assert [entry["amount_minor"] for entry in service.history("alice", monitor["id"])] == [
        30000,
        29000,
    ]
    assert store.get("capacity:collection").data["targets"] == [new]
    tombstone = store.get("target:" + old)
    assert tombstone.partition == MOVED and tombstone.data == {"moved_to": new}
    assert tombstone.expires_at is not None
    assert store.get("target:" + new).partition == COLLECTING
    # The next check finds the target where the link now leads.
    assert service.accept_link(moved["target"]["url"])["id"] == new
    assert {c.outcome for c in reidentify(store, apply=True, now=clock[0])} == {"unchanged"}


def test_two_stored_links_of_one_flight_become_one_target(before, store, clock, flight_url):
    first = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    second = watched(before, clock, "bob", flight_url + "&sa=Y", "bob-request", (31000, 30500))
    assert first["target_id"] != second["target_id"]
    changes = reidentify(store, apply=True, now=clock[0])
    assert sorted(c.outcome for c in changes) == ["merged", "moved"]
    new = import_link(flight_url)["id"]
    target = store.get("target:" + new)
    assert sorted(target.data["subscribers"]) == sorted([first["id"], second["id"]])
    service = MonitoringService(store, lambda: clock[0], global_target_limit=20)
    for tenant, monitor in (("alice", first), ("bob", second)):
        view = service.get_monitor(tenant, monitor["id"])
        assert view["target_id"] == new
        # Neither watcher is sent the other's past alerts.
        assert view["last_sequence"] == target.data["sequence"]
    assert len(service.history("bob", second["id"])) == 3
    assert store.get("capacity:collection").data["targets"] == [new]


def test_a_changed_address_with_the_same_identity_is_rewritten_in_place(
    before, store, clock, flight_url
):
    monitor = watched(before, clock, "alice", flight_url + "&utm_x=campaign", "alice-request")
    stored = store.get("target:" + monitor["target_id"])
    assert "utm_x" in stored.data["spec"]["url"]
    changes = reidentify(store, apply=True, now=clock[0])
    assert [(c.outcome, c.to) for c in changes] == [("rewritten", monitor["target_id"])]
    assert store.get("target:" + monitor["target_id"]).data["spec"] == import_link(flight_url)


def test_a_target_a_check_holds_or_with_an_alert_waiting_waits_for_a_later_run(
    before, store, clock, flight_url
):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    target = store.get("target:" + monitor["target_id"])
    store.commit([target.update({**target.data, "lease_until": clock[0] + 60})])
    assert [c.outcome for c in reidentify(store, apply=True, now=clock[0])] == ["busy"]
    clock[0] += 120
    before.record(
        Reading(monitor["target_id"], 28000, "USD", clock[0], "test-fixture"), "unsent", None
    )
    assert [c.outcome for c in reidentify(store, apply=True, now=clock[0])] == ["busy"]
    before.process_events()
    assert [c.outcome for c in reidentify(store, apply=True, now=clock[0])] == ["moved"]


def test_a_run_that_stopped_part_way_finishes_moving_the_history(before, store, clock, flight_url):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request", (30000, 29500))
    old = monitor["target_id"]
    straggler = store.page("history:" + old, limit=1).items[0]
    reidentify(store, apply=True, now=clock[0])
    new = import_link(flight_url)["id"]
    # As if the run had stopped before this observation moved.
    moved = store.get(straggler.key)
    store.commit([moved.update({**moved.data, "target_id": old}, partition="history:" + old)])
    resumed = reidentify(store, apply=True, now=clock[0])
    assert [(c.target, c.outcome, c.to, c.history) for c in resumed[:1]] == [(old, "moved", new, 1)]
    assert store.page("history:" + old, limit=10).items == []
    assert len(store.page("history:" + new, limit=10).items) == 2


def test_a_target_whose_link_no_longer_imports_is_reported_and_left_alone(store, clock, flight_url):
    service = MonitoringService(store, lambda: clock[0])
    monitor = service.create_monitor("alice", flight_url, "alice-request")
    target = store.get("target:" + monitor["target_id"])
    spec = {**target.data["spec"], "url": "https://example.com/"}
    store.commit([target.update({**target.data, "spec": spec})])
    assert [c.outcome for c in reidentify(store, apply=True, now=clock[0])] == ["unreadable"]
    assert store.get("target:" + monitor["target_id"]).data["spec"] == spec


def test_the_command_plans_by_default_and_applies_only_when_asked(
    tmp_path, clock, capsys, flight_url
):
    database = tmp_path / "local.sqlite3"
    store = SQLiteStore(database)
    service = MonitoringService(store, lambda: clock[0], link_importer=older_importer)
    monitor = service.create_monitor("alice", flight_url + "&ved=abc", "alice-request")
    main(["--database", str(database)])
    assert json.loads(capsys.readouterr().out)["outcome"] == "moved"
    assert store.get("target:" + monitor["target_id"]).partition == COLLECTING
    main(["--database", str(database), "--apply"])
    assert store.get("target:" + monitor["target_id"]).partition == MOVED
    with pytest.raises(SystemExit):
        main(["--database", str(tmp_path / "missing.sqlite3")])
