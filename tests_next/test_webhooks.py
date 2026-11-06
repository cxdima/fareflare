"""Webhook ownership, tenant isolation, durable retries and endpoint lifecycle."""
import json

import pytest

from fareflare.credentials import RateLimited
from fareflare.service import MonitoringService, NotFound, Reading
from fareflare.store import Conflict
from fareflare.webhook_http import verify_webhook
from fareflare.webhooks import RoutedSink


class Receiver:
    def __init__(self):
        self.requests = []
        self.accept = True

    def send(self, url, payload, headers):
        self.requests.append((url, payload, headers))
        return self.accept


@pytest.fixture
def webhook_service(store, clock):
    receiver = Receiver()
    return MonitoringService(store, lambda: clock[0], webhook_transport=receiver), receiver


def register(service, receiver, tenant="alice", key="webhook-create", url="https://hooks.example.com/flight"):
    endpoint = service.webhooks.register(tenant, url, key)
    service.webhooks.challenge(tenant, endpoint["id"])
    event = json.loads(receiver.requests[-1][1])
    service.webhooks.verify(tenant, endpoint["id"], event["data"]["token"])
    return endpoint


def observe(service, monitor, clock, amount=30000):
    service.record(Reading(monitor["target_id"], amount, "USD", clock[0], "test"), str(clock[0]))
    return service.process_event_batch()


def test_ownership_is_required_and_secrets_are_returned_once(webhook_service, flight_url, clock):
    service, receiver = webhook_service
    endpoint = service.webhooks.register("alice", "https://hooks.example.com/flight", "register-one")
    assert endpoint["status"] == "pending"
    assert receiver.requests == []
    with pytest.raises(ValueError, match="Verify"):
        service.create_monitor("alice", flight_url, "create-mon", webhook_id=endpoint["id"])
    response = service.webhooks.challenge("alice", endpoint["id"])
    assert response == {"delivered": True, "expires_at": clock[0] + 600}
    assert service.webhooks.get("alice", endpoint["id"])["status"] == "pending"
    _, body, headers = receiver.requests[-1]
    assert verify_webhook(endpoint["signing_secret"], body, headers, now=clock[0])
    token = json.loads(body)["data"]["token"]
    assert token not in json.dumps(service.store.get("webhook:" + endpoint["id"]).data)
    verified = service.webhooks.verify("alice", endpoint["id"], token)
    assert verified["status"] == "active"
    for result in (verified, service.webhooks.list("alice"),
                   service.webhooks.register("alice", endpoint["url"], "register-one")):
        assert "signing_secret" not in json.dumps(result)
        assert token not in json.dumps(result)
    assert len(receiver.requests) == 1


def test_challenges_are_bounded_and_failed_transport_does_not_verify(webhook_service, clock):
    service, receiver = webhook_service
    endpoint = service.webhooks.register("alice", "https://hooks.example.com/flight", "register-one")
    receiver.accept = False
    assert service.webhooks.challenge("alice", endpoint["id"])["delivered"] is False
    token = json.loads(receiver.requests[-1][1])["data"]["token"]
    with pytest.raises(RateLimited):
        service.webhooks.challenge("alice", endpoint["id"])
    for _ in range(5):
        with pytest.raises(ValueError, match="verification token"):
            service.webhooks.verify("alice", endpoint["id"], "x" * 43)
    with pytest.raises(ValueError, match="verification token"):
        service.webhooks.verify("alice", endpoint["id"], token)
    clock[0] += 60
    service.webhooks.challenge("alice", endpoint["id"])
    new_token = json.loads(receiver.requests[-1][1])["data"]["token"]
    clock[0] += 600
    with pytest.raises(ValueError, match="verification token"):
        service.webhooks.verify("alice", endpoint["id"], new_token)


