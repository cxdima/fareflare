"""Outbound Telegram adapter; destinations come from operator configuration."""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import httpx

from gfpt_next.contracts import Money


class _TelegramCredentialFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "api.telegram.org/bot" in message:
            record.msg = re.sub(r"(https://api\.telegram\.org/bot)[^/\s\"']+", r"\1[REDACTED]", message)
            record.args = ()
        return True


_CREDENTIAL_FILTER = _TelegramCredentialFilter()


def install_telegram_log_redaction() -> None:
    """Telegram credentials are URL components and must not enter HTTP access logs."""
    logging.getLogger("httpx").addFilter(_CREDENTIAL_FILTER)


class TelegramSink:
    def __init__(self, token: str, recipients: dict[str, str], transport=None):
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
            raise ValueError("Invalid Telegram bot credential")
        if not recipients or any(not re.fullmatch(r"-?\d+", chat) for chat in recipients.values()):
            raise ValueError("Configure numeric Telegram recipients per tenant")
        install_telegram_log_redaction()
        self._token, self._recipients, self._transport = token, recipients, transport

    def send(self, delivery: dict) -> bool:
        if delivery.get("webhook_id") is not None:
            return False
        chat = self._recipients.get(delivery["tenant"])
        if chat is None:
            return False
        observation = delivery["observation"]
        price = Money(observation["amount_minor"], observation["currency"]).display()
        reason = {"tracking_started": "Tracking started", "new_low": "New observed low",
                  "below_price": "Price threshold reached", "rebound": "Price rose from its low"}[delivery["reason"]]
        # Plain text: no provider text is interpreted as Telegram HTML/Markdown.
        itinerary = delivery.get("itinerary", {})
        lines = [f"{reason}: {price}"]
        for segment in itinerary.get("segments", []):
            legs = segment["legs"]
            flights = ", ".join(leg["airline"] + leg["number"] for leg in legs)
            lines.append(f"{legs[0]['origin']} → {legs[-1]['destination']} · {segment['date']} · {flights}")
        if itinerary.get("adults") and observation.get("price_basis") == "total":
            adults = itinerary["adults"]
            lines.append(f"Total for {adults} adult" + ("s" if adults > 1 else ""))
        if observation.get("fare_name"):
            lines.append("Fare: " + observation["fare_name"])
        observed = datetime.fromtimestamp(observation["observed_at"], UTC).strftime("%Y-%m-%d %H:%M UTC")
        lines.append("Observed " + observed)
        url = itinerary.get("url", "")
        if url and len(url) <= 1200:
            lines.append(url)
        lines.append(f"Alert {delivery['id'][:12]}")
        text = "\n".join(lines)
        try:
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False,
                              transport=self._transport) as client:
                response = client.post(f"https://api.telegram.org/bot{self._token}/sendMessage",
                                       json={"chat_id": chat, "text": text})
                return response.is_success and response.json().get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False
