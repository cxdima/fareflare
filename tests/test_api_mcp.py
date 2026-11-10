import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from fareflare.api import create_app
from fareflare.mcp_server import make_server
from fareflare.service import Reading

KEYS = {"alice": "a" * 40, "bob": "b" * 40}


def auth(tenant="alice"):
    return {"Authorization": "Bearer " + KEYS[tenant]}


@pytest.fixture
def client(service):
    with TestClient(create_app(service, KEYS)) as client:
        yield client


def create(client, url, tenant="alice", key="create-request"):
    return client.post(
        "/v1/monitors", json={"url": url}, headers={**auth(tenant), "Idempotency-Key": key}
    )


def test_api_create_requires_auth_and_idempotency_key(client, flight_url):
    assert client.get("/health").json()["live_collection"] is False
    assert client.get("/v1/monitors").status_code == 401
    assert client.post("/v1/monitors", json={"url": flight_url}, headers=auth()).status_code == 422
    response = create(client, flight_url)
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["latest"] is None
    assert "rule_state" not in response.json()
    assert "last_sequence" not in response.json()
    assert "provider_query" not in response.json()["target"]
    assert response.headers["Cache-Control"] == "no-store"
    assert create(client, flight_url).json()["id"] == response.json()["id"]


def test_api_monitor_ownership_and_policy_validation(client, flight_url):
    monitor = create(client, flight_url).json()
    assert client.get(f"/v1/monitors/{monitor['id']}", headers=auth("bob")).status_code == 404
    assert (
        client.get(f"/v1/monitors/{monitor['id']}/history", headers=auth("bob")).status_code == 404
    )
    assert client.get("/v1/monitors", headers=auth("bob")).json() == {
        "items": [],
        "next_cursor": None,
        "active_count": 0,
    }
    response = client.post(
        "/v1/monitors",
        headers={**auth(), "Idempotency-Key": "threshold-missing"},
        json={"url": flight_url, "policy": {"kind": "below_price"}},
    )
    assert response.status_code == 422
    assert (
        client.patch(
            f"/v1/monitors/{monitor['id']}", json={"status": "paused"}, headers=auth()
        ).json()["status"]
        == "paused"
    )


def test_api_rejects_unsupported_input_and_conflicting_idempotency(client, flight_url):
    assert create(client, "https://localhost/admin").status_code == 422
    assert create(client, flight_url).status_code == 202
    response = client.post(
        "/v1/monitors",
        headers={**auth(), "Idempotency-Key": "create-request"},
        json={"url": flight_url, "interval_seconds": 300},
    )
    assert response.status_code == 409
    assert client.post("/v1/monitors", content=b"x" * 17000, headers=auth()).status_code == 413


def test_api_history_and_alerts_expose_observation_freshness(client, service, flight_url, clock):
    monitor = create(client, flight_url).json()
    service.record(
        Reading(monitor["target_id"], 45000, "USD", clock[0], "test-fixture"), "observed"
    )
    service.process_events()
    assert (
        client.get(f"/v1/monitors/{monitor['id']}/history", headers=auth()).json()["items"][0][
            "source"
        ]
        == "test-fixture"
    )
    assert len(client.get("/v1/alerts", headers=auth()).json()["items"]) == 1
    assert client.get("/v1/alerts", headers=auth("bob")).json()["items"] == []
    clock[0] += 1801
    assert client.get(f"/v1/monitors/{monitor['id']}", headers=auth()).json()["stale"] is True


def test_weak_or_duplicate_service_credentials_are_rejected(service):
    for keys in ({}, {"alice": "short"}, {"alice": "x" * 32, "bob": "x" * 32}):
        with pytest.raises(ValueError):
            create_app(service, keys)


def test_mcp_tools_use_the_same_authenticated_api(client, flight_url):
    def route(request):
        assert request.headers["authorization"] == "Bearer " + KEYS["alice"]
        response = client.request(
            request.method, request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(response.status_code, json=response.json())

    server = make_server("http://127.0.0.1:8001", KEYS["alice"], httpx.MockTransport(route))

    async def exercise():
        names = {tool.name for tool in await server.list_tools()}
        assert {"create_monitor", "get_price_history", "pause_monitor", "stop_monitor"} <= names
        await server.call_tool(
            "create_monitor", {"url": flight_url, "idempotency_key": "from-mcp-request"}
        )
        monitor = client.get("/v1/monitors", headers=auth()).json()["items"][0]
        for tool, arguments in (
            ("list_monitors", {}),
            ("get_monitor", {"monitor_id": monitor["id"]}),
            ("get_price_history", {"monitor_id": monitor["id"]}),
            ("list_alerts", {}),
            ("pause_monitor", {"monitor_id": monitor["id"]}),
            ("resume_monitor", {"monitor_id": monitor["id"]}),
            ("stop_monitor", {"monitor_id": monitor["id"]}),
        ):
            result = await server.call_tool(tool, arguments)
            assert not result.model_dump(by_alias=True).get("isError", False)
        assert (
            client.get(f"/v1/monitors/{monitor['id']}", headers=auth()).json()["status"]
            == "cancelled"
        )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:password@example.com",
        "file:///tmp/api",
        "https://example.com?token=x",
    ],
)
def test_mcp_rejects_insecure_service_configuration(url):
    with pytest.raises(ValueError):
        make_server(url, "x" * 32)


def test_mcp_does_not_forward_credentials_to_redirects():
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    server = make_server("https://api.example.com", "x" * 32, httpx.MockTransport(redirect))
    with pytest.raises(ToolError, match="HTTP 302"):
        asyncio.run(server.call_tool("list_monitors", {}))
    assert len(calls) == 1


def test_mcp_network_errors_are_sanitized_and_identifiers_validated():
    def fail(request):
        raise httpx.ConnectError("sensitive implementation detail", request=request)

    server = make_server("http://127.0.0.1:8001", "x" * 32, httpx.MockTransport(fail))
    with pytest.raises(ToolError, match="API unavailable") as exc:
        asyncio.run(server.call_tool("list_monitors", {}))
    assert "sensitive" not in str(exc.value)
    with pytest.raises(ToolError, match="Invalid monitor identifier"):
        asyncio.run(server.call_tool("get_monitor", {"monitor_id": "../../admin"}))
