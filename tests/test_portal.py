import pytest
from fastapi.testclient import TestClient

from fareflare.accounts import Accounts
from fareflare.portal import create_portal
from fareflare.product_config import ProductConfig
from fareflare.service import MonitoringService

PASSWORD = "a long test password for signup"


@pytest.fixture
def portal(store, clock):
    config = ProductConfig(public_url="https://app.example.com")
    service = MonitoringService(
        store, lambda: clock[0], monitor_limit=3, min_interval_seconds=900, global_target_limit=20
    )
    accounts = Accounts(store, config, lambda: clock[0])
    app = create_portal(service, config, accounts)
    with TestClient(app, base_url=config.public_url) as client:
        yield client, accounts, service


def signup(client, accounts, name="traveler"):
    email = name if "@" in name else name + "@example.com"
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response


def test_signup_cookie_csrf_key_and_logout(portal, flight_url):
    client, accounts, _ = portal
    assert client.get("/v1/config").json()["billing_enabled"] is False
    assert client.get("/v1/account").status_code == 401
    denied = client.post("/auth/register", json={"username": "traveler", "password": PASSWORD})
    assert denied.status_code == 422
    assert client.get("/v1/config").json()["registration_mode"] == "open"
    response = signup(client, accounts)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "session_token" not in response.json()
    csrf = response.json()["csrf_token"]
    assert client.get("/v1/account").json()["csrf_token"] == csrf
    headers = {"X-CSRF-Token": csrf}
    assert client.post("/v1/api-keys", json={"name": "test"}).status_code == 403
    assert client.post("/v1/api-keys?require_csrf=false", json={"name": "test"}).status_code == 403
    rejected = client.post(
        "/v1/api-keys",
        headers={**headers, "Origin": "https://attacker.example"},
        json={"name": "test"},
    )
    assert rejected.status_code == 403
    key = client.post("/v1/api-keys", headers=headers, json={"name": "developer"}).json()
    assert "api_key" not in str(client.get("/v1/api-keys").json())
    created = client.post(
        "/v1/monitors",
        headers={**headers, "Idempotency-Key": "portal-monitor"},
        json={"url": flight_url},
    )
    assert created.status_code == 202, created.text
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/v1/monitors").status_code == 401
    assert (
        client.get(
            "/v1/monitors", headers={"Authorization": "Bearer " + key["api_key"]}
        ).status_code
        == 200
    )


def test_account_deletion_revokes_keys_and_stops_work(portal, flight_url):
    client, accounts, service = portal
    response = signup(client, accounts)
    csrf = {"X-CSRF-Token": response.json()["csrf_token"]}
    key = client.post("/v1/api-keys", headers=csrf, json={"name": "integration"}).json()["api_key"]
    monitor = client.post(
        "/v1/monitors",
        headers={**csrf, "Idempotency-Key": "delete-monitor"},
        json={"url": flight_url},
    ).json()
    result = client.request("DELETE", "/v1/account", headers=csrf, json={"password": PASSWORD})
    assert result.status_code == 200, result.text
    assert client.get("/v1/monitors", headers={"Authorization": "Bearer " + key}).status_code == 401
    assert service._active_subscribers(monitor["target_id"]) == []


def test_security_headers_host_and_cross_origin_signup(portal):
    client, _, _ = portal
    response = client.get("/v1/config")
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "max-age=" in response.headers["strict-transport-security"]
    assert client.get("/v1/config", headers={"host": "attacker.example"}).status_code == 400
    assert (
        client.post(
            "/auth/register",
            headers={"Origin": "https://attacker.example"},
            json={"email": "traveler@example.com", "password": PASSWORD},
        ).status_code
        == 403
    )


def test_public_auth_is_rate_limited_before_password_hashing(portal):
    client, _, _ = portal
    for _ in range(8):
        assert (
            client.post(
                "/auth/login", json={"username": "missing", "password": PASSWORD}
            ).status_code
            == 401
        )
    assert (
        client.post("/auth/login", json={"username": "missing", "password": PASSWORD}).status_code
        == 429
    )


