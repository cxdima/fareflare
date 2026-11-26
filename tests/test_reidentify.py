import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from fareflare.contracts import CollectionFailure, Reading
from fareflare.domain import AlertPolicy
from fareflare.links import import_link
from fareflare.reidentify import MOVED, apply, main, plan_changes, restore
from fareflare.service import BLOCKED, COLLECTING, EXPIRED, MonitoringService
from fareflare.store import Document, SQLiteStore

FIXTURES = Path(__file__).parent / "fixtures"


def older_importer(url):
    """Read a link the way an older release did: click tracking was part of a target."""
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
    """The service as an older release stored targets, with a capacity to keep in step."""
    return MonitoringService(
        store, lambda: clock[0], link_importer=older_importer, global_target_limit=20
    )


def now_service(store, clock):
    return MonitoringService(store, lambda: clock[0], global_target_limit=20)


def pause(store):
    store.commit([Document("configuration:admin", "configuration", {"collection_paused": True})])


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


def snapshot(store, keys):
    return {key: (doc.partition, doc.data) if (doc := store.get(key)) else None for key in keys}


def run(store, clock, tmp_path, name="before.jsonl"):
    changes = []
    apply(store, plan_changes(store, clock[0]), tmp_path / name, changes.append)
    return changes


def test_a_target_moves_with_every_monitor_its_history_and_its_requests(
    before, store, clock, flight_url, tmp_path
):
    alice = watched(
        before, clock, "alice", flight_url + "&sa=X&ved=abc", "alice-request", (30000, 29000)
    )
    old, new = alice["target_id"], import_link(flight_url)["id"]
    bob = before.create_monitor("bob", flight_url + "&sa=X&ved=abc", "bob-request-1")
    before.set_status("bob", bob["id"], "cancelled")
    carol = before.create_monitor("carol", flight_url + "&sa=X&ved=abc", "carol-request")
    before.set_policy("carol", carol["id"], AlertPolicy(kind="below_price", threshold_minor=1))
    before.process_events()

    plan = [plan.change for plan in plan_changes(store, clock[0])]
    assert [(c.target, c.outcome, c.to, c.monitors, c.history, c.requests) for c in plan] == [
        (old, "moved", new, 3, 2, 2)
    ]
    # Carol changed her rule after creating the monitor: her request cannot be rebuilt.
    assert len(plan[0].unmatched_requests) == 1
    assert store.get("target:" + new) is None  # A plan writes nothing.

    with pytest.raises(ValueError, match="Pause price checks"):
        run(store, clock, tmp_path)
    assert not (tmp_path / "before.jsonl").exists()
    pause(store)
    assert [c.outcome for c in run(store, clock, tmp_path)] == ["moved"]

    service = now_service(store, clock)
    for tenant, monitor in (("alice", alice), ("bob", bob), ("carol", carol)):
        view = service.get_monitor(tenant, monitor["id"])
        assert view["target_id"] == new and view["target"] == import_link(flight_url)
    assert service.get_monitor("bob", bob["id"])["status"] == "cancelled"
    assert [entry["amount_minor"] for entry in service.history("alice", alice["id"])] == [
        30000,
        29000,
    ]
    assert len(service.monitors_page("bob")["items"]) == 1
    assert store.get("capacity:collection").data["targets"] == [new]
    tombstone = store.get("target:" + old)
    assert tombstone.partition == MOVED and tombstone.data == {"moved_to": new}
    # A retried create request is recognized where it can be rebuilt.
    assert service.create_monitor("alice", flight_url, "alice-request")["id"] == alice["id"]
    assert {c.outcome for c in [p.change for p in plan_changes(store, clock[0])]} == {"unchanged"}


def test_an_expired_target_and_its_monitors_move_too(before, store, clock, flight_url, tmp_path):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    clock[0] = int(datetime(2027, 3, 16, tzinfo=UTC).timestamp())
    before.collect_due(Mock())
    old = monitor["target_id"]
    assert store.get("target:" + old).partition == EXPIRED
    pause(store)
    assert [c.outcome for c in run(store, clock, tmp_path)] == ["moved"]
    new = import_link(flight_url)["id"]
    view = now_service(store, clock).get_monitor("alice", monitor["id"])
    assert (view["status"], view["target_id"]) == ("expired", new)
    assert store.get("target:" + new).partition == EXPIRED


def test_a_target_is_busy_while_held_or_while_a_watcher_waits_for_an_alert(
    before, store, clock, flight_url, tmp_path
):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    target = store.get("target:" + monitor["target_id"])
    store.commit([target.update({**target.data, "lease_until": clock[0] + 60})])
    pause(store)
    assert [c.outcome for c in run(store, clock, tmp_path, "1.jsonl")] == ["busy"]
    clock[0] += 120
    before.record(Reading(monitor["target_id"], 28000, "USD", clock[0], "test-fixture"), "unsent")
    assert [c.outcome for c in run(store, clock, tmp_path, "2.jsonl")] == ["busy"]
    before.process_events()
    assert [c.outcome for c in run(store, clock, tmp_path, "3.jsonl")] == ["moved"]


