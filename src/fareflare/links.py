"""Offline, conservative import of Google Flights links.

Field mapping reference (independently implemented, not copied):
https://github.com/punitarani/fli/blob/881aee5ff4321e81ea2157cb44be94ce6a21dc1b/fli/search/_proto.py
The format is unofficial. A link is read as the facts that decide a price (the
flights, passengers, cabin, currency and country) and the context it was found in.
A target's identity is its facts plus every part of the context that might change a
price: unknown protobuf fields and query parameters are kept, because a missed match
is better than merging two differently priced products. Context that is known not to
change a price (the places searched for, the page language and view, the browser and
click tracking) is left out, so a flight has one identity however its link was found.
Whether the collector can price a target is decided separately, after import.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict
from datetime import date
from itertools import pairwise
from typing import Any
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import DecodeError

from fareflare.contracts import FlightLeg, JourneySlice, Offer
from fareflare.refusals import LinkRefused


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

AIRPORT = re.compile(r"[A-Z]{3}\Z")
_AIRLINE = re.compile(r"[A-Z0-9]{2,3}\Z")
_NUMBER = re.compile(r"[0-9]{1,5}[A-Z]?\Z")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,6000}={0,2}\Z")
# Google Flights answers on google.com and on Google's country domains. Only on
# google.com is a link without a country (gl) one for the United States.
_GOOGLE = re.compile(r"(?:www\.)?google\.(?:com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})\Z")
_US_HOSTS = {"google.com", "www.google.com"}
# The pages a flight's link opens: a search, a booking page, or the Flights page
# itself. Other Flights pages (deals, saved flights, the old /flights) name none.
_FLIGHT_PAGES = {"/travel/flights", "/travel/flights/search", "/travel/flights/booking"}
_FLIGHTS = re.compile(r"/(?:travel/)?flights(?:/.*)?\Z")
# A searched place is an airport, by its code, or a place known by its Knowledge
# Graph id: Google marks cities and wider areas with kinds 2 and 3.
AIRPORT_KIND = 1
_PLACE_CODES = {
    AIRPORT_KIND: AIRPORT,
    **dict.fromkeys((2, 3), re.compile(r"/[mg]/[0-9a-z_]{1,32}\Z")),
}
# Trip types as Google encodes them.
ROUND_TRIP, ONE_WAY, MULTI_CITY = 1, 2, 3
# The page language the collector reads. Every target is checked in it.
LANGUAGE = "en-US"

# What each known query parameter of a Google Flights link is:
#   fact      read into the target: the itinerary, its currency and its country
#   language  the page language; every page is read in US English
#   view      how the page is shown: the order of results, or the session and price
#             a booking page was opened from (a booking page opens from tfs alone)
#   browser   which browser, or which signed-in account, opened the link
#   tracking  where the click came from
# Facts and unknown parameters stay in a target and in the address it is checked at;
# the rest never changes a price.
PARAMETERS: dict[str, str] = {
    "tfs": "fact",
    "curr": "fact",
    "gl": "fact",
    "hl": "language",
    "tfu": "view",
    "authuser": "browser",
    "client": "browser",
    "biw": "browser",
    "bih": "browser",
    "rlz": "browser",
    "sa": "tracking",
    "ved": "tracking",
    "source": "tracking",
    "ictx": "tracking",
    "sxsrf": "tracking",
    "sca_esv": "tracking",
}
_TRACKING_PREFIX = "utm_"


def parameter_kind(name: str) -> str | None:
    """What a query parameter is, or None when its meaning is unknown."""
    return "tracking" if name.startswith(_TRACKING_PREFIX) else PARAMETERS.get(name)


def _kept(name: str) -> bool:
    return parameter_kind(name) in (None, "fact")


def _text_is_valid(message: Any) -> bool:
    """Whether every text field decoded as text.

    The schema is proto2, where a text field holding bytes that are not UTF-8
    is handed back as ``bytes`` instead of failing the parse.
    """
    for field, value in message.ListFields():
        for item in value if field.is_repeated else (value,):
            if field.type == field.TYPE_MESSAGE:
                if not _text_is_valid(item):
                    return False
            elif field.type == field.TYPE_STRING and not isinstance(item, str):
                return False
    return True


def _token(message: Any) -> str:
    return base64.urlsafe_b64encode(message.SerializeToString(deterministic=True)).decode()


def itinerary_link(
    segments: list[dict], *, adults: int = 1, cabin: int = 1, currency: str = "USD"
) -> str:
    """A Google Flights link that selects exactly these flights.

    The inverse of ``import_link`` for the itineraries it supports: one direction,
    or out and back. A leg without a date of its own flies on its segment's date.
    """
    message = ItineraryMessage(
        passengers=[1] * adults, cabin=cabin, trip=ROUND_TRIP if len(segments) == 2 else ONE_WAY
    )
    for segment in segments:
        legs = segment["legs"]
        entry = message.segments.add(date=segment["date"])
        for leg in legs:
            entry.legs.add(
                origin=leg["origin"],
                date=leg.get("date", segment["date"]),
                destination=leg["destination"],
                airline=leg["airline"],
                number=leg["number"],
            )
        entry.origins.add(kind=AIRPORT_KIND, code=legs[0]["origin"])
        entry.destinations.add(kind=AIRPORT_KIND, code=legs[-1]["destination"])
    return "https://www.google.com/travel/flights?" + urlencode(
        {"tfs": _token(message).rstrip("="), "curr": currency}
    )


def _address(url: str) -> SplitResult:
    if not isinstance(url, str) or not url:
        raise LinkRefused("empty")
    if len(url) > 8192:
        raise LinkRefused("too_long")
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in url) or "\\" in url:
        raise LinkRefused("characters")
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise LinkRefused("malformed") from None
    if parts.scheme != "https":
        raise LinkRefused("not_https")
    if not _GOOGLE.fullmatch(host or "") or port not in (None, 443):
        raise LinkRefused("not_google")
    if parts.username or parts.password:
        raise LinkRefused("credentials")
    if parts.path.startswith("/travel/flights/s/"):
        raise LinkRefused("shared_link")
    if not _FLIGHTS.fullmatch(parts.path):
        raise LinkRefused("not_flights_page")
    if parts.path not in _FLIGHT_PAGES:
        raise LinkRefused("flights_page")
    if parts.fragment:
        raise LinkRefused("fragment")
    return parts


def _parameters(parts: SplitResult) -> dict[str, str]:
    try:
        pairs = parse_qsl(
            parts.query,
            keep_blank_values=True,
            max_num_fields=40,
            encoding="utf-8",
            errors="strict",
        )
    except (ValueError, UnicodeError):
        raise LinkRefused("query") from None
    params: dict[str, str] = {}
    for name, value in pairs:
        # Only a repeated parameter that is kept would be ambiguous.
        if name in params and _kept(name):
            raise LinkRefused("repeated_parameter")
        params[name] = value
    return params


def _itinerary(params: dict[str, str]) -> Any:
    if "tfs" not in params:
        raise LinkRefused("no_flights")  # A text search or the Flights home page.
    token = params["tfs"]
    if not _TOKEN.fullmatch(token):
        raise LinkRefused("token")
    try:
        raw = base64.b64decode(
            token.rstrip("=") + "=" * (-len(token.rstrip("=")) % 4), altchars=b"-_", validate=True
        )
        message = ItineraryMessage()
        message.ParseFromString(raw)
    except (ValueError, DecodeError):
        raise LinkRefused("token_undecodable") from None
    if not _text_is_valid(message):
        raise LinkRefused("token_undecodable")
    return message


def parse_day(text: str, check: str) -> date:
    if _DAY.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    raise LinkRefused(check)


def _search_admits(locations: Any, airport: str) -> bool:
    """Whether a search endpoint can hold the selected flight's airport.

    The endpoint is what the person searched for: airports, places, or both.
    The selected flights decide the trip. A place's airports are not known offline,
    so the airport is checked only against an endpoint made of airports alone.
    """
    if not locations or not all(
        location.kind in _PLACE_CODES and _PLACE_CODES[location.kind].fullmatch(location.code)
        for location in locations
    ):
        return False
    return any(location.kind != AIRPORT_KIND or location.code == airport for location in locations)


def _selected_segment(segment: Any) -> dict:
    if len(segment.legs) > 4:
        raise LinkRefused("too_many_legs")
    departure = parse_day(segment.date, "date")
    legs = []
    for leg in segment.legs:
        if not 0 <= (parse_day(leg.date, "leg_date") - departure).days <= 3:
            raise LinkRefused("leg_date")
        if not (
            AIRPORT.fullmatch(leg.origin)
            and AIRPORT.fullmatch(leg.destination)
            and _AIRLINE.fullmatch(leg.airline)
            and _NUMBER.fullmatch(leg.number)
        ):
            raise LinkRefused("leg")
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
        raise LinkRefused("leg_date")
    for previous, following in pairwise(legs):
        if previous["destination"] != following["origin"] or previous["date"] > following["date"]:
            raise LinkRefused("connection_mismatch")
    if not _search_admits(segment.origins, legs[0]["origin"]) or not _search_admits(
        segment.destinations, legs[-1]["destination"]
    ):
        raise LinkRefused("searched_places")
    return {"date": segment.date, "legs": legs}


def _checked_query(message: Any, params: dict[str, str], currency: str, country: str) -> dict:
    """The parameters a target is checked with: its facts in canonical form, the
    collector's language, and every unknown parameter, since it might change a price."""
    query = {name: value for name, value in params.items() if parameter_kind(name) is None}
    query.update(tfs=_token(message).rstrip("="), curr=currency, gl=country, hl=LANGUAGE)
    return dict(sorted(query.items()))


