"""Customer authentication and lifecycle contracts on SQLite and DynamoDB."""

import hashlib
import json

import pytest

from fareflare import accounts as module
from fareflare.accounts import (
    Accounts,
    AuthenticationFailed,
    IncorrectPassword,
    hash_password,
    verify_password,
)
from fareflare.credentials import RateLimited
from fareflare.product_config import ProductConfig
from fareflare.service import MonitoringService, Reading

PASSWORD = "my development passphrase"
REPLACEMENT = "my replacement passphrase"


@pytest.fixture
def accounts(store, clock):
    return Accounts(store, ProductConfig(), lambda: clock[0])


def register(accounts, name="alice"):
    return accounts.register(name if "@" in name else name + "@example.com", PASSWORD)


def test_default_product_is_free_open_and_bounded():
    config = ProductConfig.from_env({})
    assert config.public() == {
        "product_name": "Fareflare",
        "billing_enabled": False,
        "capabilities": {"route_searches": False},
        "registration_mode": "open",
        "limits": {"monitors": 20, "min_interval_seconds": 900, "global_targets": 20},
    }
    assert ProductConfig.from_env({"FAREFLARE_SEARCH_ENABLED": "true"}).search_enabled is True
    with pytest.raises(ValueError):
        ProductConfig.from_env({"FAREFLARE_SEARCH_ENABLED": "maybe"})
    with pytest.raises(ValueError):
        ProductConfig.from_env({"FAREFLARE_BILLING_ENABLED": "true"})
    with pytest.raises(ValueError):
        ProductConfig.from_env({"FAREFLARE_BILLING_ENABLED": "maybe"})
    with pytest.raises(ValueError):
        ProductConfig(monitor_limit=True)
    with pytest.raises(ValueError):
        ProductConfig(public_url="http://public.example.com")
    with pytest.raises(ValueError):
        ProductConfig(public_url="https://user:password@example.com")
    assert ProductConfig(public_url="http://127.0.0.1:8001").billing_enabled is False


def test_passwords_use_scrypt_unique_salts_and_constant_cost_dummy(monkeypatch):
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second and first.startswith("scrypt$131072$8$1$")
    assert PASSWORD not in first
    assert verify_password(PASSWORD, first)
    assert not verify_password(REPLACEMENT, first)
    calls = []
    derive = module._derive

    def recording_derive(value, salt):
        calls.append(salt)
        return derive(value, salt)

    monkeypatch.setattr(module, "_derive", recording_derive)
    assert not verify_password(PASSWORD, None)
    assert not verify_password(PASSWORD, "malformed")
    assert len(calls) == 2


def test_sign_up_needs_an_email_and_can_be_closed(store, clock):
    accounts = Accounts(store, ProductConfig(), lambda: clock[0])
    registered = accounts.register("Alice@Example.com", PASSWORD)
    assert registered["account"]["username"] == "alice@example.com"
    assert registered["account"]["email"] == "alice@example.com"
    assert registered["account"]["email_verified"] is False
    with pytest.raises(ValueError, match="already uses that email"):
        accounts.register("ALICE@example.com", PASSWORD)
    with pytest.raises(ValueError, match="email address"):
        accounts.register("alice", PASSWORD)
    with pytest.raises(ValueError):
        accounts.register("bob@example.com", "short")
    closed = Accounts(store, ProductConfig(registration_mode="closed"), lambda: clock[0])
    with pytest.raises(ValueError, match="closed"):
        closed.register("carol@example.com", PASSWORD)
    with pytest.raises(ValueError, match="open or closed"):
        ProductConfig(registration_mode="invite")
    assert len(accounts.store.query("accounts")) == 1


def test_an_older_account_still_signs_in_with_its_username(accounts, clock):
    registered = register(accounts)
    tenant = registered["account"]["id"]
    # Accounts created before email was required kept a username and no address.
    account = accounts.store.get("account:" + tenant)
    data = {**account.data, "username": "alice"}
    data.pop("email")
    accounts.store.commit(
        [
            account.update(data),
            module.Document(
                "username:" + hashlib.sha256(b"alice").hexdigest(),
                "usernames",
                {"account_id": tenant},
            ),
        ]
    )
    assert accounts.login("Alice", PASSWORD)["account"]["id"] == tenant
    assert accounts.login("alice@example.com", PASSWORD)["account"]["id"] == tenant


