"""Sign-up, sign-in, sessions, two-step codes, passkeys, password resets and API keys.

Passwords use the OWASP scrypt baseline. Session, API, reset and confirmation
credentials are stored only as hashes. Email is sent only to reset a password or
confirm an address, and a reset link goes only to a confirmed address.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging
import re
import secrets
import time
import uuid
from collections.abc import Callable

from fareflare import mailer as mail
from fareflare import totp
from fareflare.credentials import Credentials, RateLimiter
from fareflare.passkeys import Passkeys
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
log = logging.getLogger(__name__)
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_ACCOUNT = re.compile(r"acct_[a-f0-9]{32}\Z")
_RESET_MINUTES = 30
_CONFIRM_SECONDS = 86400
_TWO_FACTOR_SECONDS = 300
_TWO_FACTOR_ATTEMPTS = 5
_SETUP_SECONDS = 900
_EMAIL_COOLDOWN = 60
MAX_USERNAME_LENGTH = 254
_USERNAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}")
# New accounts sign in with their email address. Accounts created before email
# was required may still sign in with a username.
_EMAIL = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9._%+-]{0,63}"
    r"@[a-zA-Z0-9][a-zA-Z0-9-]{0,62}(?:\.[a-zA-Z0-9][a-zA-Z0-9-]{0,62})*\.[a-zA-Z]{2,24}"
)


class AuthenticationFailed(ValueError):
    """Authentication failed without disclosing whether an account exists."""


class IncorrectPassword(ValueError):
    """A signed-in person confirmed an action with the wrong password or code.

    Distinct from ``AuthenticationFailed``: the session is still valid, so the
    browser must not treat this as having been signed out.
    """


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _username(value: str) -> str:
    """A sign-in name: an email address, or the username of an older account."""
    if (
        not isinstance(value, str)
        or len(value) > MAX_USERNAME_LENGTH
        or not (_USERNAME.fullmatch(value) or _EMAIL.fullmatch(value))
    ):
        raise ValueError("Enter your email address")
    return value.lower()


def _email(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_USERNAME_LENGTH
        or not _EMAIL.fullmatch(value.strip())
    ):
        raise ValueError("Enter an email address, like name@example.com")
    return value.strip().lower()


def _password(value: str) -> bytes:
    if not isinstance(value, str) or not 15 <= len(value) <= 128 or len(value.encode()) > 1024:
        raise ValueError("Use a password containing 15–128 characters")
    return value.encode()


def _derive(password: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password, salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, maxmem=_SCRYPT_MAXMEM, dklen=32
    )


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
        if (
            len(pieces) == 6
            and pieces[:4] == ["scrypt", "131072", "8", "1"]
            and re.fullmatch(r"[a-f0-9]{32}", pieces[4])
            and re.fullmatch(r"[a-f0-9]{64}", pieces[5])
        ):
            salt, expected, valid = bytes.fromhex(pieces[4]), bytes.fromhex(pieces[5]), True
    matches = hmac.compare_digest(_derive(password, salt), expected)
    return valid and matches


def _csrf(token: str) -> str:
    return hmac.new(token.encode(), b"gfpt-browser-csrf-v1", hashlib.sha256).hexdigest()


class Accounts:
    def __init__(
        self,
        store: Store,
        config: ProductConfig | None = None,
        clock: Callable[[], float] = time.time,
        mailer: mail.Mailer | None = None,
    ):
        self.store, self.config, self.clock = store, config or ProductConfig(), clock
        self.mailer = mailer
        self._credentials = Credentials(store, clock)
        self._login_limit = RateLimiter(store, clock, per_minute=10)
        self._code_limit = RateLimiter(store, clock, per_minute=6)
        self._email_limit = RateLimiter(store, clock, per_minute=5)
        self.passkeys = Passkeys(
            store,
            self.config.public_url or "http://localhost",
            self.config.product_name,
            clock,
        )

    def _now(self) -> int:
        return int(self.clock())

    @staticmethod
    def _public(account: Document) -> dict:
        data = account.data
        return {
            "id": data["id"],
            "username": data["username"],
            "created_at": data["created_at"],
            "email": data.get("email"),
            "email_verified": bool(data.get("email_verified")),
        }

    def _account(self, tenant: str) -> Document:
        if not isinstance(tenant, str) or not _ACCOUNT.fullmatch(tenant):
            raise AuthenticationFailed("Account unavailable")
        account = self.store.get("account:" + tenant)
        if not account or account.data.get("status") != "active":
            raise AuthenticationFailed("Account unavailable")
        return account

    def _active(self, tenant: str) -> Document | None:
        try:
            return self._account(tenant)
        except AuthenticationFailed:
            return None

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

    @property
    def email_enabled(self) -> bool:
        return self.mailer is not None and bool(self.config.public_url)

    def _session(self, account: Document) -> tuple[dict, list[Document]]:
        token, expires = secrets.token_urlsafe(32), self._now() + _SESSION_LIFETIME
        identifier = _digest(token)
        session = Document(
            "session:" + identifier,
            "sessions:" + account.data["id"],
            {
                "tenant": account.data["id"],
                "auth_epoch": account.data["auth_epoch"],
                "expires_at": expires,
                "revoked": False,
            },
            expires_at=expires,
        )
        data = {
            **account.data,
            "session_ids": [*account.data.get("session_ids", []), identifier][-_MAX_SESSIONS:],
            "last_login_at": self._now(),
        }
        return {
            "account": self._public(account),
            "session_token": token,
            "csrf_token": _csrf(token),
            "expires_at": expires,
        }, [account.update(data), session]

    def _signed_in(self, account: Document, extra: list[Document] | None = None) -> dict:
        response, writes = self._session(account)
        try:
            self.store.commit([*writes, *(extra or [])])
        except Conflict:
            raise AuthenticationFailed("Account changed; sign in again") from None
        return response

    def _by_name(self, name: str) -> Document | None:
        """The account a sign-in name belongs to: a username first, then an email."""
        index = self.store.get("username:" + _digest(name))
        if not index and _EMAIL.fullmatch(name):
            index = self.store.get("email:" + _digest(name))
            if index and index.data.get("released"):
                index = None
        account = self.store.get("account:" + index.data["account_id"]) if index else None
        return account if account and account.data["status"] == "active" else None

    # Sign-up and sign-in.

    def register(self, email: str, password: str) -> dict:
        if self.config.registration_mode == "closed":
            raise ValueError("Sign-up is closed on this server")
        email = _email(email)
        _password(password)
        self._login_limit.consume("register-" + _digest(email))
        if self.store.get("username:" + _digest(email)) or self.store.get(
            "email:" + _digest(email)
        ):
            raise ValueError("An account already uses that email. Sign in, or reset your password.")
        tenant = "acct_" + uuid.uuid4().hex
        account = Document(
            "account:" + tenant,
            "accounts",
            {
                "id": tenant,
                "username": email,
                "email": email,
                "email_verified": False,
                "created_at": self._now(),
                "status": "active",
                "password_hash": hash_password(password),
                "auth_epoch": 1,
                "key_ids": [],
                "session_ids": [],
                "passkey_ids": [],
            },
        )
        response, writes = self._session(account)
        writes.extend(
            [
                Document("username:" + _digest(email), "usernames", {"account_id": tenant}),
                Document("email:" + _digest(email), "emails", {"account_id": tenant}),
                Document("tenant:" + tenant, "tenants", {"monitors": 0, "webhooks": 0}),
            ]
        )
        try:
            self.store.commit(writes)
        except Conflict:
            raise ValueError(
                "An account already uses that email. Sign in, or reset your password."
            ) from None
        self._send_confirmation(writes[0])
        return response

    def login(self, username: str, password: str) -> dict:
        """A session, or, for an account with two-step sign-in, a short-lived
        ``two_factor_token`` to exchange with a code."""
        name = _username(username)
        _password(password)
        self._login_limit.consume("login-" + _digest(name))
        account = self._by_name(name)
        stored = account.data.get("password_hash") if account else None
        if not verify_password(password, stored) or account is None:
            raise AuthenticationFailed("Incorrect email or password")
        if (account.data.get("totp") or {}).get("enabled"):
            token = secrets.token_urlsafe(32)
            expires = self._now() + _TWO_FACTOR_SECONDS
            self.store.commit(
                [
                    Document(
                        "login-challenge:" + _digest(token),
                        "login_challenges",
                        {
                            "tenant": account.data["id"],
                            "auth_epoch": account.data["auth_epoch"],
                            "expires_at": expires,
                            "attempts": 0,
                            "used": False,
                        },
                        expires_at=expires,
                    )
                ]
            )
            return {"two_factor_token": token, "expires_at": expires}
        return self._signed_in(account)

    def complete_login(self, token: str, code: str) -> dict:
        """Finish a password sign-in with an authenticator code or a backup code."""
        expired = AuthenticationFailed("This sign-in expired. Enter your password again.")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise expired
        challenge = self.store.get("login-challenge:" + _digest(token))
        if (
            not challenge
            or challenge.data["used"]
            or challenge.data["expires_at"] <= self._now()
            or challenge.data["attempts"] >= _TWO_FACTOR_ATTEMPTS
        ):
            raise expired
        account = self._active(challenge.data["tenant"])
        if account is None or account.data["auth_epoch"] != challenge.data["auth_epoch"]:
            raise expired
        self._code_limit.consume("login-code-" + account.data["id"])
        try:
            account = self._second_factor(account, code)
        except IncorrectPassword:
            with contextlib.suppress(Conflict):
                self.store.commit(
                    [
                        challenge.update(
                            {**challenge.data, "attempts": challenge.data["attempts"] + 1}
                        )
                    ]
                )
            raise AuthenticationFailed("That code is not correct") from None
        return self._signed_in(account, [challenge.update({**challenge.data, "used": True})])

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
        if session.data["auth_epoch"] != account.data[
            "auth_epoch"
        ] or identifier not in account.data.get("session_ids", []):
            return None
        return {
            "account": self._public(account),
            "csrf_token": _csrf(token),
            "expires_at": session.data["expires_at"],
        }

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

    # Passkeys.

    def passkey_login_options(self) -> dict:
        return self.passkeys.authentication_options()

    def passkey_login(self, challenge_id: object, credential: object) -> dict:
        account, used = self.passkeys.authenticate(challenge_id, credential, self._active)
        return self._signed_in(account, [used])

    def passkey_registration_options(self, tenant: str) -> dict:
        for _ in range(5):
            account = self._account(tenant)
            options, new_handle = self.passkeys.registration_options(account)
            if not new_handle:
                return options
            try:
                self.store.commit(
                    [account.update({**account.data, "webauthn_user_id": new_handle})]
                )
                return options
            except Conflict:
                continue
        raise Conflict("Your account changed in another window; try again")

    def add_passkey(self, tenant: str, challenge_id: object, credential: object, name: object):
        account = self._account(tenant)
        passkey, updated = self.passkeys.register(account, challenge_id, credential, name)
        try:
            self.store.commit([passkey, updated])
        except Conflict:
            raise Conflict("Your account changed in another window; try again") from None
        return self.passkeys._public(passkey)

    def list_passkeys(self, tenant: str) -> list[dict]:
        return self.passkeys.list(self._account(tenant))

    def rename_passkey(self, tenant: str, identifier: object, name: object) -> dict:
        return self.passkeys.rename(self._account(tenant), identifier, name)

    def remove_passkey(self, tenant: str, identifier: object) -> None:
        passkey, updated = self.passkeys.remove(self._account(tenant), identifier)
        try:
            self.store.commit([passkey, updated])
        except Conflict:
            raise Conflict("Your account changed in another window; try again") from None

    # Email: confirmation and password reset.

    def _send(self, message: mail.Message) -> None:
        """Send account email. A provider failure is logged, never shown: the
        answer to a reset request must not depend on whether mail went out."""
        if self.mailer is None:
            return
        try:
            self.mailer.send(message)
        except Exception:
            log.exception("Account email could not be sent")

    def _cooldown(self, key: str) -> bool:
        """True when a message of this kind may be sent to this address now."""
        existing = self.store.get(key)
        if existing and (existing.expires_at or 0) > self._now():
            return False
        document = Document(key, "email_cooldowns", {}, expires_at=self._now() + _EMAIL_COOLDOWN)
        try:
            self.store.commit(
                [existing.update({}, expires_at=document.expires_at) if existing else document]
            )
        except Conflict:
            return False
        return True

    def _send_confirmation(self, account: Document) -> None:
        email = account.data.get("email")
        if not self.email_enabled or not email or account.data.get("email_verified"):
            return
        if not self._cooldown("confirm-cooldown:" + _digest(email)):
            return
        token, expires = secrets.token_urlsafe(32), self._now() + _CONFIRM_SECONDS
        self.store.commit(
            [
                Document(
                    "confirm:" + _digest(token),
                    "email_confirmations",
                    {
                        "tenant": account.data["id"],
                        "email": email,
                        "used": False,
                        "expires_at": expires,
                    },
                    expires_at=expires,
                )
            ]
        )
        link = self.config.public_url.rstrip("/") + "/confirm-email#token=" + token
        self._send(mail.email_confirmation(self.config.product_name, email, link))

    def resend_confirmation(self, tenant: str) -> None:
        account = self._account(tenant)
        if not self.email_enabled:
            raise ValueError("Email is not set up on this server")
        if not account.data.get("email"):
            raise ValueError("Add an email address first")
        self._email_limit.consume("confirm-" + tenant)
        self._send_confirmation(account)

    def confirm_email(self, token: str) -> dict:
        invalid = ValueError("This confirmation link is no longer valid")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise invalid
        document = self.store.get("confirm:" + _digest(token))
        if not document or document.data["used"] or document.data["expires_at"] <= self._now():
            raise invalid
        account = self._active(document.data["tenant"])
        if account is None or account.data.get("email") != document.data["email"]:
            raise invalid
        try:
            self.store.commit(
                [
                    account.update({**account.data, "email_verified": True}),
                    document.update({**document.data, "used": True}),
                ]
            )
        except Conflict:
            raise invalid from None
        return {"confirmed": True, "email": document.data["email"]}

    def change_email(self, tenant: str, password: str, email: str) -> dict:
        email = _email(email)
        account = self._account(tenant)
        self._confirm_password(account, password, "email")
        if account.data.get("email") == email:
            self._send_confirmation(account)
            return self._public(account)
        owner = self.store.get("username:" + _digest(email))
        if owner and owner.data["account_id"] != tenant:
            raise ValueError("Another account already uses that email")
        writes = [
            account.update({**account.data, "email": email, "email_verified": False}),
        ]
        index = self.store.get("email:" + _digest(email))
        if index and not index.data.get("released") and index.data["account_id"] != tenant:
            raise ValueError("Another account already uses that email")
        claim = {"account_id": tenant}
        writes.append(
            index.update(claim) if index else Document("email:" + _digest(email), "emails", claim)
        )
        previous = account.data.get("email")
        if previous:
            old = self.store.get("email:" + _digest(previous))
            if old and old.data.get("account_id") == tenant:
                writes.append(old.update({**old.data, "released": True}))
        try:
            self.store.commit(writes)
        except Conflict:
            raise Conflict("Your account changed in another window; try again") from None
        self._send_confirmation(writes[0])
        return self._public(writes[0])

    def request_password_reset(self, email: str) -> None:
        """Send a reset link to a confirmed address. The reply never says whether an
        account exists, so the caller answers the same way either way."""
        email = _email(email)
        self._email_limit.consume("reset-" + _digest(email))
        if not self.email_enabled:
            raise ValueError("Password reset by email is not set up on this server")
        index = self.store.get("email:" + _digest(email))
        if not index or index.data.get("released"):
            return
        account = self._active(index.data["account_id"])
        if (
            account is None
            or account.data.get("email") != email
            or not account.data.get("email_verified")
            or not self._cooldown("reset-cooldown:" + _digest(email))
        ):
            return
        token = secrets.token_urlsafe(32)
        expires = self._now() + _RESET_MINUTES * 60
        self.store.commit(
            [
                Document(
                    "reset:" + _digest(token),
                    "password_resets",
                    {
                        "tenant": account.data["id"],
                        # A link dies once the password it was sent for has changed.
                        "password": _digest(account.data.get("password_hash", "")),
                        "used": False,
                        "expires_at": expires,
                    },
                    expires_at=expires,
                )
            ]
        )
        link = self.config.public_url.rstrip("/") + "/reset-password#token=" + token
        self._send(mail.password_reset(self.config.product_name, email, link, _RESET_MINUTES))

    def _reset(self, token: str) -> tuple[Document, Document]:
        invalid = ValueError("This reset link is no longer valid. Ask for a new one.")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise invalid
        document = self.store.get("reset:" + _digest(token))
        if not document or document.data["used"] or document.data["expires_at"] <= self._now():
            raise invalid
        account = self._active(document.data["tenant"])
        if account is None or document.data["password"] != _digest(
            account.data.get("password_hash", "")
        ):
            raise invalid
        return document, account

    def check_reset(self, token: str) -> dict:
        """What the reset page needs: the address (so a password manager saves the new
        password to the right login) and whether a code is needed too."""
        _, account = self._reset(token)
        return {
            "email": account.data.get("email"),
            "two_factor": bool((account.data.get("totp") or {}).get("enabled")),
        }

    def reset_password(self, token: str, new_password: str, code: str | None = None) -> dict:
        """Set a new password from an emailed link, then sign in. Every other browser
        is signed out; API keys, connected applications and Telegram stay."""
        _password(new_password)
        document, account = self._reset(token)
        self._code_limit.consume("reset-code-" + account.data["id"])
        if (account.data.get("totp") or {}).get("enabled"):
            if not code:
                raise IncorrectPassword("Enter a code from your authenticator app")
            account = self._second_factor(account, code)
        updated = account.update(
            {**account.data, "password_hash": hash_password(new_password), "session_ids": []}
        )
        return self._signed_in(updated, [document.update({**document.data, "used": True})])

    def issue_api_key(self, tenant: str, name: str, lifetime_seconds: int = 90 * 86400) -> dict:
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 80
            or any(ord(character) < 32 for character in name)
            or type(lifetime_seconds) is not int
            or not 60 <= lifetime_seconds <= 365 * 86400
        ):
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
            key = Document(
                "credential:" + identifier,
                "credentials:" + tenant,
                {
                    "tenant": tenant,
                    "revoked": False,
                    "created_at": self._now(),
                    "name": name.strip(),
                    "expires_at": self._now() + lifetime_seconds,
                    "auth_epoch": account.data["auth_epoch"],
                },
                due=self._now(),
                expires_at=self._now() + lifetime_seconds + 30 * 86400,
            )
            try:
                self.store.commit(
                    [key, account.update({**account.data, "key_ids": [*active, identifier]})]
                )
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
        if (
            key
            and not key.data["revoked"]
            and key.data["expires_at"] > self._now()
            and key.data.get("auth_epoch") == account.data["auth_epoch"]
            and identifier in account.data.get("key_ids", [])
        ):
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
            items.append(
                {
                    "id": current.key.removeprefix("credential:"),
                    "name": data.get("name", "API key"),
                    "created_at": data.get("created_at", 0),
                    "expires_at": data["expires_at"],
                    "revoked": data["revoked"]
                    or data.get("auth_epoch") != account.data["auth_epoch"],
                }
            )
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

    def _confirm_password(self, account: Document, password: str, purpose: str) -> None:
        """Check the signed-in person's password before a sensitive account change."""
        self._login_limit.consume(purpose + "-" + _digest(account.data["id"]))
        try:
            confirmed = verify_password(password, account.data.get("password_hash"))
        except ValueError:
            confirmed = False  # Too short or too long to be this account's password.
        if not confirmed:
            raise IncorrectPassword("That password is not correct")

    def change_password(
        self, tenant: str, session_token: str, current_password: str, new_password: str
    ) -> None:
        """Replace the password and sign out every other browser.

        API keys, connected applications and Telegram are unchanged.
        """
        _password(new_password)
        account = self._account(tenant)
        self._confirm_password(account, current_password, "password")
        current = _digest(session_token) if isinstance(session_token, str) else ""
        kept = [current] if current in account.data.get("session_ids", []) else []
        try:
            self.store.commit(
                [
                    account.update(
                        {
                            **account.data,
                            "password_hash": hash_password(new_password),
                            "session_ids": kept,
                        }
                    )
                ]
            )
        except Conflict:
            raise Conflict("Your account changed in another window; try again") from None

    def sign_out_everywhere(self, tenant: str, password: str) -> dict:
        """Revoke every session, API key, connected application and Telegram link,
        then sign this browser back in. For a lost device or a leaked key."""
        account = self._account(tenant)
        self._confirm_password(account, password, "sign-out-everywhere")
        updated = account.update(
            {
                **account.data,
                "auth_epoch": account.data["auth_epoch"] + 1,
                "session_ids": [],
                "key_ids": [],
            }
        )
        return self._signed_in(updated)

    # Two-step sign-in with an authenticator app.

    def _second_factor(self, account: Document, code: object) -> Document:
        """Check an authenticator or backup code. Returns the account with the code
        spent, to be committed by the caller; raises IncorrectPassword otherwise."""
        settings = account.data.get("totp") or {}
        if not settings.get("enabled") or not isinstance(code, str):
            raise IncorrectPassword("That code is not correct")
        step = totp.matching_step(
            settings["secret"], code, self.clock(), settings.get("last_step", -1)
        )
        if step is not None:
            return account.update({**account.data, "totp": {**settings, "last_step": step}})
        digest = totp.backup_digest(code)
        if digest and digest in settings.get("backup", []):
            remaining = [item for item in settings["backup"] if item != digest]
            return account.update({**account.data, "totp": {**settings, "backup": remaining}})
        raise IncorrectPassword("That code is not correct")

    def security(self, tenant: str) -> dict:
        account = self._account(tenant)
        settings = account.data.get("totp") or {}
        return {
            "email": account.data.get("email"),
            "email_verified": bool(account.data.get("email_verified")),
            "email_enabled": self.email_enabled,
            "two_factor": {
                "enabled": bool(settings.get("enabled")),
                "backup_codes_left": len(settings.get("backup", []))
                if settings.get("enabled")
                else 0,
                "enabled_at": settings.get("enabled_at") if settings.get("enabled") else None,
            },
            "passkeys": self.passkeys.list(account),
        }

    def start_two_factor(self, tenant: str, password: str) -> dict:
        account = self._account(tenant)
        self._confirm_password(account, password, "two-factor")
        if (account.data.get("totp") or {}).get("enabled"):
            raise ValueError("Two-step sign-in is already on")
        secret = totp.new_secret()
        label = account.data.get("email") or account.data["username"]
        try:
            self.store.commit(
                [
                    account.update(
                        {
                            **account.data,
                            "totp_pending": {
                                "secret": secret,
                                "expires_at": self._now() + _SETUP_SECONDS,
                            },
                        }
                    )
                ]
            )
        except Conflict:
            raise Conflict("Your account changed in another window; try again") from None
        return {
            "secret": secret,
            "uri": totp.otpauth_uri(secret, label, self.config.product_name),
            "account": label,
            "issuer": self.config.product_name,
        }

    def enable_two_factor(self, tenant: str, code: str) -> dict:
        account = self._account(tenant)
        self._code_limit.consume("two-factor-setup-" + tenant)
        pending = account.data.get("totp_pending") or {}
        if not pending or pending["expires_at"] <= self._now():
            raise ValueError("Setup expired. Start again.")
        step = totp.matching_step(pending["secret"], code, self.clock())
        if step is None:
            raise IncorrectPassword("That code is not correct. Check the time on your device.")
        codes = totp.new_backup_codes()
        data = {
            **account.data,
            "totp": {
                "enabled": True,
                "secret": pending["secret"],
                "last_step": step,
                "backup": [totp.backup_digest(item) for item in codes],
                "enabled_at": self._now(),
            },
        }
        data.pop("totp_pending", None)
        try:
            self.store.commit([account.update(data)])
        except Conflict:
            raise Conflict("Your account changed in another window; try again") from None
        return {"backup_codes": codes}

    def disable_two_factor(self, tenant: str, password: str, code: str) -> None:
        account = self._account(tenant)
        self._confirm_password(account, password, "two-factor")
        self._code_limit.consume("two-factor-off-" + tenant)
        account = self._second_factor(account, code)
        data = {**account.data}
        data.pop("totp", None)
        try:
            self.store.commit([account.update(data)])
        except Conflict:
            raise Conflict("Your account changed in another window; try again") from None

    def new_backup_codes(self, tenant: str, password: str, code: str) -> dict:
        account = self._account(tenant)
        self._confirm_password(account, password, "backup-codes")
        self._code_limit.consume("backup-codes-" + tenant)
        account = self._second_factor(account, code)
        codes = totp.new_backup_codes()
        settings = {**account.data["totp"], "backup": [totp.backup_digest(c) for c in codes]}
        try:
            self.store.commit([account.update({**account.data, "totp": settings})])
        except Conflict:
            raise Conflict("Your account changed in another window; try again") from None
        return {"backup_codes": codes}

    def delete_account(self, tenant: str, password: str) -> dict:
        account = self._account(tenant)
        self._confirm_password(account, password, "delete")
        customer = self.store.get("tenant:" + tenant)
        assert customer is not None
        # The primary fence makes sessions, grants, keys and future collection stop
        # immediately. GSI discovery below is only cleanup, never the security gate.
        self.store.commit(
            [
                account.update(
                    {
                        "id": tenant,
                        "username": "",
                        "created_at": account.data["created_at"],
                        "status": "deleted",
                        "auth_epoch": account.data["auth_epoch"] + 1,
                        "session_ids": [],
                        "key_ids": [],
                        "passkey_ids": [],
                    }
                ),
                customer.update(
                    {
                        **customer.data,
                        "preferences": {"muted": True, "muted_routes": []},
                        "notification_epoch": customer.data.get("notification_epoch", 0) + 1,
                    }
                ),
            ]
        )
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
                if (
                    not monitor
                    or monitor.data["tenant"] != tenant
                    or monitor.data["status"] == "cancelled"
                ):
                    break
                target = self.store.get("target:" + monitor.data["target_id"])
                customer = self.store.get("tenant:" + tenant)
                assert target is not None and customer is not None
                subscribers = [
                    mid for mid in target.data["subscribers"] if mid != monitor.data["id"]
                ]
                writes = [
                    monitor.update(
                        {
                            **monitor.data,
                            "status": "cancelled",
                            "quota_released": True,
                            "notification_epoch": monitor.data.get("notification_epoch", 0) + 1,
                        }
                    ),
                    target.update({**target.data, "subscribers": subscribers}),
                    customer.update(
                        {
                            **customer.data,
                            "monitors": max(
                                0,
                                customer.data["monitors"]
                                - (0 if monitor.data.get("quota_released", False) else 1),
                            ),
                        }
                    ),
                ]
                capacity = self.store.get("capacity:collection")
                if (
                    not subscribers
                    and capacity
                    and monitor.data["target_id"] in capacity.data["targets"]
                ):
                    writes.append(
                        capacity.update(
                            {
                                "targets": [
                                    identifier
                                    for identifier in capacity.data["targets"]
                                    if identifier != monitor.data["target_id"]
                                ]
                            }
                        )
                    )
                try:
                    self.store.commit(writes)
                    break
                except Conflict:
                    continue
        for index in self.store.query("passkeys:" + tenant):
            passkey = self.store.get(index.key)
            if passkey and passkey.data["tenant"] == tenant and not passkey.data["removed"]:
                with contextlib.suppress(Conflict):
                    self.store.commit([passkey.update({**passkey.data, "removed": True})])
        for index in self.store.query("webhooks:" + tenant):
            for _ in range(5):
                endpoint = self.store.get(index.key)
                if (
                    not endpoint
                    or endpoint.data["tenant"] != tenant
                    or endpoint.data["status"] == "deleted"
                ):
                    break
                data = {
                    **endpoint.data,
                    "status": "deleted",
                    "generation": endpoint.data["generation"] + 1,
                    "challenge_hash": None,
                    "challenge_expires_at": 0,
                }
                data.pop("signing_secret", None)
                try:
                    self.store.commit([endpoint.update(data)])
                    break
                except Conflict:
                    continue
