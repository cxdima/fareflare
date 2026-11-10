"""Sign-in names a password manager can fill, and account changes made while signed in."""

import pytest

from fareflare.accounts import AuthenticationFailed, IncorrectPassword
from fareflare.credentials import RateLimited
from tests.test_accounts import PASSWORD, REPLACEMENT, accounts, register  # noqa: F401
from tests.test_portal import PASSWORD as PORTAL_PASSWORD
from tests.test_portal import portal, signup  # noqa: F401

NEW_PASSWORD = "another long passphrase entirely"


# --- Sign-in names --------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "traveler@example.com",
        "First.Last+flights@mail.example.co.uk",
        "a@b.io",
        "o_reilly-99%tag@sub-domain.example.travel",
    ],
)
def test_an_email_address_is_accepted_as_a_sign_in_name(accounts, name):  # noqa: F811
    created = register(accounts, name)
    assert created["account"]["username"] == name.lower()
    # It is matched without regard to case, the way people type addresses.
    assert accounts.login(name.upper(), PASSWORD)["account"]["id"] == created["account"]["id"]
    recovered = accounts.recover(name.swapcase(), created["recovery_code"], REPLACEMENT)
    assert recovered["account"]["username"] == name.lower()


@pytest.mark.parametrize(
    "name",
    [
        "ab",
        "has space",
        "@example.com",
        "traveler@",
        "traveler@example",
        "traveler@@example.com",
        "traveler@example..com",
        "traveler@.example.com",
        "trav eler@example.com",
        "traveler@example.c",
        "<traveler@example.com>",
        "traveler@exämple.com",
        "a" * 41,
        "a" * 64 + "x@example.com",
        "a@" + "b" * 250 + ".com",
        "",
        None,
        7,
    ],
)
def test_anything_that_is_neither_a_username_nor_an_address_is_refused(accounts, name):  # noqa: F811
    with pytest.raises(ValueError, match="Use an email address, or a username"):
        accounts.register(name, PASSWORD, accounts.create_invite()["token"])
    with pytest.raises(ValueError, match="Use an email address, or a username"):
        accounts.login(name, PASSWORD)


def test_a_username_and_an_address_are_separate_accounts(accounts):  # noqa: F811
    first = register(accounts, "traveler")
    second = register(accounts, "traveler@example.com")
    assert first["account"]["id"] != second["account"]["id"]
    with pytest.raises(ValueError, match="unavailable"):
        register(accounts, "Traveler@Example.com")


def test_the_portal_accepts_an_address_and_reports_a_bad_one_plainly(portal):  # noqa: F811
    client, accounts, _ = portal  # noqa: F811
    assert signup(client, accounts, "Traveler@Example.com").json()["account"]["username"] == (
        "traveler@example.com"
    )
    client.cookies.clear()
    signed_in = client.post(
        "/auth/login", json={"username": "traveler@example.com", "password": PORTAL_PASSWORD}
    )
    assert signed_in.status_code == 200
    client.cookies.clear()
    refused = client.post(
        "/auth/register",
        json={
            "username": "not an address",
            "password": PORTAL_PASSWORD,
            "invite_token": accounts.create_invite()["token"],
        },
    )
    assert refused.status_code == 422 and "Use an email address" in refused.json()["detail"]
    too_long = client.post("/auth/login", json={"username": "a" * 255, "password": PORTAL_PASSWORD})
    assert too_long.status_code == 422


# --- Changing the password ------------------------------------------------------------


def test_changing_the_password_signs_out_other_browsers_and_keeps_this_one(accounts):  # noqa: F811
    created = register(accounts)
    tenant = created["account"]["id"]
    other = accounts.login("alice", PASSWORD)
    key = accounts.issue_api_key(tenant, "integration")

    accounts.change_password(tenant, created["session_token"], PASSWORD, NEW_PASSWORD)

    assert accounts.authenticate_session(created["session_token"]) is not None
    assert accounts.authenticate_session(other["session_token"]) is None
    with pytest.raises(AuthenticationFailed):
        accounts.login("alice", PASSWORD)
    assert accounts.login("alice", NEW_PASSWORD)["account"]["id"] == tenant
    # Keys and the recovery code are separate credentials and are left alone.
    assert accounts.authenticate_api_key(key["api_key"]) == tenant
    assert accounts.recover("alice", created["recovery_code"], REPLACEMENT)


@pytest.mark.parametrize("wrong", [REPLACEMENT, "short", "x" * 200, ""])
def test_the_wrong_current_password_changes_nothing(accounts, wrong):  # noqa: F811
    created = register(accounts)
    tenant = created["account"]["id"]
    with pytest.raises(IncorrectPassword, match="That password is not correct"):
        accounts.change_password(tenant, created["session_token"], wrong, NEW_PASSWORD)
    assert accounts.authenticate_session(created["session_token"]) is not None
    assert accounts.login("alice", PASSWORD)


