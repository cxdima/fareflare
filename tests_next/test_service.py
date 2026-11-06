from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from fareflare.service import MonitoringService, NotFound, Reading
from fareflare.store import Conflict, Document, DynamoStore, SQLiteStore


def observe(service, monitor, clock, amount=50000, run="first"):
    return service.record(Reading(monitor["target_id"], amount, "USD", clock[0], "test-fixture"), run)


def test_customers_share_collection_but_not_monitor_ownership(service, flight_url):
    first = service.create_monitor("alice", flight_url, "request-one")
    second = service.create_monitor("bob", flight_url, "request-two")
    assert first["target_id"] == second["target_id"]
    assert first["id"] != second["id"]
    assert len(service.store.query("targets")) == 1
    assert [m["id"] for m in service.list_monitors("alice")] == [first["id"]]
    with pytest.raises(NotFound):
        service.get_monitor("bob", first["id"])
    with pytest.raises(NotFound):
        service.history("bob", first["id"])


def test_idempotent_creation_and_conflicting_reuse(service, flight_url):
    first = service.create_monitor("alice", flight_url, "request-one")
    assert service.create_monitor("alice", flight_url, "request-one")["id"] == first["id"]
    with pytest.raises(Conflict):
        service.create_monitor("alice", flight_url, "request-one", interval_seconds=300)
    assert service.store.get("tenant:alice").data["monitors"] == 1