def test_endpoint_tenant_isolation_and_immutable_monitor_binding(webhook_service, flight_url):
    service, receiver = webhook_service
    endpoint = register(service, receiver)
    for operation in (service.webhooks.get, service.webhooks.challenge, service.webhooks.disable, service.webhooks.delete):
        with pytest.raises(NotFound):
            operation("bob", endpoint["id"])
    with pytest.raises(NotFound):
        service.create_monitor("bob", flight_url, "bob-monitor", webhook_id=endpoint["id"])
    monitor = service.create_monitor("alice", flight_url, "alice-monitor", webhook_id=endpoint["id"])
    with pytest.raises(Conflict):
        service.create_monitor("alice", flight_url, "alice-monitor")
    service.webhooks.disable("alice", endpoint["id"])
    assert service.create_monitor("alice", flight_url, "alice-monitor", webhook_id=endpoint["id"])["id"] == monitor["id"]


def test_quota_deletion_and_idempotency_are_atomic(webhook_service):
    service, _ = webhook_service
    endpoints = [service.webhooks.register("alice", f"https://hooks.example.com/{i}", f"register-{i}") for i in range(10)]
    with pytest.raises(ValueError, match="quota"):
        service.webhooks.register("alice", "https://hooks.example.com/full", "register-full")
    with pytest.raises(Conflict):
        service.webhooks.register("alice", "https://hooks.example.com/different", "register-0")
    original = endpoints[0]
    service.webhooks.delete("alice", original["id"])
    service.webhooks.delete("alice", original["id"])
    assert service.store.get("tenant:alice").data["webhooks"] == 9
    assert "signing_secret" not in service.store.get("webhook:" + original["id"]).data
    assert service.webhooks.register("alice", original["url"], "register-0")["status"] == "deleted"
    service.webhooks.register("alice", "https://hooks.example.com/new", "register-new")
    assert service.store.get("tenant:alice").data["webhooks"] == 10
    with pytest.raises(ValueError):
        service.webhooks.challenge("alice", original["id"])


def test_two_tenants_share_collection_but_receive_distinct_signed_events(webhook_service, flight_url, clock):
    service, receiver = webhook_service
    endpoints, monitors = [], []
    for tenant in ("alice", "bob"):
        endpoint = register(service, receiver, tenant, url=f"https://hooks.example.com/{tenant}")
        endpoints.append(endpoint)
        monitors.append(service.create_monitor(tenant, flight_url, "new-monitor", webhook_id=endpoint["id"]))
    assert monitors[0]["target_id"] == monitors[1]["target_id"]
    receiver.requests.clear()
    observe(service, monitors[0], clock)
    assert service.deliver_due(RoutedSink(service.webhooks)) == 2
    messages = {url: (body, headers) for url, body, headers in receiver.requests}
    identifiers = set()
    for tenant, endpoint, monitor in zip(("alice", "bob"), endpoints, monitors, strict=True):
        body, headers = messages[endpoint["url"]]
        assert verify_webhook(endpoint["signing_secret"], body, headers, now=clock[0])
        event = json.loads(body)
        assert event["type"] == "flight.price_alert"
        assert event["data"]["monitor_id"] == monitor["id"]
        assert set(event["data"]) == {"monitor_id", "reason", "observation", "itinerary"}
        assert headers["webhook-id"] == event["id"]
        identifiers.add(event["id"])
        delivery = service.list_deliveries(tenant)[0]
        assert delivery["webhook_id"] == endpoint["id"] and delivery["status"] == "sent"
        assert endpoint["signing_secret"] not in json.dumps(delivery)
    assert len(identifiers) == 2


