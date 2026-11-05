import pytest

from gfpt_next.service import MonitoringService, Reading
from gfpt_next.store import Document


def test_free_limits_share_targets_and_release_capacity(store, clock, flight_url):
    service = MonitoringService(store, lambda: clock[0], monitor_limit=2,
                                min_interval_seconds=900, global_target_limit=1)
    first = service.create_monitor("alice", flight_url, "monitor-first")
    second = service.create_monitor("bob", flight_url, "monitor-second")
    assert first["target_id"] == second["target_id"]
    assert len(store.get("capacity:collection").data["targets"]) == 1
    with pytest.raises(ValueError, match="interval"):
        service.create_monitor("alice", flight_url, "too-frequent", interval_seconds=300)
    other = flight_url.replace("hl=en-US", "hl=en")
    with pytest.raises(ValueError, match="capacity"):
        service.create_monitor("bob", other, "other-monitor")
    service.set_status("alice", first["id"], "cancelled")
    assert len(store.get("capacity:collection").data["targets"]) == 1
    service.set_status("bob", second["id"], "cancelled")
    assert store.get("capacity:collection").data["targets"] == []
    service.create_monitor("bob", other, "other-monitor")


def test_account_monitor_quota_is_enforced_on_service(store, clock, flight_url):
    service = MonitoringService(store, lambda: clock[0], monitor_limit=1)
    first = service.create_monitor("alice", flight_url, "monitor-first")
    assert service.create_monitor("alice", flight_url, "monitor-first")["id"] == first["id"]
    with pytest.raises(ValueError, match="quota"):
        service.create_monitor("alice", flight_url, "monitor-second")
    service.set_status("alice", first["id"], "cancelled")
    service.create_monitor("alice", flight_url, "monitor-second")


def test_deleted_accounts_cannot_create_or_collect(store, clock, flight_url):
    tenant = "acct_" + "a" * 32
    store.commit([Document("account:" + tenant, "accounts", {"id": tenant, "status": "active"})])
    service = MonitoringService(store, lambda: clock[0])
    monitor = service.create_monitor(tenant, flight_url, "monitor-first")
    assert len(service._active_subscribers(monitor["target_id"])) == 1
    account = store.get("account:" + tenant)
    store.commit([account.update({**account.data, "status": "deleted"})])
    with pytest.raises(ValueError, match="not active"):
        service.create_monitor(tenant, flight_url, "monitor-second")
    assert service._active_subscribers(monitor["target_id"]) == []

    class NeverCollect:
        def collect(self, target) -> Reading:
            pytest.fail("Deleted account caused a billable collection")

    assert service.collect_due(NeverCollect())["skipped"] == 1


def test_account_deletion_racing_creation_rolls_back(store, clock, flight_url, monkeypatch):
    tenant = "acct_" + "b" * 32
    store.commit([Document("account:" + tenant, "accounts", {"id": tenant, "status": "active"})])
    service = MonitoringService(store, lambda: clock[0])
    original = store.commit
    raced = [False]

    def commit(documents):
        if not raced[0] and any(doc.key.startswith("monitor:") for doc in documents):
            raced[0] = True
            account = store.get("account:" + tenant)
            original([account.update({**account.data, "status": "deleted"})])
        original(documents)

    monkeypatch.setattr(store, "commit", commit)
    with pytest.raises(ValueError, match="not active"):
        service.create_monitor(tenant, flight_url, "monitor-racing")
    assert service.list_monitors(tenant) == []
def test_departure_releases_quota_and_capacity_without_reactivation(store, clock, flight_url):
    from datetime import UTC, datetime

    from gfpt_next.service import MonitoringService

    service = MonitoringService(store, lambda: clock[0], monitor_limit=1, global_target_limit=1)
    first = service.create_monitor("alice", flight_url, "depart-alice")
    second = service.create_monitor("bob", flight_url, "depart-bob")
    service.set_status("bob", second["id"], "paused")
    clock[0] = int(datetime(2027, 3, 17, tzinfo=UTC).timestamp())

    class NoCollection:
        def collect(self, target):
            raise AssertionError("Departed flights must not launch collection")

    service.collect_due(NoCollection())
    assert service.get_monitor("alice", first["id"])["status"] == "expired"
    assert service.get_monitor("bob", second["id"])["status"] == "expired"
    assert store.get("tenant:alice").data["monitors"] == 0
    assert store.get("tenant:bob").data["monitors"] == 0
    assert store.get("capacity:collection").data["targets"] == []
    for status in ("paused", "active"):
        with pytest.raises(ValueError, match="expired"):
            service.set_status("alice", first["id"], status)
    service.set_status("alice", first["id"], "cancelled")
    assert store.get("tenant:alice").data["monitors"] == 0
