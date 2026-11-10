"""Plain-text and Telegram HTML views of the same account-owned message."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from html import escape
from urllib.parse import urlsplit

from fareflare.links import import_link
from fareflare.preferences import Preferences, observed_time, regional_date, regional_price
from fareflare.product_config import ProductConfig


@dataclass(frozen=True)
class TelegramMessage:
    """Keep a plain counterpart for previews; markup is authored by presenters only."""

    text: str
    html: str | None = None
    reply_markup: dict | None = None

    def payload(self) -> dict:
        # Telegram applies its limit after parsing entities. Count UTF-16 units
        # conservatively so supplementary characters cannot exceed that bound.
        if not self.text.strip() or len(self.text.encode("utf-16-le")) // 2 > 4096:
            raise ValueError("Telegram messages must contain 1–4096 characters")
        result = {
            "text": self.html if self.html is not None else self.text,
            "link_preview_options": {"is_disabled": True},
        }
        if self.html is not None:
            result["parse_mode"] = "HTML"
        if self.reply_markup is not None:
            result["reply_markup"] = deepcopy(self.reply_markup)
        return result


def safe_flight_url(value: object) -> str | None:
    """Use the existing offline importer to validate and canonicalize booking links."""
    if not isinstance(value, str):
        return None
    try:
        canonical = import_link(value, allow_search=True)["url"]
        return canonical if len(canonical) <= 8192 else None
    except ValueError:
        return None


def safe_dashboard_url(value: str | None) -> str | None:
    """Only operator-configured HTTPS origins (or local development HTTP) are used."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
        or "\\" in value
    ):
        return None
    try:
        ProductConfig(public_url=value)
        _ = urlsplit(value).port  # Reject malformed or out-of-range ports as well.
    except ValueError:
        return None
    return value.rstrip("/") + "/app#monitors"


def single_line(value: str, limit: int = 120) -> str:
    """Provider labels cannot inject new message sections or directional controls."""
    value = "".join(
        char if ord(char) >= 32 and ord(char) != 127 else " "
        for char in value
        if char not in "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
    )
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def alert_message(
    delivery: dict, preferences: Preferences, public_url: str | None = None
) -> TelegramMessage:
    """Render prices and itinerary facts without inferring savings or market lows."""
    observation = delivery["observation"]
    price = regional_price(observation["amount_minor"], observation["currency"], preferences.locale)
    reason = {
        "tracking_started": "Tracking started",
        "new_low": "New observed low",
        "below_price": "Price threshold reached",
        "rebound": "Price rose from its low",
    }[delivery["reason"]]
    plain, markup = [price, reason], [f"<b>{escape(price)}</b>", escape(reason)]
    itinerary = delivery.get("itinerary", {})
    segments = itinerary.get("segments", [])
    if segments:
        plain.append("")
        markup.append("")
    for segment in segments:
        legs = segment["legs"]
        route = single_line(f"{legs[0]['origin']} → {legs[-1]['destination']}", 80)
        day = regional_date(date.fromisoformat(segment["date"]), preferences.locale)
        context = " · " + day
        if preferences.telegram_show_flight_numbers:
            flights = ", ".join(
                single_line(str(leg["airline"]) + str(leg["number"]), 20)
                for leg in legs
                if leg.get("airline") and leg.get("number")
            )
            if flights:
                context += " · " + flights
        plain.append(route + context)
        markup.append(f"<b>{escape(route)}</b>" + escape(context))
    details = []
    if itinerary.get("adults") and observation.get("price_basis") == "total":
        adults = itinerary["adults"]
        details.append(f"Total for {adults} adult" + ("s" if adults > 1 else ""))
    if preferences.telegram_show_fare and observation.get("fare_name"):
        details.append("Fare: " + single_line(observation["fare_name"]))
    if details:
        plain.append("")
        markup.append("")
        rows = [" · ".join(details)] if preferences.telegram_style == "compact" else details
        plain.extend(rows)
        markup.extend(escape(row) for row in rows)
    if preferences.telegram_show_observed_time:
        checked = "Observed " + observed_time(observation["observed_at"], preferences)
        plain.extend(["", checked])
        markup.extend(["", escape(checked)])
    buttons = []
    if flight_url := safe_flight_url(itinerary.get("url")):
        buttons.append({"text": "View flight", "url": flight_url, "style": "primary"})
    if dashboard_url := safe_dashboard_url(public_url):
        buttons.append({"text": "Open Fareflare", "url": dashboard_url})
    return TelegramMessage(
        "\n".join(plain), "\n".join(markup), {"inline_keyboard": [buttons]} if buttons else None
    )
