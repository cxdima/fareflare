"""Customer webhook onboarding through the same authenticated HTTP and MCP use cases."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from fareflare.api import create_app
from fareflare.mcp_server import make_server
from fareflare.service import MonitoringService, Reading
from fareflare.webhooks import RoutedSink

KEYS = {"alice": "a" * 40, "bob": "b" * 40}
DESTINATION = "https://hooks.example.com/flights"


class Receiver:
    def __init__(self):
        self.requests = []
        self.accept = True

    def send(self, url, payload, headers):
        self.requests.append((url, json.loads(payload), headers))
        return self.accept


def auth(tenant="alice", key=None):
    headers = {"Authorization": "Bearer " + KEYS[tenant]}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


@pytest.fixture
def webhook_client(store, clock):
    receiver = Receiver()
    service = MonitoringService(store, lambda: clock[0], webhook_transport=receiver)
    with TestClient(create_app(service, KEYS)) as client:
        yield client, service, receiver


def register(client, key="endpoint-request", tenant="alice", url=DESTINATION):
    return client.post("/v1/webhooks", json={"url": url}, headers=auth(tenant, key))


def activate(client, receiver, identifier, tenant="alice"):
    response = client.post(f"/v1/webhooks/{identifier}/challenge", headers=auth(tenant))
    assert response.status_code == 200
    assert set(response.json()) == {"delivered", "expires_at"}
    assert response.json()["delivered"] is True
    destination, event, headers = receiver.requests[-1]
    assert destination == DESTINATION
    assert event["type"] == "webhook.verification"
    assert event["data"]["webhook_id"] == identifier
    assert "webhook-signature" in headers
    response = client.post(
        f"/v1/webhooks/{identifier}/verify",
        json={"token": event["data"]["token"]},
        headers=auth(tenant),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_registration_requires_auth_and_request_key_without_network(webhook_client):
    client, _, receiver = webhook_client
    assert client.post("/v1/webhooks", json={"url": DESTINATION}).status_code == 401
    assert client.get("/v1/webhooks").status_code == 401
    assert client.post("/v1/webhooks", json={"url": DESTINATION}, headers=auth()).status_code == 422
    assert receiver.requests == []


def test_secret_returned_only_on_first_registration_and_metadata_is_redacted(webhook_client):
    client, service, receiver = webhook_client
    response = register(client)
    assert response.status_code == 201
    endpoint = response.json()
    assert endpoint["status"] == "pending"
    assert endpoint["signing_secret"].startswith("whsec_")
    replay = register(client)
    assert replay.status_code == 201
    assert replay.json()["id"] == endpoint["id"]
    assert replay.json().get("signing_secret") is None
    assert register(client, url="https://hooks.example.com/replacement").status_code == 409
    assert service.store.get("tenant:alice").data["webhooks"] == 1
    for response in (
        client.get("/v1/webhooks", headers=auth()),
        client.get(f"/v1/webhooks/{endpoint['id']}", headers=auth()),
    ):
        assert response.status_code == 200
        assert "signing_secret" not in response.text
        assert "challenge_hash" not in response.text
        assert "generation" not in response.text
        assert endpoint["signing_secret"] not in response.text
    assert receiver.requests == []


def test_verified_webhook_can_bind_monitor_and_appears_in_alert_history(
    webhook_client, flight_url, clock
):
    client, service, receiver = webhook_client
    endpoint = register(client).json()
    request = {"url": flight_url, "webhook_id": endpoint["id"]}
    assert (
        client.post("/v1/monitors", json=request, headers=auth(key="webhook-monitor")).status_code
        == 422
    )
    activate(client, receiver, endpoint["id"])
    response = client.post("/v1/monitors", json=request, headers=auth(key="webhook-monitor"))
    assert response.status_code == 202
    monitor = response.json()
    assert monitor["webhook_id"] == endpoint["id"]
    assert (
        client.post(
            "/v1/monitors", json={"url": flight_url}, headers=auth(key="webhook-monitor")
        ).status_code
        == 409
    )
    service.record(
        Reading(monitor["target_id"], 30900, "USD", clock[0], "test-fixture"), "fixture-observation"
    )
    service.process_events()
    response = client.get("/v1/alerts", headers=auth())
    assert response.status_code == 200
    assert response.json()["items"][0]["webhook_id"] == endpoint["id"]
    for private in ("signing_secret", "challenge_hash", "webhook_generation", "lease_token"):
        assert private not in response.text


def test_another_tenant_cannot_read_verify_disable_delete_or_use_endpoint(
    webhook_client, flight_url
):
    client, _, receiver = webhook_client
    endpoint = register(client).json()
    activate(client, receiver, endpoint["id"])
    path = f"/v1/webhooks/{endpoint['id']}"
    requests_before = len(receiver.requests)
    for method, suffix, body in (
        ("GET", "", None),
        ("POST", "/challenge", None),
        ("POST", "/verify", {"token": "x" * 43}),
        ("POST", "/disable", None),
        ("DELETE", "", None),
    ):
        response = client.request(method, path + suffix, json=body, headers=auth("bob"))
        assert response.status_code == 404
    assert client.get("/v1/webhooks", headers=auth("bob")).json()["items"] == []
    assert (
        client.post(
            "/v1/monitors",
            json={"url": flight_url, "webhook_id": endpoint["id"]},
            headers=auth("bob", "foreign-endpoint"),
        ).status_code
        == 404
    )
    assert len(receiver.requests) == requests_before


def test_challenge_does_not_activate_and_never_returns_token(webhook_client):
    client, _, receiver = webhook_client
    endpoint = register(client).json()
    path = f"/v1/webhooks/{endpoint['id']}"
    response = client.post(path + "/challenge", headers=auth())
    token = receiver.requests[-1][1]["data"]["token"]
    assert token not in response.text
    assert client.get(path, headers=auth()).json()["status"] == "pending"
    assert client.post(path + "/challenge", headers=auth()).status_code == 429
    assert (
        client.post(path + "/verify", json={"token": "x" * 43}, headers=auth()).status_code == 422
    )
    assert (
        client.post(
            path + "/verify", json={"token": token, "url": DESTINATION}, headers=auth()
        ).status_code
        == 422
    )
    response = client.post(path + "/verify", json={"token": token}, headers=auth())
    assert response.status_code == 200
    assert "signing_secret" not in response.text
    assert token not in response.text


def test_disable_and_delete_are_owner_scoped_and_idempotent(webhook_client, flight_url):
    client, service, receiver = webhook_client
    endpoint = register(client).json()
    activate(client, receiver, endpoint["id"])
    path = f"/v1/webhooks/{endpoint['id']}"
    for _ in range(2):
        assert client.post(path + "/disable", headers=auth()).json()["status"] == "disabled"
    assert (
        client.post(
            "/v1/monitors",
            json={"url": flight_url, "webhook_id": endpoint["id"]},
            headers=auth(key="disabled-endpoint"),
        ).status_code
        == 422
    )
    for _ in range(2):
        response = client.delete(path, headers=auth())
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"
        assert "signing_secret" not in response.text
    assert service.store.get("tenant:alice").data["webhooks"] == 0


def test_redrive_after_reverification_suppresses_old_alerts_and_unblocks_new_ones(
    webhook_client, flight_url, clock
):
    client, service, receiver = webhook_client
    endpoint = register(client).json()
    activate(client, receiver, endpoint["id"])
    monitor = client.post(
        "/v1/monitors",
        json={"url": flight_url, "webhook_id": endpoint["id"]},
        headers=auth(key="webhook-redrive"),
    ).json()
    sink = RoutedSink(service.webhooks)

    def observe(amount, run_id):
        clock[0] += 1
        service.record(
            Reading(monitor["target_id"], amount, "USD", clock[0], "test-fixture"), run_id
        )
        service.process_events()

    observe(30900, "initial")
    receiver.accept = False
    for _ in range(5):
        assert service.deliver_due(sink) == 0
        clock[0] += 3601
    failed = client.get("/v1/alerts", headers=auth()).json()["items"][0]
    assert failed["status"] == "dead_letter"
    observe(29900, "before-disable")
    assert client.post(f"/v1/webhooks/{endpoint['id']}/disable", headers=auth()).status_code == 200
    receiver.accept = True
    activate(client, receiver, endpoint["id"])
    observe(28900, "after-reverification")
    requests_before_redrive = len(receiver.requests)
    assert client.post(f"/v1/alerts/{failed['id']}/retry", headers=auth("bob")).status_code == 404
    assert client.post(f"/v1/alerts/{failed['id']}/retry", headers=auth()).status_code == 202
    assert sum(service.deliver_due(sink) for _ in range(4)) == 1
    alerts = client.get("/v1/alerts", headers=auth()).json()["items"]
    assert {alert["observation"]["amount_minor"]: alert["status"] for alert in alerts} == {
        30900: "suppressed",
        29900: "suppressed",
        28900: "sent",
    }
    assert len(receiver.requests) == requests_before_redrive + 1
    assert receiver.requests[-1][1]["type"] == "flight.price_alert"
    assert receiver.requests[-1][1]["data"]["observation"]["amount_minor"] == 28900


@pytest.mark.parametrize(
    "url", ["http://hooks.example.com/", "https://127.0.0.1/", "https://user:secret@example.com/"]
)
def test_invalid_destination_is_rejected_without_network(webhook_client, url):
    client, _, receiver = webhook_client
    assert register(client, url=url).status_code == 422
    assert receiver.requests == []


def test_mcp_webhook_onboarding_and_monitor_creation_use_authenticated_api(
    webhook_client, flight_url
):
    client, _, receiver = webhook_client

    def route(request):
        assert request.headers["authorization"] == "Bearer " + KEYS["alice"]
        response = client.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(response.status_code, json=response.json())

    server = make_server("http://127.0.0.1:8001", KEYS["alice"], httpx.MockTransport(route))

    async def exercise():
        names = {tool.name for tool in await server.list_tools()}
        assert {
            "register_webhook",
            "list_webhooks",
            "get_webhook",
            "send_webhook_challenge",
            "verify_webhook",
            "disable_webhook",
            "delete_webhook",
        } <= names
        await server.call_tool(
            "register_webhook", {"url": DESTINATION, "idempotency_key": "mcp-endpoint"}
        )
        endpoint = client.get("/v1/webhooks", headers=auth()).json()["items"][0]
        arguments = {"webhook_id": endpoint["id"]}
        for tool, params in (
            ("list_webhooks", {}),
            ("get_webhook", arguments),
            ("send_webhook_challenge", arguments),
        ):
            result = await server.call_tool(tool, params)
            assert not result.is_error
        token = receiver.requests[-1][1]["data"]["token"]
        await server.call_tool("verify_webhook", {**arguments, "token": token})
        await server.call_tool(
            "create_monitor",
            {"url": flight_url, "idempotency_key": "mcp-webhook-monitor", **arguments},
        )
        monitor = client.get("/v1/monitors", headers=auth()).json()["items"][0]
        assert monitor["webhook_id"] == endpoint["id"]
        for tool in ("disable_webhook", "delete_webhook"):
            result = await server.call_tool(tool, arguments)
            assert not result.is_error
        assert (
            client.get(f"/v1/webhooks/{endpoint['id']}", headers=auth()).json()["status"]
            == "deleted"
        )
        with pytest.raises(ToolError, match="Invalid webhook identifier"):
            await server.call_tool("get_webhook", {"webhook_id": "../../other"})
        with pytest.raises(ToolError, match="Invalid webhook identifier"):
            await server.call_tool(
                "create_monitor",
                {"url": flight_url, "idempotency_key": "empty-webhook-id", "webhook_id": ""},
            )

    asyncio.run(exercise())
