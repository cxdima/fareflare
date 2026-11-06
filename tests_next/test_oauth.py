"""SDK OAuth protocol and persisted authorization security on both stores."""
import base64
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

from fareflare.accounts import Accounts
from fareflare.oauth import OAuthProvider
from fareflare.store import Document

ORIGIN = "https://fareflare.example"
RESOURCE = ORIGIN + "/mcp"
CALLBACK = "http://127.0.0.1:8765/callback"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
ALICE, BOB = "acct_" + "a" * 32, "acct_" + "b" * 32


@pytest.fixture
def oauth(store):
    clock = [int(time.time())]
    accounts = Accounts(store, clock=lambda: clock[0])
    for tenant in (ALICE, BOB):
        store.commit([Document("account:" + tenant, "accounts", {
            "id": tenant, "status": "active", "auth_epoch": 1,
        })])
    provider = OAuthProvider(store, accounts, ORIGIN, lambda: clock[0])
    app = Starlette(routes=[*provider.discovery_routes(), Mount("/oauth", app=provider.build_app())])
    with TestClient(app, base_url=ORIGIN) as client:
        yield provider, client, clock


def register(client, **extra):
    response = client.post("/oauth/register", json={
        "client_name": "Test MCP client", "redirect_uris": [CALLBACK],
        "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], **extra,
    })
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


def authorize(client, client_id, **extra):
    return client.get("/oauth/authorize", params={
        "client_id": client_id, "redirect_uri": CALLBACK, "response_type": "code",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256", "scope": "monitor",
        "resource": RESOURCE, "state": "client-state", **extra,
    }, follow_redirects=False)


def consent(provider, client, client_id, tenant=ALICE):
    response = authorize(client, client_id)
    assert response.status_code == 302, response.text
    request_id = parse_qs(urlsplit(response.headers["location"]).query)["authorize"][0]
    public = provider.consent_request(tenant, request_id)
    assert public["client_id"] == client_id and public["scopes"] == ["monitor"]
    result = provider.complete_consent(tenant, request_id, True)
    query = parse_qs(urlsplit(result["redirect_url"]).query)
    assert query["state"] == ["client-state"] and query["iss"] == [ORIGIN + "/oauth"]
    return query["code"][0]


def exchange(client, client_id, code, **extra):
    return client.post("/oauth/token", data={
        "grant_type": "authorization_code", "client_id": client_id, "code": code,
        "redirect_uri": CALLBACK, "code_verifier": VERIFIER, "resource": RESOURCE, **extra,
    })


def issued(oauth):
    provider, client, _ = oauth
    client_id = register(client)
    code = consent(provider, client, client_id)
    response = exchange(client, client_id, code)
    assert response.status_code == 200, response.text
    return client_id, response.json()


def refresh(client, client_id, token, **extra):
    return client.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id,
                                            "refresh_token": token, "resource": RESOURCE, **extra})


def test_discovery_full_code_flow_and_hashed_storage(oauth, store):
    provider, client, _ = oauth
    metadata = client.get("/.well-known/oauth-authorization-server/oauth").json()
    assert metadata["issuer"] == ORIGIN + "/oauth"
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["authorization_response_iss_parameter_supported"] is True
    assert client.get("/oauth/.well-known/oauth-authorization-server").json() == metadata
    protected = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert protected["resource"] == RESOURCE
    assert protected["authorization_servers"] == [ORIGIN + "/oauth"]
    assert protected["scopes_supported"] == ["monitor"]
    client_id = register(client)
    code = consent(provider, client, client_id)
    response = exchange(client, client_id, code)
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert tokens["expires_in"] == 900 and tokens["scope"] == "monitor"
    assert provider.bearer_to_tenant(tokens["access_token"]) == ALICE
    assert provider.bearer_to_tenant(tokens["refresh_token"]) is None
    persisted = json.dumps([{"key": doc.key, "data": doc.data} for part in (
        "oauth-codes", "oauth-tokens", "oauth-requests", "oauth-grants:" + ALICE,
    ) for doc in store.query(part)])
    for secret in (code, tokens["access_token"], tokens["refresh_token"], VERIFIER):
        assert secret not in persisted
    # Persistence works across Lambda instances, without in-memory auth state.
    fresh = OAuthProvider(store, provider.accounts, ORIGIN, provider.clock)
    assert fresh.bearer_to_tenant(tokens["access_token"]) == ALICE
    assert exchange(client, client_id, code).status_code == 400


def test_wrong_pkce_redirect_audience_and_client_cannot_spend_code(oauth):
    provider, client, _ = oauth
    client_id, stranger = register(client), register(client)
    code = consent(provider, client, client_id)
    assert exchange(client, stranger, code).status_code == 400
    assert exchange(client, client_id, code, code_verifier="z" * 64).json()["error"] == "invalid_grant"
    assert exchange(client, client_id, code, redirect_uri="https://evil.example/").status_code == 400
    assert exchange(client, client_id, code, resource="https://evil.example/mcp").json()["error"] == "invalid_target"
    assert exchange(client, client_id, code, resource="").json()["error"] == "invalid_target"
    assert exchange(client, client_id, code).status_code == 200


def test_code_exchange_is_atomic_under_concurrency(oauth):
    provider, client, _ = oauth
    client_id = register(client)
    code = consent(provider, client, client_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(exchange, client, client_id, code) for _ in range(2)]
        assert sorted(future.result().status_code for future in futures) == [200, 400]


