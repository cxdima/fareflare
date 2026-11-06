"""Validated account preferences shared by API, MCP and notification delivery."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gfpt_next.contracts import Money

Locale = Literal["en-US", "en-GB", "de-DE", "fr-FR", "es-ES", "uk-UA"]
HourCycle = Literal["auto", "h12", "h23"]
_DATE_FORMATS: dict[Locale, str] = {
    "en-US": "%m/%d/%Y", "en-GB": "%d/%m/%Y", "de-DE": "%d.%m.%Y",
    "fr-FR": "%d/%m/%Y", "es-ES": "%d/%m/%Y", "uk-UA": "%d.%m.%Y",
}
_NUMBER_SEPARATORS: dict[Locale, tuple[str, str]] = {
    "en-US": (",", "."), "en-GB": (",", "."), "de-DE": (".", ","),
    "fr-FR": ("\u202f", ","), "es-ES": (".", ","), "uk-UA": ("\u00a0", ","),
}


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    muted: bool = False
    muted_routes: list[str] = Field(default_factory=list, max_length=100)
    time_zone: str | None = Field(default=None, max_length=80)
    locale: Locale = "en-US"
    hour_cycle: HourCycle = "auto"
    telegram_style: Literal["detailed", "compact"] = "detailed"
    telegram_show_flight_numbers: bool = True
    telegram_show_observed_time: bool = True
    telegram_show_fare: bool = True
    telegram_silent: bool = False

    @field_validator("muted_routes")
    @classmethod
    def valid_routes(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[A-Z]{3}-[A-Z]{3}", value) for value in values):
            raise ValueError("Use airport pairs such as DEN-DFW")
        return sorted(set(values))

    @field_validator("time_zone")
    @classmethod
    def valid_time_zone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if (not re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", value)
                or value.startswith(("posix/", "right/")) or value in ("localtime", "posixrules")):
            raise ValueError("Choose a valid IANA time zone")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA time zone") from None
        return value


def merge_preferences(current: dict | None, updates: dict | None = None) -> Preferences:
    return Preferences.model_validate({**(current or {}), **(updates or {})})


def regional_date(value: date, locale: Locale) -> str:
    # The supported formatting regions are explicit; message prose remains English.
    return value.strftime(_DATE_FORMATS[locale])


def observed_time(seconds: int, preferences: Preferences) -> str:
    zone = ZoneInfo(preferences.time_zone or "UTC")
    local = datetime.fromtimestamp(seconds, UTC).astimezone(zone)
    twelve_hour = preferences.hour_cycle == "h12" or (
        preferences.hour_cycle == "auto" and preferences.locale == "en-US")
    clock = local.strftime("%I:%M %p").lstrip("0") if twelve_hour else local.strftime("%H:%M")
    offset = local.strftime("%z")
    label = "UTC" if zone.key == "UTC" else f"{zone.key} (UTC{offset[:3]}:{offset[3:]})"
    return f"{regional_date(local.date(), preferences.locale)} {clock} {label}"


def regional_price(amount_minor: int, currency: str, locale: Locale) -> str:
    value = Money(amount_minor, currency)
    whole, fraction = divmod(value.amount_minor, 10 ** value.exponent)
    grouping, decimal = _NUMBER_SEPARATORS[locale]
    number = f"{whole:,}".replace(",", grouping)
    if value.exponent:
        number += f"{decimal}{fraction:02d}"
    return f"{currency} {number}"


def telegram_text(delivery: dict, preferences: Preferences) -> str:
    """Render plain text only; provider strings are never interpreted as markup."""
    observation = delivery["observation"]
    price = regional_price(observation["amount_minor"], observation["currency"], preferences.locale)
    reason = {"tracking_started": "Tracking started", "new_low": "New observed low",
              "below_price": "Price threshold reached", "rebound": "Price rose from its low"}[delivery["reason"]]
    itinerary = delivery.get("itinerary", {})
    lines = [f"{reason}: {price}"]
    for segment in itinerary.get("segments", []):
        legs = segment["legs"]
        day = regional_date(date.fromisoformat(segment["date"]), preferences.locale)
        route = f"{legs[0]['origin']} → {legs[-1]['destination']} · {day}"
        if preferences.telegram_show_flight_numbers:
            flights = ", ".join(leg["airline"] + leg["number"] for leg in legs)
            route += " · " + flights
        lines.append(route)
    details = []
    if itinerary.get("adults") and observation.get("price_basis") == "total":
        adults = itinerary["adults"]
        details.append(f"Total for {adults} adult" + ("s" if adults > 1 else ""))
    if preferences.telegram_show_fare and observation.get("fare_name"):
        details.append("Fare: " + observation["fare_name"])
    if preferences.telegram_style == "compact":
        if details:
            lines.append(" · ".join(details))
    else:
        lines.extend(details)
    if preferences.telegram_show_observed_time:
        lines.append("Observed " + observed_time(observation["observed_at"], preferences))
    url = itinerary.get("url", "")
    if url and len(url) <= 1200:
        lines.append(url)
    if preferences.telegram_style == "detailed":
        lines.append(f"Alert {delivery['id'][:12]}")
    return "\n".join(lines)
