"""Email sign-in a password manager can fill, and account changes made while signed in."""

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
def test_an_email_address_is_the_sign_in_name(accounts, name):  # noqa: F811
    created = register(accounts, name)
    assert created["account"]["username"] == name.lower()
    assert created["account"]["email"] == name.lower()
    # It is matched without regard to case, the way people type addresses.
    assert accounts.login(name.upper(), PASSWORD)["account"]["id"] == created["account"]["id"]


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
def test_anything_that_is_not_an_address_is_refused(accounts, name):  # noqa: F811
    with pytest.raises(ValueError, match="Enter an email address"):
        accounts.register(name, PASSWORD)
    with pytest.raises(ValueError, match="Enter your email address"):
        accounts.login(name, PASSWORD)


def test_one_address_has_one_account_whatever_its_case(accounts):  # noqa: F811
    register(accounts, "traveler@example.com")
    with pytest.raises(ValueError, match="already uses that email"):
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
        "/auth/register", json={"email": "not an address", "password": PORTAL_PASSWORD}
    )
    assert refused.status_code == 422 and "Enter an email address" in refused.json()["detail"]
    too_long = client.post("/auth/login", json={"username": "a" * 255, "password": PORTAL_PASSWORD})
    assert too_long.status_code == 422


# --- Changing the password ------------------------------------------------------------


def test_changing_the_password_signs_out_other_browsers_and_keeps_this_one(accounts):  # noqa: F811
    created = register(accounts)
    tenant = created["account"]["id"]
    other = accounts.login("alice@example.com", PASSWORD)
    key = accounts.issue_api_key(tenant, "integration")

    accounts.change_password(tenant, created["session_token"], PASSWORD, NEW_PASSWORD)

    assert accounts.authenticate_session(created["session_token"]) is not None
    assert accounts.authenticate_session(other["session_token"]) is None
    with pytest.raises(AuthenticationFailed):
        accounts.login("alice@example.com", PASSWORD)
    assert accounts.login("alice@example.com", NEW_PASSWORD)["account"]["id"] == tenant
    # Keys are separate credentials and are left alone.
    assert accounts.authenticate_api_key(key["api_key"]) == tenant


@pytest.mark.parametrize("wrong", [REPLACEMENT, "short", "x" * 200, ""])
def test_the_wrong_current_password_changes_nothing(accounts, wrong):  # noqa: F811
    created = register(accounts)
    tenant = created["account"]["id"]
    with pytest.raises(IncorrectPassword, match="That password is not correct"):
        accounts.change_password(tenant, created["session_token"], wrong, NEW_PASSWORD)
    assert accounts.authenticate_session(created["session_token"]) is not None
    assert accounts.login("alice@example.com", PASSWORD)


def test_a_new_password_must_meet_the_same_rule_as_at_signup(accounts):  # noqa: F811
    created = register(accounts)
    with pytest.raises(ValueError, match="8–128 characters"):
        accounts.change_password(
            created["account"]["id"], created["session_token"], PASSWORD, "short"
        )
    assert accounts.login("alice@example.com", PASSWORD)


def test_password_guesses_while_signed_in_are_rate_limited(accounts):  # noqa: F811
    created = register(accounts)
    tenant = created["account"]["id"]
    for _ in range(10):
        with pytest.raises(IncorrectPassword):
            accounts.change_password(tenant, created["session_token"], REPLACEMENT, NEW_PASSWORD)
    with pytest.raises(RateLimited):
        accounts.change_password(tenant, created["session_token"], PASSWORD, NEW_PASSWORD)


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
    old = client.post(
        "/auth/login", json={"username": "traveler@example.com", "password": PORTAL_PASSWORD}
    )
    assert old.status_code == 401
    new = client.post(
        "/auth/login", json={"username": "traveler@example.com", "password": NEW_PASSWORD}
    )
    assert new.status_code == 200
    assert client.post("/auth/password", json=body).status_code == 403


def test_the_portal_signs_out_everywhere_after_confirming_the_password(portal):  # noqa: F811
    client, accounts, _ = portal  # noqa: F811
    created = signup(client, accounts).json()
    csrf = {"X-CSRF-Token": created["csrf_token"]}
    key = client.post("/v1/api-keys", headers=csrf, json={"name": "integration"}).json()
    wrong = client.post("/auth/sign-out-everywhere", headers=csrf, json={"password": NEW_PASSWORD})
    assert wrong.status_code == 403
    renewed = client.post(
        "/auth/sign-out-everywhere", headers=csrf, json={"password": PORTAL_PASSWORD}
    )
    assert renewed.status_code == 200 and renewed.json()["csrf_token"] != created["csrf_token"]
    assert client.get("/v1/account").status_code == 200  # This browser has a fresh session.
    bearer = {"Authorization": "Bearer " + key["api_key"]}
    assert client.get("/v1/monitors", headers=bearer).status_code == 401


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
