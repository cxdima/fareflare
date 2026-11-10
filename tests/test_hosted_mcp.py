"""Actual MCP protocol exchanges, including a networked official SDK client."""

import asyncio
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.routing import Route

from fareflare.api import create_app
from fareflare.hosted_mcp import make_hosted_mcp

KEYS = {"alice": "a" * 40, "bob": "b" * 40}
HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}


def application(service, keys=None, authenticate=None):
    keys = keys if keys is not None else dict(KEYS)
    app = create_app(service, keys)
    adapter = make_hosted_mcp(
        app,
        authenticate
        or (lambda token: next((name for name, key in keys.items() if key == token), None)),
        allowed_hosts=["testserver", "127.0.0.1:*"],
        allowed_origins=["https://app.example"],
    )
    app.router.routes.append(Route("/mcp", endpoint=adapter))
    return app


def rpc(client, method, params=None, tenant="alice"):
    return client.post(
        "/mcp",
        headers={**HEADERS, "Authorization": "Bearer " + KEYS[tenant]},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def tool(client, name, args=None, tenant="alice"):
    response = rpc(client, "tools/call", {"name": name, "arguments": args or {}}, tenant)
    assert response.status_code == 200
    return response.json()["result"]


def test_hosted_tools_share_api_tenancy_and_projection(service, flight_url):
    app = application(service)
    with TestClient(app) as client:
        initialized = rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        assert initialized.status_code == 200
        assert "mcp-session-id" not in initialized.headers
        assert initialized.headers["cache-control"] == "no-store"
        names = {item["name"] for item in rpc(client, "tools/list").json()["result"]["tools"]}
        assert {
            "create_monitor",
            "list_monitors",
            "get_price_history",
            "update_policy",
            "verify_webhook",
        } <= names
        result = tool(
            client, "create_monitor", {"url": flight_url, "idempotency_key": "hosted-create"}
        )
        monitor = result["structuredContent"]
        assert "rule_state" not in monitor and "provider_query" not in monitor["target"]
        assert tool(client, "get_monitor", {"monitor_id": monitor["id"]}, "bob")["isError"]
        assert tool(client, "list_monitors", tenant="bob")["structuredContent"]["items"] == []
        assert (
            tool(client, "pause_monitor", {"monitor_id": monitor["id"]})["structuredContent"][
                "status"
            ]
            == "paused"
        )
        assert (
            tool(client, "get_price_history", {"monitor_id": monitor["id"]})["structuredContent"][
                "items"
            ]
            == []
        )


def test_credentials_checked_on_every_request_and_never_from_cookie(service):
    keys = dict(KEYS)
    app = application(service, keys)
    with TestClient(app) as client:
        assert rpc(client, "tools/list").status_code == 200
        del keys["alice"]
        assert rpc(client, "tools/list").status_code == 401
        response = client.post(
            "/mcp", headers={**HEADERS, "Cookie": "api_key=" + KEYS["bob"]}, json={}
        )
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert KEYS["bob"] not in response.text


def test_request_boundaries_and_dns_rebinding_protection(service):
    with TestClient(application(service)) as client:
        headers = {**HEADERS, "Authorization": "Bearer " + KEYS["alice"]}
        for extra, status in (
            ({"Host": "evil.example"}, 421),
            ({"Origin": "https://evil.example"}, 403),
        ):
            assert client.post("/mcp", headers={**headers, **extra}, json={}).status_code == status
        assert client.post("/mcp", headers=headers, content=b"x" * 17000).status_code == 413
        assert client.get("/mcp", headers=headers).status_code == 405
        assert client.delete("/mcp", headers=headers).status_code == 405
        duplicate = [
            ("authorization", "Bearer " + KEYS["alice"]),
            ("authorization", "Bearer " + KEYS["bob"]),
        ]
        assert client.post("/mcp", headers=duplicate, json={}).status_code == 400


def test_warm_lifespans_and_concurrent_credentials_are_isolated(service, flight_url):
    app = application(service)
    for _ in range(2):
        with TestClient(app) as client:
            assert rpc(client, "tools/list").status_code == 200
    with TestClient(app) as client:
        tool(client, "create_monitor", {"url": flight_url, "idempotency_key": "parallel-create"})
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                (tenant, pool.submit(tool, client, "list_monitors", None, tenant))
                for tenant in ["alice", "bob"] * 4
            ]
            for tenant, future in futures:
                assert len(future.result()["structuredContent"]["items"]) == (
                    1 if tenant == "alice" else 0
                )


def test_official_client_session_over_loopback_http(service, flight_url):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(application(service), log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "HTTP server failed to start"
            time.sleep(0.01)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"

        async def exercise():
            async with (
                httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + KEYS["alice"]}, trust_env=False
                ) as client,
                streamable_http_client(url, http_client=client) as streams,
                ClientSession(*streams, read_timeout_seconds=5) as session,
            ):
                initialized = await session.initialize()
                assert initialized.server_info.name == "fareflare"
                assert len((await session.list_tools()).tools) == 21
                created = await session.call_tool(
                    "create_monitor",
                    {"url": flight_url, "idempotency_key": "real-sdk-http-create"},
                )
                assert not created.is_error
                listed = await session.call_tool("list_monitors", {})
                assert len(listed.structured_content["items"]) == 1

        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()


def test_hosted_configuration_requires_allowlists(service):
    for hosts, origins in (([], []), (["*"], []), (["example.com"], ["*"])):
        with pytest.raises(ValueError):
            make_hosted_mcp(
                create_app(service, KEYS),
                lambda _: "alice",
                allowed_hosts=hosts,
                allowed_origins=origins,
            )