def test_retry_uses_stable_body_and_id_but_fresh_timestamp(webhook_service, flight_url, clock):
    service, receiver = webhook_service
    endpoint = register(service, receiver)
    monitor = service.create_monitor("alice", flight_url, "monitor-one", webhook_id=endpoint["id"])
    observe(service, monitor, clock)
    receiver.requests.clear()
    receiver.accept = False
    assert service.deliver_due(RoutedSink(service.webhooks)) == 0
    first = receiver.requests[-1]
    clock[0] += 900
    observe(service, monitor, clock, 25000)
    receiver.accept = True
    # Reopen the application on the same store, as after a process restart.
    service = MonitoringService(service.store, lambda: clock[0], webhook_transport=receiver)
    assert service.deliver_due(RoutedSink(service.webhooks), limit=1) == 1
    second = receiver.requests[-1]
    assert first[:2] == second[:2]
    assert first[2]["webhook-id"] == second[2]["webhook-id"]
    assert first[2]["webhook-timestamp"] != second[2]["webhook-timestamp"]
    assert verify_webhook(endpoint["signing_secret"], second[1], second[2], now=clock[0])
    assert service.deliver_due(RoutedSink(service.webhooks)) == 1
    assert json.loads(receiver.requests[-1][1])["data"]["reason"] == "new_low"


def test_disabled_generation_is_suppressed_even_after_reverification(webhook_service, flight_url, clock):
    service, receiver = webhook_service
    endpoint = register(service, receiver)
    monitor = service.create_monitor("alice", flight_url, "monitor-one", webhook_id=endpoint["id"])
    observe(service, monitor, clock)
    service.webhooks.disable("alice", endpoint["id"])
    revision = service.store.get("webhook:" + endpoint["id"]).revision
    service.webhooks.disable("alice", endpoint["id"])
    assert service.store.get("webhook:" + endpoint["id"]).revision == revision
    clock[0] += 900
    observe(service, monitor, clock, 29000)
    assert len(service.list_deliveries("alice")) == 1
    service.webhooks.challenge("alice", endpoint["id"])
    token = json.loads(receiver.requests[-1][1])["data"]["token"]
    service.webhooks.verify("alice", endpoint["id"], token)
    clock[0] += 900
    observe(service, monitor, clock, 28000)
    receiver.requests.clear()
    service.deliver_due(RoutedSink(service.webhooks), limit=1)
    deliveries = service.list_deliveries("alice")
    assert deliveries[0]["status"] == "suppressed" and deliveries[0]["attempts"] == 0
    assert receiver.requests == []
    assert service.deliver_due(RoutedSink(service.webhooks)) == 1


def test_endpoint_disable_racing_monitor_creation_is_fenced(webhook_service, flight_url, monkeypatch):
    service, receiver = webhook_service
    endpoint = register(service, receiver)
    commit = service.store.commit
    raced = [False]

    def competing_commit(documents):
        if not raced[0] and any(doc.key.startswith("monitor:") for doc in documents):
            raced[0] = True
            service.webhooks.disable("alice", endpoint["id"])
        return commit(documents)

    monkeypatch.setattr(service.store, "commit", competing_commit)
    with pytest.raises(ValueError, match="Verify"):
        service.create_monitor("alice", flight_url, "racing-monitor", webhook_id=endpoint["id"])
    assert service.list_monitors("alice") == []


def test_webhook_failure_never_falls_back_to_other_destination(webhook_service, flight_url, clock):
    service, receiver = webhook_service
    endpoint = register(service, receiver)
    monitor = service.create_monitor("alice", flight_url, "monitor-one", webhook_id=endpoint["id"])
    observe(service, monitor, clock)

    class OtherDestination:
        def send(self, delivery):
            pytest.fail("Webhook data leaked to a different notification destination")

    receiver.accept = False
    assert service.deliver_due(RoutedSink(service.webhooks, OtherDestination())) == 0


def test_disable_during_challenge_prevents_activation(webhook_service):
    service, receiver = webhook_service
    endpoint = service.webhooks.register("alice", "https://hooks.example.com/flight", "register-one")
    send = receiver.send

    def disable_during_send(url, body, headers):
        service.webhooks.disable("alice", endpoint["id"])
        return send(url, body, headers)

    receiver.send = disable_during_send
    service.webhooks.challenge("alice", endpoint["id"])
    token = json.loads(receiver.requests[-1][1])["data"]["token"]
    with pytest.raises(ValueError):
        service.webhooks.verify("alice", endpoint["id"], token)
