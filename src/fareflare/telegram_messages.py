"""Plain-text and Telegram HTML views of the same account-owned message.

Message wording comes from the account's style: a built-in preset or its own
templates. This module turns stored facts into placeholder values and never
infers a saving, a forecast or a market-wide low.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fareflare.airlines import airline_name
from fareflare.links import import_link
from fareflare.message_templates import DIRECTIONAL, Rendered, Run, Value, render
from fareflare.preferences import (
    Preferences,
    clock_time,
    observed_time,
    regional_date,
    regional_price,
    short_date,
    short_price,
)
from fareflare.product_config import ProductConfig
from fareflare.telegram_templates import ALERT_KEYS, PRESETS, VOCABULARY, templates_for

STATUS_LABELS = {
    "pending": "Awaiting check",
    "active": "Watching",
    "degraded": "Check delayed",
    "paused": "Paused",
    "cancelled": "Stopped",
    "expired": "Departed",
}
_ALERT_WORDING = {
    # reason: (emoji, short headline, full reason)
    "tracking_started": ("✈️", "Now tracking", "Tracking started"),
    "new_low": ("📉", "New low!", "New observed low"),
    "below_price": ("🎯", "Target reached", "Price threshold reached"),
    "rebound": ("📈", "Rebounding", "Price rose from its low"),
}
# Plain-language explanations; the codes themselves are shown only on request.
_FAILURE_MEANING = {
    "unsupported_itinerary": "this itinerary is outside what Fareflare can check",
    "consent_required": "Google asked for a consent choice",
    "login_required": "Google asked for a sign-in",
    "challenge": "Google asked for a human check",
    "timeout": "the page took too long to load",
    "provider_error": "Google Flights showed an error page",
    "browser_start_failed": "the browser could not start",
    "browser_failed": "the browser stopped unexpectedly",
}
_SAMPLE_URL = (
    "https://www.google.com/travel/flights?tfs=CBoQAho_EgoyMDI3LTAzLTE0Ih8KA0RFThIKMjAyNy0wMy0x"
    "NBoDREZXKgJVQTIDNDE0agcIARIDREVOcgcIARIDREZXQAFIAVIDVVNEyAEB&curr=USD&hl=en-US&gl=US&gsas=1"
)
PREVIEW_KINDS = (*ALERT_KEYS, "flight_list")
_HHMM = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
# Telegram limits the visible text; this bounds the request when links repeat.
_MAX_MARKUP = 16_384


@dataclass(frozen=True)
class TelegramMessage:
    """Keep a plain counterpart for previews; markup is authored by presenters only."""

    text: str
    html: str | None = None
    reply_markup: dict | None = None

    def payload(self) -> dict:
        # Telegram applies its limit after parsing entities. Count UTF-16 units
        # conservatively so supplementary characters cannot exceed that bound.
        if not self.text.strip() or _utf16_length(self.text) > 4096:
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


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


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
        if char not in DIRECTIONAL
    )
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _shows(preferences: Preferences, enabled: bool) -> bool:
    # Checkboxes tune the built-in styles. A custom template states its own content.
    return enabled or preferences.telegram_style == "custom"


def _local_year(seconds: int, preferences: Preferences) -> int:
    zone = ZoneInfo(preferences.time_zone or "UTC")
    return datetime.fromtimestamp(seconds, UTC).astimezone(zone).year


def _flight_numbers(segments: list[dict]) -> list[str]:
    return [
        single_line(f"{leg['airline']} {leg['number']}", 20)
        for segment in segments
        for leg in segment["legs"]
        if leg.get("airline") and leg.get("number")
    ]


def _airlines(segments: list[dict]) -> str:
    codes = dict.fromkeys(
        str(leg["airline"]) for segment in segments for leg in segment["legs"] if leg.get("airline")
    )
    return ", ".join(single_line(airline_name(code), 40) for code in codes)


def _party(adults: object) -> str:
    if type(adults) is not int or adults < 1:
        return ""
    return f"{adults} adult" + ("s" if adults > 1 else "")


def _trip_values(
    segments: list[dict], preferences: Preferences, reference_year: int | None
) -> dict[str, Value]:
    if not segments:
        return {}
    first, last = segments[0], segments[-1]
    origin = single_line(str(first["legs"][0]["origin"]), 8)
    destination = single_line(str(first["legs"][-1]["destination"]), 8)
    round_trip = len(segments) > 1 and last["legs"][-1]["destination"] == first["legs"][0]["origin"]
    departure = date.fromisoformat(first["date"])
    values: dict[str, Value] = {
        "route": f"{origin} {'⇄' if round_trip else '→'} {destination}",
        "origin": origin,
        "destination": destination,
        "date": regional_date(departure, preferences.locale),
        "date_short": short_date(departure, reference_year),
        "dates": " / ".join(
            regional_date(date.fromisoformat(segment["date"]), preferences.locale)
            for segment in segments
        ),
    }
    if len(segments) > 1:
        returning = date.fromisoformat(last["date"])
        values["return_date"] = regional_date(returning, preferences.locale)
        values["return_date_short"] = short_date(returning, reference_year)
    return values


def recorded_times(schedule: object, segments: list[dict]) -> list[dict]:
    """Recorded clock times, one per direction, or nothing when they do not fit the trip."""
    if not isinstance(schedule, list) or not schedule or len(schedule) != len(segments):
        return []
    for item in schedule:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) and _HHMM.match(item[key])
            for key in ("departs", "arrives")
        ):
            return []
    return schedule


def _duration(minutes: object) -> str:
    if type(minutes) is not int or not 0 < minutes <= 24 * 60:
        return ""
    hours, rest = divmod(minutes, 60)
    return " ".join(
        part for part in (f"{hours} hr" if hours else "", f"{rest} min" if rest else "")
    )


def _time_values(times: list[dict], preferences: Preferences) -> dict[str, Value]:
    """Clock times in the reader's style. Airport-local, so no zone is shown."""
    values: dict[str, Value] = {}
    for prefix, item in zip(("", "return_"), times, strict=False):
        departs = clock_time(item["departs"], preferences)
        arrives = clock_time(item["arrives"], preferences)
        later = item.get("arrival_day_offset")
        if type(later) is int and 0 < later <= 3:
            arrives += f" +{later}"
        values[prefix + "depart_time"] = departs
        values[prefix + "arrive_time"] = arrives
        values[prefix + "times"] = f"{departs} → {arrives}"
        if duration := _duration(item.get("duration_minutes")):
            values[prefix + "duration"] = duration
    return values


