"""Telegram message styles: template names, their placeholders and the built-in presets.

This module owns vocabulary and validation only. Values are produced by
``telegram_messages`` and the syntax by ``message_templates``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from fareflare.message_templates import (
    MAX_PLACEHOLDERS,
    MAX_TEMPLATE_LENGTH,
    MAX_TEMPLATE_LINES,
    TemplateError,
    normalize_template,
    parse_template,
)

TelegramStyle = Literal["detailed", "compact", "classic", "custom"]
TemplateKey = Literal[
    "tracking_started", "new_low", "below_price", "rebound", "flight_group", "flight_row"
]

ALERT_KEYS: tuple[TemplateKey, ...] = ("tracking_started", "new_low", "below_price", "rebound")
TEMPLATE_KEYS: tuple[TemplateKey, ...] = (*ALERT_KEYS, "flight_group", "flight_row")
# A list needs no heading; every other message must say something.
OPTIONAL_KEYS: frozenset[str] = frozenset({"flight_group"})
LABELS: dict[str, str] = {
    "tracking_started": "Tracking started",
    "new_low": "New low",
    "below_price": "Target reached",
    "rebound": "Price rebound",
    "flight_group": "Flight list heading",
    "flight_row": "Flight list row",
}


@dataclass(frozen=True)
class Placeholder:
    name: str
    description: str
    example: str


_TRIP = (
    Placeholder("route", "Airports, with ⇄ for a round trip", "DFW → DEN"),
    Placeholder("origin", "Departure airport", "DFW"),
    Placeholder("destination", "Arrival airport", "DEN"),
    Placeholder("date", "Departure date in your regional format", "03/10/2027"),
    Placeholder("date_short", "Departure date as a short month and day", "Mar 10"),
    Placeholder("return_date", "Return date; empty for a one-way trip", "03/14/2027"),
    Placeholder("return_date_short", "Short return date; empty for a one-way trip", "Mar 14"),
    Placeholder("dates", "Every travel date in your regional format", "03/10/2027"),
)
_FLIGHT = (
    Placeholder("flights", "Flight numbers", "UA 1753"),
    Placeholder("airline", "Airline name, or its code when unlisted", "United"),
    Placeholder("passengers", "Travelling party", "1 adult"),
)
_TIMES = (
    Placeholder("times", "Departure and arrival times, when known", "4:42 PM → 5:58 PM"),
    Placeholder("depart_time", "Departure time at the origin airport", "4:42 PM"),
    Placeholder("arrive_time", "Arrival time at the destination airport", "5:58 PM"),
    Placeholder("duration", "Time in the air, when known", "2 hr 16 min"),
    Placeholder(
        "return_times", "Return flight times; empty for a one-way trip", "9:05 AM → 12:14 PM"
    ),
    Placeholder("return_depart_time", "Return departure time", "9:05 AM"),
    Placeholder("return_arrive_time", "Return arrival time", "12:14 PM"),
    Placeholder("return_duration", "Return time in the air", "2 hr 9 min"),
)
_ALERT = (
    Placeholder("emoji", "A symbol for this kind of alert", "📉"),
    Placeholder("headline", "A short title", "New low!"),
    Placeholder("reason", "The alert reason in full", "New observed low"),
    Placeholder("price", "The recorded price with its currency code", "USD 246.00"),
    Placeholder("price_short", "The recorded price with a currency symbol", "$246"),
    Placeholder("previous_price", "The price recorded before this one", "USD 259.00"),
    Placeholder("previous_price_short", "The previous price with a currency symbol", "$259"),
    Placeholder("previous_low", "The lowest price recorded before this one", "USD 254.00"),
    Placeholder("previous_low_short", "The previous low with a currency symbol", "$254"),
    Placeholder("change", "Difference from the price being compared", "−$8"),
    Placeholder("change_percent", "That difference as a percentage", "−3%"),
    Placeholder("change_summary", "The comparison in one phrase", "was $254, −$8 · −3%"),
    *_TRIP,
    *_FLIGHT,
    *_TIMES,
    Placeholder(
        "itinerary", "Each direction: route, date and flights, then its times", "DFW → DEN · …"
    ),
    Placeholder("total", "Who the price covers, when verified", "Total for 1 adult"),
    Placeholder("fare", "Fare name", "Economy"),
    Placeholder("details", "Total and fare on one line", "Total for 1 adult · Fare: Economy"),
    Placeholder(
        "observed", "When the price was checked, with its time zone", "03/02/2027 9:38 AM UTC"
    ),
    Placeholder("observed_short", "When the price was checked, briefly", "03/02/2027 9:38 AM"),
    Placeholder("link", "A link that opens the flight on Google Flights", "Open in Google Flights"),
)
_ROW = (
    *_TRIP,
    *_FLIGHT,
    *_TIMES,
    Placeholder("status", "Tracking status", "Watching"),
    Placeholder("status_note", "Status, only when the flight needs attention", "Paused"),
    Placeholder("price", "Latest recorded price with its currency code", "USD 246.00"),
    Placeholder("price_short", "Latest recorded price with a currency symbol", "$246"),
    Placeholder("low", "Lowest recorded price with its currency code", "USD 231.00"),
    Placeholder("low_short", "Lowest recorded price with a currency symbol", "$231"),
    Placeholder("low_note", "How the latest price compares with the low", "🔥 at the low"),
    Placeholder("low_status", "The same comparison in plain words", "Lowest observed USD 231.00"),
    Placeholder("checked", "When the latest price was checked", "03/02/2027 9:38 AM UTC"),
)

PLACEHOLDERS: dict[str, tuple[Placeholder, ...]] = {
    **dict.fromkeys(ALERT_KEYS, _ALERT),
    "flight_group": _TRIP,
    "flight_row": _ROW,
}
VOCABULARY: dict[str, frozenset[str]] = {
    key: frozenset(item.name for item in items) for key, items in PLACEHOLDERS.items()
}

_DETAILED_ALERT = """\
**{price}**
{reason}

