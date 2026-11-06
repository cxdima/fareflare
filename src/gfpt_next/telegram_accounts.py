"""Private Telegram connections for Fareflare accounts.

The HTTP adapter verifies Telegram's webhook secret before calling this module.
Connection links are single use; no Telegram identity is trusted from the web UI.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from collections.abc import Callable

import httpx

from gfpt_next.accounts import Accounts, AuthenticationFailed
from gfpt_next.credentials import RateLimiter
from gfpt_next.delivery import TelegramSink, install_telegram_log_redaction
from gfpt_next.preferences import merge_preferences
from gfpt_next.store import Conflict, Document, Store

_START = re.compile(r"/start(?:@([A-Za-z0-9_]+))?\s+ff_([A-Za-z0-9_-]{43})\Z")
_COMMAND = re.compile(r"/(start|help|stop)(?:@([A-Za-z0-9_]+))?\Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class TelegramConnections:
    def __init__(self, store: Store, accounts: Accounts, bot_token: str, bot_username: str,
                 public_url: str, *, transport=None,
                 client: httpx.Client | None = None, clock: Callable[[], float] = time.time):
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", bot_token):
            raise ValueError("Invalid Telegram bot credential")
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", bot_username):
            raise ValueError("Invalid Telegram bot username")
        # httpx's INFO request log otherwise includes Telegram's URL credential.
        install_telegram_log_redaction()
        self.store, self.accounts, self.clock = store, accounts, clock
        self._token, self.bot_username = bot_token, bot_username
        self.public_url = public_url.rstrip("/")
        self._transport, self._client = transport, client
        self._limit = RateLimiter(store, clock, per_minute=5)

    def _now(self) -> int:
        return int(self.clock())

    def _account(self, tenant: str) -> Document:
        self.accounts.get_account(tenant)
        account = self.store.get("account:" + tenant)
        if not account or account.data.get("status") != "active":
            raise AuthenticationFailed("Account unavailable")
        return account

    def _binding(self, tenant: str, epoch: int) -> Document | None:
        binding = self.store.get("telegram-account:" + tenant)
        if (not binding or not binding.data.get("connected")
                or binding.data.get("auth_epoch") != epoch):
            return None
        chat = self.store.get("telegram-chat:" + binding.data["chat_id"])
        if (not chat or not chat.data.get("connected") or chat.data.get("tenant") != tenant
                or chat.data.get("auth_epoch") != epoch):
            return None
        return binding

    def status(self, tenant: str) -> dict:
        account = self._account(tenant)
        return {"enabled": True, "connected": self._binding(tenant, account.data["auth_epoch"]) is not None,
                "bot_username": self.bot_username}

    def connect(self, tenant: str) -> dict:
        self._limit.consume("telegram-connect-" + tenant)
        account = self._account(tenant)
        if self._binding(tenant, account.data["auth_epoch"]):
            raise ValueError("Disconnect Telegram before connecting another chat")
        token, expires = secrets.token_urlsafe(32), self._now() + 600
        identifier = _digest(token)
        current = self.store.get("telegram-account:" + tenant)
        binding = current or Document("telegram-account:" + tenant, "telegram-accounts", {})
        self.store.commit([
            account.update(account.data),
            binding.update({**binding.data, "tenant": tenant, "auth_epoch": account.data["auth_epoch"],
                            "connected": False, "pending_hash": identifier}),
            Document("telegram-connect:" + identifier, "telegram-connect", {
                "tenant": tenant, "auth_epoch": account.data["auth_epoch"],
                "expires_at": expires, "used": False,
            }, expires_at=expires),
        ])
        return {"url": f"https://t.me/{self.bot_username}?start=ff_{token}", "expires_at": expires}

    def _notification_fence(self, tenant: str) -> Document:
        preferences = self.store.get("tenant:" + tenant) or Document("tenant:" + tenant, "tenants", {})
        return preferences.update({**preferences.data,
                                   "notification_epoch": preferences.data.get("notification_epoch", 0) + 1})

    def disconnect(self, tenant: str) -> None:
        for _ in range(5):
            account = self._account(tenant)
            binding = self.store.get("telegram-account:" + tenant)
            if not binding or (not binding.data.get("connected") and not binding.data.get("pending_hash")):
                return
            writes = [account.update(account.data), self._notification_fence(tenant),
                      binding.update({"tenant": tenant, "auth_epoch": account.data["auth_epoch"],
                                      "connected": False, "pending_hash": None})]
            chat_id = binding.data.get("chat_id")
            chat = self.store.get("telegram-chat:" + chat_id) if chat_id else None
            if chat and chat.data.get("tenant") == tenant:
                writes.append(chat.update({"connected": False}))
            try:
                self.store.commit(writes)
                return
            except Conflict:
                continue
        raise Conflict("Concurrent Telegram change; retry disconnect")

    def _consume(self, token: str, chat_id: str) -> str:
        identifier = _digest(token)
        for _ in range(5):
            challenge = self.store.get("telegram-connect:" + identifier)
            if not challenge or challenge.data["used"] or challenge.data["expires_at"] <= self._now():
                return "This connection link has expired or was used. Create another link in Fareflare."
            tenant, epoch = challenge.data["tenant"], challenge.data["auth_epoch"]
            try:
                account = self._account(tenant)
            except AuthenticationFailed:
                return "This connection link is no longer valid."
            binding = self.store.get("telegram-account:" + tenant)
            if (account.data["auth_epoch"] != epoch or not binding or binding.data.get("connected")
                    or binding.data.get("pending_hash") != identifier):
                return "This connection link is no longer valid."
            chat = self.store.get("telegram-chat:" + chat_id)
            if chat and chat.data.get("connected") and chat.data.get("tenant") != tenant:
                if self.accounts.validate_account_active(chat.data["tenant"], chat.data["auth_epoch"]):
                    return "This Telegram chat is already connected to another account. Disconnect it first."
            chat = chat or Document("telegram-chat:" + chat_id, "telegram-chats", {})
            old_chat_id = binding.data.get("chat_id")
            old_chat = (self.store.get("telegram-chat:" + old_chat_id)
                        if old_chat_id and old_chat_id != chat_id else None)
            writes = [
                account.update(account.data), self._notification_fence(tenant),
                challenge.update({**challenge.data, "used": True}),
                binding.update({"tenant": tenant, "auth_epoch": epoch, "connected": True,
                                "chat_id": chat_id, "pending_hash": None, "connected_at": self._now()}),
                chat.update({"tenant": tenant, "auth_epoch": epoch, "connected": True}, expires_at=None),
            ]
            if old_chat and old_chat.data.get("tenant") == tenant:
                writes.append(old_chat.update({"connected": False}, expires_at=self._now()))
            try:
                self.store.commit(writes)
                return "Fareflare is connected. Price alerts will arrive here. Use /stop to disconnect."
            except Conflict:
                continue
        raise Conflict("Concurrent Telegram connection; retry")

    @staticmethod
    def _private_chat(message: dict) -> str | None:
        chat, sender = message.get("chat"), message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return None
        identifier = chat.get("id")
        if (chat.get("type") != "private" or type(identifier) is not int
                or not 0 < identifier < 2**52 or type(sender.get("id")) is not int
                or sender["id"] != identifier or sender.get("is_bot") is True):
            return None
        return str(identifier)

    def _claim_update(self, update_id: int) -> Document | None:
        key = "telegram-update:" + str(update_id)
        for _ in range(5):
            current = self.store.get(key)
            if current and (current.data.get("done") or current.due > self._now()):
                return current
            current = current or Document(key, "telegram-updates", {})
            lease = secrets.token_hex(16)
            try:
                self.store.commit([current.update({"done": False, "lease": lease},
                                                   due=self._now() + 30, expires_at=self._now() + 2 * 86400)])
                claimed = self.store.get(key)
                if claimed and claimed.data.get("lease") == lease:
                    return claimed.update({**claimed.data, "claimed": True})
            except Conflict:
                continue
        return None

    def _reply(self, chat_id: str, text: str) -> None:
        try:
            if self._client is not None:
                self._client.post(f"https://api.telegram.org/bot{self._token}/sendMessage",
                                  json={"chat_id": chat_id, "text": text})
            else:
                with httpx.Client(timeout=10, follow_redirects=False, trust_env=False,
                                  transport=self._transport) as client:
                    client.post(f"https://api.telegram.org/bot{self._token}/sendMessage",
                                json={"chat_id": chat_id, "text": text})
        except httpx.HTTPError:
            pass  # The durable connection does not depend on this optional confirmation.

    def handle_update(self, update: dict) -> bool:
        if not isinstance(update, dict) or type(update.get("update_id")) is not int or update["update_id"] < 0:
            return True
        claim = self._claim_update(update["update_id"])
        if claim is None:
            return False
        if not claim.data.get("claimed"):
            return claim.data.get("done") is True
        message = update.get("message")
        message = message if isinstance(message, dict) else {}
        text = message.get("text")
        text = text.strip() if isinstance(text, str) else ""
        private_chat = self._private_chat(message)
        reply = None
        match = _START.fullmatch(text)
        if private_chat and match and (not match[1] or match[1].lower() == self.bot_username.lower()):
            reply = self._consume(match[2], private_chat)
        elif private_chat:
            command = _COMMAND.fullmatch(text)
            chat = self.store.get("telegram-chat:" + private_chat)
            tenant = chat.data.get("tenant") if chat and chat.data.get("connected") else None
            bound = (chat is not None and isinstance(tenant, str)
                     and self.accounts.validate_account_active(tenant, chat.data["auth_epoch"])
                     and self._binding(tenant, chat.data["auth_epoch"]) is not None)
            if command and (not command[2] or command[2].lower() == self.bot_username.lower()):
                if command[1] == "stop":
                    if bound and isinstance(tenant, str):
                        self.disconnect(tenant)
                        reply = "Telegram alerts are disconnected. Your flights and alert history remain in Fareflare."
                    else:
                        reply = "This chat is not connected to Fareflare."
                elif bound:
                    reply = ("Your Fareflare alerts are connected. Manage flights and alert preferences in your account. "
                             "Use /stop to disconnect Telegram.\n" + self.public_url + "/app")
                else:
                    reply = ("Fareflare sends alerts when it observes a flight price change. "
                             "Sign in, open Account settings, and choose Connect Telegram to link this chat.\n"
                             + self.public_url + "/app#settings")
        self.store.commit([claim.update({"done": True})])
        if private_chat and reply:
            self._reply(private_chat, reply)
        return True

    def send(self, delivery: dict) -> bool:
        tenant = delivery.get("tenant")
        if delivery.get("webhook_id") is not None or not isinstance(tenant, str) or not tenant.startswith("acct_"):
            return False
        try:
            epoch = self.accounts.auth_epoch(tenant)
        except AuthenticationFailed:
            return True
        binding = self._binding(tenant, epoch)
        preferences = self.store.get("tenant:" + tenant)
        current_epoch = preferences.data.get("notification_epoch", 0) if preferences else 0
        if not binding or delivery.get("tenant_epoch", 0) != current_epoch:
            return True  # Inbox history already exists; no stale alert is sent to a newly connected chat.
        return TelegramSink(self._token, {tenant: binding.data["chat_id"]},
                            transport=self._transport,
                            preferences=merge_preferences(preferences.data.get("preferences") if preferences else None)).send(delivery)
