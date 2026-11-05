"""Fail-closed interpretation of the public selected-flight booking page.

This adapter verifies one or two adults, nonstop one-way or round-trip
economy itineraries, USD/JPY, and the US English page. A price is usable only when the
summary and Google's explicitly search-matching booking option agree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from gfpt_next.contracts import CollectionFailure, QuoteEvidence, Reading
from gfpt_next.links import import_link

QuoteUnavailable = CollectionFailure


@dataclass(frozen=True)
class PageEvidence:
    url: str
    body: str
    summary_prices: list[str]
    matching_options: list[str]
    selected_text: str
    flight_numbers: list[str]
    departure_dates: list[str]


def supported_target(target: dict) -> None:
    if (target["adults"] not in (1, 2) or target["cabin"] != 1
            or target["currency"] not in ("USD", "JPY") or target["market"] != "US"
            or target["provider_query"].get("hl", "en-US") not in ("en", "en-US")
            or len(target["segments"]) not in (1, 2)
            or any(len(segment["legs"]) != 1 for segment in target["segments"])):
        raise QuoteUnavailable("unsupported_itinerary")


def _normal(text: str) -> str:
    return " ".join(text.split())


def _money(label: str, currency: str) -> int:
    # Accessible labels identify the currency; a dollar sign alone is ambiguous.
    name = {"USD": "US dollars", "JPY": "Japanese yen"}[currency]
    decimals = r"(\.\d{2})?" if currency == "USD" else r"()"
    match = re.fullmatch(r"([1-9]\d{0,7}|[1-9]\d{0,2}(?:,\d{3})+)" + decimals + " " + name, label)
    if not match:
        raise QuoteUnavailable("unrecognized_price")
    amount = int(Decimal(match[1].replace(",", "") + (match[2] or "")) * (100 if currency == "USD" else 1))
    if not 0 < amount <= 100_000_000:
        raise QuoteUnavailable("unrecognized_price")
    return amount


def verified_reading(target: dict, page: PageEvidence, observed_at: int) -> Reading:
    supported_target(target)
    try:
        actual = import_link(page.url)
    except ValueError:
        raise QuoteUnavailable("unexpected_page") from None
    if actual["id"] != target["id"]:
        raise QuoteUnavailable("itinerary_changed")
    body, selected = _normal(page.body), _normal(page.selected_text)
    adults, currency = target["adults"], target["currency"]
    party = f"{adults} passenger" + ("s" if adults > 1 else "")
    taxes = f"Prices include required taxes + fees for {adults} adult" + ("s." if adults > 1 else ".")
    trip_label = "Round trip" if len(target["segments"]) == 2 else "One way"
    if (trip_label not in body or party not in body
            or taxes not in body
            or "Currency" + currency not in body.replace(" ", "")
            or "Economy" not in selected):
        raise QuoteUnavailable("incomplete_trip_context")
    segments = target["segments"]
    sections = [selected]
    if len(segments) == 2:
        if selected.count("Departing flight") != 1 or selected.count("Returning flight") != 1:
            raise QuoteUnavailable("incomplete_trip_context")
        outbound, inbound = selected.split("Returning flight")
        sections = [outbound.split("Departing flight")[-1], inbound]
    numbers = {_normal(number) for number in page.flight_numbers}
    expected = {f"{s['legs'][0]['airline']} {s['legs'][0]['number']}" for s in segments}
    if numbers != expected or set(page.departure_dates) != {segments[0]["date"]}:
        raise QuoteUnavailable("flight_identity_mismatch")
    for segment, section in zip(segments, sections, strict=True):
        leg = segment["legs"][0]
        departure = date.fromisoformat(leg["date"])
        month = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[departure.month - 1]
        day_label = f"{month} {departure.day}"
        if (not re.search(re.escape(day_label) + r"\b", section)
                or not re.search(re.escape(f"{leg['airline']} {leg['number']}") + r"\b", section)
                or re.findall(r"\(([A-Z]{3})\)", section) != [leg["origin"], leg["destination"]]):
            raise QuoteUnavailable("flight_identity_mismatch")
    if len(page.summary_prices) != 1 or len(page.matching_options) != 1:
        raise QuoteUnavailable("ambiguous_fare")
    summary = _money(_normal(page.summary_prices[0]), currency)
    option = re.fullmatch(r"Continue to book with (.+), (.+) for (.+)",
                          _normal(page.matching_options[0]))
    if not option or len(option[2]) > 120:
        raise QuoteUnavailable("unrecognized_fare")
    if summary != _money(option[3], currency):
        raise QuoteUnavailable("price_disagreement")
    return Reading(target["id"], summary, currency, observed_at,
                   "google-flights-public-browser", fare_name=option[2], price_basis="total",
                   evidence=QuoteEvidence("public-dom-v2", True, True, True,
                       (100 if "." not in page.summary_prices[0] else 1) if currency == "USD" else 1))
