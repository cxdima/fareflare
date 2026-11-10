"""Private Telegram connections for Fareflare accounts.

The HTTP adapter verifies Telegram's webhook secret before calling this module.
Connection links are single use; no Telegram identity is trusted from the web UI.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import httpx

from fareflare.accounts import Accounts, AuthenticationFailed
from fareflare.credentials import RateLimited, RateLimiter
from fareflare.delivery import TelegramSink, install_telegram_log_redaction
from fareflare.preferences import stored_preferences
from fareflare.store import Conflict, Document, Store
from fareflare.telegram_messages import TelegramMessage, collection_notice

if TYPE_CHECKING:
    from fareflare.service import MonitoringService

_START = re.compile(r"/start(?:@([A-Za-z0-9_]+))?\s+ff_([A-Za-z0-9_-]{43})\Z")
_COMMAND = re.compile(r"/([a-z_]+)(?:@([A-Za-z0-9_]+))?(?=\s|$)")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class ReplyResult:
    sent: bool
    retry_after: int = 2


class TelegramConnections:
    def __init__(
        self,
        store: Store,
        accounts: Accounts,
        bot_token: str,
        bot_username: str,
        public_url: str,
        *,
        transport=None,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        service: MonitoringService | None = None,
    ):
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
        self._commands_limit = RateLimiter(store, clock, per_minute=20)
        from fareflare.service import MonitoringService
        from fareflare.telegram_bot import TelegramBot

        self._bot = TelegramBot(
            service or MonitoringService(store, clock), accounts, self.public_url, clock=clock
        )

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
        if (
            not binding
            or not binding.data.get("connected")
            or binding.data.get("auth_epoch") != epoch
        ):
            return None
        chat = self.store.get("telegram-chat:" + binding.data["chat_id"])
        if (
            not chat
            or not chat.data.get("connected")
            or chat.data.get("tenant") != tenant
            or chat.data.get("auth_epoch") != epoch
            or chat.data.get("connection_id") != binding.data.get("connection_id")
        ):
            return None
        return binding

    def status(self, tenant: str) -> dict:
        account = self._account(tenant)
        return {
            "enabled": True,
            "connected": self._binding(tenant, account.data["auth_epoch"]) is not None,
            "bot_username": self.bot_username,
        }

    def connect(self, tenant: str) -> dict:
        self._limit.consume("telegram-connect-" + tenant)
        account = self._account(tenant)
        if self._binding(tenant, account.data["auth_epoch"]):
            raise ValueError("Disconnect Telegram before connecting another chat")
        token, expires = secrets.token_urlsafe(32), self._now() + 600
        identifier = _digest(token)
        current = self.store.get("telegram-account:" + tenant)
        binding = current or Document("telegram-account:" + tenant, "telegram-accounts", {})
        self.store.commit(
            [
                account.update(account.data),
                binding.update(
                    {
                        **binding.data,
                        "tenant": tenant,
                        "auth_epoch": account.data["auth_epoch"],
                        "connected": False,
                        "pending_hash": identifier,
                    }
                ),
                Document(
                    "telegram-connect:" + identifier,
                    "telegram-connect",
                    {
                        "tenant": tenant,
                        "auth_epoch": account.data["auth_epoch"],
                        "expires_at": expires,
                        "used": False,
                    },
                    expires_at=expires,
                ),
            ]
        )
        return {"url": f"https://t.me/{self.bot_username}?start=ff_{token}", "expires_at": expires}

    def _notification_fence(self, tenant: str) -> Document:
        preferences = self.store.get("tenant:" + tenant) or Document(
            "tenant:" + tenant, "tenants", {}
        )
        return preferences.update(
            {
                **preferences.data,
                "notification_epoch": preferences.data.get("notification_epoch", 0) + 1,
            }
        )

    def disconnect(self, tenant: str, *, expected: dict | None = None) -> None:
        for _ in range(5):
            account = self._account(tenant)
            binding = self.store.get("telegram-account:" + tenant)
            if expected is not None and (
                account.data["auth_epoch"] != expected["auth_epoch"]
                or not binding
                or not binding.data.get("connected")
                or binding.data.get("chat_id") != expected["chat_id"]
                or binding.data.get("connection_id", binding.data.get("connected_at"))
                != expected["connection_id"]
            ):
                return  # An old chat cannot disconnect a connection established after its command.
            if not binding or (
                not binding.data.get("connected") and not binding.data.get("pending_hash")
            ):
                return
            writes = [
                account.update(account.data),
                self._notification_fence(tenant),
                binding.update(
                    {
                        "tenant": tenant,
                        "auth_epoch": account.data["auth_epoch"],
                        "connected": False,
                        "pending_hash": None,
                    }
                ),
            ]
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
            if (
                not challenge
                or challenge.data["used"]
                or challenge.data["expires_at"] <= self._now()
            ):
                return "This connection link has expired or was used. Create another link in Fareflare."
            tenant, epoch = challenge.data["tenant"], challenge.data["auth_epoch"]
            try:
                account = self._account(tenant)
            except AuthenticationFailed:
                return "This connection link is no longer valid."
            binding = self.store.get("telegram-account:" + tenant)
            if (
                account.data["auth_epoch"] != epoch
                or not binding
                or binding.data.get("connected")
                or binding.data.get("pending_hash") != identifier
            ):
                return "This connection link is no longer valid."
            chat = self.store.get("telegram-chat:" + chat_id)
            if (
                chat
                and chat.data.get("connected")
                and chat.data.get("tenant") != tenant
                and self.accounts.validate_account_active(
                    chat.data["tenant"], chat.data["auth_epoch"]
                )
            ):
                return (
                    "This Telegram chat is already connected to another account. "
                    "Disconnect it first."
                )
            chat = chat or Document("telegram-chat:" + chat_id, "telegram-chats", {})
            old_chat_id = binding.data.get("chat_id")
            old_chat = (
                self.store.get("telegram-chat:" + old_chat_id)
                if old_chat_id and old_chat_id != chat_id
                else None
            )
            writes = [
                account.update(account.data),
                self._notification_fence(tenant),
                challenge.update({**challenge.data, "used": True}),
                binding.update(
                    {
                        "tenant": tenant,
                        "auth_epoch": epoch,
                        "connected": True,
                        "chat_id": chat_id,
                        "pending_hash": None,
                        "connected_at": self._now(),
                        "connection_id": identifier,
                    }
                ),
                chat.update(
                    {
                        "tenant": tenant,
                        "auth_epoch": epoch,
                        "connected": True,
                        "connection_id": identifier,
                    },
                    expires_at=None,
                ),
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
        if (
            chat.get("type") != "private"
            or type(identifier) is not int
            or not 0 < identifier < 2**52
            or type(sender.get("id")) is not int
            or sender["id"] != identifier
            or sender.get("is_bot") is True
        ):
            return None
        return str(identifier)

    def _claim_update(self, update_id: int, fingerprint: str) -> Document | None:
        key = "telegram-update:" + str(update_id)
        for _ in range(5):
            current = self.store.get(key)
            if current and current.data.get("fingerprint", fingerprint) != fingerprint:
                return current.update({"done": True})
            if current and (current.data.get("done") or current.due > self._now()):
                return current
            current = current or Document(key, "telegram-updates", {})
            lease = secrets.token_hex(16)
            try:
                self.store.commit(
                    [
                        current.update(
                            {
                                **current.data,
                                "done": False,
                                "lease": lease,
                                "fingerprint": fingerprint,
                            },
                            due=self._now() + 30,
                            expires_at=self._now() + 2 * 86400,
                        )
                    ]
                )
                claimed = self.store.get(key)
                if claimed and claimed.data.get("lease") == lease:
                    return claimed.update({**claimed.data, "claimed": True})
            except Conflict:
                continue
        return None

    def _call(self, method: str, payload: dict) -> dict:
        try:
            if self._client is not None:
                response = self._client.post(
                    f"https://api.telegram.org/bot{self._token}/{method}", json=payload
                )
            else:
                with httpx.Client(
                    timeout=5, follow_redirects=False, trust_env=False, transport=self._transport
                ) as client:
                    response = client.post(
                        f"https://api.telegram.org/bot{self._token}/{method}", json=payload
                    )
            result = response.json()
            if not isinstance(result, dict):
                return {"ok": False}
            parameters = result.get("parameters")
            delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
            retry_after = (
                min(3600, max(2, delay))
                if response.status_code == 429 and type(delay) is int
                else 2
            )
            return {
                **result,
                "http_status": response.status_code,
                "retry_after": retry_after,
                "ok": response.is_success and result.get("ok") is True,
            }
        except (httpx.HTTPError, ValueError):
            return {"ok": False}

    def _reply(
        self, chat_id: str, message: TelegramMessage, *, message_id: int | None = None
    ) -> ReplyResult:
        payload = {"chat_id": chat_id, **message.payload()}
        if message_id is not None:
            result = self._call("editMessageText", {**payload, "message_id": message_id})
            description = result.get("description")
            if result.get("ok") or (
                result.get("http_status") == 400
                and result.get("error_code") == 400
                and isinstance(description, str)
                and "message is not modified" in description.lower()
            ):
                return ReplyResult(True)
            if result.get("http_status") == 403 and result.get("error_code") == 403:
                return ReplyResult(
                    True
                )  # A blocked bot cannot deliver; retries cannot repair that.
            if result.get("http_status") != 400 or result.get("error_code") != 400:
                return ReplyResult(False, result.get("retry_after", 2))
            # Old or inaccessible messages can no longer be edited. Send a fresh menu.
        result = self._call("sendMessage", payload)
        return ReplyResult(
            result.get("ok") is True
            or (result.get("http_status") == 403 and result.get("error_code") == 403),
            result.get("retry_after", 2),
        )

    def _identity(self, chat_id: str) -> dict | None:
        chat = self.store.get("telegram-chat:" + chat_id)
        if not chat or not chat.data.get("connected"):
            return None
        tenant, epoch = chat.data.get("tenant"), chat.data.get("auth_epoch")
        if (
            not isinstance(tenant, str)
            or type(epoch) is not int
            or not self.accounts.validate_account_active(tenant, epoch)
        ):
            return None
        binding = self._binding(tenant, epoch)
        if not binding or binding.data.get("chat_id") != chat_id:
            return None
        return {
            "tenant": tenant,
            "auth_epoch": epoch,
            "connection_id": binding.data.get("connection_id", binding.data.get("connected_at")),
        }

    def _connection_instructions(self) -> TelegramMessage:
        return TelegramMessage(
            "Welcome to Fareflare\n\nWatch flight prices and manage your alerts here.\n"
            "Sign in to Fareflare, open Account settings, and choose Connect Telegram.",
            "<b>Welcome to Fareflare</b>\n\nWatch flight prices and manage your alerts here.\n"
            "Sign in to Fareflare, open <b>Account settings</b>, and choose <b>Connect Telegram</b>.",
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "Connect your account",
                            "url": self.public_url + "/app#settings",
                            "style": "primary",
                        }
                    ]
                ]
            },
        )

    def _callback(self, query: dict) -> tuple[str, int, str] | None:
        message = query.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("from"), dict):
            return None
        author = message["from"]
        if (
            author.get("id") != int(self._token.split(":", 1)[0])
            or author.get("is_bot") is not True
        ):
            return None
        chat_id = self._private_chat({"chat": message.get("chat"), "from": query.get("from")})
        message_id, data = message.get("message_id"), query.get("data")
        if (
            not chat_id
            or type(message_id) is not int
            or message_id <= 0
            or message.get("date") == 0
            or not isinstance(data, str)
        ):
            return None
        try:
            if not 1 <= len(data.encode()) <= 64:
                return None
        except UnicodeError:
            return None
        return chat_id, message_id, data

    def _deliver_reply(self, claim: Document) -> bool:
        cached = claim.data.get("reply")
        if cached is None:
            self.store.commit([claim.update({"done": True})])
            return True
        chat_id, scope = claim.data["chat_id"], claim.data.get("scope")
        if scope is not None and self._identity(chat_id) != scope:
            self.store.commit([claim.update({"done": True})])
            return True  # Recovery/rebinding must never deliver a cached account view.
        message = TelegramMessage(**cached)
        message_id = claim.data.get("message_id")
        result = (
            self._reply(chat_id, message, message_id=message_id)
            if message_id is not None
            else self._reply(chat_id, message)
        )
        data = {key: value for key, value in claim.data.items() if key != "claimed"}
        self.store.commit(
            [
                claim.update(
                    {"done": True} if result.sent else data,
                    due=self._now() + (0 if result.sent else result.retry_after),
                )
            ]
        )
        return result.sent

    def _cache_reply(
        self,
        claim: Document,
        chat_id: str | None,
        reply: TelegramMessage | None,
        message_id: int | None,
        scope: dict | None,
    ) -> bool:
        if chat_id and reply is not None:
            reply.payload()
            data = {key: value for key, value in claim.data.items() if key != "claimed"}
            self.store.commit(
                [
                    claim.update(
                        {
                            **data,
                            "reply": asdict(reply),
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "scope": scope,
                        }
                    )
                ]
            )
            refreshed = self.store.get(claim.key)
            assert refreshed is not None
            return self._deliver_reply(refreshed)
        return self._deliver_reply(claim)

    def _throttle_notice(self, chat_id: str) -> TelegramMessage | None:
        # Cap notices too: excess commands must not create an outbound flood.
        key = f"telegram-throttle:{chat_id}:{self._now() // 60}"
        if self.store.get(key):
            return None
        try:
            self.store.commit(
                [Document(key, "telegram-throttle", {}, expires_at=self._now() + 120)]
            )
        except Conflict:
            return None
        return TelegramMessage(
            "Please wait a minute before sending another command. Your flight checks continue."
        )

    def handle_update(self, update: dict) -> bool:
        if (
            not isinstance(update, dict)
            or type(update.get("update_id")) is not int
            or update["update_id"] < 0
        ):
            return True
        fingerprint = _digest(json.dumps(update, sort_keys=True, separators=(",", ":")))
        claim = self._claim_update(update["update_id"], fingerprint)
        if claim is None:
            return False
        if not claim.data.get("claimed"):
            return claim.data.get("done") is True
        query = update.get("callback_query")
        callback = self._callback(query) if isinstance(query, dict) else None
        if (
            isinstance(query, dict)
            and isinstance(query.get("id"), str)
            and 0 < len(query["id"]) <= 256
        ):
            payload = {"callback_query_id": query["id"]}
            if callback is None:
                payload["text"] = "Open /start in your private Fareflare chat."
            self._call("answerCallbackQuery", payload)
        if claim.data.get("reply") is not None:
            return self._deliver_reply(claim)
        if isinstance(query, dict) and callback is None:
            return self._deliver_reply(claim)
        message = update.get("message")
        message = message if isinstance(message, dict) else {}
        text = message.get("text")
        text = text.strip() if isinstance(text, str) else ""
        private_chat = callback[0] if callback else self._private_chat(message)
        message_id = callback[1] if callback else None
        callback_data = callback[2] if callback else None
        reply = None
        scope = self._identity(private_chat) if private_chat else None
        command = _COMMAND.match(text)
        if command and command[2] and command[2].lower() != self.bot_username.lower():
            return self._deliver_reply(claim)
        normalized = "/" + command[1] + text[command.end() :] if command else text
        if private_chat and normalized in ("/stop", "/disconnect") and scope:
            # Opting out remains available even after the interactive command limit.
            self.disconnect(scope["tenant"], expected={**scope, "chat_id": private_chat})
            reply = TelegramMessage(
                "Telegram alerts are disconnected. Your flights and alert history remain in Fareflare."
            )
            return self._cache_reply(claim, private_chat, reply, message_id, None)
        if private_chat:
            try:
                self._commands_limit.consume("telegram-command-" + private_chat)
            except RateLimited:
                return self._cache_reply(
                    claim, private_chat, self._throttle_notice(private_chat), message_id, scope
                )
        match = _START.fullmatch(text)
        if (
            private_chat
            and match
            and (not match[1] or match[1].lower() == self.bot_username.lower())
        ):
            reply = TelegramMessage(self._consume(match[2], private_chat))
            scope = self._identity(private_chat)
            if reply.text.startswith("Fareflare is connected") and scope:
                reply = self._bot.handle(
                    scope["tenant"],
                    private_chat,
                    scope["auth_epoch"],
                    "/start",
                    None,
                    update["update_id"],
                )
        elif private_chat:
            text = normalized
            if text in ("/stop", "/disconnect"):
                reply = TelegramMessage("This chat is not connected to Fareflare.")
                scope = None
            elif scope:
                reply = self._bot.handle(
                    scope["tenant"],
                    private_chat,
                    scope["auth_epoch"],
                    text or None,
                    callback_data,
                    update["update_id"],
                )
            elif (
                callback
                or text in ("/start", "/help", "/flights", "/add", "/settings", "/cancel")
                or text.startswith("https://")
            ):
                reply = self._connection_instructions()
        return self._cache_reply(claim, private_chat, reply, message_id, scope)

    def send(self, delivery: dict) -> bool:
        tenant = delivery.get("tenant")
        if (
            delivery.get("webhook_id") is not None
            or not isinstance(tenant, str)
            or not tenant.startswith("acct_")
        ):
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
        return TelegramSink(
            self._token,
            {tenant: binding.data["chat_id"]},
            transport=self._transport,
            public_url=self.public_url,
            preferences=stored_preferences(
                preferences.data.get("preferences") if preferences else None
            ),
        ).send(delivery)

    def notify(self, notice: dict) -> bool | None:
        """Send an opt-in diagnostic notice. ``None`` means no chat can receive it."""
        tenant = notice.get("tenant")
        if not isinstance(tenant, str) or not tenant.startswith("acct_"):
            return None
        try:
            epoch = self.accounts.auth_epoch(tenant)
        except AuthenticationFailed:
            return None
        binding = self._binding(tenant, epoch)
        if not binding:
            return None  # The dashboard still shows the status; nothing is pushed.
        saved = self.store.get("tenant:" + tenant)
        preferences = stored_preferences(saved.data.get("preferences") if saved else None)
        message = collection_notice(notice, notice["monitor"], preferences, self.public_url)
        result = self._call(
            "sendMessage",
            {
                "chat_id": binding.data["chat_id"],
                **message.payload(),
                "disable_notification": preferences.telegram_silent,
            },
        )
        # A blocked bot cannot be reached; retrying would not change that.
        return result.get("ok") is True or (
            result.get("http_status") == 403 and result.get("error_code") == 403
        )
