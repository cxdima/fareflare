"""Exercise the composed portal across OAuth, MCP, and API Gateway boundaries."""

import asyncio
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from mangum import Mangum

from fareflare.accounts import Accounts
from fareflare.portal import create_portal
from fareflare.product_config import ProductConfig
from fareflare.service import MonitoringService

ORIGIN = "https://app.example.com"
PASSWORD = "correct test password for integrations"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-11-25",
}


@pytest.fixture
def product(store, clock):
    clock[0] = int(time.time())  # The official OAuth token handler also checks wall time.
    service = MonitoringService(store, lambda: clock[0])
    accounts = Accounts(store, clock=lambda: clock[0])
    result = accounts.register("traveler", PASSWORD, accounts.create_invite()["token"])
    app = create_portal(service, ProductConfig(public_url=ORIGIN), accounts)
    return app, accounts, result


def test_portal_oauth_pkce_consent_audience_and_revocation(product, flight_url):
    app, _, signed_in = product
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        for endpoint in ("/oauth/register", "/oauth/token"):
            preflight = client.options(
                endpoint,
                headers={
                    "Origin": "https://client.example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert preflight.status_code == 200, preflight.text
            assert preflight.headers["access-control-allow-origin"] == "*"
        discovery = client.get("/.well-known/oauth-protected-resource/mcp").json()
        assert discovery["resource"] == ORIGIN + "/mcp"
        assert discovery["authorization_servers"] == [ORIGIN + "/oauth"]
        metadata = client.get("/.well-known/oauth-authorization-server/oauth").json()
        assert metadata["authorization_endpoint"] == ORIGIN + "/oauth/authorize"
        assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
        registered = client.post(
            "/oauth/register",
            json={
                "client_name": "Fareflare integration test",
                "redirect_uris": ["http://127.0.0.1:8787/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "monitor",
            },
        )
        assert registered.status_code == 201, registered.text
        client_id = registered.json()["client_id"]
        verifier = "v" * 64
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        authorize = client.get(
            "/oauth/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:8787/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "monitor",
                "state": "bound-to-client-session",
                "resource": ORIGIN + "/mcp",
            },
        )
        assert authorize.status_code == 302, authorize.text
        request_id = parse_qs(urlsplit(authorize.headers["location"]).query)["authorize"][0]
        path = "/v1/oauth/requests/" + request_id
        assert client.get(path).status_code == 401
        client.cookies.set("__Host-fareflare_session", signed_in["session_token"])
        assert client.get(path).json()["resource"] == ORIGIN + "/mcp"
        assert client.post(path, json={"approve": True}).status_code == 403
        consent = client.post(
            path, json={"approve": True}, headers={"X-CSRF-Token": signed_in["csrf_token"]}
        )
        assert consent.status_code == 200, consent.text
        redirect = parse_qs(urlsplit(consent.json()["redirect_url"]).query)
        assert redirect["state"] == ["bound-to-client-session"]
        token_input = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": redirect["code"][0],
            "code_verifier": verifier,
            "redirect_uri": "http://127.0.0.1:8787/callback",
            "resource": ORIGIN + "/mcp",
        }
        wrong_audience = client.post(
            "/oauth/token", data={**token_input, "resource": ORIGIN + "/v1"}
        )
        assert wrong_audience.status_code == 400
        issued = client.post("/oauth/token", data=token_input)
        assert issued.status_code == 200, issued.text
        token = issued.json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/v1/monitors", headers=headers).status_code == 401
        assert (
            client.get(
                "/v1/monitors", headers={**headers, "fareflare.mcp_internal": "true"}
            ).status_code
            == 401
        )
        called = client.post(
            "/mcp",
            headers={**headers, **MCP_HEADERS},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "create_monitor",
                    "arguments": {"url": flight_url, "idempotency_key": "oauth-actual-monitor"},
                },
            },
        )
        assert called.status_code == 200, called.text
        assert not called.json()["result"].get("isError")
        assert called.json()["result"]["structuredContent"]["status"] == "pending"
        grants = client.get("/v1/oauth/grants").json()["items"]
        assert len(grants) == 1 and grants[0]["client_name"] == "Fareflare integration test"
        assert token not in str(grants) and "refresh_digest" not in str(grants)
        assert client.delete("/v1/oauth/grants/" + grants[0]["id"]).status_code == 403
        revoked = client.post("/oauth/revoke", data={"token": token, "client_id": client_id})
        assert revoked.status_code == 200, revoked.text
        assert client.post("/mcp", headers={**headers, **MCP_HEADERS}, json={}).status_code == 401
        assert client.get("/v1/oauth/grants").json()["items"][0]["revoked"] is True
        assert (
            client.delete(
                "/v1/oauth/grants/" + grants[0]["id"],
                headers={"X-CSRF-Token": signed_in["csrf_token"]},
            ).status_code
            == 200
        )


def test_warm_api_gateway_invocations_preserve_cookies_and_stateless_mcp(product):
    app, accounts, signed_in = product
    key = accounts.issue_api_key(signed_in["account"]["id"], "gateway-test")["api_key"]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    adapter = Mangum(app, lifespan="off")

    def invoke(path, method="GET", body=None, headers=None, cookies=None):
        return adapter(
            {
                "version": "2.0",
                "routeKey": "$default",
                "rawPath": path,
                "rawQueryString": "",
                "headers": {
                    "host": "app.example.com",
                    "content-type": "application/json",
                    **(headers or {}),
                },
                "requestContext": {
                    "http": {
                        "method": method,
                        "path": path,
                        "sourceIp": "192.0.2.1",
                        "protocol": "HTTP/1.1",
                    },
                    "domainName": "app.example.com",
                    "stage": "$default",
                },
                "cookies": cookies or [],
                "body": json.dumps(body) if body is not None else "",
                "isBase64Encoded": False,
            },
            None,
        )

    try:
        assert invoke("/v1/config")["statusCode"] == 200
        login = invoke("/auth/login", "POST", {"username": "traveler", "password": PASSWORD})
        assert login["statusCode"] == 200
        cookie = login["cookies"][0].split(";", 1)[0]
        assert invoke("/v1/account", cookies=[cookie])["statusCode"] == 200
        for _ in range(3):
            result = invoke(
                "/mcp",
                "POST",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {**MCP_HEADERS, "Authorization": "Bearer " + key},
            )
            assert result["statusCode"] == 200, result
            assert len(json.loads(result["body"])["result"]["tools"]) == 20
        anonymous = invoke("/mcp", "POST", {}, MCP_HEADERS)
        assert anonymous["statusCode"] == 401
        assert "resource_metadata" in anonymous["headers"]["www-authenticate"]
    finally:
        loop.close()
        asyncio.set_event_loop(None)