def schedule_lines(times: list[dict], preferences: Preferences) -> list[str]:
    """One plain line per direction: ``4:42 PM → 5:58 PM · 1 hr 16 min``."""
    lines = []
    for item in times:
        values = _time_values([item], preferences)
        duration = values.get("duration")
        lines.append(f"{values['times']}" + (f" · {duration}" if duration else ""))
    return lines


def _itinerary(
    segments: list[dict], preferences: Preferences, flights: bool, times: list[dict]
) -> tuple[Run, ...]:
    runs: list[Run] = []
    clocks = schedule_lines(times, preferences)
    for index, segment in enumerate(segments):
        legs = segment["legs"]
        route = single_line(f"{legs[0]['origin']} → {legs[-1]['destination']}", 80)
        context = " · " + regional_date(date.fromisoformat(segment["date"]), preferences.locale)
        numbers = ", ".join(_flight_numbers([segment])) if flights else ""
        if numbers:
            context += " · " + numbers
        if clocks:
            context += "\n" + clocks[index]
        runs += [Run(("\n" if index else "") + route, bold=True), Run(context)]
    return tuple(runs)


def _comparison(delivery: dict, preferences: Preferences) -> dict[str, Value]:
    """Facts recorded with the alert; an older alert without them simply shows none."""
    observation = delivery["observation"]
    amount, currency, locale = (
        observation["amount_minor"],
        observation["currency"],
        preferences.locale,
    )
    previous = delivery.get("previous") or {}
    values: dict[str, Value] = {}
    for name in ("price", "low"):
        recorded = previous.get(name + "_minor")
        if type(recorded) is int and recorded > 0:
            values[f"previous_{name}"] = regional_price(recorded, currency, locale)
            values[f"previous_{name}_short"] = short_price(recorded, currency, locale)
    # A target is crossed from the previous price; a low or rebound is measured from the low.
    reference = previous.get("price_minor" if delivery["reason"] == "below_price" else "low_minor")
    if type(reference) is not int or reference <= 0 or reference == amount:
        return values
    change = short_price(amount - reference, currency, locale, signed=True)
    percent = round((amount - reference) / reference * 100)
    values["change"] = change
    if percent:
        values["change_percent"] = f"{'−' if percent < 0 else '+'}{abs(percent)}%"
    was = short_price(reference, currency, locale)
    if delivery["reason"] == "rebound":
        values["change_summary"] = f"was at low {was}, {change}"
    else:
        values["change_summary"] = f"was {was}, {change}" + (
            f" · {values['change_percent']}" if percent else ""
        )
    return values


