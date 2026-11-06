"""Invite onboarding, password authentication, opaque sessions and customer keys.

No mail or payment provider is required. Passwords use the OWASP scrypt baseline;
session, invite, API and recovery credentials are stored only as hashes.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import uuid
from collections.abc import Callable

from fareflare.credentials import Credentials, RateLimiter
from fareflare.product_config import ProductConfig
from fareflare.store import Conflict, Document, Store

_SESSION_LIFETIME = 7 * 86400
_MAX_SESSIONS = 10
_MAX_KEYS = 10
_SCRYPT_N = 2**17
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 256 * 1024 * 1024
_DUMMY_SALT = bytes.fromhex("86924ed509cef2bf4148bfffc357c86d")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_ACCOUNT = re.compile(r"acct_[a-f0-9]{32}\Z")


class AuthenticationFailed(ValueError):
    """Authentication failed without disclosing whether an account exists."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _username(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}", value):
        raise ValueError("Username must contain 3–40 letters, numbers, periods, underscores or hyphens")
    return value.lower()


def _password(value: str) -> bytes:
    if not isinstance(value, str) or not 15 <= len(value) <= 128 or len(value.encode()) > 1024:
        raise ValueError("Use a password containing 15–128 characters")
    return value.encode()


def _derive(password: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(password, salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                          maxmem=_SCRYPT_MAXMEM, dklen=32)


def hash_password(value: str) -> str:
    salt = secrets.token_bytes(16)
    return "scrypt$131072$8$1$" + salt.hex() + "$" + _derive(_password(value), salt).hex()


def verify_password(value: str, stored: str | None) -> bool:
    """Unknown accounts perform the same expensive derivation as valid accounts."""
    password = _password(value)
    valid = False
    salt, expected = _DUMMY_SALT, bytes(32)
    if isinstance(stored, str):
        pieces = stored.split("$")
        if (len(pieces) == 6 and pieces[:4] == ["scrypt", "131072", "8", "1"]
                and re.fullmatch(r"[a-f0-9]{32}", pieces[4])
                and re.fullmatch(r"[a-f0-9]{64}", pieces[5])):
            salt, expected, valid = bytes.fromhex(pieces[4]), bytes.fromhex(pieces[5]), True
    matches = hmac.compare_digest(_derive(password, salt), expected)
    return valid and matches


def _csrf(token: str) -> str:
    return hmac.new(token.encode(), b"gfpt-browser-csrf-v1", hashlib.sha256).hexdigest()


class Accounts:
    def __init__(self, store: Store, config: ProductConfig | None = None,
                 clock: Callable[[], float] = time.time):
        self.store, self.config, self.clock = store, config or ProductConfig(), clock
        self._credentials = Credentials(store, clock)
        self._login_limit = RateLimiter(store, clock, per_minute=10)
        self._recovery_limit = RateLimiter(store, clock, per_minute=5)

    def _now(self) -> int:
        return int(self.clock())

    @staticmethod
    def _public(account: Document) -> dict:
        return {name: account.data[name] for name in ("id", "username", "created_at")}

    def _account(self, tenant: str) -> Document:
        if not isinstance(tenant, str) or not _ACCOUNT.fullmatch(tenant):
            raise AuthenticationFailed("Account unavailable")
        account = self.store.get("account:" + tenant)
        if not account or account.data.get("status") != "active":
            raise AuthenticationFailed("Account unavailable")
        return account

    def get_account(self, tenant: str) -> dict:
        return self._public(self._account(tenant))

    def auth_epoch(self, tenant: str) -> int:
        return self._account(tenant).data["auth_epoch"]

    def validate_account_active(self, tenant: str, epoch: int | None = None) -> bool:
        if epoch is not None and type(epoch) is not int:
            return False
        try:
            account = self._account(tenant)
        except AuthenticationFailed:
            return False
        return epoch is None or account.data["auth_epoch"] == epoch

    def create_invite(self, lifetime_seconds: int = 7 * 86400) -> dict:
        if type(lifetime_seconds) is not int or not 60 <= lifetime_seconds <= 30 * 86400:
            raise ValueError("Invitation lifetime must be 60 seconds to 30 days")
        token, expires = secrets.token_urlsafe(32), self._now() + lifetime_seconds
        self.store.commit([Document("invite:" + _digest(token), "invites", {
            "created_at": self._now(), "expires_at": expires, "used": False,
        }, expires_at=expires)])
        return {"token": token, "expires_at": expires}

    def _invite(self, token: str | None) -> Document | None:
        if self.config.registration_mode == "open" and token is None:
            return None
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise ValueError("A valid unused invitation is required")
        invite = self.store.get("invite:" + _digest(token))
        if not invite or invite.data["used"] or invite.data["expires_at"] <= self._now():
            raise ValueError("A valid unused invitation is required")
        return invite

    def _session(self, account: Document) -> tuple[dict, list[Document]]:
        token, expires = secrets.token_urlsafe(32), self._now() + _SESSION_LIFETIME
        identifier = _digest(token)
        session = Document("session:" + identifier, "sessions:" + account.data["id"], {
            "tenant": account.data["id"], "auth_epoch": account.data["auth_epoch"],
            "expires_at": expires, "revoked": False,
        }, expires_at=expires)
        data = {**account.data, "session_ids": [*account.data.get("session_ids", []), identifier][-_MAX_SESSIONS:],
                "last_login_at": self._now()}
        return {"account": self._public(account), "session_token": token, "csrf_token": _csrf(token),
                "expires_at": expires}, [account.update(data), session]

    def register(self, username: str, password: str, invite_token: str | None = None) -> dict:
        username = _username(username)
        _password(password)
        self._login_limit.consume("register-" + _digest(username))
        invite = self._invite(invite_token)
        username_key = "username:" + _digest(username)
        if self.store.get(username_key):
            raise ValueError("This username is unavailable")
        tenant, recovery = "acct_" + uuid.uuid4().hex, secrets.token_urlsafe(32)
        account = Document("account:" + tenant, "accounts", {
            "id": tenant, "username": username, "created_at": self._now(), "status": "active",
            "password_hash": hash_password(password), "recovery_hash": _digest(recovery),
            "auth_epoch": 1, "key_ids": [], "session_ids": [],
        })
        response, writes = self._session(account)
        writes.extend([
            Document(username_key, "usernames", {"account_id": tenant}),
            Document("tenant:" + tenant, "tenants", {"monitors": 0, "webhooks": 0}),
        ])
        if invite:
            writes.append(invite.update({**invite.data, "used": True}))
        try:
            self.store.commit(writes)
        except Conflict:
            raise ValueError("The username or invitation is no longer available") from None
        return {**response, "recovery_code": recovery}

    def login(self, username: str, password: str) -> dict:
        username = _username(username)
        _password(password)
        self._login_limit.consume("login-" + _digest(username))
        index = self.store.get("username:" + _digest(username))
        account = self.store.get("account:" + index.data["account_id"]) if index else None
        stored = account.data.get("password_hash") if account and account.data["status"] == "active" else None
        if not verify_password(password, stored) or account is None:
            raise AuthenticationFailed("Invalid username or password")
        response, writes = self._session(account)
        try:
            self.store.commit(writes)
        except Conflict:
            raise AuthenticationFailed("Account changed; sign in again") from None
        return response

    def authenticate_session(self, token: str) -> dict | None:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return None
        identifier = _digest(token)
        session = self.store.get("session:" + identifier)
        if not session or session.data["revoked"] or session.data["expires_at"] <= self._now():
            return None
        try:
            account = self._account(session.data["tenant"])
        except AuthenticationFailed:
            return None
        if (session.data["auth_epoch"] != account.data["auth_epoch"]
                or identifier not in account.data.get("session_ids", [])):
            return None
        return {"account": self._public(account), "csrf_token": _csrf(token),
                "expires_at": session.data["expires_at"]}

    def logout(self, token: str) -> None:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return
        key = "session:" + _digest(token)
        for _ in range(5):
            session = self.store.get(key)
            if not session or session.data["revoked"]:
                return
            try:
                self.store.commit([session.update({**session.data, "revoked": True})])
                return
            except Conflict:
                continue
        raise Conflict("Concurrent session change; retry logout")

    def recover(self, username: str, recovery_code: str, new_password: str) -> dict:
        username = _username(username)
        _password(new_password)
        self._recovery_limit.consume("recovery-" + _digest(username))
        index = self.store.get("username:" + _digest(username))
        account = self.store.get("account:" + index.data["account_id"]) if index else None
        supplied = _digest(recovery_code) if isinstance(recovery_code, str) and _TOKEN.fullmatch(recovery_code) else ""
        expected = account.data.get("recovery_hash", "") if account else ""
        if (not supplied or not hmac.compare_digest(supplied, expected) or account is None
                or account.data["status"] != "active"):
            raise AuthenticationFailed("Invalid recovery credentials")
        recovery = secrets.token_urlsafe(32)
        updated = account.update({**account.data, "password_hash": hash_password(new_password),
                                  "recovery_hash": _digest(recovery), "auth_epoch": account.data["auth_epoch"] + 1,
                                  "session_ids": [], "key_ids": []})
        response, writes = self._session(updated)
        try:
            self.store.commit(writes)
        except Conflict:
            raise AuthenticationFailed("Account changed; retry recovery") from None
        return {**response, "recovery_code": recovery}

    def issue_api_key(self, tenant: str, name: str, lifetime_seconds: int = 90 * 86400) -> dict:
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                or any(ord(character) < 32 for character in name)
                or type(lifetime_seconds) is not int or not 60 <= lifetime_seconds <= 365 * 86400):
            raise ValueError("Provide a key name and a lifetime between 60 seconds and one year")
        for _ in range(5):
            account = self._account(tenant)
            active = []
            for identifier in account.data.get("key_ids", []):
                key = self.store.get("credential:" + identifier)
                if key and not key.data["revoked"] and key.data["expires_at"] > self._now():
                    active.append(identifier)
            if len(active) >= _MAX_KEYS:
                raise ValueError("API key quota reached (10 active keys)")
            token = secrets.token_urlsafe(32)
            identifier = _digest(token)
            key = Document("credential:" + identifier, "credentials:" + tenant, {
                "tenant": tenant, "revoked": False, "created_at": self._now(), "name": name.strip(),
                "expires_at": self._now() + lifetime_seconds, "auth_epoch": account.data["auth_epoch"],
            }, due=self._now(), expires_at=self._now() + lifetime_seconds + 30 * 86400)
            try:
                self.store.commit([key, account.update({**account.data, "key_ids": [*active, identifier]})])
                return {"id": identifier, "api_key": token}
            except Conflict:
                continue
        raise Conflict("Concurrent key creation; retry the request")

    def authenticate_api_key(self, token: str) -> str | None:
        if not isinstance(token, str):
            return None
        tenant = self._credentials.authenticate(token)
        if tenant is None:
            return None
        try:
            account = self._account(tenant)
        except AuthenticationFailed:
            return None
        identifier = _digest(token)
        key = self.store.get("credential:" + identifier)
        if (key and not key.data["revoked"] and key.data["expires_at"] > self._now()
                and key.data.get("auth_epoch") == account.data["auth_epoch"]
                and identifier in account.data.get("key_ids", [])):
            return tenant
        return None

    def list_api_keys(self, tenant: str, limit: int = 100, cursor: str | None = None) -> dict:
        account = self._account(tenant)
        items = []
        page = self.store.page("credentials:" + tenant, limit=limit, cursor=cursor, reverse=True)
        for document in page.items:
            current = self.store.get(document.key)
            if not current or current.data["tenant"] != tenant:
                continue
            data = current.data
            items.append({"id": current.key.removeprefix("credential:"), "name": data.get("name", "API key"),
                          "created_at": data.get("created_at", 0), "expires_at": data["expires_at"],
                          "revoked": data["revoked"] or data.get("auth_epoch") != account.data["auth_epoch"]})
        return {"items": items, "next_cursor": page.cursor}

    def revoke_api_key(self, tenant: str, identifier: str) -> None:
        self._account(tenant)
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise ValueError("API key not found")
        for _ in range(5):
            key = self.store.get("credential:" + identifier)
            if not key or key.data["tenant"] != tenant:
                raise ValueError("API key not found")
            if key.data["revoked"]:
                return
            try:
                self.store.commit([key.update({**key.data, "revoked": True})])
                return
            except Conflict:
                continue
        raise Conflict("Concurrent key change; retry revocation")

    def delete_account(self, tenant: str, password: str) -> dict:
        account = self._account(tenant)
        self._login_limit.consume("delete-" + _digest(tenant))
        if not verify_password(password, account.data.get("password_hash")):
            raise AuthenticationFailed("Invalid username or password")
        customer = self.store.get("tenant:" + tenant)
        assert customer is not None
        # The primary fence makes sessions, grants, keys and future collection stop
        # immediately. GSI discovery below is only cleanup, never the security gate.
        self.store.commit([
            account.update({"id": tenant, "username": "", "created_at": account.data["created_at"],
                            "status": "deleted", "auth_epoch": account.data["auth_epoch"] + 1,
                            "session_ids": [], "key_ids": []}),
            customer.update({**customer.data, "preferences": {"muted": True, "muted_routes": []},
                             "notification_epoch": customer.data.get("notification_epoch", 0) + 1}),
        ])
        self.cleanup_deleted_account(tenant)
        return {"deleted": True}

    def cleanup_deleted_account(self, tenant: str) -> None:
        """Idempotent cleanup; authenticated access is already permanently revoked."""
        account = self.store.get("account:" + tenant)
        if not account or account.data.get("status") != "deleted":
            raise ValueError("Only deleted accounts can be cleaned up")
        for _ in range(5):
            binding = self.store.get("telegram-account:" + tenant)
            if not binding or "tenant" not in binding.data:
                break
            writes = [binding.update({"connected": False}, expires_at=self._now())]
            chat_id = binding.data.get("chat_id")
            chat = self.store.get("telegram-chat:" + chat_id) if chat_id else None
            if chat and chat.data.get("tenant") == tenant:
                writes.append(chat.update({"connected": False}, expires_at=self._now()))
            try:
                self.store.commit(writes)
                break
            except Conflict:
                continue
        else:
            raise Conflict("Telegram cleanup contention; retry account cleanup")
        for index in self.store.query("monitors:" + tenant):
            for _ in range(5):
                monitor = self.store.get(index.key)
                if not monitor or monitor.data["tenant"] != tenant or monitor.data["status"] == "cancelled":
                    break
                target = self.store.get("target:" + monitor.data["target_id"])
                customer = self.store.get("tenant:" + tenant)
                assert target is not None and customer is not None
                subscribers = [mid for mid in target.data["subscribers"] if mid != monitor.data["id"]]
                writes = [
                    monitor.update({**monitor.data, "status": "cancelled",
                                    "quota_released": True,
                                    "notification_epoch": monitor.data.get("notification_epoch", 0) + 1}),
                    target.update({**target.data, "subscribers": subscribers}),
                    customer.update({**customer.data, "monitors": max(0, customer.data["monitors"]
                                    - (0 if monitor.data.get("quota_released", False) else 1))}),
                ]
                capacity = self.store.get("capacity:collection")
                if not subscribers and capacity and monitor.data["target_id"] in capacity.data["targets"]:
                    writes.append(capacity.update({"targets": [identifier for identifier in capacity.data["targets"]
                                                               if identifier != monitor.data["target_id"]]}))
                try:
                    self.store.commit(writes)
                    break
                except Conflict:
                    continue
        for index in self.store.query("webhooks:" + tenant):
            for _ in range(5):
                endpoint = self.store.get(index.key)
                if not endpoint or endpoint.data["tenant"] != tenant or endpoint.data["status"] == "deleted":
                    break
                data = {**endpoint.data, "status": "deleted", "generation": endpoint.data["generation"] + 1,
                        "challenge_hash": None, "challenge_expires_at": 0}
                data.pop("signing_secret", None)
                try:
                    self.store.commit([endpoint.update(data)])
                    break
                except Conflict:
                    continue
