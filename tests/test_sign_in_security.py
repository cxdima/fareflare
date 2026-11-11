"""Two-step codes, passkeys, email confirmation and password reset."""

import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from fareflare import totp
from fareflare.accounts import Accounts, AuthenticationFailed, IncorrectPassword
from fareflare.credentials import RateLimited
from fareflare.mailer import FileMailer, MemoryMailer, SesMailer, mailer_from_env
from fareflare.passkeys import MAX_PASSKEYS, PasskeyRejected
from fareflare.portal import create_portal
from fareflare.product_config import ProductConfig
from fareflare.service import MonitoringService
from tests.softauthn import SoftPasskey

PASSWORD = "a long password for sign-in tests"
NEW_PASSWORD = "a different long password entirely"
ORIGIN = "https://app.example.com"


@pytest.fixture
def mailer():
    return MemoryMailer()


@pytest.fixture
def accounts(store, clock, mailer):
    return Accounts(store, ProductConfig(public_url=ORIGIN), lambda: clock[0], mailer=mailer)


def link_token(message) -> str:
    return re.search(r"#token=([A-Za-z0-9_-]{43})", message.text).group(1)


def confirmed(accounts, mailer, email="alice@example.com"):
    created = accounts.register(email, PASSWORD)
    accounts.confirm_email(link_token(mailer.sent[-1]))
    return created