def alert_values(delivery: dict, preferences: Preferences) -> dict[str, Value]:
    observation = delivery["observation"]
    itinerary = delivery.get("itinerary", {})
    segments = itinerary.get("segments", [])
    emoji, headline, reason = _ALERT_WORDING[delivery["reason"]]
    flights = _shows(preferences, preferences.telegram_show_flight_numbers)
    times = (
        recorded_times(observation.get("schedule"), segments)
        if _shows(preferences, preferences.telegram_show_times)
        else []
    )
    values: dict[str, Value] = {
        "emoji": emoji,
        "headline": headline,
        "reason": reason,
        "price": regional_price(
            observation["amount_minor"], observation["currency"], preferences.locale
        ),
        "price_short": short_price(
            observation["amount_minor"], observation["currency"], preferences.locale
        ),
        "passengers": _party(itinerary.get("adults")),
        "airline": _airlines(segments),
        "flights": ", ".join(_flight_numbers(segments)) if flights else "",
        "itinerary": _itinerary(segments, preferences, flights, times),
        **_trip_values(segments, preferences, _local_year(observation["observed_at"], preferences)),
        **_time_values(times, preferences),
        **_comparison(delivery, preferences),
    }
    if values["passengers"] and observation.get("price_basis") == "total":
        values["total"] = f"Total for {values['passengers']}"
    if _shows(preferences, preferences.telegram_show_fare) and observation.get("fare_name"):
        values["fare"] = single_line(observation["fare_name"])
    values["details"] = " · ".join(
        part
        for part in (values.get("total"), f"Fare: {values['fare']}" if "fare" in values else "")
        if isinstance(part, str) and part
    )
    if _shows(preferences, preferences.telegram_show_observed_time):
        values["observed"] = observed_time(observation["observed_at"], preferences)
        values["observed_short"] = observed_time(
            observation["observed_at"], preferences, zone_label=False
        )
    if flight_url := safe_flight_url(itinerary.get("url")):
        values["link"] = (Run("Open in Google Flights", href=flight_url),)
    return values


def _render(key: str, preferences: Preferences, values: dict[str, Value]) -> Rendered:
    """Render the account's template, falling back to a preset if it says nothing."""
    templates = templates_for(preferences.telegram_style, preferences.telegram_templates)
    rendered = render(templates[key], values, VOCABULARY[key])
    if (
        rendered.text.strip()
        and _utf16_length(rendered.text) <= 4096
        and len(rendered.html) <= _MAX_MARKUP
    ):
        return rendered
    return render(PRESETS["detailed"][key], values, VOCABULARY[key])


def alert_message(
    delivery: dict, preferences: Preferences, public_url: str | None = None
) -> TelegramMessage:
    """Render a price alert in the account's chosen style."""
    rendered = _render(delivery["reason"], preferences, alert_values(delivery, preferences))
    buttons = []
    if preferences.telegram_show_buttons:
        itinerary = delivery.get("itinerary", {})
        # A template that already links to the flight does not need a second link.
        if "link" not in rendered.used and (url := safe_flight_url(itinerary.get("url"))):
            buttons.append({"text": "View flight", "url": url, "style": "primary"})
        if dashboard_url := safe_dashboard_url(public_url):
            buttons.append({"text": "Open Fareflare", "url": dashboard_url})
    return TelegramMessage(
        rendered.text, rendered.html, {"inline_keyboard": [buttons]} if buttons else None
    )


def monitor_segments(monitor: dict) -> list[dict]:
    """The flights a monitor currently refers to: its last matched offer, else its target."""
    offer = (monitor.get("latest") or {}).get("observed_offer") or {}
    return offer.get("segments") or monitor["target"]["segments"]


