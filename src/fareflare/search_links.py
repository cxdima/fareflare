"""Narrow, explicit fixed-date route searches; selected-itinerary IDs are unchanged."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from fareflare.links import AIRPORT, AIRPORT_KIND, ItineraryMessage, parse_day
from fareflare.refusals import LinkRefused


@dataclass(frozen=True)
class SearchTarget:
    origin: str
    destination: str
    date: str
    max_stops: int
    constraints_digest: str


def _search_message_class() -> Any:
    # Do not change the selected-itinerary descriptor: recognizing formerly
    # opaque fields there could reorder old tokens and change persisted IDs.
    schema = descriptor_pb2.FileDescriptorProto.FromString(
        ItineraryMessage.DESCRIPTOR.file.serialized_pb
    )
    schema.name = "fareflare_search.proto"
    segment = next(item for item in schema.message_type if item.name == "Segment")
    segment.field.add(name="max_stops", number=5, type=13, label=1)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("Itinerary"))


SearchMessage = _search_message_class()


def _without_selection(token: str) -> str:
    message = ItineraryMessage()
    message.ParseFromString(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    for segment in message.segments:
        segment.ClearField("legs")
    return (
        base64.urlsafe_b64encode(message.SerializeToString(deterministic=True)).decode().rstrip("=")
    )


def import_search_target(message: Any, query: dict[str, str]) -> dict:
    """A route search. Called only by the common importer, after it has read the
    link's facts and built the parameters the search is checked with."""
    decoded = SearchMessage()
    decoded.ParseFromString(message.SerializeToString())
    segment = decoded.segments[0]
    places = (*segment.origins, *segment.destinations)
    for unsupported, check in (
        (len(message.passengers) != 1, "search_passengers"),
        (message.cabin != 1, "search_cabin"),
        (query["curr"] != "USD", "search_currency"),
        (query["gl"] != "US", "search_country"),
        (not segment.HasField("max_stops") or segment.max_stops != 0, "search_stops"),
        (
            len(segment.origins) != 1
            or len(segment.destinations) != 1
            or any(
                place.kind != AIRPORT_KIND or not AIRPORT.fullmatch(place.code) for place in places
            )
            or segment.origins[0].code == segment.destinations[0].code,
            "search_places",
        ),
    ):
        if unsupported:
            raise LinkRefused(check)
    parse_day(segment.date, "date")
    digest = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
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
        "adults": 1,
        "cabin": 1,
        "currency": query["curr"],
        "market": query["gl"],
        "provider_query": query,
        "url": "https://www.google.com/travel/flights/search?" + urlencode(query),
    }


def offer_matches_search(target: dict, selected: dict) -> bool:
    """Verify the selection preserves every encoded search pricing constraint."""
    expected, actual = target["provider_query"], selected["provider_query"]
    if any(target[key] != selected[key] for key in ("adults", "cabin", "currency", "market")):
        return False
    if len(selected["segments"]) != 1 or len(selected["segments"][0]["legs"]) != 1:
        return False
    leg = selected["segments"][0]["legs"][0]
    criteria = target["search"]
    if any(leg[key] != criteria[key] for key in ("origin", "destination", "date")):
        return False
    return _without_selection(actual["tfs"]) == _without_selection(expected["tfs"]) and {
        k: v for k, v in actual.items() if k != "tfs"
    } == {k: v for k, v in expected.items() if k != "tfs"}
