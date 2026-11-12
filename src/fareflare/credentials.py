"""Revocable hashed API credentials and a shared, atomic per-tenant rate limit."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from collections.abc import Callable

from fareflare.store import Conflict, Document, Store


class RateLimited(ValueError):
    pass


class Credentials:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time):
        self.store, self.clock = store, clock

    def issue(self, tenant: str, lifetime_seconds: int = 90 * 86400) -> tuple[str, str]:
        if (
            not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", tenant)
            or not 60 <= lifetime_seconds <= 365 * 86400
        ):
            raise ValueError("Invalid credential owner or lifetime")
        secret = secrets.token_urlsafe(32)
        identifier = hashlib.sha256(secret.encode()).hexdigest()
        self.store.commit(
            [
                Document(
                    "credential:" + identifier,
                    "credentials:" + tenant,
                    {
                        "tenant": tenant,
                        "revoked": False,
                        "expires_at": int(self.clock()) + lifetime_seconds,
                    },
                )
            ]
        )
        return identifier, secret

    def authenticate(self, secret: str) -> str | None:
        if not 32 <= len(secret) <= 128:
            return None
        doc = self.store.get("credential:" + hashlib.sha256(secret.encode()).hexdigest())
        if doc and not doc.data["revoked"] and doc.data["expires_at"] > self.clock():
            return doc.data["tenant"]
        return None

    def revoke(self, tenant: str, identifier: str) -> None:
        doc = self.store.get("credential:" + identifier)
        if not doc or doc.data["tenant"] != tenant:
            raise ValueError("Credential not found")
        self.store.commit([doc.update({**doc.data, "revoked": True})])


class RateLimiter:
    """A fixed-window counter shared through the store.

    ``per_minute`` is the allowance per window; the window is a minute unless
    ``window_seconds`` says otherwise (an hour or a day for slower budgets).
    """

    def __init__(
        self,
        store: Store,
        clock: Callable[[], float] = time.time,
        per_minute: int = 120,
        *,
        window_seconds: int = 60,
        message: str = "Request limit reached; retry next minute",
    ):
        self.store, self.clock, self.per_minute = store, clock, per_minute
        self.window, self.message = window_seconds, message

    def _key(self, tenant: str, now: int) -> str:
        if self.window == 60:
            return f"rate:{tenant}:{now // 60}"
        return f"rate:{tenant}:w{self.window}:{now // self.window}"

    def exhausted(self, tenant: str) -> bool:
        """True when the current window is used up, without spending from it."""
        doc = self.store.get(self._key(tenant, int(self.clock())))
        return bool(doc and doc.data["count"] >= self.per_minute)

    def check(self, tenant: str) -> None:
        if self.exhausted(tenant):
            raise RateLimited(self.message)

    def consume(self, tenant: str) -> None:
        now = int(self.clock())
        key = self._key(tenant, now)
        for _ in range(5):
            doc = self.store.get(key) or Document(
                key, "rate_limits", {"count": 0}, expires_at=now + 2 * self.window
            )
            if doc.data["count"] >= self.per_minute:
                raise RateLimited(self.message)
            try:
                self.store.commit([doc.update({"count": doc.data["count"] + 1})])
                return
            except Conflict:
                continue
        raise RateLimited("Request limit busy; retry next minute")

    def spend(self, tenant: str) -> bool:
        """Take one from the window if any is left; never raises for an empty one."""
        try:
            self.consume(tenant)
        except RateLimited:
            return False
        return True