def test_reference_and_validation_do_not_need_remote_scripts_or_echo_passwords(portal):
    client, _, _ = portal
    reference = client.get("/docs")
    assert reference.status_code == 200
    assert "/v1/monitors" in reference.text and "/openapi.json" in reference.text
    assert "<script" not in reference.text
    oversized_password = "do-not-echo-this-password" * 12
    invalid = client.post("/auth/login", json={"username": "alice", "password": oversized_password})
    assert invalid.status_code == 422
    assert oversized_password not in invalid.text


def test_unsaved_telegram_preview_requires_session_csrf_and_never_persists(portal):
    client, accounts, service = portal
    identity = signup(client, accounts).json()
    account_id = identity["account"]["id"]
    original = service.preferences(account_id)
    body = {"time_zone": "America/Chicago", "telegram_silent": True}
    assert client.post("/v1/preferences/telegram-preview", json=body).status_code == 403
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    response = client.post("/v1/preferences/telegram-preview", headers=headers, json=body)
    assert response.status_code == 200
    assert response.json()["silent"] is True
    assert "America/Chicago" in response.json()["text"]
    assert service.preferences(account_id) == original
    rejected = client.post(
        "/v1/preferences/telegram-preview",
        json=body,
        headers={**headers, "Origin": "https://attacker.example"},
    )
    assert rejected.status_code == 403


def test_open_signup_is_bounded_by_peer_not_spoofed_forwarded_headers(store, clock):
    config = ProductConfig(public_url="https://fareflare.dev")
    service = MonitoringService(store, lambda: clock[0], monitor_limit=config.monitor_limit)
    accounts = Accounts(store, config, lambda: clock[0])
    app = create_portal(service, config, accounts)
    with TestClient(app, base_url=config.public_url) as client:
        assert client.get("/v1/config").json()["limits"]["monitors"] == 20
        for index in range(3):
            response = client.post(
                "/auth/register",
                json={"email": f"openuser{index}@example.com", "password": PASSWORD},
                headers={"X-Forwarded-For": f"203.0.113.{index}"},
            )
            assert response.status_code == 201
        blocked = client.post(
            "/auth/register",
            json={"email": "blockeduser@example.com", "password": PASSWORD},
            headers={"X-Forwarded-For": "198.51.100.12"},
        )
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "60"
        clock[0] += 61
        assert (
            client.post(
                "/auth/register",
                json={"email": "nextminute@example.com", "password": PASSWORD},
            ).status_code
            == 201
        )


def test_old_browser_origin_redirects_but_api_and_webhook_paths_remain_available(store, clock):
    config = ProductConfig(
        public_url="https://fareflare.dev", additional_hosts=("old.example.com",)
    )
    app = create_portal(MonitoringService(store, lambda: clock[0]), config)
    with TestClient(app, base_url="https://old.example.com", follow_redirects=False) as client:
        response = client.get("/login?authorize=example")
        assert response.status_code == 308
        assert response.headers["location"] == "https://fareflare.dev/login?authorize=example"
        assert client.get("/v1/config").status_code == 200
        assert (
            client.post(
                "/auth/login",
                json={"username": "user", "password": PASSWORD},
                headers={"Origin": "https://old.example.com"},
            ).status_code
            == 403
        )
        assert client.get("/", headers={"Host": "attacker.example.com"}).status_code == 400


def test_twenty_monitor_quota_rejects_twenty_first_and_releases_on_stop(store, clock, flight_url):
    service = MonitoringService(
        store, lambda: clock[0], monitor_limit=ProductConfig().monitor_limit
    )
    monitors = [
        service.create_monitor("quotauser", flight_url, f"quota-request-{index}")
        for index in range(20)
    ]
    with pytest.raises(ValueError, match="quota"):
        service.create_monitor("quotauser", flight_url, "quota-request-over")
    service.set_status("quotauser", monitors[0]["id"], "cancelled")
    service.create_monitor("quotauser", flight_url, "quota-request-replacement")
    assert store.get("tenant:quotauser").data["monitors"] == 20
