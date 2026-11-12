"""Limits that keep one person from guessing their way in, or from using Fareflare
to mail strangers: password strength, failure caps, and email budgets."""

import hashlib

import httpx
import pytest

from fareflare import accounts as accounts_module
from fareflare import passwords, totp
from fareflare.accounts import Accounts, AuthenticationFailed
from fareflare.credentials import RateLimited
from fareflare.mailer import MemoryMailer
from fareflare.product_config import ProductConfig
from tests.test_sign_in_security import (
    NEW_PASSWORD,
    ORIGIN,
    PASSWORD,
    add_passkey,
    confirmed,
    link_token,
    with_two_factor,
)


@pytest.fixture
def mailer():
    return MemoryMailer()


@pytest.fixture
def accounts(store, clock, mailer):
    return Accounts(store, ProductConfig(public_url=ORIGIN), lambda: clock[0], mailer=mailer)


def subjects(mailer):
    return [message.subject for message in mailer.sent]


# --- Password strength ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("password", passwords.COMMON),
        ("Password1!", passwords.COMMON),
        ("2024dragon", passwords.COMMON),
        ("qwerty123", passwords.COMMON),
        ("iloveyou", passwords.COMMON),
        ("12345678", passwords.PATTERN),
        ("87654321", passwords.PATTERN),
        ("aaaaaaaa", passwords.PATTERN),
        ("abababab", passwords.PATTERN),
        ("abcdefgh", passwords.PATTERN),
        ("lkjhgfdsa", passwords.PATTERN),
        ("Alice.Smith1990", passwords.PERSONAL),
        ("alicesmith!!", passwords.PERSONAL),
    ],
)
def test_predictable_passwords_are_refused_with_the_reason(password, reason):
    assert passwords.weakness(password, ["alice.smith@example.com", "Fareflare"]) == reason


@pytest.mark.parametrize(
    "password",
    ["Tr0ub4dor&3", "correct horse battery staple", "8 chars!", "MyAliceSmithTrip#92x"],
)
def test_ordinary_passwords_pass(password):
    assert passwords.weakness(password, ["alice.smith@example.com", "Fareflare"]) is None


def test_the_breach_check_sends_only_a_hash_prefix_and_ignores_padding():
    digest = hashlib.sha1(b"hunter2hunter2", usedforsecurity=False).hexdigest().upper()
    seen = []

    def answer(request):
        seen.append(request)
        lines = [f"{digest[5:]}:{count}"]  # A count of 0 is a padding entry.
        lines += ["0" * 35 + ":0", "F" * 35 + ":3"]  # Padding, and another password.
        return httpx.Response(200, text="\r\n".join(lines))

    count = 42
    check = passwords.BreachedPasswords(transport=httpx.MockTransport(answer))
    assert check("hunter2hunter2") is True
    request = seen[-1]
    assert request.url.path == "/range/" + digest[:5]
    assert request.headers["add-padding"] == "true"
    assert digest[5:] not in str(request.url) and b"hunter2" not in request.content
    count = 0  # Present only as padding: not breached.
    assert check("hunter2hunter2") is False


def test_an_unreachable_breach_check_allows_the_password():
    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    assert passwords.BreachedPasswords(transport=httpx.MockTransport(fail))("x" * 12) is False
    for status in (429, 503):
        down = passwords.BreachedPasswords(
            transport=httpx.MockTransport(lambda request, status=status: httpx.Response(status))
        )
        assert down("x" * 12) is False


def test_the_breach_check_is_on_unless_switched_off():
    assert isinstance(passwords.breach_check_from_env({}), passwords.BreachedPasswords)
    assert passwords.breach_check_from_env({"FAREFLARE_PASSWORD_BREACH_CHECK": "off"}) is None
    with pytest.raises(ValueError, match="on or off"):
        passwords.breach_check_from_env({"FAREFLARE_PASSWORD_BREACH_CHECK": "maybe"})


def test_every_new_password_is_checked_but_signing_in_is_not(store, clock, mailer):
    breached = {"a breached but long password"}
    accounts = Accounts(
        store,
        ProductConfig(public_url=ORIGIN),
        lambda: clock[0],
        mailer=mailer,
        breached=breached.__contains__,
    )
    with pytest.raises(ValueError, match="data breach"):
        accounts.register("alice@example.com", "a breached but long password")
    with pytest.raises(ValueError, match="most common"):
        accounts.register("alice@example.com", "Password123!")
    created = confirmed(accounts, mailer)
    tenant = created["account"]["id"]
    with pytest.raises(ValueError, match="data breach"):
        accounts.change_password(
            tenant, created["session_token"], PASSWORD, "a breached but long password"
        )
    with pytest.raises(ValueError, match="email address"):
        accounts.change_password(tenant, created["session_token"], PASSWORD, "alice2024!")
    accounts.request_password_reset("alice@example.com")
    token = link_token(mailer.sent[-1])
    with pytest.raises(ValueError, match="data breach"):
        accounts.reset_password(token, "a breached but long password")
    accounts.reset_password(token, NEW_PASSWORD)
    # A password set before the rules is still accepted at sign-in.
    breached.add(NEW_PASSWORD)
    assert accounts.login("alice@example.com", NEW_PASSWORD)["account"]["id"] == tenant


# --- Guessing ---------------------------------------------------------------------------


