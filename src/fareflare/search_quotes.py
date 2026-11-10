"""Verify the cheapest matching Google result against its selected booking fare."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

from fareflare.contracts import FlightLeg, JourneySlice, ObservedOffer, Reading
from fareflare.links import import_link
from fareflare.public_quotes import (
    PageEvidence,
    QuoteUnavailable,
    _money,
    _normal,
    verified_reading,
)
from fareflare.search_links import offer_matches_search


@dataclass(frozen=True)
class SearchPageEvidence:
    url: str
    body: str
    rows: list[dict]
    sort_label: str
    stops_label: str
    passenger_label: str
    more_results: bool


def verified_search_minimum(target: dict, page: SearchPageEvidence) -> int:
    try:
        actual = import_link(page.url, allow_search=True)
    except ValueError:
        raise QuoteUnavailable("unexpected_page") from None
    if actual["id"] != target["id"] or actual.get("kind") != "search":
        raise QuoteUnavailable("itinerary_changed")
    body = _normal(page.body)
    count = re.findall(r"\b(\d+) results returned\.", body)
    if (
        page.sort_label != "Sorted by price, Change sort order."
        or page.stops_label != "Nonstop, Stops, Selected"
        or page.passenger_label not in ("1 passenger", "1 passenger, change number of passengers.")
        or "One way" not in body
        or "Economy (exclude Basic)" not in body
        or "Prices include required taxes + fees for 1 adult." not in body
        or "CurrencyUSD" not in body.replace(" ", "")
        or page.more_results
        or len(count) != 1
        or not 1 <= len(page.rows) <= 100
        or int(count[0]) != len(page.rows)
    ):
        raise QuoteUnavailable("incomplete_trip_context")
    criteria = target["search"]
    route = criteria["origin"] + "–" + criteria["destination"]
    departure = date.fromisoformat(criteria["date"])
    month = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )[departure.month - 1]
    departure_label = f", {month} {departure.day}"
    prices = []
    for row in page.rows:
        label, text = _normal(row["label"]), _normal(row["text"])
        match = re.match(r"From (.+? US dollars)\. Nonstop flight with ", label)
        if (
            not match
            or route not in text
            or "Nonstop" not in text
            or len(row["prices"]) != 1
            or not re.search(re.escape(departure_label) + r"\b", label.split(" and arrives ")[0])
        ):
            raise QuoteUnavailable("flight_identity_mismatch")
        amount = _money(_normal(row["prices"][0]), "USD")
        if amount != _money(match[1], "USD"):
            raise QuoteUnavailable("price_disagreement")
        prices.append(amount)
    # Google's sort control changes before the result list is rerendered.
    # Reject that transition instead of accidentally selecting a former top pick.
    if prices != sorted(prices):
        raise QuoteUnavailable("incomplete_trip_context")
    return prices[0]


def verified_search_reading(
    target: dict,
    search: SearchPageEvidence,
    selected: dict,
    booking: PageEvidence,
    observed_at: int,
) -> Reading:
    minimum = verified_search_minimum(target, search)
    if not offer_matches_search(target, selected):
        raise QuoteUnavailable("itinerary_changed")
    reading = verified_reading(selected, booking, observed_at)
    if reading.amount_minor != minimum:
        raise QuoteUnavailable("price_disagreement")
    offer = ObservedOffer(
        selected["id"],
        tuple(
            JourneySlice(segment["date"], tuple(FlightLeg(**leg) for leg in segment["legs"]))
            for segment in selected["segments"]
        ),
        selected["adults"],
        selected["cabin"],
        selected["url"],
    )
    assert reading.evidence is not None
    return replace(
        reading,
        target_id=target["id"],
        source="google-flights-public-search",
        evidence=replace(reading.evidence, adapter_version="public-search-v1"),
        observed_offer=offer,
    )
