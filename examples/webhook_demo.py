"""Runnable customer workflow using synthetic prices and an in-process receiver.

No Google, AWS, Telegram, or external HTTPS calls. Run: make next-webhook-demo.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from fareflare.api import create_app
from fareflare.service import MonitoringService, Reading
from fareflare.store import SQLiteStore
from fareflare.webhook_http import verify_webhook
from fareflare.webhooks import RoutedSink


def main() -> dict:
    now = [int(time.time())]

    class Receiver:
        secret = ""
        token = ""
        attempts = 0

        def __init__(self):
            self.events: dict[str, dict] = {}

        def send(self, url, payload, headers):
            if not verify_webhook(self.secret, payload, headers, now=now[0]):
                raise AssertionError("Invalid signature")
            event = json.loads(payload)
            if event["type"] == "webhook.verification":
                self.token = event["data"]["token"]
                return True
            self.attempts += 1
            if self.attempts == 1:
                return False  # Simulate one temporary receiver failure.
            self.events.setdefault(event["id"], event)
            return True

    receiver = Receiver()
    sample = json.loads((Path(__file__).parent / "next-demo.json").read_text())
    with tempfile.TemporaryDirectory(prefix="gfpt-webhook-demo-") as directory:
        store = SQLiteStore(Path(directory) / "demo.sqlite3")
        service = MonitoringService(store, lambda: now[0], webhook_transport=receiver)
        # This credential exists only in the temporary demonstration API.
        import secrets
        key = secrets.token_urlsafe(32)
        with TestClient(create_app(service, {"demo": key})) as client:
            headers = {"Authorization": "Bearer " + key}
            response = client.post("/v1/webhooks", json={"url": "https://receiver.example.com/prices"},
                                   headers={**headers, "Idempotency-Key": "demo-webhook"})
            response.raise_for_status()
            endpoint = response.json()
            receiver.secret = endpoint["signing_secret"]
            path = "/v1/webhooks/" + endpoint["id"]
            client.post(path + "/challenge", headers=headers).raise_for_status()
            client.post(path + "/verify", json={"token": receiver.token}, headers=headers).raise_for_status()
            response = client.post("/v1/monitors", json={"url": sample["url"], "webhook_id": endpoint["id"]},
                                   headers={**headers, "Idempotency-Key": "demo-monitor"})
            response.raise_for_status()
            monitor = response.json()
            for index, amount in enumerate(sample["synthetic_prices_minor"][:2]):
                service.record(Reading(monitor["target_id"], amount, "USD", now[0], "synthetic-demo"), f"demo-{index}")
                service.process_events()
                service.deliver_due(RoutedSink(service.webhooks), limit=1)
                # The following attempt uses a newly constructed application.
                service = MonitoringService(store, lambda: now[0], webhook_transport=receiver)
                now[0] += 900
            service.deliver_due(RoutedSink(service.webhooks))
            alerts = client.get("/v1/alerts", headers=headers).json()["items"]
            assert len(alerts) == 2 and all(alert["status"] == "sent" for alert in alerts)
            assert len(receiver.events) == 2 and receiver.attempts == 3
            client.post(path + "/disable", headers=headers).raise_for_status()
            result = {"simulation": True, "external_requests": 0, "endpoint_verified": True,
                      "monitor_created": True, "signed_alerts_received": len(receiver.events),
                      "delivery_attempts": receiver.attempts, "retry_survived_restart": True,
                      "prices_minor": [event["data"]["observation"]["amount_minor"] for event in receiver.events.values()],
                      "endpoint_disabled": client.get(path, headers=headers).json()["status"] == "disabled"}
            print(json.dumps(result, indent=2))
            return result


if __name__ == "__main__":
    main()
