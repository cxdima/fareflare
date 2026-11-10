"""Narrow, explicit fixed-date route searches; selected-itinerary IDs are unchanged."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from fareflare.links import InvalidLink, ItineraryMessage


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


def import_search_target(message, params: dict[str, str]) -> dict:
    """Called only after the common importer validates the URL and protobuf."""
    decoded = SearchMessage()
    decoded.ParseFromString(message.SerializeToString())
    segment = decoded.segments[0]
    currency, market = params.get("curr", message.currency or "USD"), params.get("gl", "US")
    if (
        len(message.passengers) != 1
        or message.cabin != 1
        or currency != "USD"
        or market != "US"
        or params.get("hl", "en-US") not in ("en", "en-US")
        or params.get("gsas") != "1"
        or (message.currency and message.currency != currency)
        or not segment.HasField("max_stops")
        or segment.max_stops != 0
        or len(segment.origins) != 1
        or len(segment.destinations) != 1
        or segment.origins[0].kind != 1
        or segment.destinations[0].kind != 1
        or not re.fullmatch(r"[A-Z]{3}", segment.origins[0].code)
        or not re.fullmatch(r"[A-Z]{3}", segment.destinations[0].code)
        or segment.origins[0].code == segment.destinations[0].code
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", segment.date)
    ):
        raise InvalidLink(
            "Route searches currently require one adult, one-way nonstop, Economy excluding Basic, USD, US English, and exact airports and date."
        )
    try:
        date.fromisoformat(segment.date)
    except ValueError:
        raise InvalidLink("The search contains an invalid departure date.") from None
    # Observed tfu variants contain only result sorting/navigation. Reject any
    # unrecognized variant rather than silently dropping a pricing constraint.
    if params.get("tfu", "") not in ("", "EgYIABAAGAA", "EgYIAhAAGAA"):
        raise InvalidLink("Copy a direct search-results link without a selected flight.")
    query = {key: value for key, value in params.items() if key not in ("authuser", "tfu")}
    query.update(curr=currency, gl=market, hl="en-US")
    query["tfs"] = (
        base64.urlsafe_b64encode(message.SerializeToString(deterministic=True)).decode().rstrip("=")
    )
    constraints = {key: value for key, value in query.items() if not key.startswith("utm_")}
    digest = hashlib.sha256(json.dumps(constraints, sort_keys=True).encode()).hexdigest()
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
        "currency": currency,
        "market": market,
        "provider_query": dict(sorted(query.items())),
        "url": "https://www.google.com/travel/flights/search?" + urlencode(sorted(query.items())),
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
    ignored = {"tfs", "tfu", "authuser"}
    return _without_selection(actual["tfs"]) == _without_selection(expected["tfs"]) and {
        k: v for k, v in actual.items() if k not in ignored
    } == {k: v for k, v in expected.items() if k not in ignored}