def test_a_new_password_must_meet_the_same_rule_as_at_signup(accounts):  # noqa: F811
    created = register(accounts)
    with pytest.raises(ValueError, match="15–128 characters"):
        accounts.change_password(
            created["account"]["id"], created["session_token"], PASSWORD, "too short"
        )
    assert accounts.login("alice", PASSWORD)


def test_password_guesses_while_signed_in_are_rate_limited(accounts):  # noqa: F811
    created = register(accounts)
    tenant = created["account"]["id"]
    for _ in range(10):
        with pytest.raises(IncorrectPassword):
            accounts.change_password(tenant, created["session_token"], REPLACEMENT, NEW_PASSWORD)
    with pytest.raises(RateLimited):
        accounts.change_password(tenant, created["session_token"], PASSWORD, NEW_PASSWORD)


# --- A new recovery code --------------------------------------------------------------


def test_a_new_recovery_code_replaces_the_old_one(accounts):  # noqa: F811
    created = register(accounts)
    tenant = created["account"]["id"]
    with pytest.raises(IncorrectPassword):
        accounts.new_recovery_code(tenant, REPLACEMENT)
    replacement = accounts.new_recovery_code(tenant, PASSWORD)["recovery_code"]
    assert replacement != created["recovery_code"]
    # Still signed in: only the code changed.
    assert accounts.authenticate_session(created["session_token"]) is not None
    with pytest.raises(AuthenticationFailed, match="Incorrect email, username or recovery code"):
        accounts.recover("alice", created["recovery_code"], REPLACEMENT)
    assert accounts.recover("alice", replacement, REPLACEMENT)["account"]["id"] == tenant


# --- Over HTTP ------------------------------------------------------------------------


def test_the_portal_changes_a_password_only_with_the_session_csrf_and_current_password(
    portal,  # noqa: F811
):
    client, accounts, _ = portal  # noqa: F811
    csrf = {"X-CSRF-Token": signup(client, accounts).json()["csrf_token"]}
    body = {"current_password": PORTAL_PASSWORD, "new_password": NEW_PASSWORD}

    assert client.post("/auth/password", json=body).status_code == 403  # No CSRF token.
    wrong = client.post(
        "/auth/password", headers=csrf, json={**body, "current_password": NEW_PASSWORD}
    )
    # 403, not 401: the browser must not conclude that the session ended.
    assert wrong.status_code == 403 and wrong.json()["detail"] == "That password is not correct"
    weak = client.post("/auth/password", headers=csrf, json={**body, "new_password": "short"})
    assert weak.status_code == 422
    assert client.get("/v1/account").status_code == 200

    changed = client.post("/auth/password", headers=csrf, json=body)
    assert changed.status_code == 200 and changed.json() == {"changed": True}
    assert client.get("/v1/account").status_code == 200  # This browser stays signed in.
    client.cookies.clear()
    old = client.post("/auth/login", json={"username": "traveler", "password": PORTAL_PASSWORD})
    assert old.status_code == 401
    new = client.post("/auth/login", json={"username": "traveler", "password": NEW_PASSWORD})
    assert new.status_code == 200
    assert client.post("/auth/password", json=body).status_code == 403


def test_the_portal_issues_a_new_recovery_code_after_confirming_the_password(portal):  # noqa: F811
    client, accounts, _ = portal  # noqa: F811
    created = signup(client, accounts).json()
    csrf = {"X-CSRF-Token": created["csrf_token"]}
    wrong = client.post("/auth/recovery-code", headers=csrf, json={"password": NEW_PASSWORD})
    assert wrong.status_code == 403
    issued = client.post("/auth/recovery-code", headers=csrf, json={"password": PORTAL_PASSWORD})
    assert issued.status_code == 200
    code = issued.json()["recovery_code"]
    assert code != created["recovery_code"] and list(issued.json()) == ["recovery_code"]
    client.cookies.clear()
    stale = client.post(
        "/auth/recover",
        json={
            "username": "traveler",
            "recovery_code": created["recovery_code"],
            "new_password": NEW_PASSWORD,
        },
    )
    assert stale.status_code == 401
    fresh = client.post(
        "/auth/recover",
        json={"username": "traveler", "recovery_code": code, "new_password": NEW_PASSWORD},
    )
    assert fresh.status_code == 200
    assert client.post("/auth/recovery-code", json={"password": NEW_PASSWORD}).status_code == 403


def test_a_wrong_password_when_deleting_an_account_does_not_look_like_a_signed_out_session(
    portal,  # noqa: F811
):
    client, accounts, _ = portal  # noqa: F811
    csrf = {"X-CSRF-Token": signup(client, accounts).json()["csrf_token"]}
    refused = client.request("DELETE", "/v1/account", headers=csrf, json={"password": NEW_PASSWORD})
    assert refused.status_code == 403
    assert refused.json()["detail"] == "That password is not correct"
    assert client.get("/v1/account").status_code == 200


def test_password_managers_are_sent_to_the_page_where_a_password_is_changed(portal):  # noqa: F811
    client, _, _ = portal
    response = client.get("/.well-known/change-password", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/app#settings?section=security"