def import_link(url: str, *, allow_search: bool = False) -> dict:
    """No network, cookies or environment access. Return a versioned target."""
    parts = _address(url)
    params = _parameters(parts)
    message = _itinerary(params)
    trip = (
        message.trip
        if message.HasField("trip")
        else {1: ONE_WAY, 2: ROUND_TRIP}.get(len(message.segments))
    )
    if trip == MULTI_CITY or len(message.segments) > 2:
        raise LinkRefused("multi_city")
    if trip not in (ROUND_TRIP, ONE_WAY) or len(message.segments) != (
        2 if trip == ROUND_TRIP else 1
    ):
        raise LinkRefused("segments")
    if not message.passengers:
        raise LinkRefused("passengers_missing")
    if any(passenger != 1 for passenger in message.passengers):
        raise LinkRefused("children")  # Only adults are encoded as 1.
    if len(message.passengers) > 9:
        raise LinkRefused("adults")
    if message.cabin not in (1, 2, 3, 4):
        raise LinkRefused("cabin_missing")
    if "gl" not in params and parts.hostname not in _US_HOSTS:
        raise LinkRefused("country")  # Another country's Google, with no location stated.
    currency, country = params.get("curr", message.currency or "USD"), params.get("gl", "US")
    if not re.fullmatch(r"[A-Za-z]{3}", currency) or not re.fullmatch(r"[A-Za-z]{2}", country):
        raise LinkRefused("codes")
    # Google writes both codes in either case: links from Safari carry gl=us.
    currency, country = currency.upper(), country.upper()
    if message.currency and message.currency != currency:
        raise LinkRefused("currency_mismatch")
    query = _checked_query(message, params, currency, country)
    if not any(segment.legs for segment in message.segments):
        if allow_search and len(message.segments) == 1:
            from fareflare.search_links import import_search_target

            return import_search_target(message, query)
        raise LinkRefused("search_shape" if allow_search else "no_flights")
    if not all(segment.legs for segment in message.segments):
        raise LinkRefused("return_missing")
    segments = [_selected_segment(segment) for segment in message.segments]
    if len(segments) == 2:
        outbound, inbound = segments
        if (
            outbound["date"] > inbound["date"]
            or outbound["legs"][0]["origin"] != inbound["legs"][-1]["destination"]
            or outbound["legs"][-1]["destination"] != inbound["legs"][0]["origin"]
        ):
            raise LinkRefused("open_jaw")
    return _selected_target(message, segments, query)


