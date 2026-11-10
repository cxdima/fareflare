"""Validated account preferences shared by API, MCP and notification delivery."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from fareflare.contracts import Money
from fareflare.telegram_templates import TelegramStyle, validate_templates

Locale = Literal["en-US", "en-GB", "de-DE", "fr-FR", "es-ES", "uk-UA"]
HourCycle = Literal["auto", "h12", "h23"]
_DATE_FORMATS: dict[Locale, str] = {
    "en-US": "%m/%d/%Y",
    "en-GB": "%d/%m/%Y",
    "de-DE": "%d.%m.%Y",
    "fr-FR": "%d/%m/%Y",
    "es-ES": "%d/%m/%Y",
    "uk-UA": "%d.%m.%Y",
}
_NUMBER_SEPARATORS: dict[Locale, tuple[str, str]] = {
    "en-US": (",", "."),
    "en-GB": (",", "."),
    "de-DE": (".", ","),
    "fr-FR": (" ", ","),
    "es-ES": (".", ","),
    "uk-UA": (" ", ","),
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_SYMBOLS = {"USD": "$", "CAD": "CA$", "EUR": "€", "GBP": "£", "AUD": "A$", "JPY": "¥"}
# These regions conventionally write the amount first: 246,50 $.
_SYMBOL_AFTER: frozenset[str] = frozenset({"de-DE", "fr-FR", "es-ES", "uk-UA"})
_QUIET_HOURS = re.compile(r"((?:[01]\d|2[0-3]):[0-5]\d)-((?:[01]\d|2[0-3]):[0-5]\d)")


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    muted: bool = False
    muted_routes: list[str] = Field(default_factory=list, max_length=100)
    time_zone: str | None = Field(default=None, max_length=80)
    locale: Locale = "en-US"
    hour_cycle: HourCycle = "auto"
    telegram_style: TelegramStyle = Field(
        default="detailed",
        description="A built-in message style, or custom to use telegram_templates.",
    )
    telegram_templates: dict[str, str] = Field(
        default_factory=dict,
        description="Message templates used by the custom style, keyed by message name.",
    )
    telegram_show_flight_numbers: bool = True
    telegram_show_times: bool = Field(
        default=True, description="Include departure and arrival times when they are known."
    )
    telegram_show_observed_time: bool = True
    telegram_show_fare: bool = True
    telegram_show_buttons: bool = Field(
        default=True, description="Show link buttons beneath Telegram price alerts."
    )
    telegram_silent: bool = False
    quiet_hours: str | None = Field(
        default=None,
        max_length=11,
        description=(
            "A daily window in the account time zone, such as 22:00-07:00, during which "
            "Telegram messages arrive without sound. Nothing is held back or dropped."
        ),
    )
    diagnostics: bool = Field(
        default=False,
        description="Show technical details and receive notices about failing price checks.",
    )

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
        if (
            not re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", value)
            or value.startswith(("posix/", "right/"))
            or value in ("localtime", "posixrules")
        ):
            raise ValueError("Choose a valid IANA time zone")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA time zone") from None
        return value

    @field_validator("quiet_hours")
    @classmethod
    def valid_quiet_hours(cls, value: str | None) -> str | None:
        if value is None:
            return value
        match = _QUIET_HOURS.fullmatch(value)
        if not match or match[1] == match[2]:
            raise ValueError("Use two different 24-hour times such as 22:00-07:00")
        return value

    @field_validator("telegram_templates")
    @classmethod
    def valid_templates(cls, value: dict[str, str]) -> dict[str, str]:
        return validate_templates(value)


def stored_preferences(saved: dict | None) -> Preferences:
    """Read saved preferences without ever failing delivery or a settings page.

    A field written by a newer release, or one that is no longer valid, falls
    back to its default instead of making the whole record unreadable.
    """
    known = {
        name: value for name, value in (saved or {}).items() if name in Preferences.model_fields
    }
    try:
        return Preferences.model_validate(known)
    except ValidationError as error:
        invalid = {str(item["loc"][0]) for item in error.errors() if item["loc"]}
        return Preferences.model_validate(
            {name: value for name, value in known.items() if name not in invalid}
        )


def merge_preferences(current: dict | None, updates: dict | None = None) -> Preferences:
    """Apply a strict partial update on top of the saved preferences."""
    return Preferences.model_validate(
        {**stored_preferences(current).model_dump(), **(updates or {})}
    )


def regional_date(value: date, locale: Locale) -> str:
    # The supported formatting regions are explicit; message prose remains English.
    return value.strftime(_DATE_FORMATS[locale])


def short_date(value: date, reference_year: int | None = None) -> str:
    """Mar 10, adding the year only when it differs from the reference year."""
    text = f"{_MONTHS[value.month - 1]} {value.day}"
    return text if reference_year in (None, value.year) else f"{text}, {value.year}"


def _twelve_hour(preferences: Preferences) -> bool:
    return preferences.hour_cycle == "h12" or (
        preferences.hour_cycle == "auto" and preferences.locale == "en-US"
    )


def clock_time(value: str, preferences: Preferences) -> str:
    """A stored 24-hour ``HH:MM`` airport time in the reader's clock style: 4:42 PM or 16:42."""
    hour, minute = int(value[:2]), value[3:5]
    if not _twelve_hour(preferences):
        return f"{hour:02d}:{minute}"
    return f"{hour % 12 or 12}:{minute} {'PM' if hour >= 12 else 'AM'}"


