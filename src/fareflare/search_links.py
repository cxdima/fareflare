"""Narrow, explicit fixed-date route searches, read by the common importer.

A route search has the same identity rules as chosen flights (``links``): its facts
and whatever else might decide a price. Its searched places are part of what is
asked, so they stay in its identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode

from fareflare.limits import ROUTE_SEARCHES
from fareflare.links import (
    AIRPORT,
    AIRPORT_KIND,
    constraint_hash,
    parse_day,
    parse_token,
    price_facts,
)
from fareflare.refusals import LinkRefused


@dataclass(frozen=True)
class SearchTarget:
    origin: str
    destination: str
    date: str
    max_stops: int
    constraints_digest: str


def _search_identity(message: Any, query: dict[str, str]) -> str:
    """The search's facts and constraints as one hash."""
    facts = {"currency": query["curr"], "country": query["gl"]}
    return hashlib.sha256(
        json.dumps(
            {**facts, "constraints": constraint_hash(message, query)}, sort_keys=True
        ).encode()
    ).hexdigest()


def import_search_target(message: Any, query: dict[str, str]) -> dict:
    """A route search. Called only by the common importer, after it has read the
    link's facts and built the parameters the search is checked with."""
    limits = ROUTE_SEARCHES
    segment = message.segments[0]
    places = (*segment.origins, *segment.destinations)
    for unsupported, check in (
        (len(message.passengers) > limits.adults, "search_passengers"),
        (message.cabin != limits.cabin, "search_cabin"),
        (query["curr"] not in limits.currencies, "search_currency"),
        (query["gl"] != limits.country, "search_country"),
        (
            limits.nonstop and (not segment.HasField("max_stops") or segment.max_stops != 0),
            "search_stops",
        ),
        (
            limits.exact_airports
            and (
                len(segment.origins) != 1
                or len(segment.destinations) != 1
                or any(
                    place.kind != AIRPORT_KIND or not AIRPORT.fullmatch(place.code)
                    for place in places
                )
                or segment.origins[0].code == segment.destinations[0].code
            ),
            "search_places",
        ),
        # The route-search reader verifies the fares that leave Basic out.
        (limits.exclude_basic and message.exclude_basic != 1, "search_basic"),
    ):
        if unsupported:
            raise LinkRefused(check)
    parse_day(segment.date, "date")
    digest = _search_identity(message, query)
    criteria = SearchTarget(
        segment.origins[0].code, segment.destinations[0].code, segment.date, 0, digest
    )
    identifier = hashlib.sha256(("route-search-v1:" + digest).encode()).hexdigest()
    return {
        "schema_version": 3,
        "kind": "search",
        "id": identifier,
        "search": asdict(criteria),
        "segments": [
            {
                "date": criteria.date,
                "legs": [
                    {
                        "origin": criteria.origin,
                        "destination": criteria.destination,
                        "date": criteria.date,
                        "airline": None,
                        "number": None,
                    }
                ],
            }
        ],
        "adults": len(message.passengers),
        "cabin": message.cabin,
        "currency": query["curr"],
        "market": query["gl"],
        "provider_query": query,
        "url": "https://www.google.com/travel/flights/search?" + urlencode(query),
    }


def offer_matches_search(target: dict, selected: dict) -> bool:
    """Verify the selection preserves every encoded search pricing constraint."""
    if any(target[key] != selected[key] for key in ("adults", "cabin", "currency", "market")):
        return False
    if len(selected["segments"]) != 1 or len(selected["segments"][0]["legs"]) != 1:
        return False
    leg = selected["segments"][0]["legs"][0]
    criteria = target["search"]
    if any(leg[key] != criteria[key] for key in ("origin", "destination", "date")):
        return False
    # The flight chosen from the results meets the search's criteria by construction;
    # what must survive the click is everything that decides its price.
    expected, actual = target["provider_query"], selected["provider_query"]
    return price_facts(parse_token(actual["tfs"])) == price_facts(
        parse_token(expected["tfs"])
    ) and {k: v for k, v in actual.items() if k != "tfs"} == {
        k: v for k, v in expected.items() if k != "tfs"
    }