def _selected_target(message: Any, segments: list[dict], query: dict) -> dict:
    # The identity token is the itinerary without its navigation defaults and with
    # each searched place replaced by the selected flight's airport: what was
    # searched for does not change the price of the flights that were chosen.
    identity = ItineraryMessage()
    identity.CopyFrom(message)
    identity.ClearField("trip")
    identity.ClearField("currency")
    for entry, segment in zip(identity.segments, segments, strict=True):
        for field, airport in (
            ("origins", segment["legs"][0]["origin"]),
            ("destinations", segment["legs"][-1]["destination"]),
        ):
            entry.ClearField(field)
            getattr(entry, field).add(kind=AIRPORT_KIND, code=airport)
    constraints = {name: value for name, value in query.items() if parameter_kind(name) != "fact"}
    constraints["opaque_token"] = _token(identity)
    constraint_hash = hashlib.sha256(json.dumps(constraints, sort_keys=True).encode()).hexdigest()
    currency, country = query["curr"], query["gl"]
    offer = Offer(
        tuple(
            JourneySlice(s["date"], tuple(FlightLeg(**leg) for leg in s["legs"])) for s in segments
        ),
        len(message.passengers),
        message.cabin,
        currency,
        country,
        constraint_hash,
    )
    return {
        "schema_version": 2,
        "segments": segments,
        "adults": len(message.passengers),
        "cabin": message.cabin,
        "currency": currency,
        "market": country,
        "provider_query": query,
        "offer": json.loads(json.dumps(asdict(offer))),
        "id": hashlib.sha256(json.dumps(asdict(offer), sort_keys=True).encode()).hexdigest(),
        "url": "https://www.google.com/travel/flights/booking?" + urlencode(query),
    }