{itinerary}

{total}
[Fare: {fare}]

[Observed {observed}]"""
_COMPACT_ALERT = """\
**{price}**
{reason}

{itinerary}

{details}

[Observed {observed}]"""
_CLASSIC_TRIP = """\
🛫 **{route}**
[{airline}][  ·  `{flights}`]
{date_short}[  ·  {times}]
[↩ {return_date_short}][  ·  {return_times}]
{link}
"""
_CLASSIC_FOOTER = "\n__{observed_short}__"
_CLASSIC_CHANGE = "{emoji} **{headline}**  **{price_short}**[  __({change_summary})__]\n"

PRESETS: dict[str, dict[str, str]] = {
    "detailed": {
        **dict.fromkeys(ALERT_KEYS, _DETAILED_ALERT),
        "flight_group": "",
        "flight_row": (
            "{route}  {dates}\n[{flights} · ][{times} · ]{status}\n"
            "[Last observed {price}]\n[{low_status}]"
        ),
    },
    "compact": {
        **dict.fromkeys(ALERT_KEYS, _COMPACT_ALERT),
        "flight_group": "",
        "flight_row": (
            "{route} · {date_short}[ {depart_time}][ · {flights}][ · {price}][ · {status_note}]"
        ),
    },
    "classic": {
        "tracking_started": (
            "{emoji} **{headline}**  ·  **{price_short}**\n" + _CLASSIC_TRIP + _CLASSIC_FOOTER
        ),
        "new_low": _CLASSIC_CHANGE + _CLASSIC_TRIP + _CLASSIC_FOOTER,
        "below_price": _CLASSIC_CHANGE + _CLASSIC_TRIP + _CLASSIC_FOOTER,
        "rebound": (
            _CLASSIC_CHANGE
            + _CLASSIC_TRIP
            + "__The discount window may be closing.__\n"
            + _CLASSIC_FOOTER
        ),
        "flight_group": "🛫 **{route}**  __{date_short}[ – {return_date_short}]__",
        "flight_row": (
            "  • `{flights}`[  {times}][ · **{price_short}**][ __{low_note}__][ · {status_note}]\n"
            "[      ↩ {return_date_short}  ·  {return_times}]"
        ),
    },
}


def validate_templates(templates: Mapping[str, str]) -> dict[str, str]:
    """Return the canonical stored form, or raise ``TemplateError`` naming the template."""
    if not isinstance(templates, Mapping):
        raise TemplateError("Message templates must be an object")
    unknown = sorted(set(templates) - set(TEMPLATE_KEYS))
    if unknown:
        raise TemplateError(f"Unknown message template: {unknown[0]}")
    result: dict[str, str] = {}
    for key in TEMPLATE_KEYS:
        if key not in templates:
            continue
        try:
            text = normalize_template(templates[key])
            if not text and key not in OPTIONAL_KEYS:
                raise TemplateError("the template cannot be empty")
            parse_template(text, VOCABULARY[key])
        except TemplateError as error:
            raise TemplateError(f"{LABELS[key]}: {error}") from None
        result[key] = text
    return result


def templates_for(style: str, custom: Mapping[str, str] | None = None) -> dict[str, str]:
    """Templates for a style. Custom templates fall back to the detailed preset."""
    if style == "custom":
        return {**PRESETS["detailed"], **(custom or {})}
    return PRESETS[style]


def template_catalog() -> dict:
    """Everything an editor needs: names, placeholders, presets and limits."""
    return {
        "templates": [
            {"key": key, "label": LABELS[key], "optional": key in OPTIONAL_KEYS}
            for key in TEMPLATE_KEYS
        ],
        "placeholders": {
            key: [
                {"name": item.name, "description": item.description, "example": item.example}
                for item in PLACEHOLDERS[key]
            ]
            for key in TEMPLATE_KEYS
        },
        "presets": {style: dict(templates) for style, templates in PRESETS.items()},
        "limits": {
            "characters": MAX_TEMPLATE_LENGTH,
            "lines": MAX_TEMPLATE_LINES,
            "placeholders": MAX_PLACEHOLDERS,
        },
    }