def test_sessions_are_hashed_expire_and_logout_idempotently(accounts, clock):
    result = register(accounts)
    authenticated = accounts.authenticate_session(result["session_token"])
    assert authenticated is not None
    assert authenticated["account"] == result["account"]
    assert authenticated["csrf_token"] == result["csrf_token"]
    tenant = result["account"]["id"]
    raw = json.dumps(
        [doc.data for doc in accounts.store.query("accounts")]
        + [doc.data for doc in accounts.store.query("sessions:" + tenant)]
    )
    for secret in (
        PASSWORD,
        result["session_token"],
        result["csrf_token"],
    ):
        assert secret not in raw
    assert accounts.authenticate_session("x" * 43) is None
    accounts.logout(result["session_token"])
    accounts.logout(result["session_token"])
    assert accounts.authenticate_session(result["session_token"]) is None
    login = accounts.login("ALICE@example.com", PASSWORD)
    clock[0] = login["expires_at"]
    assert accounts.authenticate_session(login["session_token"]) is None


def test_bad_login_is_generic_and_rate_limited(accounts):
    register(accounts)
    for name in ("alice@example.com", "unknown@example.com"):
        for _ in range(10):
            with pytest.raises(AuthenticationFailed, match="Incorrect email or password"):
                accounts.login(name, REPLACEMENT)
        with pytest.raises(RateLimited):
            accounts.login(name, REPLACEMENT)


def test_session_count_is_bounded(accounts, clock):
    first = register(accounts)
    sessions = [first]
    for _ in range(10):
        clock[0] += 61
        sessions.append(accounts.login("alice@example.com", PASSWORD))
    assert accounts.authenticate_session(first["session_token"]) is None
    assert all(accounts.authenticate_session(session["session_token"]) for session in sessions[1:])


def test_keys_are_named_hashed_revocable_and_tenant_scoped(accounts):
    alice, bob = register(accounts), register(accounts, "bob")
    tenant = alice["account"]["id"]
    key = accounts.issue_api_key(tenant, "My MCP client")
    assert accounts.authenticate_api_key(key["api_key"]) == tenant
    listing = accounts.list_api_keys(tenant)["items"]
    assert listing[0]["name"] == "My MCP client" and listing[0]["revoked"] is False
    assert key["api_key"] not in json.dumps(listing)
    assert key["api_key"] not in json.dumps(accounts.store.get("credential:" + key["id"]).data)
    with pytest.raises(ValueError, match="not found"):
        accounts.revoke_api_key(bob["account"]["id"], key["id"])
    accounts.revoke_api_key(tenant, key["id"])
    accounts.revoke_api_key(tenant, key["id"])
    assert accounts.authenticate_api_key(key["api_key"]) is None
    assert accounts.list_api_keys(tenant)["items"][0]["revoked"] is True


def test_key_expiration_and_quota(accounts, clock):
    tenant = register(accounts)["account"]["id"]
    keys = [
        accounts.issue_api_key(tenant, f"client-{index}", lifetime_seconds=60)
        for index in range(10)
    ]
    with pytest.raises(ValueError, match="quota"):
        accounts.issue_api_key(tenant, "overflow")
    clock[0] += 60
    assert all(accounts.authenticate_api_key(key["api_key"]) is None for key in keys)
    assert accounts.issue_api_key(tenant, "replacement")["api_key"]
    page = accounts.list_api_keys(tenant, limit=3)
    assert len(page["items"]) == 3 and page["next_cursor"]
    assert len(accounts.list_api_keys(tenant, limit=3, cursor=page["next_cursor"])["items"]) == 3


def test_signing_out_everywhere_revokes_sessions_keys_and_grants(accounts):
    original = register(accounts)
    other = accounts.login("alice@example.com", PASSWORD)
    tenant = original["account"]["id"]
    key = accounts.issue_api_key(tenant, "client")
    old_epoch = accounts.auth_epoch(tenant)
    with pytest.raises(IncorrectPassword):
        accounts.sign_out_everywhere(tenant, REPLACEMENT)
    renewed = accounts.sign_out_everywhere(tenant, PASSWORD)
    assert accounts.authenticate_session(original["session_token"]) is None
    assert accounts.authenticate_session(other["session_token"]) is None
    assert accounts.authenticate_session(renewed["session_token"])
    assert accounts.authenticate_api_key(key["api_key"]) is None
    assert accounts.validate_account_active(tenant) is True
    assert accounts.validate_account_active(tenant, old_epoch) is False
    assert accounts.validate_account_active(tenant, accounts.auth_epoch(tenant)) is True
    assert accounts.validate_account_active(tenant, True) is False
    assert accounts.list_api_keys(tenant)["items"][0]["revoked"] is True
    assert accounts.login("alice@example.com", PASSWORD)["account"]["id"] == tenant