def test_refresh_rotation_and_replay_revoke_the_entire_grant(oauth):
    provider, client, _ = oauth
    client_id, original = issued(oauth)
    rotated = refresh(client, client_id, original["refresh_token"])
    assert rotated.status_code == 200, rotated.text
    replacement = rotated.json()
    assert replacement["refresh_token"] != original["refresh_token"]
    assert provider.bearer_to_tenant(original["access_token"]) == ALICE
    assert provider.bearer_to_tenant(replacement["access_token"]) == ALICE
    assert refresh(client, client_id, original["refresh_token"]).status_code == 400
    assert provider.bearer_to_tenant(original["access_token"]) is None
    assert provider.bearer_to_tenant(replacement["access_token"]) is None
    assert refresh(client, client_id, replacement["refresh_token"]).status_code == 400


def test_wrong_client_cannot_revoke_or_refresh_another_grant(oauth):
    provider, client, _ = oauth
    client_id, tokens = issued(oauth)
    stranger = register(client)
    assert refresh(client, stranger, tokens["refresh_token"]).status_code == 400
    assert refresh(client, client_id, tokens["refresh_token"], scope="monitor admin").status_code == 400
    assert client.post("/oauth/revoke", data={"client_id": stranger, "token": tokens["access_token"]}).status_code == 200
    assert provider.bearer_to_tenant(tokens["access_token"]) == ALICE
    assert client.post("/oauth/revoke", data={"client_id": client_id, "token": tokens["access_token"]}).status_code == 200
    assert provider.bearer_to_tenant(tokens["access_token"]) is None
    assert refresh(client, client_id, tokens["refresh_token"]).status_code == 400


def test_account_epoch_invalidates_codes_access_and_refresh(oauth, store):
    provider, client, _ = oauth
    client_id, tokens = issued(oauth)
    code = consent(provider, client, client_id)
    account = store.get("account:" + ALICE)
    store.commit([account.update({**account.data, "auth_epoch": 2})])
    assert provider.bearer_to_tenant(tokens["access_token"]) is None
    assert refresh(client, client_id, tokens["refresh_token"]).status_code == 400
    assert exchange(client, client_id, code).status_code == 400


def test_expiry_is_enforced_before_background_ttl_deletion(oauth):
    provider, client, clock = oauth
    client_id, tokens = issued(oauth)
    code = consent(provider, client, client_id)
    clock[0] += 121
    assert exchange(client, client_id, code).status_code == 400
    clock[0] += 900
    assert provider.bearer_to_tenant(tokens["access_token"]) is None
    assert refresh(client, client_id, tokens["refresh_token"]).status_code == 200
    clock[0] += 30 * 86400
    assert refresh(client, client_id, tokens["refresh_token"]).status_code == 400


def test_consent_binding_deny_and_no_approval_without_preview(oauth):
    provider, client, _ = oauth
    client_id = register(client)
    response = authorize(client, client_id)
    request_id = parse_qs(urlsplit(response.headers["location"]).query)["authorize"][0]
    with pytest.raises(ValueError):
        provider.complete_consent(ALICE, request_id, True)
    provider.consent_request(ALICE, request_id)
    with pytest.raises(ValueError):
        provider.consent_request(BOB, request_id)
    with pytest.raises(ValueError):
        provider.complete_consent(BOB, request_id, True)
    denied = provider.complete_consent(ALICE, request_id, False)
    query = parse_qs(urlsplit(denied["redirect_url"]).query)
    assert query["error"] == ["access_denied"] and query["state"] == ["client-state"]
    assert "code" not in query
    with pytest.raises(ValueError):
        provider.complete_consent(ALICE, request_id, True)


@pytest.mark.parametrize("uri", ["http://evil.example/callback", "https://user:pass@example.com/callback",
                                "https://example.com/callback#fragment", "javascript:alert(1)"])
def test_registration_rejects_unsafe_redirects(oauth, uri):
    _, client, _ = oauth
    response = client.post("/oauth/register", json={"client_name": "Bad callback", "redirect_uris": [uri],
                                                  "token_endpoint_auth_method": "none"})
    assert response.status_code == 400


def test_registration_limits_confidential_clients_and_body_size(oauth):
    _, client, _ = oauth
    response = client.post("/oauth/register", json={"client_name": "Secret client", "redirect_uris": [CALLBACK],
                                                  "token_endpoint_auth_method": "client_secret_post"})
    assert response.status_code == 400
    assert client.post("/oauth/register", content=b"x" * 17000).status_code == 413
    for _ in range(4):
        register(client)
    assert client.post("/oauth/register", json={}).status_code == 429


def test_authorization_requires_registered_redirect_and_s256(oauth):
    _, client, _ = oauth
    client_id = register(client)
    invalid = authorize(client, client_id, redirect_uri="https://evil.example/callback")
    assert invalid.status_code == 400 and "location" not in invalid.headers
    assert authorize(client, client_id, code_challenge_method="plain").status_code == 400
    assert authorize(client, client_id, resource="https://evil.example/mcp").status_code == 400
    duplicate = client.get("/oauth/authorize?resource=a&resource=b")
    assert duplicate.status_code == 400
    scope_error = authorize(client, client_id, scope="admin")
    assert scope_error.status_code == 302
    assert parse_qs(urlsplit(scope_error.headers["location"]).query)["iss"] == [ORIGIN + "/oauth"]
