"""Customer authentication and lifecycle contracts on SQLite and DynamoDB."""
import hashlib
import json

import pytest

from gfpt_next import accounts as module
from gfpt_next.accounts import Accounts, AuthenticationFailed, hash_password, verify_password
from gfpt_next.credentials import RateLimited
from gfpt_next.product_config import ProductConfig
from gfpt_next.service import MonitoringService, Reading

PASSWORD = "my development passphrase"
REPLACEMENT = "my replacement passphrase"


@pytest.fixture
def accounts(store, clock):
    return Accounts(store, ProductConfig(), lambda: clock[0])


def register(accounts, username="alice"):
    invitation = accounts.create_invite()
    return accounts.register(username, PASSWORD, invitation["token"])


def test_default_product_is_free_invite_only_and_bounded():
    config = ProductConfig.from_env({})
    assert config.public() == {"product_name": "Fareflare", "billing_enabled": False,
        "capabilities": {"route_searches": False},
        "registration_mode": "invite", "limits": {"monitors": 3, "min_interval_seconds": 900, "global_targets": 20}}
    assert ProductConfig.from_env({"GFPT_NEXT_SEARCH_ENABLED": "true"}).search_enabled is True
    with pytest.raises(ValueError):
        ProductConfig.from_env({"GFPT_NEXT_SEARCH_ENABLED": "maybe"})
    with pytest.raises(ValueError):
        ProductConfig.from_env({"GFPT_NEXT_BILLING_ENABLED": "true"})
    with pytest.raises(ValueError):
        ProductConfig.from_env({"GFPT_NEXT_BILLING_ENABLED": "maybe"})
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


def test_invite_is_required_single_use_and_expires(accounts, clock):
    with pytest.raises(ValueError, match="invitation"):
        accounts.register("alice", PASSWORD)
    invitation = accounts.create_invite(lifetime_seconds=60)
    clock[0] += 60
    with pytest.raises(ValueError, match="invitation"):
        accounts.register("alice", PASSWORD, invitation["token"])
    invitation = accounts.create_invite()
    registered = accounts.register("ALICE", PASSWORD, invitation["token"])
    assert registered["account"]["username"] == "alice"
    with pytest.raises(ValueError, match="invitation"):
        accounts.register("bob", PASSWORD, invitation["token"])
    assert len(accounts.store.query("accounts")) == 1


def test_open_registration_is_explicit_and_unique_names_are_case_insensitive(store, clock):
    accounts = Accounts(store, ProductConfig(registration_mode="open"), lambda: clock[0])
    accounts.register("Alice", PASSWORD)
    with pytest.raises(ValueError, match="username"):
        accounts.register("ALICE", PASSWORD)
    with pytest.raises(ValueError):
        accounts.register("bad/name", PASSWORD)
    with pytest.raises(ValueError):
        accounts.register("bob", "short")


def test_sessions_are_hashed_expire_and_logout_idempotently(accounts, clock):
    result = register(accounts)
    authenticated = accounts.authenticate_session(result["session_token"])
    assert authenticated is not None
    assert authenticated["account"] == result["account"]
    assert authenticated["csrf_token"] == result["csrf_token"]
    tenant = result["account"]["id"]
    raw = json.dumps([doc.data for doc in accounts.store.query("accounts")]
                     + [doc.data for doc in accounts.store.query("sessions:" + tenant)])
    for secret in (PASSWORD, result["session_token"], result["csrf_token"], result["recovery_code"]):
        assert secret not in raw
    assert accounts.authenticate_session("x" * 43) is None
    accounts.logout(result["session_token"])
    accounts.logout(result["session_token"])
    assert accounts.authenticate_session(result["session_token"]) is None
    login = accounts.login("ALICE", PASSWORD)
    clock[0] = login["expires_at"]
    assert accounts.authenticate_session(login["session_token"]) is None


def test_bad_login_is_generic_and_rate_limited(accounts):
    register(accounts)
    for name in ("alice", "unknown"):
        for _ in range(10):
            with pytest.raises(AuthenticationFailed, match="Invalid username or password"):
                accounts.login(name, REPLACEMENT)
        with pytest.raises(RateLimited):
            accounts.login(name, REPLACEMENT)


