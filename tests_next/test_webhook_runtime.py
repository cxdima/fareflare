"""Production mode selection must never change a customer's selected channel."""
import json
from unittest.mock import Mock

import httpx
import pytest

from gfpt_next import runtime
from gfpt_next.delivery import TelegramSink
from gfpt_next.service import MonitoringService, Reading
from gfpt_next.webhooks import RoutedSink


class Receiver:
    def __init__(self):
        self.events = []

    def send(self, url, payload, headers):
        self.events.append(json.loads(payload))
        return True


@pytest.mark.parametrize("mode", ["shadow", "telegram", "webhooks", "routed"])
def test_runtime_delivery_mode_preserves_explicit_destination(store, clock, flight_url, monkeypatch, mode):
    receiver = Receiver()
    service = MonitoringService(store, lambda: clock[0], webhook_transport=receiver)
    endpoint = service.webhooks.register("alice", "https://hooks.example.com/flight", "runtime-endpoint")
    service.webhooks.challenge("alice", endpoint["id"])
    service.webhooks.verify("alice", endpoint["id"], receiver.events[-1]["data"]["token"])
    webhook_monitor = service.create_monitor("alice", flight_url, "runtime-webhook", webhook_id=endpoint["id"])
    legacy_monitor = service.create_monitor("alice", flight_url, "runtime-telegram")
    service.record(Reading(webhook_monitor["target_id"], 30900, "USD", clock[0], "test-fixture"), "runtime-price")
    service.process_events()
    receiver.events.clear()

    monkeypatch.setenv("GFPT_NEXT_TABLE", "gfpt-next-tests")
    monkeypatch.setenv("GFPT_NEXT_DELIVERY", mode)
    monkeypatch.setenv("GFPT_NEXT_TELEGRAM_SECRET_ARN", "test-secret")
    monkeypatch.setattr(runtime, "DynamoStore", lambda *args, **kwargs: store)
    aws = Mock()
    aws.return_value.get_secret_value.return_value = {"SecretString": json.dumps({
        "bot_token": "123:" + "a" * 25, "recipients": {"alice": "111"}})}
    monkeypatch.setattr(runtime.boto3, "client", aws)
    worker = runtime.build_worker()
    if mode in ("telegram", "routed"):
        aws.assert_called_once_with("secretsmanager", region_name="us-east-1")
    else:
        aws.assert_not_called()

    telegram_requests = []
    telegram_monitors = []
    send = TelegramSink.send

    def record_delivery(sink, delivery):
        sent = send(sink, delivery)
        if sent:
            telegram_monitors.append(delivery["monitor_id"])
        return sent

    monkeypatch.setattr(TelegramSink, "send", record_delivery)

    def telegram(request):
        telegram_requests.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    if isinstance(worker.sink, TelegramSink):
        worker.sink._transport = httpx.MockTransport(telegram)
    elif isinstance(worker.sink, RoutedSink):
        worker.sink.webhook.registry.transport = receiver
        if worker.sink.default is not None:
            assert isinstance(worker.sink.default, TelegramSink)
            worker.sink.default._transport = httpx.MockTransport(telegram)

    service.outbox.deliver(worker.sink, force_suppress=mode == "shadow")
    assert len(receiver.events) == int(mode in ("webhooks", "routed"))
    assert len(telegram_requests) == int(mode in ("telegram", "routed"))
    deliveries = {delivery["monitor_id"]: delivery for delivery in service.list_deliveries("alice")}
    if mode == "shadow":
        assert all(delivery["status"] == "suppressed" for delivery in deliveries.values())
        assert all(delivery["attempts"] == 0 for delivery in deliveries.values())
    else:
        assert deliveries[webhook_monitor["id"]]["status"] == ("sent" if mode != "telegram" else "pending")
        assert deliveries[legacy_monitor["id"]]["status"] == ("sent" if mode != "webhooks" else "pending")
    if receiver.events:
        assert receiver.events[0]["data"]["monitor_id"] == webhook_monitor["id"]
    if telegram_requests:
        assert telegram_monitors == [legacy_monitor["id"]]
        assert telegram_requests[0]["chat_id"] == "111"
        assert "USD 309.00" in telegram_requests[0]["text"]


def test_invalid_runtime_delivery_mode_fails_before_secret_or_network_access(store, monkeypatch):
    monkeypatch.setenv("GFPT_NEXT_TABLE", "gfpt-next-tests")
    monkeypatch.setenv("GFPT_NEXT_DELIVERY", "unrecognized")
    monkeypatch.setattr(runtime, "DynamoStore", lambda *args, **kwargs: store)
    aws = Mock()
    monkeypatch.setattr(runtime.boto3, "client", aws)
    with pytest.raises(ValueError, match="Unsupported notification delivery mode"):
        runtime.build_worker()
    aws.assert_not_called()
