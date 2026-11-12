"""The admin panel: who may open it, what it shows, what it may do, and its record."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fareflare import admin_cli, totp
from fareflare.accounts import Accounts
from fareflare.mailer import MemoryMailer
from fareflare.portal import create_portal
from fareflare.product_config import ProductConfig
from fareflare.service import MonitoringService
from fareflare.store import SQLiteStore

ORIGIN = "https://app.example.com"
ADMIN = "admin@app.example.com"
TEMPORARY = "123"
ADMIN_PASSWORD = "an admin passphrase nobody guesses"
USER_PASSWORD = "a long password for the traveller"


@pytest.fixture
def env(store, clock, flight_url):
    config = ProductConfig(public_url=ORIGIN)
    service = MonitoringService(store, lambda: clock[0], global_target_limit=20)
    accounts = Accounts(store, config, lambda: clock[0], mailer=MemoryMailer())
    app = create_portal(service, config, accounts, auth_attempts_per_minute=500)
    return SimpleNamespace(
        app=app, service=service, accounts=accounts, clock=clock, flight_url=flight_url
    )


def browser(env) -> TestClient:
    return TestClient(env.app, base_url=ORIGIN)


def sign_in(env, name, password, client=None):
    client = client or browser(env)
    response = client.post("/auth/login", json={"username": name, "password": password})
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json().get("csrf_token", "")}, response.json()


def ready_admin(env, email=ADMIN):
    """An admin who replaced the temporary password and turned on two-step sign-in."""
    env.accounts.create_admin(email, TEMPORARY)
    client, csrf, _ = sign_in(env, email, TEMPORARY)
    changed = client.post(
        "/auth/password",
        headers=csrf,
        json={"current_password": TEMPORARY, "new_password": ADMIN_PASSWORD},
    )
    assert changed.status_code == 200, changed.text
    setup = client.post("/auth/two-factor/setup", headers=csrf, json={"password": ADMIN_PASSWORD})
    secret = setup.json()["secret"]
    enabled = client.post(
        "/auth/two-factor/enable",
        headers=csrf,
        json={"code": totp.code_at(secret, env.clock[0] // 30)},
    )
    assert enabled.status_code == 200, enabled.text
    return client, csrf, secret


def traveller(env, email="alice@example.com"):
    env.clock[0] += 61  # Sign-ups from one address are limited per minute.
    client = browser(env)
    created = client.post("/auth/register", json={"email": email, "password": USER_PASSWORD})
    assert created.status_code == 201, created.text
    return client, {"X-CSRF-Token": created.json()["csrf_token"]}, created.json()["account"]["id"]


# --- Getting in ---------------------------------------------------------------------


def test_a_new_admin_signs_in_once_with_the_temporary_password_and_must_replace_it(env):
    created = env.accounts.create_admin(ADMIN, TEMPORARY)
    assert created["account"]["admin"] and created["account"]["must_change_password"]
    client = browser(env)
    wrong = client.post("/auth/login", json={"username": ADMIN, "password": "124"})
    assert wrong.status_code == 401
    client, csrf, signed = sign_in(env, ADMIN, TEMPORARY, client)
    assert signed["account"]["must_change_password"] is True
    assert client.get("/v1/account").status_code == 200
    for path in ("/v1/monitors", "/v1/admin/gate", "/v1/api-keys"):
        blocked = client.get(path)
        assert blocked.status_code == 403 and "new password" in blocked.json()["detail"]
    weak = client.post(
        "/auth/password",
        headers=csrf,
        json={"current_password": TEMPORARY, "new_password": "Password123!"},
    )
    assert weak.status_code == 422
    changed = client.post(
        "/auth/password",
        headers=csrf,
        json={"current_password": TEMPORARY, "new_password": ADMIN_PASSWORD},
    )
    assert changed.status_code == 200
    assert client.get("/v1/account").json()["account"]["must_change_password"] is False
    assert client.get("/v1/monitors").status_code == 200
    env.clock[0] += 61
    assert (
        browser(env)
        .post("/auth/login", json={"username": ADMIN, "password": TEMPORARY})
        .status_code
        == 401
    )  # Spent once replaced.
    sign_in(env, ADMIN, ADMIN_PASSWORD)


def test_a_temporary_password_expires(env):
    env.accounts.create_admin(ADMIN, TEMPORARY, seconds=300)
    env.clock[0] += 301
    response = browser(env).post("/auth/login", json={"username": ADMIN, "password": TEMPORARY})
    assert response.status_code == 401


def test_bootstrap_takes_a_used_address_only_when_told_to_and_then_wipes_it(env):
    client, csrf, tenant = traveller(env, "taken@example.com")
    client.post("/v1/api-keys", headers=csrf, json={"name": "script"})
    with pytest.raises(ValueError, match="--reclaim"):
        env.accounts.create_admin("taken@example.com", TEMPORARY)
    result = env.accounts.create_admin("taken@example.com", TEMPORARY, reclaim=True)
    assert result["reclaimed"] and result["account"]["id"] == tenant
    assert client.get("/v1/account").status_code == 401  # The old holder is signed out.
    env.clock[0] += 61
    old = browser(env).post(
        "/auth/login", json={"username": "taken@example.com", "password": USER_PASSWORD}
    )
    assert old.status_code == 401
    _, _, signed = sign_in(env, "taken@example.com", TEMPORARY)
    assert signed["account"]["admin"] is True


def test_public_sign_up_cannot_use_the_service_domain(env):
    client = browser(env)
    for address in (ADMIN, "ops@mail.app.example.com"):
        refused = client.post("/auth/register", json={"email": address, "password": USER_PASSWORD})
        assert refused.status_code == 422 and "reserved" in refused.json()["detail"]
    client, csrf, _ = traveller(env)
    moved = client.post(
        "/auth/email", headers=csrf, json={"email": ADMIN, "password": USER_PASSWORD}
    )
    assert moved.status_code == 422


def test_the_panel_opens_only_for_an_admin_with_a_second_factor_in_this_session(env):
    client, csrf, _ = traveller(env)
    assert client.get("/v1/admin/gate").status_code == 404  # Not even acknowledged.
    assert client.get("/v1/admin/overview").status_code == 404

    env.accounts.create_admin(ADMIN, TEMPORARY)
    admin, csrf, _ = sign_in(env, ADMIN, TEMPORARY)
    admin.post(
        "/auth/password",
        headers=csrf,
        json={"current_password": TEMPORARY, "new_password": ADMIN_PASSWORD},
    )
    assert admin.get("/v1/admin/gate").json()["reason"] == "mfa"
    assert admin.get("/v1/admin/overview").status_code == 403
    setup = admin.post("/auth/two-factor/setup", headers=csrf, json={"password": ADMIN_PASSWORD})
    secret = setup.json()["secret"]
    admin.post(
        "/auth/two-factor/enable",
        headers=csrf,
        json={"code": totp.code_at(secret, env.clock[0] // 30)},
    )
    gate = admin.get("/v1/admin/gate").json()
    assert gate["ready"] is True and gate["expires_at"] > env.clock[0]
    assert admin.get("/v1/admin/overview").status_code == 200

    env.clock[0] += 12 * 3600  # An admin session is good for twelve hours.
    assert admin.get("/v1/admin/gate").json()["reason"] == "reauth"
    assert admin.get("/v1/admin/overview").status_code == 403
    fresh = browser(env)
    challenge = fresh.post("/auth/login", json={"username": ADMIN, "password": ADMIN_PASSWORD})
    fresh.post(
        "/auth/login/two-factor",
        json={
            "token": challenge.json()["token"],
            "code": totp.code_at(secret, env.clock[0] // 30),
        },
    )
    assert fresh.get("/v1/admin/gate").json()["ready"] is True

    key = admin.post("/v1/api-keys", headers=csrf, json={"name": "script"})
    token = key.json()["api_key"]
    keyed = browser(env).get("/v1/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert keyed.status_code == 401  # An API key never opens the panel.


def test_admin_answers_are_never_cached_and_changes_need_csrf(env):
    admin, csrf, _ = ready_admin(env)
    _, _, tenant = traveller(env)
    response = admin.get("/v1/admin/users")
    assert response.headers["cache-control"] == "no-store"
    assert admin.post(f"/v1/admin/users/{tenant}/sign-out", json={}).status_code == 403
    assert (
        admin.post(f"/v1/admin/users/{tenant}/sign-out", headers=csrf, json={}).status_code == 200
    )


# --- Seeing -----------------------------------------------------------------------


def test_admins_see_every_user_their_flights_and_the_service_but_no_secrets(env):
    admin, _, _ = ready_admin(env)
    client, csrf, tenant = traveller(env)
    traveller(env, "bob@example.com")
    env.service.create_monitor(tenant, env.flight_url, "alice-monitor-1")
    key = client.post("/v1/api-keys", headers=csrf, json={"name": "Spreadsheet sync"}).json()

    users = admin.get("/v1/admin/users").json()
    assert users["total"] == 3 and users["truncated"] is False
    assert [row["email"] for row in users["items"]][:2] == ["bob@example.com", "alice@example.com"]
    found = admin.get("/v1/admin/users", params={"q": "ALI"}).json()["items"]
    assert [row["id"] for row in found] == [tenant]
    assert found[0]["flights"] == 1 and found[0]["api_keys"] == 1
    by_flights = admin.get("/v1/admin/users", params={"sort": "flights"}).json()["items"]
    assert by_flights[0]["id"] == tenant
    admins = admin.get("/v1/admin/users", params={"status": "admins"}).json()["items"]
    assert [row["email"] for row in admins] == [ADMIN]

    detail = admin.get(f"/v1/admin/users/{tenant}").json()
    assert detail["account"]["email"] == "alice@example.com"
    assert detail["account"]["sessions"] == 1
    assert len(detail["flights"]) == 1 and detail["flights"][0]["target"]["segments"]
    assert detail["api_keys"][0]["name"] == "Spreadsheet sync"
    text = json.dumps(detail)
    for secret in ("password_hash", "secret", "csrf", "session_token", key["api_key"]):
        assert secret not in text

    flights = admin.get("/v1/admin/flights").json()
    assert flights["capacity"] == {"used": 1, "limit": 20}
    assert flights["items"][0]["watchers"][0]["email"] == "alice@example.com"

    overview = admin.get("/v1/admin/overview").json()
    assert overview["users"]["total"] == 3 and overview["users"]["admins"] == 1
    assert overview["users"]["two_factor"] == 1 and overview["users"]["new_day"] == 3
    assert overview["signups"][-1]["count"] == 3 and len(overview["signups"]) == 30
    assert overview["flights"]["watched"] == 1
    assert overview["flights"]["capacity"]["used"] == 1
    assert overview["switches"] == {"registration_paused": False, "collection_paused": False}
    assert set(overview["email"]) == {"confirm", "reset", "notice"}
    assert overview["config"]["global_target_limit"] == 20
    assert len(overview["collection"]["hours"]) == 24
    assert admin.get("/v1/admin/users/acct_" + "0" * 32).status_code == 404


# --- Acting -------------------------------------------------------------------------


def test_suspending_stops_every_way_in_and_reactivating_restores_sign_in(env):
    admin, csrf, _ = ready_admin(env)
    client, user_csrf, tenant = traveller(env)
    token = client.post("/v1/api-keys", headers=user_csrf, json={"name": "cli"}).json()["api_key"]
    no_reason = admin.post(f"/v1/admin/users/{tenant}/suspend", headers=csrf, json={})
    assert no_reason.status_code == 422
    suspended = admin.post(
        f"/v1/admin/users/{tenant}/suspend", headers=csrf, json={"reason": "Card testing"}
    )
    assert suspended.status_code == 200
    assert client.get("/v1/account").status_code == 401
    keyed = browser(env).get("/v1/monitors", headers={"Authorization": f"Bearer {token}"})
    assert keyed.status_code == 401
    env.clock[0] += 61
    refused = browser(env).post(
        "/auth/login", json={"username": "alice@example.com", "password": USER_PASSWORD}
    )
    assert refused.status_code == 401 and "suspended" in refused.json()["detail"]
    detail = admin.get(f"/v1/admin/users/{tenant}").json()["account"]
    assert detail["status"] == "suspended" and detail["suspended_reason"] == "Card testing"

    assert (
        admin.post(f"/v1/admin/users/{tenant}/reactivate", headers=csrf, json={}).status_code == 200
    )
    sign_in(env, "alice@example.com", USER_PASSWORD)
    actions = [entry["action"] for entry in admin.get("/v1/admin/audit").json()["items"]]
    assert actions == ["reactivate", "suspend"]
    record = admin.get(f"/v1/admin/users/{tenant}").json()["audit"]
    assert record[1]["detail"] == {"reason": "Card testing"}
    assert record[1]["admin"] == ADMIN and record[1]["target"] == "alice@example.com"


def test_support_actions_sign_out_reset_two_step_and_issue_a_temporary_password(env):
    admin, csrf, _ = ready_admin(env)
    client, _, tenant = traveller(env)
    secret = env.accounts.start_two_factor(tenant, USER_PASSWORD)["secret"]
    env.accounts.enable_two_factor(tenant, totp.code_at(secret, env.clock[0] // 30))

    assert (
        admin.post(f"/v1/admin/users/{tenant}/sign-out", headers=csrf, json={}).status_code == 200
    )
    assert client.get("/v1/account").status_code == 401

    reset = admin.post(f"/v1/admin/users/{tenant}/reset-two-factor", headers=csrf, json={})
    assert reset.status_code == 200
    assert admin.get(f"/v1/admin/users/{tenant}").json()["account"]["two_factor"] is False
    again = admin.post(f"/v1/admin/users/{tenant}/reset-two-factor", headers=csrf, json={})
    assert again.status_code == 422

    issued = admin.post(
        f"/v1/admin/users/{tenant}/temporary-password",
        headers=csrf,
        json={"reason": "Lost access, verified by reply"},
    ).json()
    temporary = issued["temporary_password"]
    env.clock[0] += 61
    old = browser(env).post(
        "/auth/login", json={"username": "alice@example.com", "password": USER_PASSWORD}
    )
    assert old.status_code == 401
    _, _, signed = sign_in(env, "alice@example.com", temporary)
    assert signed["account"]["must_change_password"] is True
    assert temporary not in json.dumps(admin.get("/v1/admin/audit").json())


def test_admins_cannot_act_on_themselves_or_on_other_admins_from_the_panel(env):
    admin, csrf, _ = ready_admin(env)
    me = admin.get("/v1/account").json()["account"]["id"]
    other = env.accounts.create_admin("ops@app.example.com", TEMPORARY)["account"]["id"]
    for tenant in (me, other):
        refused = admin.post(
            f"/v1/admin/users/{tenant}/suspend", headers=csrf, json={"reason": "test"}
        )
        assert refused.status_code == 422
    assert admin.post(f"/v1/admin/users/{other}/promote", headers=csrf, json={}).status_code == 404


def test_deleting_needs_the_address_typed_and_a_reason(env):
    admin, csrf, _ = ready_admin(env)
    _, _, tenant = traveller(env)
    wrong = admin.request(
        "DELETE",
        f"/v1/admin/users/{tenant}",
        headers=csrf,
        json={"confirm": "bob@example.com", "reason": "Spam"},
    )
    assert wrong.status_code == 422
    unexplained = admin.request(
        "DELETE", f"/v1/admin/users/{tenant}", headers=csrf, json={"confirm": "alice@example.com"}
    )
    assert unexplained.status_code == 422
    deleted = admin.request(
        "DELETE",
        f"/v1/admin/users/{tenant}",
        headers=csrf,
        json={"confirm": "Alice@Example.com", "reason": "Asked to be removed"},
    )
    assert deleted.status_code == 200
    detail = admin.get(f"/v1/admin/users/{tenant}").json()
    assert detail["account"]["status"] == "deleted" and detail["account"]["email"] is None
    assert admin.get("/v1/admin/users", params={"status": "deleted"}).json()["total"] == 1
    entry = admin.get("/v1/admin/audit").json()["items"][0]
    assert entry["action"] == "delete" and entry["target"] == "alice@example.com"


def test_admins_can_pause_resume_and_stop_a_users_flight(env):
    admin, csrf, _ = ready_admin(env)
    _, _, tenant = traveller(env)
    monitor = env.service.create_monitor(tenant, env.flight_url, "alice-monitor-2")
    path = f"/v1/admin/users/{tenant}/flights/{monitor['id']}"
    assert admin.patch(path, headers=csrf, json={"status": "paused"}).json()["status"] == "paused"
    assert admin.patch(path, headers=csrf, json={"status": "active"}).json()["status"] == "pending"
    stopped = admin.patch(path, headers=csrf, json={"status": "cancelled", "reason": "Abuse"})
    assert stopped.json()["status"] == "cancelled"
    assert admin.get("/v1/admin/flights").json()["capacity"]["used"] == 0
    actions = [entry["action"] for entry in admin.get("/v1/admin/audit").json()["items"]]
    assert actions == ["stop-flight", "resume-flight", "pause-flight"]
    other = admin.patch(
        f"/v1/admin/users/{tenant}/flights/" + "0" * 32, headers=csrf, json={"status": "paused"}
    )
    assert other.status_code == 404


def test_switches_pause_new_sign_ups_and_every_price_check(env):
    admin, csrf, _ = ready_admin(env)
    paused = admin.put("/v1/admin/switches", headers=csrf, json={"registration_paused": True})
    assert paused.json() == {"registration_paused": True, "collection_paused": False}
    env.clock[0] += 61
    refused = browser(env).post(
        "/auth/register", json={"email": "late@example.com", "password": USER_PASSWORD}
    )
    assert refused.status_code == 422 and "paused" in refused.json()["detail"]

    admin.put("/v1/admin/switches", headers=csrf, json={"registration_paused": False})
    _, _, tenant = traveller(env, "early@example.com")
    env.service.create_monitor(tenant, env.flight_url, "early-monitor-1")
    admin.put("/v1/admin/switches", headers=csrf, json={"collection_paused": True})

    class Refuse:
        def collect(self, target):  # pragma: no cover - must not be called
            raise AssertionError("a paused service must not check prices")

    batch = env.service.collect_batch(Refuse(), limit=5)
    assert batch.counts == {"collected": 0, "failed": 0, "skipped": 0}
    assert admin.put("/v1/admin/switches", headers=csrf, json={}).status_code == 422
    entries = admin.get("/v1/admin/audit").json()["items"]
    assert entries[0]["detail"] == {"collection_paused": True}


# --- The command line ---------------------------------------------------------------


def test_the_command_line_makes_lists_and_recovers_admins(tmp_path, capsys):
    database = tmp_path / "admin.sqlite3"
    run = ["--database", str(database)]
    assert (
        admin_cli.main([*run, "bootstrap", "root@example.com", "--temporary-password", "123"]) == 0
    )
    assert "Created admin root@example.com" in capsys.readouterr().out
    assert admin_cli.main([*run, "bootstrap", "root@example.com"]) == 1
    assert "--reclaim" in capsys.readouterr().err
    assert admin_cli.main([*run, "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [row["email"] for row in listed] == ["root@example.com"]

    accounts = Accounts(SQLiteStore(database), ProductConfig())
    accounts.register("helper@example.com", USER_PASSWORD)
    assert admin_cli.main([*run, "grant", "helper@example.com"]) == 0
    assert "is now an admin" in capsys.readouterr().out
    assert admin_cli.main([*run, "revoke", "helper@example.com"]) == 0
    assert "no longer an admin" in capsys.readouterr().out
    assert admin_cli.main([*run, "reset-password", "root@example.com"]) == 0
    printed = capsys.readouterr().out
    temporary = printed.split("Temporary password: ")[1].split()[0]
    assert accounts.login("root@example.com", temporary)["account"]["must_change_password"]
    assert admin_cli.main([*run, "grant", "nobody@example.com"]) == 1
