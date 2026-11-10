"""Outbound Telegram adapter; destinations come from operator configuration."""

from __future__ import annotations

import logging
import re

import httpx

from fareflare.preferences import Preferences
from fareflare.telegram_messages import alert_message


class _TelegramCredentialFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "api.telegram.org/bot" in message:
            record.msg = re.sub(
                r"(https://api\.telegram\.org/bot)[^/\s\"']+", r"\1[REDACTED]", message
            )
            record.args = ()
        return True


_CREDENTIAL_FILTER = _TelegramCredentialFilter()


def install_telegram_log_redaction() -> None:
    """Telegram credentials are URL components and must not enter HTTP access logs."""
    logging.getLogger("httpx").addFilter(_CREDENTIAL_FILTER)


class TelegramSink:
    def __init__(
        self,
        token: str,
        recipients: dict[str, str],
        transport=None,
        *,
        preferences: Preferences | None = None,
        public_url: str | None = None,
    ):
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
            raise ValueError("Invalid Telegram bot credential")
        if not recipients or any(not re.fullmatch(r"-?\d+", chat) for chat in recipients.values()):
            raise ValueError("Configure numeric Telegram recipients per tenant")
        install_telegram_log_redaction()
        self._token, self._recipients, self._transport = token, recipients, transport
        self._preferences = preferences or Preferences()
        self._public_url = public_url

    def send(self, delivery: dict) -> bool:
        if delivery.get("webhook_id") is not None:
            return False
        chat = self._recipients.get(delivery["tenant"])
        if chat is None:
            return False
        try:
            message = alert_message(delivery, self._preferences, self._public_url)
            payload = {
                **message.payload(),
                "chat_id": chat,
                "disable_notification": self._preferences.telegram_silent,
            }
            with httpx.Client(
                timeout=10, follow_redirects=False, trust_env=False, transport=self._transport
            ) as client:
                response = client.post(
                    f"https://api.telegram.org/bot{self._token}/sendMessage", json=payload
                )
                return response.is_success and response.json().get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False
