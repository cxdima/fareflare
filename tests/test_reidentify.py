import hashlib
import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from fareflare.contracts import CollectionFailure, Reading
from fareflare.domain import AlertPolicy
from fareflare.links import import_link
from fareflare.reidentify import (
    MOVED,
    NotReady,
    Skipped,
    apply,
    main,
    plan_changes,
    restore,
)
from fareflare.service import BLOCKED, COLLECTING, EXPIRED, IDLE, MonitoringService
from fareflare.store import Conflict, Document, SQLiteStore

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

    with pytest.raises(NotReady, match="Pause price checks"):
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


def test_a_twin_blocked_as_unreadable_is_checked_again_once_its_link_reads(
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
    changes = run(store, clock, tmp_path)
    assert any(change.unblocked for change in changes)
    merged = store.get("target:" + import_link(flight_url)["id"])
    # These rules read its link, so it is checked again for Bob, who still watches it.
    assert merged.partition == COLLECTING and merged.data["last_error"] is None
    assert now_service(store, clock).get_monitor("bob", blocked["id"])["collection_status"] == (
        "ready"
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
    assert restore(store, tmp_path / "before.jsonl") == (2, [])
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


def test_the_command_says_by_its_status_whether_anything_is_left_to_write(
    tmp_path, clock, capsys, flight_url, monkeypatch
):
    database = tmp_path / "local.sqlite3"
    store = SQLiteStore(database)
    service = MonitoringService(store, lambda: clock[0], link_importer=older_importer)
    monitor = service.create_monitor("alice", flight_url + "&ved=abc", "alice-request")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("fareflare.reidentify.time.time", lambda: clock[0])
    run = ["--database", str(database)]
    assert main(run) == 3  # Changes are pending.
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["outcome"] for line in printed] == ["moved"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["local.sqlite3"]  # Saves nothing.
    assert main([*run, "--apply", "abc1234"]) == 2  # Checks are not paused.
    pause(store)
    assert main([*run, "--apply", "abc1234"]) == 0
    saved = next((tmp_path / ".fareflare/release-abc1234/reidentify").iterdir())
    assert stat.S_IMODE(saved.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert store.get("target:" + monitor["target_id"]).partition == MOVED
    assert main([*run, "--apply", "abc1234"]) == 2  # The same second's file is never overwritten.
    assert main(run) == 0  # Done: nothing left to write.
    # A collected flight whose link the rules now refuse is stopped as unreadable: a
    # finished state, so the plan is done afterwards.
    target = store.get("target:" + import_link(flight_url)["id"])
    spec = {**target.data["spec"], "url": "https://example.com/"}
    store.commit([target.update({**target.data, "spec": spec})])
    assert main(run) == 3
    clock[0] += 1
    capsys.readouterr()
    assert main([*run, "--apply", "abc1234"]) == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(line["outcome"], line["check"]) for line in printed] == [("blocked", "not_google")]
    blocked = store.get(target.key)
    assert (blocked.partition, blocked.data["last_error"]) == (BLOCKED, "unsupported_itinerary")
    assert main(run) == 0
    with pytest.raises(SystemExit):
        main(["--database", str(tmp_path / "missing.sqlite3")])


class _Flaky:
    """A store whose first main commit fails in a given way, after or instead of writing."""

    def __init__(self, store, failure, *, applies):
        self.store, self.failure, self.applies, self.failed = store, failure, applies, False

    def __getattr__(self, name):
        return getattr(self.store, name)

    def commit(self, documents):
        if not self.failed and any(doc.key.startswith("monitor:") for doc in documents):
            self.failed = True
            if self.applies:
                self.store.commit(documents)
            raise self.failure
        self.store.commit(documents)


def test_a_commit_that_raised_after_writing_is_still_undone(
    before, store, clock, flight_url, tmp_path
):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    keys = ["target:" + monitor["target_id"], "monitor:" + monitor["id"], "capacity:collection"]
    original = snapshot(store, keys)
    pause(store)
    flaky = _Flaky(store, Conflict("lost the answer"), applies=True)
    changes = []
    apply(flaky, plan_changes(store, clock[0]), tmp_path / "before.jsonl", changes.append)
    assert [c.outcome for c in changes] == ["conflict"]
    assert store.get("target:" + monitor["target_id"]).partition == MOVED  # It did apply.
    assert restore(store, tmp_path / "before.jsonl") == (1, [])
    assert snapshot(store, keys) == original


def test_a_failed_target_is_reported_and_the_run_goes_on(
    before, store, clock, flight_url, tmp_path
):
    other = json.loads((FIXTURES / "selected_jpy.json").read_text())["page"]["url"]
    watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    before.create_monitor("bob", other + "&ved=Z", "bob-request")
    pause(store)
    changes = []
    flaky = _Flaky(store, RuntimeError("secret detail"), applies=False)
    apply(flaky, plan_changes(store, clock[0]), tmp_path / "before.jsonl", changes.append)
    assert sorted(c.outcome for c in changes) == ["failed", "moved"]
    failed = next(c for c in changes if c.outcome == "failed")
    assert failed.error.startswith("RuntimeError") and "secret" not in failed.error


def test_a_target_changed_after_the_run_is_listed_and_left_alone(
    before, store, clock, flight_url, tmp_path
):
    watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    pause(store)
    run(store, clock, tmp_path)
    service = now_service(store, clock)
    # After the run, someone watches the moved flight and someone adds another flight.
    later = service.create_monitor("bob", flight_url, "bob-request")
    other = json.loads((FIXTURES / "selected_jpy.json").read_text())["page"]["url"]
    service.create_monitor("carol", other, "carol-request")
    restored, skipped = restore(store, tmp_path / "before.jsonl")
    new = import_link(flight_url)["id"]
    assert restored == 0
    assert Skipped("target:" + new, "changed since the run") in skipped
    # Bob's monitor still has its flight, and every reservation is kept.
    assert service.get_monitor("bob", later["id"])["target_id"] == import_link(flight_url)["id"]
    assert len(store.get("capacity:collection").data["targets"]) == 2


def test_restoring_needs_paused_checks_and_a_private_file_of_known_documents(
    before, store, clock, flight_url, tmp_path
):
    watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    pause(store)
    saved = tmp_path / "runs" / "before.jsonl"
    run(store, clock, tmp_path, "runs/before.jsonl")
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert stat.S_IMODE(saved.parent.stat().st_mode) == 0o700
    switch = store.get("configuration:admin")
    store.commit([switch.update({"collection_paused": False})])
    with pytest.raises(NotReady, match="Pause"):
        restore(store, saved)
    pause_again = store.get("configuration:admin")
    store.commit([pause_again.update({"collection_paused": True})])
    saved.chmod(0o644)
    with pytest.raises(NotReady, match="0600"):
        restore(store, saved)
    saved.chmod(0o600)
    with saved.open("a") as tampered:
        tampered.write(
            json.dumps({"target": "x", "key": "account:acct_x", "before": None, "after": 1}) + "\n"
        )
    with pytest.raises(NotReady, match="never writes"):
        restore(store, saved)


def test_a_watcher_that_cannot_be_read_stops_its_target_from_moving(
    before, store, clock, flight_url
):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    target = store.get("target:" + monitor["target_id"])
    subscribers = [*target.data["subscribers"], "f" * 32]
    store.commit([target.update({**target.data, "subscribers": subscribers})])
    assert [p.change.outcome for p in plan_changes(store, clock[0])] == ["missing_monitor"]


def test_a_suspended_accounts_watcher_does_not_keep_its_flight_busy(
    before, store, clock, flight_url, tmp_path
):
    tenant = "acct_" + "a" * 32
    store.commit([Document("account:" + tenant, "accounts", {"id": tenant, "status": "active"})])
    monitor = watched(before, clock, tenant, flight_url + "&sa=X", "alice-request")
    clock[0] += 60
    before.record(Reading(monitor["target_id"], 28000, "USD", clock[0], "test-fixture"), "unsent")
    account = store.get("account:" + tenant)
    store.commit([account.update({**account.data, "status": "suspended"})])
    # Its alert will never be sent, so it must not hold the move back for ever.
    assert [p.change.outcome for p in plan_changes(store, clock[0])] == ["moved"]


def test_an_address_that_changed_alone_is_rewritten_in_place(
    before, store, clock, flight_url, tmp_path
):
    monitor = watched(before, clock, "alice", flight_url + "&utm_x=campaign", "alice-request")
    assert "utm_x" in store.get("target:" + monitor["target_id"]).data["spec"]["url"]
    pause(store)
    assert [(c.outcome, c.to) for c in run(store, clock, tmp_path)] == [
        ("rewritten", monitor["target_id"])
    ]
    assert store.get("target:" + monitor["target_id"]).data["spec"] == import_link(flight_url)


def test_a_run_that_stopped_part_way_finishes_moving_the_history(
    before, store, clock, flight_url, tmp_path
):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request", (30000, 29500))
    old = monitor["target_id"]
    straggler = store.page("history:" + old, limit=1).items[0]
    pause(store)
    run(store, clock, tmp_path, "first.jsonl")
    new = import_link(flight_url)["id"]
    # As if the run had stopped before this observation moved.
    moved = store.get(straggler.key)
    store.commit([moved.update({**moved.data, "target_id": old}, partition="history:" + old)])
    resumed = run(store, clock, tmp_path, "second.jsonl")
    assert [(c.target, c.outcome, c.to, c.history) for c in resumed[:1]] == [(old, "moved", new, 1)]
    assert store.page("history:" + old, limit=10).items == []
    assert len(store.page("history:" + new, limit=10).items) == 2


def test_a_twin_a_check_holds_keeps_the_merge_waiting(before, store, clock, flight_url):
    watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    # The same flight, already stored under its new identity, and a check holds it.
    twin = now_service(store, clock).create_monitor("bob", flight_url, "bob-request")
    target = store.get("target:" + twin["target_id"])
    store.commit([target.update({**target.data, "lease_until": clock[0] + 60})])
    outcomes = sorted(plan.change.outcome for plan in plan_changes(store, clock[0]))
    assert outcomes == ["busy", "unchanged"]


@pytest.mark.parametrize("where", ["expired", "idle"])
def test_a_merge_into_a_departed_or_unwatched_twin_stays_there(
    before, store, clock, flight_url, tmp_path, where
):
    first = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    second = watched(before, clock, "bob", flight_url + "&sa=Y", "bob-request")
    if where == "expired":  # Both departed while watched.
        clock[0] = int(datetime(2027, 3, 16, tzinfo=UTC).timestamp())
    else:  # Nobody watches either any more.
        for tenant, monitor in (("alice", first), ("bob", second)):
            before.set_status(tenant, monitor["id"], "paused")
        clock[0] += 3600
    before.collect_due(Mock())
    pause(store)
    run(store, clock, tmp_path)
    merged = store.get("target:" + import_link(flight_url)["id"])
    assert merged.partition == {"expired": EXPIRED, "idle": IDLE}[where]
    service = now_service(store, clock)
    for tenant, monitor in (("alice", first), ("bob", second)):
        assert service.get_monitor(tenant, monitor["id"])["target_id"] == merged.data["spec"]["id"]


@pytest.mark.parametrize("where", ["idle", "expired"])
def test_an_unread_link_on_an_idle_or_departed_flight_is_left_where_it_is(
    before, store, clock, flight_url, where
):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    if where == "idle":
        before.set_status("alice", monitor["id"], "paused")
        clock[0] += 3600
    else:
        clock[0] = int(datetime(2027, 3, 16, tzinfo=UTC).timestamp())
    before.collect_due(Mock())
    target = store.get("target:" + monitor["target_id"])
    spec = {**target.data["spec"], "url": "https://example.com/"}
    store.commit([target.update({**target.data, "spec": spec})])
    plans = plan_changes(store, clock[0])
    assert [(p.change.outcome, p.change.check, bool(p.writes)) for p in plans] == [
        ("unreadable", "not_google", False)
    ]


def test_a_stopped_flight_tells_the_watchers_who_asked_for_notices(
    before, store, clock, flight_url, tmp_path
):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    before.set_preferences("alice", diagnostics=True)
    target = store.get("target:" + monitor["target_id"])
    spec = {**target.data["spec"], "url": "https://example.com/"}
    store.commit([target.update({**target.data, "spec": spec})])
    pause(store)
    assert [c.outcome for c in run(store, clock, tmp_path)] == ["blocked"]
    notices = store.page("notices_pending", limit=10).items
    assert [(n.data["kind"], n.data["code"]) for n in notices] == [
        ("collection_blocked", "unsupported_itinerary")
    ]
    # The run can be undone, notice and all.
    assert restore(store, tmp_path / "before.jsonl") == (1, [])
    assert store.page("notices_pending", limit=10).items == []
    assert store.get(target.key).partition == COLLECTING


def test_a_flight_blocked_as_unreadable_is_checked_again_when_the_rules_read_it(
    store, clock, flight_url, tmp_path
):
    service = now_service(store, clock)
    monitor = service.create_monitor("alice", flight_url, "alice-request")
    target = store.get("target:" + monitor["target_id"])
    blocked = {**target.data, "last_error": "unsupported_itinerary", "failures": 1}
    store.commit([target.update(blocked, partition=BLOCKED)])
    plans = plan_changes(store, clock[0])
    assert [(p.change.outcome, p.change.unblocked) for p in plans] == [("unblocked", True)]
    pause(store)
    run(store, clock, tmp_path)
    again = store.get(target.key)
    assert (again.partition, again.data["last_error"], again.data["failures"]) == (
        COLLECTING,
        None,
        0,
    )


def test_a_restore_finishes_whenever_it_is_run_again(before, store, clock, flight_url, tmp_path):
    first = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request", (30000, 29000))
    keys = ["target:" + first["target_id"], "monitor:" + first["id"], "capacity:collection"]
    original = snapshot(store, keys)
    pause(store)
    run(store, clock, tmp_path)

    class Interrupted:
        """Puts the first batch back, then stops as a crash would."""

        def __init__(self, store):
            self.store, self.commits = store, 0

        def __getattr__(self, name):
            return getattr(self.store, name)

        def commit(self, documents):
            self.commits += 1
            if self.commits > 1:
                raise RuntimeError("the process stopped")
            self.store.commit(documents)

    with pytest.raises(RuntimeError):
        restore(Interrupted(store), tmp_path / "before.jsonl")
    assert restore(store, tmp_path / "before.jsonl") == (1, [])
    assert snapshot(store, keys) == original
    assert restore(store, tmp_path / "before.jsonl") == (0, [])  # Nothing left: still done.


def test_a_document_someone_wrote_after_the_run_is_never_reverted(
    before, store, clock, flight_url, tmp_path
):
    monitor = watched(before, clock, "alice", flight_url + "&sa=X", "alice-request")
    pause(store)
    run(store, clock, tmp_path)
    # Alice changes her rule after the move: the revision moves on with her change.
    service = now_service(store, clock)
    service.set_policy("alice", monitor["id"], AlertPolicy(kind="below_price", threshold_minor=5))
    restored, skipped = restore(store, tmp_path / "before.jsonl")
    assert restored == 0 and Skipped("monitor:" + monitor["id"], "changed since the run") in skipped
    assert service.get_monitor("alice", monitor["id"])["policy"]["threshold_minor"] == 5