def test_delete_requires_password_revokes_all_access_and_stops_collection(
    accounts, flight_url, clock
):
    alice = register(accounts)
    tenant = alice["account"]["id"]
    service = MonitoringService(accounts.store, lambda: clock[0], global_target_limit=20)
    monitor = service.create_monitor(tenant, flight_url, "delete-account-monitor")
    key = accounts.issue_api_key(tenant, "client")
    service.record(Reading(monitor["target_id"], 30000, "USD", clock[0], "test"), "initial")
    service.process_events()
    with pytest.raises(IncorrectPassword):
        accounts.delete_account(tenant, REPLACEMENT)
    assert accounts.delete_account(tenant, PASSWORD) == {"deleted": True}
    assert accounts.authenticate_session(alice["session_token"]) is None
    assert accounts.authenticate_api_key(key["api_key"]) is None
    assert accounts.validate_account_active(tenant) is False
    assert service.get_monitor(tenant, monitor["id"])["status"] == "cancelled"
    assert service.store.get("target:" + monitor["target_id"]).data["subscribers"] == []
    assert service.store.get("capacity:collection").data["targets"] == []
    assert service.store.get("tenant:" + tenant).data["preferences"]["muted"] is True
    assert "password_hash" not in service.store.get("account:" + tenant).data
    assert "recovery_hash" not in service.store.get("account:" + tenant).data
    assert service.store.get("account:" + tenant).data["username"] == ""
    accounts.cleanup_deleted_account(tenant)
    assert service.store.get("tenant:" + tenant).data["monitors"] == 0
    with pytest.raises(AuthenticationFailed):
        accounts.login("alice@example.com", PASSWORD)


def test_deleted_account_does_not_stop_other_subscribers(accounts, flight_url, clock):
    alice, bob = register(accounts), register(accounts, "bob")
    service = MonitoringService(accounts.store, lambda: clock[0], global_target_limit=20)
    first = service.create_monitor(alice["account"]["id"], flight_url, "alice-monitor")
    second = service.create_monitor(bob["account"]["id"], flight_url, "bob-monitor")
    accounts.delete_account(alice["account"]["id"], PASSWORD)
    assert service.store.get("target:" + first["target_id"]).data["subscribers"] == [second["id"]]
    assert service.store.get("capacity:collection").data["targets"] == [second["target_id"]]


def test_login_cannot_issue_session_across_an_epoch_change(accounts, monkeypatch):
    initial = register(accounts)
    tenant = initial["account"]["id"]
    commit = accounts.store.commit
    raced = [False]

    def competing_commit(documents):
        if not raced[0] and any(doc.key.startswith("session:") for doc in documents):
            raced[0] = True
            account = accounts.store.get("account:" + tenant)
            commit([account.update({**account.data, "auth_epoch": account.data["auth_epoch"] + 1})])
        return commit(documents)

    monkeypatch.setattr(accounts.store, "commit", competing_commit)
    with pytest.raises(AuthenticationFailed, match="changed"):
        accounts.login("alice@example.com", PASSWORD)


def test_api_key_revocation_between_authentication_reads_is_observed(accounts, monkeypatch):
    tenant = register(accounts)["account"]["id"]
    key = accounts.issue_api_key(tenant, "client")
    get = accounts.store.get
    reads = [0]

    def revoking_get(identifier):
        if identifier == "credential:" + key["id"]:
            reads[0] += 1
            if reads[0] == 2:
                document = get(identifier)
                accounts.store.commit([document.update({**document.data, "revoked": True})])
        return get(identifier)

    monkeypatch.setattr(accounts.store, "get", revoking_get)
    assert accounts.authenticate_api_key(key["api_key"]) is None


def test_a_sign_up_race_for_one_email_creates_one_account(accounts, monkeypatch):
    commit = accounts.store.commit
    raced = [False]

    def competing_commit(documents):
        if not raced[0] and any(doc.key.startswith("account:") for doc in documents):
            raced[0] = True
            key = "email:" + hashlib.sha256(b"alice@example.com").hexdigest()
            commit([module.Document(key, "emails", {"account_id": "acct_" + "0" * 32})])
        return commit(documents)

    monkeypatch.setattr(accounts.store, "commit", competing_commit)
    with pytest.raises(ValueError, match="already uses that email"):
        accounts.register("alice@example.com", PASSWORD)
    assert accounts.store.query("accounts") == []