def test_session_count_is_bounded(accounts, clock):
    first = register(accounts)
    sessions = [first]
    for _ in range(10):
        clock[0] += 61
        sessions.append(accounts.login("alice", PASSWORD))
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
    keys = [accounts.issue_api_key(tenant, f"client-{index}", lifetime_seconds=60) for index in range(10)]
    with pytest.raises(ValueError, match="quota"):
        accounts.issue_api_key(tenant, "overflow")
    clock[0] += 60
    assert all(accounts.authenticate_api_key(key["api_key"]) is None for key in keys)
    assert accounts.issue_api_key(tenant, "replacement")["api_key"]
    page = accounts.list_api_keys(tenant, limit=3)
    assert len(page["items"]) == 3 and page["next_cursor"]
    assert len(accounts.list_api_keys(tenant, limit=3, cursor=page["next_cursor"])["items"]) == 3


def test_recovery_rotates_code_and_invalidates_sessions_keys_and_grants(accounts):
    original = register(accounts)
    tenant = original["account"]["id"]
    key = accounts.issue_api_key(tenant, "client")
    old_epoch = accounts.auth_epoch(tenant)
    with pytest.raises(AuthenticationFailed):
        accounts.recover("alice", "x" * 43, REPLACEMENT)
    recovered = accounts.recover("alice", original["recovery_code"], REPLACEMENT)
    assert recovered["recovery_code"] != original["recovery_code"]
    assert accounts.authenticate_session(original["session_token"]) is None
    assert accounts.authenticate_session(recovered["session_token"])
    assert accounts.authenticate_api_key(key["api_key"]) is None
    assert accounts.validate_account_active(tenant) is True
    assert accounts.validate_account_active(tenant, old_epoch) is False
    assert accounts.validate_account_active(tenant, accounts.auth_epoch(tenant)) is True
    assert accounts.validate_account_active(tenant, True) is False
    assert accounts.list_api_keys(tenant)["items"][0]["revoked"] is True
    with pytest.raises(AuthenticationFailed):
        accounts.recover("alice", original["recovery_code"], PASSWORD)
    with pytest.raises(AuthenticationFailed):
        accounts.login("alice", PASSWORD)
    assert accounts.login("alice", REPLACEMENT)["account"]["id"] == tenant


def test_delete_requires_password_revokes_all_access_and_stops_collection(accounts, flight_url, clock):
    alice = register(accounts)
    tenant = alice["account"]["id"]
    service = MonitoringService(accounts.store, lambda: clock[0], global_target_limit=20)
    monitor = service.create_monitor(tenant, flight_url, "delete-account-monitor")
    key = accounts.issue_api_key(tenant, "client")
    service.record(Reading(monitor["target_id"], 30000, "USD", clock[0], "test"), "initial")
    service.process_events()
    with pytest.raises(AuthenticationFailed):
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
        accounts.login("alice", PASSWORD)


def test_deleted_account_does_not_stop_other_subscribers(accounts, flight_url, clock):
    alice, bob = register(accounts), register(accounts, "bob")
    service = MonitoringService(accounts.store, lambda: clock[0], global_target_limit=20)
    first = service.create_monitor(alice["account"]["id"], flight_url, "alice-monitor")
    second = service.create_monitor(bob["account"]["id"], flight_url, "bob-monitor")
    accounts.delete_account(alice["account"]["id"], PASSWORD)
    assert service.store.get("target:" + first["target_id"]).data["subscribers"] == [second["id"]]
    assert service.store.get("capacity:collection").data["targets"] == [second["target_id"]]


def test_login_cannot_issue_session_across_recovery_race(accounts, monkeypatch):
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
        accounts.login("alice", PASSWORD)


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


def test_invite_consumption_is_transaction_fenced(accounts, monkeypatch):
    invitation = accounts.create_invite()
    key = "invite:" + hashlib.sha256(invitation["token"].encode()).hexdigest()
    commit = accounts.store.commit
    raced = [False]

    def competing_commit(documents):
        if not raced[0] and any(doc.key.startswith("account:") for doc in documents):
            raced[0] = True
            invite = accounts.store.get(key)
            commit([invite.update({**invite.data, "used": True})])
        return commit(documents)

    monkeypatch.setattr(accounts.store, "commit", competing_commit)
    with pytest.raises(ValueError, match="no longer available"):
        accounts.register("alice", PASSWORD, invitation["token"])
    assert accounts.store.query("accounts") == []