def observed_time(seconds: int, preferences: Preferences, *, zone_label: bool = True) -> str:
    zone = ZoneInfo(preferences.time_zone or "UTC")
    local = datetime.fromtimestamp(seconds, UTC).astimezone(zone)
    clock = (
        local.strftime("%I:%M %p").lstrip("0")
        if _twelve_hour(preferences)
        else local.strftime("%H:%M")
    )
    stamp = f"{regional_date(local.date(), preferences.locale)} {clock}"
    if not zone_label:
        # A saved zone is the reader's own; an unlabeled UTC time would mislead.
        return stamp if preferences.time_zone else stamp + " UTC"
    offset = local.strftime("%z")
    label = "UTC" if zone.key == "UTC" else f"{zone.key} (UTC{offset[:3]}:{offset[3:]})"
    return f"{stamp} {label}"


def in_quiet_hours(preferences: Preferences, seconds: float) -> bool:
    """Whether a moment falls inside the account's quiet hours, in its own time zone.

    The window starts at its first time and ends just before its second, and may
    run past midnight: 22:00-07:00 covers 22:00 through 06:59.
    """
    if preferences.quiet_hours is None:
        return False
    start, end = preferences.quiet_hours.split("-")
    zone = ZoneInfo(preferences.time_zone or "UTC")
    now = datetime.fromtimestamp(seconds, UTC).astimezone(zone).strftime("%H:%M")
    return start <= now < end if start < end else now >= start or now < end


def quiet_hours_label(value: str, preferences: Preferences) -> str:
    """A quiet-hours window in the reader's clock style: 10:00 PM – 7:00 AM."""
    start, end = value.split("-")
    return f"{clock_time(start, preferences)} – {clock_time(end, preferences)}"


def sends_silently(preferences: Preferences, seconds: float) -> bool:
    """Whether a Telegram message sent at this moment should make no sound."""
    return preferences.telegram_silent or in_quiet_hours(preferences, seconds)


def regional_price(amount_minor: int, currency: str, locale: Locale) -> str:
    value = Money(amount_minor, currency)
    whole, fraction = divmod(value.amount_minor, 10**value.exponent)
    grouping, decimal = _NUMBER_SEPARATORS[locale]
    number = f"{whole:,}".replace(",", grouping)
    if value.exponent:
        number += f"{decimal}{fraction:02d}"
    return f"{currency} {number}"


def short_price(amount_minor: int, currency: str, locale: Locale, *, signed: bool = False) -> str:
    """Symbol form for compact text: $246, $246.50, or −$8 when signed."""
    value = Money(abs(amount_minor), currency)
    whole, fraction = divmod(value.amount_minor, 10**value.exponent)
    grouping, decimal = _NUMBER_SEPARATORS[locale]
    number = f"{whole:,}".replace(",", grouping)
    if value.exponent and fraction:
        number += f"{decimal}{fraction:02d}"
    symbol = _SYMBOLS[currency]
    text = f"{number} {symbol}" if locale in _SYMBOL_AFTER else f"{symbol}{number}"
    if not signed or amount_minor == 0:
        return text
    return ("−" if amount_minor < 0 else "+") + text


def telegram_text(delivery: dict, preferences: Preferences) -> str:
    """Plain-text body of a price alert, as rendered for this account."""
    from fareflare.telegram_messages import alert_message

    return alert_message(delivery, preferences).text
