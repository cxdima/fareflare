"""Telegram message styles: template names, their placeholders and the built-in presets.

This module owns vocabulary and validation only. Values are produced by
``telegram_messages`` and the syntax by ``message_templates``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from fareflare.message_templates import (
    MAX_PLACEHOLDERS,
    MAX_TEMPLATE_LENGTH,
    MAX_TEMPLATE_LINES,
    TemplateError,
    normalize_template,
    parse_template,
    template_fields,
)

TelegramStyle = Literal["compact", "detailed", "custom"]
BuiltInStyle = Literal["compact", "detailed"]
TemplateKey = Literal[
    "tracking_started", "new_low", "below_price", "rebound", "flight_group", "flight_row"
]

# The style of a new account, and the wording used wherever an account's own is missing.
DEFAULT_STYLE: BuiltInStyle = "compact"
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
STYLES: dict[str, tuple[str, str]] = {
    # style: (name, what it shows)
    "compact": ("Compact", "The price, what changed, the flight and its times."),
    "detailed": ("Detailed", "Adds the airline, flight length, fare and time of the check."),
    "custom": ("Custom", "Your own wording for every message."),
}


@dataclass(frozen=True)
class Placeholder:
    name: str
    description: str
    example: str
    # Where an editor lists it. Set once for a whole family below.
    group: str = ""


def _family(group: str, *items: Placeholder) -> tuple[Placeholder, ...]:
    return tuple(replace(item, group=group) for item in items)


_TRIP = _family(
    "Trip",
    Placeholder("route", "Airports, with ⇄ for a round trip", "DFW → DEN"),
    Placeholder("dates_short", "Travel days as a short month and day", "Mar 10 – Mar 14"),
    Placeholder("date_short", "Departure date as a short month and day", "Mar 10"),
    Placeholder("return_date_short", "Short return date; empty for a one-way trip", "Mar 14"),
    Placeholder("date", "Departure date in your regional format", "03/10/2027"),
    Placeholder("return_date", "Return date; empty for a one-way trip", "03/14/2027"),
    Placeholder("dates", "Every travel date in your regional format", "03/10/2027"),
    Placeholder("origin", "Departure airport", "DFW"),
    Placeholder("destination", "Arrival airport", "DEN"),
)
_FLIGHT = _family(
    "Flight",
    Placeholder("flights", "Flight numbers", "UA 1753"),
    Placeholder("airline", "Airline name, or its code when unlisted", "United"),
    Placeholder("passengers", "Travelling party", "1 adult"),
)
_TIMES = _family(
    "Times",
    Placeholder("times", "Departure and arrival times, when known", "4:42 PM → 5:58 PM"),
    Placeholder("times_short", "The same times, written tightly for a list", "4:42→5:58 PM"),
    Placeholder("depart_time", "Departure time at the origin airport", "4:42 PM"),
    Placeholder("arrive_time", "Arrival time at the destination airport", "5:58 PM"),
    Placeholder("duration", "Time in the air, when known", "2 hr 16 min"),
    Placeholder(
        "return_times", "Return flight times; empty for a one-way trip", "9:05 AM → 12:14 PM"
    ),
    Placeholder("return_times_short", "Return times, written tightly", "9:05 AM→12:14 PM"),
    Placeholder("return_depart_time", "Return departure time", "9:05 AM"),
    Placeholder("return_arrive_time", "Return arrival time", "12:14 PM"),
    Placeholder("return_duration", "Return time in the air", "2 hr 9 min"),
)
_ALERT = (
    *_family(
        "Price",
        Placeholder("price_short", "The recorded price with a currency symbol", "$246"),
        Placeholder("previous_low_short", "The lowest price recorded before this one", "$254"),
        Placeholder("previous_price_short", "The price recorded before this one", "$259"),
        Placeholder("change", "Difference from the price being compared", "−$8"),
        Placeholder("change_percent", "That difference as a percentage", "−3%"),
        Placeholder("change_summary", "The comparison in one phrase", "was $254, −$8 · −3%"),
        Placeholder("price", "The recorded price with its currency code", "USD 246.00"),
        Placeholder("previous_low", "The previous low with its currency code", "USD 254.00"),
        Placeholder("previous_price", "The previous price with its currency code", "USD 259.00"),
    ),
    *_family(
        "Alert",
        Placeholder("emoji", "A symbol for this kind of alert", "🔥"),
        Placeholder("headline", "A short title", "New low"),
        Placeholder("reason", "The alert reason in full", "New observed low"),
    ),
    *_TRIP,
    *_FLIGHT,
    *_TIMES,
    *_family(
        "More",
        Placeholder("fare", "Fare name", "Economy"),
        Placeholder("total", "Who the price covers, when verified", "Total for 1 adult"),
        Placeholder(
            "party_note", "Who the price covers, only for more than one traveller", "for 2 adults"
        ),
        Placeholder("details", "Total and fare on one line", "Total for 1 adult · Fare: Economy"),
        Placeholder("observed_short", "When the price was checked", "03/02/2027 9:38 AM"),
        Placeholder(
            "observed", "When the price was checked, with its time zone", "03/02/2027 9:38 AM UTC"
        ),
        Placeholder(
            "late_note",
            "When the price was checked, only on an alert that arrives late",
            "Checked 03/02/2027 9:38 AM",
        ),
        Placeholder(
            "itinerary", "Each direction: route, date and flights, then its times", "DFW → DEN · …"
        ),
        Placeholder(
            "link", "A link that opens the flight on Google Flights", "Open in Google Flights"
        ),
    ),
)
_ROW = (
    *_family(
        "Price",
        Placeholder("price_short", "Latest recorded price with a currency symbol", "$246"),
        Placeholder("low_note", "How the latest price compares with the low", "🔥 at the low"),
        Placeholder("low_short", "Lowest recorded price with a currency symbol", "$231"),
        Placeholder("low_status", "The same comparison as a phrase", "Lowest $231"),
        Placeholder("price", "Latest recorded price with its currency code", "USD 246.00"),
        Placeholder("low", "Lowest recorded price with its currency code", "USD 231.00"),
    ),
    *_TRIP,
    *_FLIGHT,
    *_TIMES,
    *_family(
        "More",
        Placeholder("status_note", "Status, only when the flight needs attention", "Paused"),
        Placeholder("status", "Tracking status", "Watching"),
        Placeholder("checked", "When the latest price was checked", "03/02/2027 9:38 AM UTC"),
    ),
)

PLACEHOLDERS: dict[str, tuple[Placeholder, ...]] = {
    **dict.fromkeys(ALERT_KEYS, _ALERT),
    "flight_group": _TRIP,
    "flight_row": _ROW,
}
VOCABULARY: dict[str, frozenset[str]] = {
    key: frozenset(item.name for item in items) for key, items in PLACEHOLDERS.items()
}

# Every alert says what happened and the price first, then which flight.
_HEADLINE = "{emoji} **{headline}** · **{price_short}**"
_COMPACT_TRIP = """
{route} · {dates_short} · {flights}
{times}
[↩ {return_times}]
[__{late_note}__]"""
_DETAILED_TRIP = """
{route} · {dates_short} · {flights}
{times} · {duration}
[↩ {return_times}] · {return_duration}
{airline} · {fare} · {total}
[__Checked {observed_short}__]"""
# What each kind of alert compares its price with.
_COMPACT_COMPARISON = {
    "tracking_started": "",
    "new_low": "[ __(was {previous_low_short})__]",
    "below_price": "[ __(was {previous_price_short})__]",
    "rebound": "[ __(low {previous_low_short})__]",
}
_DETAILED_COMPARISON = {
    "tracking_started": "",
    **dict.fromkeys(("new_low", "below_price", "rebound"), "[ __({change_summary})__]"),
}

PRESETS: dict[str, dict[str, str]] = {
    "compact": {
        # The detailed style names the travelling party on its own line instead.
        **{
            key: _HEADLINE + "[ {party_note}]" + comparison + _COMPACT_TRIP
            for key, comparison in _COMPACT_COMPARISON.items()
        },
        # Flights on one route and day share a heading; each takes a single line.
        "flight_group": "🛫 **{route}** · {dates_short}",
        "flight_row": (
            "• `{flights}` {times_short} · **{price_short}** __{low_note}__ · {status_note}\n"
            "[   ↩ {return_times_short}]"
        ),
    },
    "detailed": {
        **{
            key: _HEADLINE + comparison + _DETAILED_TRIP
            for key, comparison in _DETAILED_COMPARISON.items()
        },
        "flight_group": "",
        "flight_row": (
            "**{route}** · {dates_short}\n"
            "{flights} · {times} · **{price_short}**\n"
            "[↩ {return_times}]\n"
            "{low_status} · {status_note}"
        ),
    },
}
# Which "include in alerts" choices a built-in style can act on: the details they govern.
SWITCHES: dict[str, frozenset[str]] = {
    "telegram_show_flight_numbers": frozenset({"flights", "itinerary"}),
    "telegram_show_times": frozenset(
        {"itinerary", *(item.name for item in _TIMES if "duration" not in item.name)}
    ),
    "telegram_show_observed_time": frozenset({"observed", "observed_short"}),
    "telegram_show_fare": frozenset({"fare", "details"}),
}


def style_switches(style: str) -> list[str]:
    """The detail choices that change this built-in style's alerts."""
    shown = frozenset().union(
        *(template_fields(PRESETS[style][key], VOCABULARY[key]) for key in ALERT_KEYS)
    )
    return [name for name, governed in SWITCHES.items() if shown & governed]


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
    """Templates for a style. A message without its own wording uses the default style's."""
    if style == "custom":
        return {**PRESETS[DEFAULT_STYLE], **(custom or {})}
    return PRESETS[style]


def template_catalog() -> dict:
    """Everything an editor needs: styles, names, placeholders, presets and limits."""
    return {
        "styles": [
            {
                "value": style,
                "label": label,
                "description": description,
                "switches": style_switches(style) if style in PRESETS else [],
            }
            for style, (label, description) in STYLES.items()
        ],
        "default_style": DEFAULT_STYLE,
        "templates": [
            {"key": key, "label": LABELS[key], "optional": key in OPTIONAL_KEYS}
            for key in TEMPLATE_KEYS
        ],
        "placeholders": {
            key: [
                {
                    "name": item.name,
                    "description": item.description,
                    "example": item.example,
                    "group": item.group,
                }
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