def with_two_factor(accounts, tenant, clock):
    setup = accounts.start_two_factor(tenant, PASSWORD)
    codes = accounts.enable_two_factor(tenant, totp.code_at(setup["secret"], clock[0] // 30))
    return setup["secret"], codes["backup_codes"]


# --- Codes ----------------------------------------------------------------------------


def test_codes_follow_rfc_6238_and_a_used_step_cannot_be_reused():
    # RFC 6238 appendix B, SHA-1, at T = 59 s: 94287082, of which an app shows six digits.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp.code_at(secret, 59 // 30) == "287082"
    assert totp.matching_step(secret, "287 082", 59) == 1
    assert totp.matching_step(secret, "287082", 59 + 30) == 1  # A clock half a minute off.
    assert totp.matching_step(secret, "287082", 59 + 90) is None
    assert totp.matching_step(secret, "287082", 59, after_step=1) is None
    assert totp.matching_step(secret, "28708", 59) is None
    assert totp.matching_step(secret, None, 59) is None
    uri = totp.otpauth_uri(secret, "alice@example.com", "Fareflare")
    assert uri.startswith("otpauth://totp/Fareflare:alice@example.com?secret=" + secret)
    assert "issuer=Fareflare" in uri and "digits=6" in uri and "period=30" in uri


def test_backup_codes_are_unambiguous_and_tolerant_of_how_they_are_typed():
    codes = totp.new_backup_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(re.fullmatch(r"[a-z2-9]{4}-[a-z2-9]{4}", code) for code in codes)
    assert not any(character in "".join(codes) for character in "01il")
    digest = totp.backup_digest(codes[0])
    assert totp.backup_digest(codes[0].upper().replace("-", "")) == digest
    assert totp.backup_digest(" " + codes[0] + " ") == digest
    assert totp.backup_digest("not a code") is None and totp.backup_digest(5) is None


# --- Two-step sign-in -----------------------------------------------------------------


def test_two_step_sign_in_needs_the_password_then_a_fresh_code(accounts, clock):
    created = confirmed(accounts, accounts.mailer)
    tenant = created["account"]["id"]
    with pytest.raises(IncorrectPassword):
        accounts.start_two_factor(tenant, NEW_PASSWORD)
    setup = accounts.start_two_factor(tenant, PASSWORD)
    assert setup["uri"].startswith("otpauth://totp/Fareflare:alice%40example.com") or setup[
        "uri"
    ].startswith("otpauth://totp/Fareflare:alice@example.com")
    with pytest.raises(IncorrectPassword, match="not correct"):
        accounts.enable_two_factor(tenant, "000000")
    step = clock[0] // 30
    backup = accounts.enable_two_factor(tenant, totp.code_at(setup["secret"], step))["backup_codes"]
    assert accounts.security(tenant)["two_factor"]["backup_codes_left"] == 10
    stored = str(accounts.store.get("account:" + tenant).data)
    assert not any(code in stored for code in backup)

    clock[0] += 30
    pending = accounts.login("alice@example.com", PASSWORD)
    assert "session_token" not in pending and pending["two_factor_token"]
    with pytest.raises(AuthenticationFailed, match="not correct"):
        accounts.complete_login(pending["two_factor_token"], "123456")
    code = totp.code_at(setup["secret"], clock[0] // 30)
    signed_in = accounts.complete_login(pending["two_factor_token"], code)
    assert accounts.authenticate_session(signed_in["session_token"])
    # The same code cannot open a second session, and a used challenge is spent.
    with pytest.raises(AuthenticationFailed, match="expired"):
        accounts.complete_login(pending["two_factor_token"], code)
    again = accounts.login("alice@example.com", PASSWORD)
    with pytest.raises(AuthenticationFailed, match="not correct"):
        accounts.complete_login(again["two_factor_token"], code)

    # A backup code works once.
    assert accounts.complete_login(again["two_factor_token"], backup[0].upper())
    third = accounts.login("alice@example.com", PASSWORD)
    with pytest.raises(AuthenticationFailed):
        accounts.complete_login(third["two_factor_token"], backup[0])
    assert accounts.security(tenant)["two_factor"]["backup_codes_left"] == 9


def test_a_sign_in_challenge_expires_and_stops_after_five_wrong_codes(accounts, clock):
    tenant = confirmed(accounts, accounts.mailer)["account"]["id"]
    secret, _ = with_two_factor(accounts, tenant, clock)
    pending = accounts.login("alice@example.com", PASSWORD)["two_factor_token"]
    for _ in range(5):
        with pytest.raises(AuthenticationFailed, match="not correct"):
            accounts.complete_login(pending, "000000")
        clock[0] += 11
    with pytest.raises(AuthenticationFailed, match="expired"):
        accounts.complete_login(pending, totp.code_at(secret, clock[0] // 30))
    later = accounts.login("alice@example.com", PASSWORD)["two_factor_token"]
    clock[0] += 301
    with pytest.raises(AuthenticationFailed, match="expired"):
        accounts.complete_login(later, totp.code_at(secret, clock[0] // 30))
    with pytest.raises(AuthenticationFailed, match="expired"):
        accounts.complete_login("not a token", "000000")


def test_turning_two_step_off_and_new_backup_codes_need_the_password_and_a_code(accounts, clock):
    tenant = confirmed(accounts, accounts.mailer)["account"]["id"]
    secret, backup = with_two_factor(accounts, tenant, clock)
    clock[0] += 30
    with pytest.raises(IncorrectPassword):
        accounts.new_backup_codes(tenant, PASSWORD, "000000")
    fresh = accounts.new_backup_codes(tenant, PASSWORD, totp.code_at(secret, clock[0] // 30))
    assert set(fresh["backup_codes"]).isdisjoint(backup)
    with pytest.raises(ValueError, match="already on"):
        accounts.start_two_factor(tenant, PASSWORD)
    with pytest.raises(IncorrectPassword):
        accounts.disable_two_factor(tenant, NEW_PASSWORD, fresh["backup_codes"][0])
    accounts.disable_two_factor(tenant, PASSWORD, fresh["backup_codes"][0])
    assert accounts.security(tenant)["two_factor"]["enabled"] is False
    assert accounts.login("alice@example.com", PASSWORD)["session_token"]


def test_setup_expires_without_a_code(accounts, clock):
    tenant = confirmed(accounts, accounts.mailer)["account"]["id"]
    setup = accounts.start_two_factor(tenant, PASSWORD)
    clock[0] += 901
    with pytest.raises(ValueError, match="expired"):
        accounts.enable_two_factor(tenant, totp.code_at(setup["secret"], clock[0] // 30))


# --- Email ----------------------------------------------------------------------------


def test_sign_up_sends_one_confirmation_and_the_link_confirms_the_address(accounts, mailer):
    created = accounts.register("Alice@Example.com", PASSWORD)
    assert len(mailer.sent) == 1
    message = mailer.sent[0]
    assert message.to == "alice@example.com" and "Confirm" in message.subject
    assert ORIGIN + "/confirm-email#token=" in message.text and ORIGIN in message.html
    token = link_token(message)
    assert token not in str(accounts.store.query("email_confirmations"))
    assert accounts.confirm_email(token) == {"confirmed": True, "email": "alice@example.com"}
    assert accounts.get_account(created["account"]["id"])["email_verified"] is True
    with pytest.raises(ValueError, match="no longer valid"):
        accounts.confirm_email(token)
    with pytest.raises(ValueError, match="Email is not set up"):
        Accounts(accounts.store, accounts.config).resend_confirmation(created["account"]["id"])


def test_a_confirmation_link_expires_and_dies_when_the_address_changes(accounts, mailer, clock):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    first = link_token(mailer.sent[-1])
    clock[0] += 61
    accounts.change_email(tenant, PASSWORD, "alice@work.example.com")
    with pytest.raises(ValueError, match="no longer valid"):
        accounts.confirm_email(first)
    second = link_token(mailer.sent[-1])
    clock[0] += 86401
    with pytest.raises(ValueError, match="no longer valid"):
        accounts.confirm_email(second)
    clock[0] += 61
    accounts.resend_confirmation(tenant)
    assert accounts.confirm_email(link_token(mailer.sent[-1]))["email"] == "alice@work.example.com"


def test_changing_the_address_needs_the_password_and_a_free_address(accounts, mailer, clock):
    alice = confirmed(accounts, mailer)["account"]["id"]
    accounts.register("bob@example.com", PASSWORD)
    with pytest.raises(IncorrectPassword):
        accounts.change_email(alice, NEW_PASSWORD, "alice@new.example.com")
    with pytest.raises(ValueError, match="Another account"):
        accounts.change_email(alice, PASSWORD, "BOB@example.com")
    changed = accounts.change_email(alice, PASSWORD, "alice@new.example.com")
    assert changed["email"] == "alice@new.example.com" and changed["email_verified"] is False
    # The new address signs in; the old one is released.
    assert accounts.login("alice@new.example.com", PASSWORD)["account"]["id"] == alice
    assert accounts.register("alice2@example.com", PASSWORD)


def test_confirmation_email_is_sent_at_most_once_a_minute(accounts, mailer, clock):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    accounts.resend_confirmation(tenant)
    assert len(mailer.sent) == 1
    clock[0] += 61
    accounts.resend_confirmation(tenant)
    assert len(mailer.sent) == 2


# --- Password reset -------------------------------------------------------------------


def test_a_reset_link_goes_only_to_a_confirmed_address(accounts, mailer, clock):
    accounts.register("alice@example.com", PASSWORD)
    sent = len(mailer.sent)
    accounts.request_password_reset("alice@example.com")
    accounts.request_password_reset("nobody@example.com")
    assert len(mailer.sent) == sent  # Unconfirmed, and unknown: nothing is sent either way.
    accounts.confirm_email(link_token(mailer.sent[-1]))
    accounts.request_password_reset("ALICE@example.com")
    assert len(mailer.sent) == sent + 1
    message = mailer.sent[-1]
    assert message.to == "alice@example.com" and "Reset" in message.subject
    assert ORIGIN + "/reset-password#token=" in message.text and "30 minutes" in message.text
    accounts.request_password_reset("alice@example.com")
    assert len(mailer.sent) == sent + 1  # One link a minute.


def test_resetting_signs_in_and_signs_every_other_browser_out(accounts, mailer, clock):
    created = confirmed(accounts, mailer)
    tenant = created["account"]["id"]
    key = accounts.issue_api_key(tenant, "integration")
    accounts.request_password_reset("alice@example.com")
    token = link_token(mailer.sent[-1])
    assert accounts.check_reset(token) == {"email": "alice@example.com", "two_factor": False}
    with pytest.raises(ValueError, match="15–128"):
        accounts.reset_password(token, "short")
    reset = accounts.reset_password(token, NEW_PASSWORD)
    assert accounts.authenticate_session(reset["session_token"])
    assert accounts.authenticate_session(created["session_token"]) is None
    assert accounts.authenticate_api_key(key["api_key"]) == tenant
    with pytest.raises(ValueError, match="no longer valid"):
        accounts.reset_password(token, PASSWORD)
    with pytest.raises(AuthenticationFailed):
        accounts.login("alice@example.com", PASSWORD)
    assert accounts.login("alice@example.com", NEW_PASSWORD)


def test_a_reset_link_dies_when_the_password_changes_or_time_runs_out(accounts, mailer, clock):
    created = confirmed(accounts, mailer)
    tenant = created["account"]["id"]
    accounts.request_password_reset("alice@example.com")
    first = link_token(mailer.sent[-1])
    accounts.change_password(tenant, created["session_token"], PASSWORD, NEW_PASSWORD)
    with pytest.raises(ValueError, match="no longer valid"):
        accounts.check_reset(first)
    clock[0] += 61
    accounts.request_password_reset("alice@example.com")
    second = link_token(mailer.sent[-1])
    clock[0] += 30 * 60
    with pytest.raises(ValueError, match="no longer valid"):
        accounts.reset_password(second, PASSWORD)


def test_with_two_step_on_a_reset_also_needs_a_code(accounts, mailer, clock):
    tenant = confirmed(accounts, mailer)["account"]["id"]
    _, backup = with_two_factor(accounts, tenant, clock)
    accounts.request_password_reset("alice@example.com")
    token = link_token(mailer.sent[-1])
    assert accounts.check_reset(token) == {"email": "alice@example.com", "two_factor": True}
    with pytest.raises(IncorrectPassword, match="authenticator"):
        accounts.reset_password(token, NEW_PASSWORD)
    with pytest.raises(IncorrectPassword, match="not correct"):
        accounts.reset_password(token, NEW_PASSWORD, "000000")
    assert accounts.reset_password(token, NEW_PASSWORD, backup[3])["session_token"]


def test_reset_requests_are_rate_limited_and_need_email_set_up(store, clock, accounts):
    for _ in range(5):
        accounts.request_password_reset("someone@example.com")
    with pytest.raises(RateLimited):
        accounts.request_password_reset("someone@example.com")
    without = Accounts(store, ProductConfig(public_url=ORIGIN), lambda: clock[0])
    with pytest.raises(ValueError, match="not set up"):
        without.request_password_reset("other@example.com")
    assert without.email_enabled is False


# --- Passkeys -------------------------------------------------------------------------


def add_passkey(accounts, tenant, passkey=None, name=None):
    passkey = passkey or SoftPasskey(ORIGIN, "app.example.com")
    options = accounts.passkey_registration_options(tenant)
    created = accounts.add_passkey(
        tenant, options["challenge_id"], passkey.create(options["options"]), name
    )
    return passkey, created


def sign_in(accounts, passkey, **kwargs):
    options = accounts.passkey_login_options()
    return accounts.passkey_login(
        options["challenge_id"], passkey.get(options["options"], **kwargs)
    )


def test_a_passkey_signs_in_on_its_own_and_is_named_after_its_provider(accounts, clock):
    tenant = confirmed(accounts, accounts.mailer)["account"]["id"]
    with_two_factor(accounts, tenant, clock)  # A passkey stands in for both steps.
    options = accounts.passkey_registration_options(tenant)["options"]
    assert options["rp"] == {"id": "app.example.com", "name": "Fareflare"}
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    passkey, created = add_passkey(accounts, tenant)
    assert created["name"] == "1Password" and created["provider"] == "1Password"
    assert created["synced"] is True
    signed_in = sign_in(accounts, passkey)
    assert signed_in["account"]["id"] == tenant
    assert accounts.authenticate_session(signed_in["session_token"])
    listed = accounts.list_passkeys(tenant)
    assert len(listed) == 1 and listed[0]["last_used_at"] == clock[0]
    renamed = accounts.rename_passkey(tenant, listed[0]["id"], "Work laptop")
    assert renamed["name"] == "Work laptop"
    # Adding the same passkey twice is refused, and the next request excludes it.
    excluded = accounts.passkey_registration_options(tenant)["options"]["excludeCredentials"]
    assert excluded[0]["id"] == listed[0]["credential_id"]


def test_a_passkey_response_is_refused_from_another_site_or_without_verification(accounts):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    passkey = SoftPasskey(ORIGIN, "app.example.com")
    options = accounts.passkey_registration_options(tenant)
    with pytest.raises(PasskeyRejected):
        accounts.add_passkey(
            tenant,
            options["challenge_id"],
            passkey.create(options["options"], origin="https://evil.example"),
            None,
        )
    options = accounts.passkey_registration_options(tenant)
    with pytest.raises(PasskeyRejected):
        accounts.add_passkey(
            tenant,
            options["challenge_id"],
            passkey.create(options["options"], verified=False),
            None,
        )
    add_passkey(accounts, tenant, passkey)
    with pytest.raises(PasskeyRejected):
        sign_in(accounts, passkey, origin="https://evil.example")
    with pytest.raises(PasskeyRejected):
        sign_in(accounts, passkey, verified=False)
    stranger = SoftPasskey(ORIGIN, "app.example.com")
    stranger.user_handle = passkey.user_handle
    with pytest.raises(PasskeyRejected, match="not recognized"):
        sign_in(accounts, stranger)


def test_a_passkey_challenge_works_once_and_for_one_purpose(accounts, clock):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    passkey, _ = add_passkey(accounts, tenant)
    options = accounts.passkey_login_options()
    response = passkey.get(options["options"])
    assert accounts.passkey_login(options["challenge_id"], response)
    with pytest.raises(PasskeyRejected, match="expired"):
        accounts.passkey_login(options["challenge_id"], response)
    registration = accounts.passkey_registration_options(tenant)
    with pytest.raises(PasskeyRejected, match="expired"):
        accounts.passkey_login(registration["challenge_id"], passkey.get(registration["options"]))
    late = accounts.passkey_login_options()
    clock[0] += 301
    with pytest.raises(PasskeyRejected, match="expired"):
        accounts.passkey_login(late["challenge_id"], passkey.get(late["options"]))
    with pytest.raises(PasskeyRejected):
        accounts.passkey_login(None, {})


def test_a_removed_passkey_or_a_deleted_account_cannot_sign_in(accounts):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    passkey, created = add_passkey(accounts, tenant)
    second, _ = add_passkey(accounts, tenant, name="Phone")
    accounts.remove_passkey(tenant, created["id"])
    with pytest.raises(PasskeyRejected):
        sign_in(accounts, passkey)
    with pytest.raises(ValueError, match="not found"):
        accounts.remove_passkey(tenant, created["id"])
    assert [item["name"] for item in accounts.list_passkeys(tenant)] == ["Phone"]
    accounts.delete_account(tenant, PASSWORD)
    with pytest.raises(PasskeyRejected):
        sign_in(accounts, second)


def test_an_account_keeps_at_most_ten_passkeys(accounts):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    for _ in range(MAX_PASSKEYS):
        add_passkey(accounts, tenant)
    with pytest.raises(ValueError, match="up to 10"):
        add_passkey(accounts, tenant)
    with pytest.raises(ValueError, match="60 characters"):
        accounts.rename_passkey(tenant, accounts.list_passkeys(tenant)[0]["id"], "x" * 61)


# --- Over HTTP ------------------------------------------------------------------------


@pytest.fixture
def portal(store, clock, mailer):
    config = ProductConfig(public_url=ORIGIN)
    service = MonitoringService(store, lambda: clock[0])
    accounts = Accounts(store, config, lambda: clock[0], mailer=mailer)
    with TestClient(create_portal(service, config, accounts), base_url=ORIGIN) as client:
        yield client, accounts


def test_the_portal_signs_in_in_two_steps_without_a_cookie_in_between(portal, mailer, clock):
    client, _ = portal
    assert client.get("/v1/config").json()["email_enabled"] is True
    created = client.post(
        "/auth/register", json={"email": "alice@example.com", "password": PASSWORD}
    )
    csrf = {"X-CSRF-Token": created.json()["csrf_token"]}
    setup = client.post("/auth/two-factor/setup", headers=csrf, json={"password": PASSWORD}).json()
    code = totp.code_at(setup["secret"], clock[0] // 30)
    enabled = client.post("/auth/two-factor/enable", headers=csrf, json={"code": code})
    assert len(enabled.json()["backup_codes"]) == 10
    security = client.get("/v1/account/security").json()
    assert security["two_factor"]["enabled"] is True and security["passkeys"] == []
    client.cookies.clear()
    clock[0] += 30
    first = client.post("/auth/login", json={"username": "alice@example.com", "password": PASSWORD})
    assert first.status_code == 200 and first.json()["two_factor_required"] is True
    assert "set-cookie" not in first.headers
    assert client.get("/v1/account").status_code == 401
    wrong = client.post(
        "/auth/login/two-factor", json={"token": first.json()["token"], "code": "000000"}
    )
    assert wrong.status_code == 401
    second = client.post(
        "/auth/login/two-factor",
        json={
            "token": first.json()["token"],
            "code": totp.code_at(setup["secret"], clock[0] // 30),
        },
    )
    assert second.status_code == 200 and "HttpOnly" in second.headers["set-cookie"]
    assert client.get("/v1/account").json()["account"]["email"] == "alice@example.com"


def test_the_portal_resets_a_password_by_email(portal, mailer):
    client, _ = portal
    client.post("/auth/register", json={"email": "alice@example.com", "password": PASSWORD})
    confirm = client.post("/auth/email/confirm", json={"token": link_token(mailer.sent[-1])})
    assert confirm.json() == {"confirmed": True, "email": "alice@example.com"}
    client.cookies.clear()
    for address in ("alice@example.com", "nobody@example.com"):
        sent = client.post("/auth/password-reset", json={"email": address})
        assert sent.status_code == 202 and sent.json() == {"sent": True}
    token = link_token(mailer.sent[-1])
    assert client.post("/auth/password-reset/check", json={"token": token}).json() == {
        "email": "alice@example.com",
        "two_factor": False,
    }
    reset = client.post(
        "/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert reset.status_code == 200 and "set-cookie" in reset.headers
    stale = client.post(
        "/auth/password-reset/confirm", json={"token": token, "new_password": PASSWORD}
    )
    assert stale.status_code == 422


def test_the_portal_adds_and_signs_in_with_a_passkey(portal):
    client, _ = portal
    created = client.post(
        "/auth/register", json={"email": "alice@example.com", "password": PASSWORD}
    )
    csrf = {"X-CSRF-Token": created.json()["csrf_token"]}
    assert client.post("/auth/passkeys/options").status_code == 403  # No CSRF token.
    options = client.post("/auth/passkeys/options", headers=csrf).json()
    passkey = SoftPasskey(ORIGIN, "app.example.com")
    added = client.post(
        "/auth/passkeys",
        headers=csrf,
        json={
            "challenge_id": options["challenge_id"],
            "credential": passkey.create(options["options"]),
        },
    )
    assert added.status_code == 201 and added.json()["name"] == "1Password"
    renamed = client.patch(
        f"/auth/passkeys/{added.json()['id']}", headers=csrf, json={"name": "MacBook"}
    )
    assert renamed.json()["name"] == "MacBook"
    client.cookies.clear()
    login = client.post("/auth/passkey/options").json()
    bad = client.post(
        "/auth/passkey",
        json={"challenge_id": login["challenge_id"], "credential": {"rawId": "AAAA"}},
    )
    assert bad.status_code == 400
    login = client.post("/auth/passkey/options").json()
    signed_in = client.post(
        "/auth/passkey",
        json={"challenge_id": login["challenge_id"], "credential": passkey.get(login["options"])},
    )
    assert signed_in.status_code == 200 and "set-cookie" in signed_in.headers
    csrf = {"X-CSRF-Token": signed_in.json()["csrf_token"]}
    assert client.delete(f"/auth/passkeys/{added.json()['id']}", headers=csrf).json() == {
        "removed": True
    }


def test_password_managers_can_find_where_passkeys_are_managed(portal):
    client, _ = portal
    endpoints = client.get("/.well-known/passkey-endpoints").json()
    assert endpoints == {
        "enroll": ORIGIN + "/app#settings?section=security",
        "manage": ORIGIN + "/app#settings?section=security",
    }


def test_the_portal_changes_the_address_and_resends_the_confirmation(portal, mailer, clock):
    client, _ = portal
    created = client.post(
        "/auth/register", json={"email": "alice@example.com", "password": PASSWORD}
    )
    csrf = {"X-CSRF-Token": created.json()["csrf_token"]}
    changed = client.post(
        "/auth/email", headers=csrf, json={"email": "alice@new.example.com", "password": PASSWORD}
    )
    assert changed.json()["account"]["email"] == "alice@new.example.com"
    assert mailer.sent[-1].to == "alice@new.example.com"
    clock[0] += 61
    assert client.post("/auth/email/resend", headers=csrf).status_code == 202
    assert len(mailer.sent) == 3


# --- Mail delivery --------------------------------------------------------------------


def test_mail_is_written_privately_locally_and_sent_through_ses_in_production(tmp_path):
    from fareflare import mailer as module

    message = module.password_reset("Fareflare", "alice@example.com", ORIGIN + "/x", 30)
    local = FileMailer(tmp_path / "outbox")
    local.send(message)
    written = next((tmp_path / "outbox").glob("*.eml"))
    assert written.stat().st_mode & 0o777 == 0o600
    assert "Reset your Fareflare password" in written.read_text()
    client = Mock()
    SesMailer("Fareflare <no-reply@fareflare.dev>", client=client).send(message)
    sent = client.send_email.call_args.kwargs
    assert sent["FromEmailAddress"] == "Fareflare <no-reply@fareflare.dev>"
    assert sent["Destination"] == {"ToAddresses": ["alice@example.com"]}
    assert sent["Content"]["Simple"]["Subject"]["Data"] == "Reset your Fareflare password"
    with pytest.raises(ValueError, match="FAREFLARE_EMAIL_FROM"):
        SesMailer("", client=client)
    assert mailer_from_env({}) is None
    assert isinstance(mailer_from_env({"FAREFLARE_EMAIL": "file"}), FileMailer)
    assert isinstance(
        mailer_from_env(
            {"FAREFLARE_EMAIL": "ses", "FAREFLARE_EMAIL_FROM": "a@b.co", "AWS_REGION": "us-east-1"}
        ),
        SesMailer,
    )
    with pytest.raises(ValueError, match="ses, file or off"):
        mailer_from_env({"FAREFLARE_EMAIL": "smtp"})


def test_a_mail_provider_failure_does_not_break_sign_up_or_reveal_an_account(store, clock, caplog):
    class Broken:
        def send(self, message):
            raise RuntimeError("SES sandbox: address not verified")

    accounts = Accounts(store, ProductConfig(public_url=ORIGIN), lambda: clock[0], mailer=Broken())
    assert accounts.register("alice@example.com", PASSWORD)["session_token"]
    assert "could not be sent" in caplog.text