def test_atomic_observation_and_durable_delivery_retry(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    observe(service, monitor, clock)
    # Simulate process death after price persistence, before event dispatch.
    restarted = MonitoringService(service.store, lambda: clock[0])
    assert restarted.process_events() == 1
    failing_sink = Mock()
    failing_sink.send.return_value = False
    assert restarted.deliver_due(failing_sink) == 0
    assert restarted.list_deliveries("alice")[0]["status"] == "pending"
    assert restarted.process_events() == 0
    clock[0] += 61
    failing_sink.send.return_value = True
    assert restarted.deliver_due(failing_sink) == 1
    assert restarted.deliver_due(failing_sink) == 0
    assert failing_sink.send.call_count == 2
    assert restarted.list_deliveries("alice")[0]["status"] == "sent"


def test_observation_deduplication_and_ordering(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    assert observe(service, monitor, clock)
    assert not observe(service, monitor, clock)
    with pytest.raises(Conflict):
        observe(service, monitor, clock, amount=49000)
    with pytest.raises(ValueError):
        observe(service, monitor, clock, run="older")
    assert len(service.history("alice", monitor["id"])) == 1


def test_event_fanout_is_independent_and_replay_safe(service, flight_url, clock):
    alice = service.create_monitor("alice", flight_url, "request-one")
    service.create_monitor("bob", flight_url, "request-two")
    observe(service, alice, clock)
    service.process_events()
    service.process_events()
    assert len(service.list_deliveries("alice")) == len(service.list_deliveries("bob")) == 1
    clock[0] += 900
    observe(service, alice, clock, amount=40000, run="drop")
    service.process_events()
    assert [d["reason"] for d in service.list_deliveries("alice")] == ["tracking_started", "new_low"]


def test_cancel_does_not_remove_other_customer_or_target(service, flight_url, clock):
    alice = service.create_monitor("alice", flight_url, "request-one")
    bob = service.create_monitor("bob", flight_url, "request-two")
    service.set_status("alice", alice["id"], "cancelled")
    service.set_status("alice", alice["id"], "cancelled")
    assert service.store.get("tenant:alice").data["monitors"] == 0
    observe(service, bob, clock)
    service.process_events()
    assert not service.list_deliveries("alice")
    assert len(service.list_deliveries("bob")) == 1
    with pytest.raises(ValueError):
        service.set_status("alice", alice["id"], "active")


def test_pause_suppresses_queued_alerts_and_resume_rebases_cursor(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    observe(service, monitor, clock)
    service.process_events()
    service.set_status("alice", monitor["id"], "paused")
    sink = Mock()
    assert service.deliver_due(sink) == 0
    sink.send.assert_not_called()
    clock[0] += 900
    observe(service, monitor, clock, amount=40000, run="while-paused")
    service.process_events()
    service.set_status("alice", monitor["id"], "active")
    clock[0] += 900
    observe(service, monitor, clock, amount=35000, run="after-resume")
    service.process_events()
    assert service.get_monitor("alice", monitor["id"])["status"] == "active"
    assert service.list_deliveries("alice")[-1]["reason"] == "new_low"


def test_retry_exhaustion_and_owner_scoped_redrive(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    observe(service, monitor, clock)
    service.process_events()
    sink = Mock()
    sink.send.side_effect = RuntimeError("temporary outage")
    for _ in range(5):
        service.deliver_due(sink)
        clock[0] += 4000
    delivery = service.list_deliveries("alice")[0]
    assert delivery["status"] == "dead_letter"
    with pytest.raises(NotFound):
        service.retry_delivery("bob", delivery["id"])
    service.retry_delivery("alice", delivery["id"])
    sink.send.side_effect = None
    sink.send.return_value = True
    assert service.deliver_due(sink) == 1


def test_collection_failure_keeps_intent_and_previous_price(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    provider = Mock()
    provider.collect.return_value = Reading(monitor["target_id"], 50000, "USD", clock[0], "fixture")
    assert service.collect_due(provider)["collected"] == 1
    service.process_events()
    clock[0] += 901
    provider.collect.side_effect = RuntimeError("cookie=DO-NOT-PERSIST")
    assert service.collect_due(provider)["failed"] == 1
    view = service.get_monitor("alice", monitor["id"])
    assert view["latest"]["amount_minor"] == 50000
    assert view["last_error"] == "collection_failed"
    assert "DO-NOT-PERSIST" not in str(view)
    assert service.collect_due(provider)["failed"] == 0  # Backoff, no immediate retry.


def test_leases_prevent_duplicate_collection_and_fence_old_workers(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    target = service.store.get("target:" + monitor["target_id"])
    service.store.commit([target.update({**target.data, "lease_token": "new-worker", "lease_until": clock[0] + 120})])
    provider = Mock()
    assert service.collect_due(provider)["skipped"] == 1
    provider.collect.assert_not_called()
    with pytest.raises(Conflict):
        service.record(Reading(monitor["target_id"], 40000, "USD", clock[0], "fixture"), "stale-worker", "old-worker")


def test_currency_mismatch_and_wrong_target_are_rejected(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    with pytest.raises(ValueError):
        service.record(Reading(monitor["target_id"], 40000, "EUR", clock[0], "fixture"), "wrong-currency")
    provider = Mock()
    provider.collect.return_value = Reading("different-target", 40000, "USD", clock[0], "fixture")
    assert service.collect_due(provider)["failed"] == 1
    assert service.history("alice", monitor["id"]) == []


def test_atomic_commit_rolls_back_all_documents_on_revision_conflict(store):
    doc = Document("existing", "test", {"value": 1})
    store.commit([doc])
    with pytest.raises(Conflict):
        store.commit([Document("new", "test", {}), doc.update({"value": 2})])
    assert store.get("new") is None
    assert store.get("existing").data == {"value": 1}


def test_dynamo_adapter_rejects_stable_resource_names():
    with pytest.raises(ValueError):
        DynamoStore("gfpricetracker-prices")


def test_concurrent_local_idempotent_creates_have_one_effect(tmp_path, flight_url, clock):
    service = MonitoringService(SQLiteStore(tmp_path / "concurrent.db"), lambda: clock[0])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.create_monitor("alice", flight_url, "same-request"), range(4)))
    assert len({m["id"] for m in results}) == 1
    assert len(service.list_monitors("alice")) == 1


def test_out_of_order_event_discovery_waits_for_missing_sequence(service, flight_url, clock, monkeypatch):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    observe(service, monitor, clock)
    clock[0] += 900
    observe(service, monitor, clock, amount=40000, run="second")
    from fareflare.store import Page
    original_page = service.store.page
    def page(partition, *args, **kwargs):
        result = original_page(partition, *args, **kwargs)
        return Page(list(reversed(result.items)), result.cursor) if partition == "events_pending" else result
    monkeypatch.setattr(service.store, "page", page)
    assert service.process_events() == 1
    assert service.process_events() == 1
    assert [d["reason"] for d in service.list_deliveries("alice")] == ["tracking_started", "new_low"]


def test_failed_observation_transaction_never_advances_price_without_event(service, flight_url, clock, monkeypatch):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    commit = service.store.commit
    monkeypatch.setattr(service.store, "commit", Mock(side_effect=RuntimeError("storage unavailable")))
    with pytest.raises(RuntimeError):
        observe(service, monitor, clock)
    assert service.get_monitor("alice", monitor["id"])["latest"] is None
    assert service.store.query("events_pending") == []
    monkeypatch.setattr(service.store, "commit", commit)
    assert observe(service, monitor, clock)
    assert service.process_events() == 1


def test_delivery_lease_excludes_another_worker(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "request-one")
    observe(service, monitor, clock)
    service.process_events()
    other = Mock()
    sink = Mock()
    def send(delivery):
        assert service.deliver_due(other) == 0
        other.send.assert_not_called()
        return True
    sink.send.side_effect = send
    assert service.deliver_due(sink) == 1
    sink.send.assert_called_once()


def test_expiry_preserves_customer_record_and_allows_local_date_grace(service, flight_url, clock):
    from datetime import UTC, datetime
    monitor = service.create_monitor("alice", flight_url, "request-one")
    provider = Mock()
    provider.collect.side_effect = lambda target: Reading(target["id"], 40000, "USD", clock[0], "fixture")
    clock[0] = int(datetime(2027, 3, 15, tzinfo=UTC).timestamp())
    assert service.collect_due(provider)["collected"] == 1
    clock[0] = int(datetime(2027, 3, 16, tzinfo=UTC).timestamp())
    service.collect_due(provider)
    assert service.get_monitor("alice", monitor["id"])["status"] == "expired"
    assert len(service.list_monitors("alice")) == 1
    assert service.store.query("targets") == []


def test_creation_validates_interval_identity_quota_and_dates(service, flight_url, clock):
    with pytest.raises(ValueError):
        service.create_monitor("bad:tenant", flight_url, "valid-request")
    with pytest.raises(ValueError):
        service.create_monitor("alice", flight_url, "short")
    with pytest.raises(ValueError):
        service.create_monitor("alice", flight_url, "valid-request", interval_seconds=1)
    service.store.commit([Document("tenant:alice", "tenants", {"monitors": 100})])
    with pytest.raises(ValueError, match="quota"):
        service.create_monitor("alice", flight_url, "valid-request")
    clock[0] += 365 * 86400
    with pytest.raises(ValueError, match="departed"):
        service.create_monitor("bob", flight_url, "valid-request")


def test_repeated_resume_does_not_skip_an_unprocessed_drop(service, flight_url, clock):
    monitor = service.create_monitor('alice', flight_url, 'resume-regression')
    observe(service, monitor, clock)
    service.process_events()
    clock[0] += 900
    observe(service, monitor, clock, amount=40000, run='drop')
    service.set_status('alice', monitor['id'], 'active')
    service.process_events()
    assert [d['observation']['amount_minor'] for d in service.list_deliveries('alice')] == [50000, 40000]


def test_delivery_order_survives_failure_and_multiple_workers(service, flight_url, clock):
    monitor = service.create_monitor('alice', flight_url, 'ordered-regression')
    for index, amount in enumerate((50000, 40000, 35000)):
        observe(service, monitor, clock, amount=amount, run=str(index))
        clock[0] += 900
    service.process_events()
    failed = Mock()
    failed.send.return_value = False
    assert service.deliver_due(failed) == 0
    assert failed.send.call_count == 1
    received = []
    sink = Mock()
    def send(delivery):
        # A second worker cannot overtake a leased predecessor.
        assert service.deliver_due(Mock()) == 0
        received.append(delivery['observation']['amount_minor'])
        return True
    sink.send.side_effect = send
    assert service.deliver_due(sink) == 0
    clock[0] += 61
    assert sum(service.deliver_due(sink) for _ in range(3)) == 3
    assert received == [50000, 40000, 35000]


def test_pause_then_resume_suppresses_pre_pause_queue(service, flight_url, clock):
    monitor = service.create_monitor('alice', flight_url, 'epoch-regression')
    observe(service, monitor, clock)
    service.process_events()
    service.set_status('alice', monitor['id'], 'paused')
    service.set_status('alice', monitor['id'], 'active')
    sink = Mock()
    assert service.deliver_due(sink) == 0
    sink.send.assert_not_called()


def test_unsupported_collection_is_blocked_without_losing_intent(service, flight_url):
    from fareflare.contracts import CollectionFailure
    monitor = service.create_monitor('alice', flight_url, 'unsupported-test')
    provider = Mock()
    provider.collect.side_effect = CollectionFailure('unsupported_itinerary')
    assert service.collect_due(provider)['failed'] == 1
    view = service.get_monitor('alice', monitor['id'])
    assert view['last_error'] == 'unsupported_itinerary'
    assert view['collection_status'] == 'blocked'
    assert service.collect_due(provider)['failed'] == 0
    provider.collect.assert_called_once()