def monitor_times(monitor: dict) -> list[dict]:
    """Clock times recorded with the monitor's latest price, when they fit its flights."""
    return recorded_times((monitor.get("latest") or {}).get("schedule"), monitor_segments(monitor))


def observed_low(monitor: dict) -> int | None:
    """Lowest price this monitor has recorded since it began tracking."""
    low = (monitor.get("rule_state") or {}).get("low_minor")
    return low if type(low) is int and low > 0 else None


def _needs_attention(monitor: dict) -> bool:
    return monitor.get("collection_status") == "blocked" or bool(
        monitor.get("stale") and monitor.get("latest")
    )


def flight_row_values(
    monitor: dict, preferences: Preferences, reference_year: int | None = None
) -> dict[str, Value]:
    target, latest = monitor["target"], monitor.get("latest")
    segments = monitor_segments(monitor)
    currency, locale = target["currency"], preferences.locale
    status = STATUS_LABELS.get(monitor["status"], "Unknown")
    numbers = _flight_numbers(segments)
    values: dict[str, Value] = {
        **_trip_values(target["segments"], preferences, reference_year),
        "flights": ", ".join(numbers) or ("Route search" if target.get("kind") == "search" else ""),
        "airline": _airlines(segments),
        "passengers": _party(target.get("adults")),
        "status": status,
    }
    if _shows(preferences, preferences.telegram_show_times):
        values.update(_time_values(monitor_times(monitor), preferences))
    if monitor["status"] == "active":
        values["status_note"] = "Check delayed" if _needs_attention(monitor) else ""
    else:
        values["status_note"] = status
    low = observed_low(monitor)
    if low is not None:
        values["low"] = regional_price(low, currency, locale)
        values["low_short"] = short_price(low, currency, locale)
    if latest:
        amount = latest["amount_minor"]
        values["price"] = regional_price(amount, latest["currency"], locale)
        values["price_short"] = short_price(amount, latest["currency"], locale)
        values["checked"] = observed_time(latest["observed_at"], preferences)
        if low is not None and amount <= low:
            values["low_note"] = "🔥 at the low"
            values["low_status"] = "At its lowest observed price"
        elif low is not None:
            values["low_note"] = f"(low {values['low_short']})"
            values["low_status"] = f"Lowest observed {values['low']}"
    return values


def flight_list(
    monitors: list[dict], preferences: Preferences, reference_year: int | None = None
) -> tuple[list[str], list[str]]:
    """Plain and HTML lines for a list of monitors, grouped under shared headings."""
    templates = templates_for(preferences.telegram_style, preferences.telegram_templates)
    plain: list[str] = []
    markup: list[str] = []
    heading = None
    # Multi-line rows need air between them; one-line rows read best as a list.
    spaced = "\n" in templates["flight_row"]
    for monitor in monitors:
        values = flight_row_values(monitor, preferences, reference_year)
        row = _render("flight_row", preferences, values)
        group = (
            render(templates["flight_group"], values, VOCABULARY["flight_group"])
            if templates["flight_group"]
            else None
        )
        if group is not None and group.text.strip():
            if group.text != heading:
                if plain:
                    plain.append("")
                    markup.append("")
                plain.append(group.text)
                markup.append(group.html)
                heading = group.text
        elif plain and spaced:
            plain.append("")
            markup.append("")
        plain.extend(row.text.split("\n"))
        markup.extend(row.html.split("\n"))
    return plain, markup


def flight_list_page_size(preferences: Preferences) -> int:
    """Short rows fit more flights into one message than multi-line rows."""
    templates = templates_for(preferences.telegram_style, preferences.telegram_templates)
    return 5 if templates["flight_row"].count("\n") >= 2 else 8


def failure_meaning(code: object) -> str:
    """A reader-friendly reason for a collection failure code."""
    return _FAILURE_MEANING.get(str(code), "the fare could not be verified")