def test_twins_become_one_target_and_the_plan_says_so_first(
    before, store, clock, flight_url, tmp_path
):
    first = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    second = watched(before, clock, "bob", flight_url + "&sa=Y", "bob-request", (31000, 30500))
    new = import_link(flight_url)["id"]
    assert [plan.change.outcome for plan in plan_changes(store, clock[0])] == ["moved", "merged"]
    pause(store)
    assert sorted(c.outcome for c in run(store, clock, tmp_path)) == ["merged", "moved"]
    target = store.get("target:" + new)
    assert sorted(target.data["subscribers"]) == sorted([first["id"], second["id"]])
    assert target.data["latest"]["amount_minor"] == 30500  # The newer of the two prices.
    assert target.data["sequence"] == 2 and target.partition == COLLECTING
    service = now_service(store, clock)
    for tenant, monitor in (("alice", first), ("bob", second)):
        # Neither watcher is sent the other's past alerts.
        assert service.get_monitor(tenant, monitor["id"])["last_sequence"] == 2
    assert store.get("capacity:collection").data["targets"] == [new]


def test_a_blocked_twin_keeps_its_watchers_able_to_retry(
    before, store, clock, flight_url, tmp_path
):
    idle = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    before.set_status("alice", idle["id"], "paused")
    blocked = watched(before, clock, "bob", flight_url + "&sa=Y", "bob-request")
    provider = Mock()
    provider.collect.side_effect = CollectionFailure("unsupported_itinerary")
    clock[0] += 3600
    before.collect_due(provider)
    targets = {store.get("target:" + m["target_id"]).partition for m in (idle, blocked)}
    assert BLOCKED in targets
    pause(store)
    run(store, clock, tmp_path)
    merged = store.get("target:" + import_link(flight_url)["id"])
    # Bob still watches it and can choose Retry collection: it is not left idle.
    assert merged.partition == BLOCKED and merged.data["last_error"] == "unsupported_itinerary"
    assert now_service(store, clock).get_monitor("bob", blocked["id"])["collection_status"] == (
        "blocked"
    )


def test_a_run_is_undone_exactly_from_what_it_saved(before, store, clock, flight_url, tmp_path):
    first = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request", (30000, 29000))
    second = watched(before, clock, "bob", flight_url + "&sa=Y", "bob-request")
    keys = [
        "target:" + first["target_id"],
        "target:" + second["target_id"],
        "target:" + import_link(flight_url)["id"],
        "monitor:" + first["id"],
        "monitor:" + second["id"],
        "capacity:collection",
        *(doc.key for doc in store.page("history:" + first["target_id"], limit=10).items),
    ]
    original = snapshot(store, keys)
    history = [doc.key for doc in store.page("history:" + first["target_id"], limit=10).items]
    pause(store)
    run(store, clock, tmp_path)
    assert snapshot(store, keys) != original
    assert restore(store, tmp_path / "before.jsonl") > 0
    assert snapshot(store, keys) == original
    assert store.get("target:" + import_link(flight_url)["id"]) is None  # Removed, not emptied.
    assert [doc.key for doc in store.page("history:" + first["target_id"], limit=10).items] == (
        history
    )


def test_a_target_changed_underneath_the_run_is_a_conflict_and_the_rest_continue(
    before, store, clock, flight_url, tmp_path
):
    other = json.loads((FIXTURES / "selected_jpy.json").read_text())["page"]["url"]
    first = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    second = before.create_monitor("bob", other + "&ved=Z", "bob-request")
    plans = plan_changes(store, clock[0])
    # Someone pauses Alice's monitor between the plan and its write.
    before.set_status("alice", first["id"], "paused")
    pause(store)
    changes = []
    apply(store, plans, tmp_path / "before.jsonl", changes.append)
    outcomes = {change.target: change.outcome for change in changes}
    assert outcomes == {first["target_id"]: "conflict", second["target_id"]: "moved"}
    # The capacity record swaps only the reservation that moved.
    reserved = store.get("capacity:collection").data["targets"]
    assert first["target_id"] in reserved and import_link(other)["id"] in reserved


def test_the_command_plans_by_default_and_reports_problems_by_its_status(
    tmp_path, clock, capsys, flight_url
):
    database = tmp_path / "local.sqlite3"
    store = SQLiteStore(database)
    service = MonitoringService(store, lambda: clock[0], link_importer=older_importer)
    monitor = service.create_monitor("alice", flight_url + "&ved=abc", "alice-request")
    assert main(["--database", str(database)]) == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["outcome"] for line in printed] == ["moved"]
    assert list(tmp_path.iterdir()) == [database]  # A plan saves nothing either.
    saved = tmp_path / "before.jsonl"
    assert main(["--database", str(database), "--apply", str(saved)]) == 2  # Not paused.
    pause(store)
    assert main(["--database", str(database), "--apply", str(saved)]) == 0
    assert store.get("target:" + monitor["target_id"]).partition == MOVED
    assert main(["--database", str(database), "--apply", str(saved)]) == 2  # Never overwrites.
    # A link that no longer imports is reported with its check, and the status says so.
    target = store.get("target:" + import_link(flight_url)["id"])
    spec = {**target.data["spec"], "url": "https://example.com/"}
    store.commit([target.update({**target.data, "spec": spec})])
    capsys.readouterr()
    assert main(["--database", str(database)]) == 1
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(line["outcome"], line["check"]) for line in printed] == [("unreadable", "not_google")]
    with pytest.raises(SystemExit):
        main(["--database", str(tmp_path / "missing.sqlite3")])