def test_wrong_passwords_for_one_name_are_capped_per_hour(accounts, clock):
    accounts.register("alice@example.com", PASSWORD)
    for _ in range(30):
        clock[0] += 7  # Under the per-minute limit: only the hourly cap applies.
        with pytest.raises(AuthenticationFailed):
            accounts.login("alice@example.com", "a wrong guess, again")
    with pytest.raises(RateLimited, match="passkey"):
        accounts.login("alice@example.com", PASSWORD)
    # The same answer for a name with no account, so the cap reveals nothing.
    for _ in range(30):
        clock[0] += 7
        with pytest.raises(AuthenticationFailed):
            accounts.login("nobody@example.com", "a wrong guess, again")
    with pytest.raises(RateLimited):
        accounts.login("nobody@example.com", "a wrong guess, again")
    clock[0] = (clock[0] // 3600 + 1) * 3600
    assert accounts.login("alice@example.com", PASSWORD)


def test_wrong_codes_are_capped_across_fresh_sign_ins(accounts, clock):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    secret, _ = with_two_factor(accounts, tenant, clock)
    wrong = 0
    while wrong < 10:
        clock[0] += 61
        token = accounts.login("alice@example.com", PASSWORD)["two_factor_token"]
        for _ in range(4):  # Each sign-in allows five tries; start over before that.
            if wrong == 10:
                break
            clock[0] += 11
            guess = f"{(int(totp.code_at(secret, clock[0] // 30)) + 500_000) % 1_000_000:06d}"
            with pytest.raises(AuthenticationFailed):
                accounts.complete_login(token, guess)
            wrong += 1
    clock[0] += 61
    token = accounts.login("alice@example.com", PASSWORD)["two_factor_token"]
    with pytest.raises(RateLimited, match="incorrect codes"):
        accounts.complete_login(token, totp.code_at(secret, clock[0] // 30))
    clock[0] = (clock[0] // 3600 + 1) * 3600 + 1
    token = accounts.login("alice@example.com", PASSWORD)["two_factor_token"]
    assert accounts.complete_login(token, totp.code_at(secret, clock[0] // 30))


# --- Email --------------------------------------------------------------------------


def test_the_service_mails_within_an_hourly_budget(store, clock, mailer, monkeypatch):
    monkeypatch.setattr(accounts_module, "_EMAIL_PER_HOUR", 2)
    accounts = Accounts(store, ProductConfig(public_url=ORIGIN), lambda: clock[0], mailer=mailer)
    for name in ("one", "two", "three"):
        accounts.register(f"{name}@example.com", PASSWORD)  # Each still signs up.
    assert len(mailer.sent) == 2
    clock[0] += 3600
    accounts.register("four@example.com", PASSWORD)
    assert len(mailer.sent) == 3


def test_one_account_cannot_mail_a_list_of_strangers(accounts, clock, mailer):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    for number in range(5):
        clock[0] += 61
        accounts.change_email(tenant, PASSWORD, f"stranger{number}@example.com")
    with pytest.raises(RateLimited, match="tomorrow"):
        accounts.change_email(tenant, PASSWORD, "stranger5@example.com")
    with pytest.raises(RateLimited, match="tomorrow"):
        accounts.resend_confirmation(tenant)
    assert len(mailer.sent) == 6  # Sign-up, then five changes.


def test_changes_to_how_an_account_signs_in_are_reported_to_its_address(accounts, clock, mailer):
    created = confirmed(accounts, mailer)
    tenant = created["account"]["id"]
    accounts.change_password(tenant, created["session_token"], PASSWORD, NEW_PASSWORD)
    assert mailer.sent[-1].to == "alice@example.com"
    assert mailer.sent[-1].subject.startswith("Your password was changed")
    add_passkey_with(accounts, tenant, NEW_PASSWORD)
    assert mailer.sent[-1].subject.startswith("A passkey was added")
    secret = accounts.start_two_factor(tenant, NEW_PASSWORD)["secret"]
    accounts.enable_two_factor(tenant, totp.code_at(secret, clock[0] // 30))
    clock[0] += 30
    accounts.disable_two_factor(tenant, NEW_PASSWORD, totp.code_at(secret, clock[0] // 30))
    assert mailer.sent[-1].subject.startswith("Two-step sign-in was turned off")
    accounts.change_email(tenant, NEW_PASSWORD, "new@example.com")
    notice, confirmation = mailer.sent[-2:]
    assert notice.to == "alice@example.com" and "new@example.com" in notice.text
    assert notice.subject.startswith("Your email address was changed")
    assert confirmation.to == "new@example.com"
    # An address that was never confirmed hears nothing about the account.
    before = len(mailer.sent)
    accounts.change_password(tenant, created["session_token"], NEW_PASSWORD, PASSWORD)
    assert len(mailer.sent) == before


def add_passkey_with(accounts, tenant, password):
    from tests.softauthn import SoftPasskey

    passkey = SoftPasskey(ORIGIN, "app.example.com")
    options = accounts.passkey_registration_options(tenant, password)
    return accounts.add_passkey(
        tenant, options["challenge_id"], passkey.create(options["options"]), None
    )


def test_adding_a_passkey_needs_the_password(accounts):
    tenant = accounts.register("alice@example.com", PASSWORD)["account"]["id"]
    with pytest.raises(ValueError, match="not correct"):
        accounts.passkey_registration_options(tenant, "not the password at all")
    add_passkey(accounts, tenant)
    assert len(accounts.list_passkeys(tenant)) == 1