def collection_notice(
    notice: dict, monitor: dict, preferences: Preferences, public_url: str | None = None
) -> TelegramMessage:
    """An opt-in diagnostic notice. Sent only to accounts that asked for them."""
    trip = _trip_values(monitor["target"]["segments"], preferences, None)
    route = f"{trip.get('route', 'Your flight')} · {trip.get('dates', '')}".rstrip(" ·")
    code = single_line(str(notice.get("code") or "unknown"), 40)
    if notice["kind"] == "collection_recovered":
        title, body = "✅ Price checks are working again", ["Fareflare recorded a fresh price."]
    elif notice["kind"] == "collection_blocked":
        title = "⚠️ Price checks have stopped"
        body = [
            f"Fareflare stopped checking because {failure_meaning(code)}.",
            "Open the flight and choose Retry collection when you are ready.",
            f"Diagnostic code: {code}",
        ]
    else:
        attempts = notice.get("failures")
        count = f"The last {attempts} checks" if type(attempts) is int else "Recent checks"
        title = "⚠️ Price checks are failing"
        body = [
            f"{count} could not finish because {failure_meaning(code)}.",
            "Fareflare keeps retrying automatically; your last recorded price is unchanged.",
            f"Diagnostic code: {code}",
        ]
    footer = "You receive this because diagnostic notices are on in Account settings."
    lines = [title, route, "", *body, "", footer]
    html = "\n".join(
        [
            f"<b>{escape(title)}</b>",
            escape(route),
            "",
            *map(escape, body),
            "",
            f"<i>{escape(footer)}</i>",
        ]
    )
    button = safe_dashboard_url(public_url)
    markup = {"inline_keyboard": [[{"text": "Open Fareflare", "url": button}]]} if button else None
    return TelegramMessage("\n".join(lines), html, markup)


_SAMPLE_TIMES = {
    "414": {"departs": "15:50", "arrives": "18:54", "duration_minutes": 124},
    "1565": {"departs": "07:05", "arrives": "10:02", "duration_minutes": 117},
    "1832": {"departs": "19:40", "arrives": "22:41", "duration_minutes": 121},
}


def _sample_delivery(reason: str, now: int) -> dict:
    amount, previous = {
        "tracking_started": (19100, {"price_minor": None, "low_minor": None}),
        "new_low": (19100, {"price_minor": 20400, "low_minor": 19900}),
        "below_price": (19100, {"price_minor": 20400, "low_minor": 19900}),
        "rebound": (21100, {"price_minor": 19100, "low_minor": 19100}),
    }[reason]
    return {
        "id": "example-alert",
        "reason": reason,
        "previous": previous,
        "observation": {
            "amount_minor": amount,
            "currency": "USD",
            "price_basis": "total",
            "fare_name": "Economy",
            "observed_at": now,
            "schedule": [_SAMPLE_TIMES["414"]],
        },
        "itinerary": {
            "adults": 1,
            "url": _SAMPLE_URL,
            "segments": [
                {
                    "date": "2027-03-14",
                    "legs": [
                        {"origin": "DEN", "destination": "DFW", "airline": "UA", "number": "414"}
                    ],
                }
            ],
        },
    }


def _sample_monitor(number: str, amount: int, low: int, status: str, now: int) -> dict:
    return {
        "status": status,
        "stale": False,
        "collection_status": "ready",
        "rule_state": {"low_minor": low},
        "latest": {
            "amount_minor": amount,
            "currency": "USD",
            "observed_at": now,
            "schedule": [_SAMPLE_TIMES[number]],
        },
        "target": {
            "adults": 1,
            "currency": "USD",
            "segments": [
                {
                    "date": "2027-03-14",
                    "legs": [
                        {"origin": "DEN", "destination": "DFW", "airline": "UA", "number": number}
                    ],
                }
            ],
        },
    }


def preview_message(
    kind: str, preferences: Preferences, public_url: str | None, now: int
) -> TelegramMessage:
    """Sample data rendered with the given preferences; nothing is sent or saved."""
    if kind not in PREVIEW_KINDS:
        raise ValueError("Choose a message to preview")
    if kind != "flight_list":
        return alert_message(_sample_delivery(kind, now), preferences, public_url)
    # In departure order, the way the bot lists a day of flights.
    samples = [
        _sample_monitor("1565", 21400, 21400, "active", now),
        _sample_monitor("414", 26900, 21900, "active", now),
        _sample_monitor("1832", 26900, 19900, "paused", now),
    ]
    plain, markup = flight_list(samples, preferences, _local_year(now, preferences))
    return TelegramMessage("\n".join(plain), "\n".join(markup))
