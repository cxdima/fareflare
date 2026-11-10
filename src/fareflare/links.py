"""Offline, conservative import of selected-itinerary Google Flights URLs.

Field mapping reference (independently implemented, not copied):
https://github.com/punitarani/fli/blob/881aee5ff4321e81ea2157cb44be94ce6a21dc1b/fli/search/_proto.py
The format is unofficial. Preserve unknown protobuf fields and query parameters;
prefer a missed deduplication over merging two different priced products.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict
from datetime import date
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import DecodeError

from fareflare.contracts import FlightLeg, JourneySlice, Offer


class InvalidLink(ValueError):
    """The URL cannot be safely interpreted as a supported exact itinerary."""


def _message_class() -> Any:
    schema = descriptor_pb2.FileDescriptorProto(name="fareflare_itinerary.proto", syntax="proto2")
    definitions = {
        "Location": [(1, "kind", 13, False, None), (2, "code", 9, False, None)],
        "Leg": [
            (1, "origin", 9, False, None),
            (2, "date", 9, False, None),
            (3, "destination", 9, False, None),
            (5, "airline", 9, False, None),
            (6, "number", 9, False, None),
        ],
        "Segment": [
            (2, "date", 9, False, None),
            (4, "legs", 11, True, ".Leg"),
            (13, "origins", 11, True, ".Location"),
            (14, "destinations", 11, True, ".Location"),
        ],
        "Itinerary": [
            (3, "segments", 11, True, ".Segment"),
            (8, "passengers", 13, True, None),
            (9, "cabin", 13, False, None),
            (10, "currency", 9, False, None),
            (19, "trip", 13, False, None),
        ],
    }
    for name, fields in definitions.items():
        message = schema.message_type.add(name=name)
        for number, field_name, kind, repeated, target in fields:
            field = message.field.add(
                name=field_name, number=number, type=kind, label=3 if repeated else 1
            )
            if target:
                field.type_name = target
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("Itinerary"))


ItineraryMessage = _message_class()
_AIRPORT = re.compile(r"[A-Z]{3}\Z")
_AIRLINE = re.compile(r"[A-Z0-9]{2,3}\Z")
_NUMBER = re.compile(r"[0-9]{1,5}[A-Z]?\Z")
_HOSTS = {"google.com", "www.google.com"}
_PATHS = {"/travel/flights", "/travel/flights/search", "/travel/flights/booking"}


def import_link(url: str, *, allow_search: bool = False) -> dict:
    """No network, cookies or environment access. Return a versioned target."""
    if not isinstance(url, str) or not url or len(url) > 8192:
        raise InvalidLink("Supply a Google Flights link of at most 8192 characters.")
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in url) or "\\" in url:
        raise InvalidLink("The link contains ambiguous or control characters.")
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme == "https"
            and parts.hostname in _HOSTS
            and parts.port in (None, 443)
            and not parts.username
            and not parts.password
            and not parts.fragment
        )
    except ValueError as exc:
        raise InvalidLink("Malformed Google Flights URL.") from exc
    if not valid:
        raise InvalidLink(
            "Use a direct HTTPS Google Flights link without credentials or fragments."
        )
    if parts.path.startswith("/travel/flights/s/"):
        raise InvalidLink("Open the shared link and copy the full selected-itinerary URL.")
    if parts.path not in _PATHS:
        raise InvalidLink("This Google URL is not a supported Flights page.")
    try:
        pairs = parse_qsl(
            parts.query,
            keep_blank_values=True,
            max_num_fields=40,
            encoding="utf-8",
            errors="strict",
        )
    except (ValueError, UnicodeError) as exc:
        raise InvalidLink("Malformed query parameters.") from exc
    params = dict(pairs)
    if len(params) != len(pairs):
        raise InvalidLink("Duplicate query parameters are ambiguous.")
    token = params.get("tfs", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,6000}={0,2}", token):
        raise InvalidLink("The link needs a valid tfs itinerary token.")
    try:
        raw = base64.b64decode(
            token.rstrip("=") + "=" * (-len(token.rstrip("=")) % 4), altchars=b"-_", validate=True
        )
        message = ItineraryMessage()
        message.ParseFromString(raw)
    except (ValueError, DecodeError) as exc:
        raise InvalidLink("The itinerary token could not be decoded.") from exc
    trip = message.trip if message.HasField("trip") else {1: 2, 2: 1}.get(len(message.segments))
    if trip not in (1, 2) or len(message.segments) != (2 if trip == 1 else 1):
        raise InvalidLink("Currently supported: fixed-date one-way and round-trip itineraries.")
    if not 1 <= len(message.passengers) <= 9 or any(p != 1 for p in message.passengers):
        raise InvalidLink(
            "This prototype supports 1–9 adults; children/infants are not validated yet."
        )
    if message.cabin not in (1, 2, 3, 4):
        raise InvalidLink("The cabin class is missing or unsupported.")
    if allow_search and len(message.segments) == 1 and not message.segments[0].legs:
        from fareflare.search_links import import_search_target

        return import_search_target(message, params)
    segments = []
    try:
        for segment in message.segments:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", segment.date):
                raise InvalidLink("Itinerary dates must use YYYY-MM-DD.")
            departure = date.fromisoformat(segment.date)
            if not 1 <= len(segment.legs) <= 4:
                raise InvalidLink(
                    "Select every flight leg, including the return, before copying the link."
                )
            legs = []
            for leg in segment.legs:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", leg.date):
                    raise InvalidLink("Flight dates must use YYYY-MM-DD.")
                leg_date = date.fromisoformat(leg.date)
                if not (
                    _AIRPORT.fullmatch(leg.origin)
                    and _AIRPORT.fullmatch(leg.destination)
                    and _AIRLINE.fullmatch(leg.airline)
                    and _NUMBER.fullmatch(leg.number)
                ):
                    raise InvalidLink("A selected flight leg is incomplete.")
                if not 0 <= (leg_date - departure).days <= 3:
                    raise InvalidLink("The selected flight dates do not match the search.")
                legs.append(
                    {
                        "origin": leg.origin,
                        "destination": leg.destination,
                        "date": leg.date,
                        "airline": leg.airline,
                        "number": leg.number,
                    }
                )
            if legs[0]["date"] != segment.date:
                raise InvalidLink("The first leg does not match the departure date.")
            for previous, following in zip(legs, legs[1:], strict=False):
                if (
                    previous["destination"] != following["origin"]
                    or previous["date"] > following["date"]
                ):
                    raise InvalidLink("Selected connections are inconsistent.")
            for locations, airport in (
                (segment.origins, legs[0]["origin"]),
                (segment.destinations, legs[-1]["destination"]),
            ):
                if len(locations) != 1 or locations[0].kind != 1 or locations[0].code != airport:
                    raise InvalidLink("Airport selection does not match the selected itinerary.")
            segments.append({"date": segment.date, "legs": legs})
    except ValueError as exc:
        if isinstance(exc, InvalidLink):
            raise
        raise InvalidLink("The itinerary contains invalid dates.") from exc
    if len(segments) == 2:
        outbound, inbound = segments
        if (
            outbound["date"] > inbound["date"]
            or outbound["legs"][0]["origin"] != inbound["legs"][-1]["destination"]
            or outbound["legs"][-1]["destination"] != inbound["legs"][0]["origin"]
        ):
            raise InvalidLink("Open-jaw or inconsistent round trips are not supported yet.")
    currency, market = params.get("curr", message.currency or "USD"), params.get("gl", "US")
    if message.currency and message.currency != currency:
        raise InvalidLink("The URL currency and encoded itinerary currency disagree.")
    if not re.fullmatch(r"[A-Z]{3}", currency) or not re.fullmatch(r"[A-Z]{2}", market):
        raise InvalidLink("Use an explicit three-letter currency and two-letter market.")
    # authuser is a browser account selector, never a part of a customer target.
    params.pop("authuser", None)
    params.update(curr=currency, gl=market)
    params["tfs"] = (
        base64.urlsafe_b64encode(message.SerializeToString(deterministic=True)).decode().rstrip("=")
    )
    target = {
        "schema_version": 1,
        "segments": segments,
        "adults": len(message.passengers),
        "cabin": message.cabin,
        "currency": currency,
        "market": market,
        "provider_query": dict(sorted(params.items())),
    }
    # Separate product identity from navigation. Known defaults can normalize, while
    # opaque fields remain constraints until their meaning is verified.
    opaque = ItineraryMessage()
    opaque.CopyFrom(message)
    opaque.ClearField("trip")
    opaque.ClearField("currency")
    constraints = {
        k: v
        for k, v in params.items()
        if k not in ("tfs", "curr", "gl")
        and not k.startswith("utm_")
        and not (k == "source" and v == "flre_fli_share")
    }
    constraints["opaque_token"] = base64.urlsafe_b64encode(
        opaque.SerializeToString(deterministic=True)
    ).decode()
    constraint_hash = hashlib.sha256(json.dumps(constraints, sort_keys=True).encode()).hexdigest()
    offer = Offer(
        tuple(
            JourneySlice(s["date"], tuple(FlightLeg(**leg) for leg in s["legs"])) for s in segments
        ),
        len(message.passengers),
        message.cabin,
        currency,
        market,
        constraint_hash,
    )
    fingerprint = hashlib.sha256(json.dumps(asdict(offer), sort_keys=True).encode()).hexdigest()
    return {
        **target,
        "schema_version": 2,
        "offer": json.loads(json.dumps(asdict(offer))),
        "id": fingerprint,
        "url": "https://www.google.com/travel/flights/booking?" + urlencode(sorted(params.items())),
    }
