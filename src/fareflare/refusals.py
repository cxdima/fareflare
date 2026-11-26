"""Why Fareflare will not watch a link: one finite vocabulary for every surface.

The Telegram bot, the dashboard and API, MCP and the command line show the same
sentence for the same reason. The finer check names exactly what was wrong: it is
shown only to accounts with diagnostics on, and the admin panel counts refusals by
it. Neither ever carries the link. Sentences about what is supported are written
from the limits table, so they say exactly the value that is needed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from fareflare.limits import (
    FLIGHTS,
    ROUTE_SEARCHES,
    adults,
    cabin,
    country,
    currencies,
    stops,
    trips,
)
from fareflare.store import Conflict, Document, Store

log = logging.getLogger(__name__)
_CHANGE = "Change the {} and send the link again."

# One sentence per reason: what Fareflare cannot do, and what to do instead.
REASONS: dict[str, str] = {
    "not_flights": "This isn't a Google Flights link. Open your flight in Google Flights "
    "and send its link.",
    "incomplete": "This Google Flights link is incomplete. Copy it again from the address bar "
    "and send the whole link.",
    "old_link": "This is an old Google Flights link. Open it, then send the link Google "
    "Flights shows.",
    "short_link": "This short link didn't open. Open it, then send the full Google Flights link.",
    "no_flight_chosen": "This link doesn't name a flight. Choose your flights in Google "
    "Flights, then send the link.",
    "return_not_chosen": "Choose your return flight too, then send the link again.",
    "trip_type": f"Fareflare watches {trips(FLIGHTS)} only. Search a one-way or round trip, "
    "then send its link.",
    "open_jaw": "Fareflare watches round trips that fly back between the same two airports. "
    "Choose a return between them, then send the link again.",
    "connections": f"Fareflare watches {stops(FLIGHTS)} flights only. Choose a "
    f"{stops(FLIGHTS)} flight, then send its link.",
    "cabin": f"Fareflare watches {cabin(FLIGHTS)} fares only. " + _CHANGE.format("cabin"),
    "passengers": f"Fareflare watches trips for {adults(FLIGHTS)} only. "
    + _CHANGE.format("passengers"),
    "currency": f"Fareflare checks prices in {currencies(FLIGHTS)} only. "
    + _CHANGE.format("currency"),
    "country": f"Fareflare checks prices for {country(FLIGHTS)} only. "
    + _CHANGE.format("location"),
    "country_unstated": "This link doesn't say its country. Set the location to "
    f"{country(FLIGHTS)} and send the link again.",
    "search_trip": f"Route searches need {trips(ROUTE_SEARCHES)}. Search one way, or choose "
    "your flights and send that link.",
    "search_passengers": f"Route searches need {adults(ROUTE_SEARCHES)}. "
    + _CHANGE.format("passengers"),
    "search_stops": f"Route searches need {stops(ROUTE_SEARCHES)} flights. Set Stops to "
    "Nonstop in Google Flights and send the link again.",
    "search_cabin": f"Route searches need {cabin(ROUTE_SEARCHES)}. Choose it in Google "
    "Flights and send the link again.",
    "search_currency": f"Route searches need prices in {currencies(ROUTE_SEARCHES)}. "
    + _CHANGE.format("currency"),
    "search_places": "Route searches go from one airport to another. Search between two "
    "airports and send the link again.",
    "departed": "This flight has already left. Choose a future flight and send its link.",
}

# Each check is one precise fault and belongs to exactly one reason.
CHECKS: dict[str, str] = {
    # Not a Google Flights page at all.
    "empty": "not_flights",
    "malformed": "not_flights",
    "not_https": "not_flights",
    "not_google": "not_flights",
    "not_flights_page": "not_flights",
    # A Flights link that lost or garbled part of itself.
    "too_long": "incomplete",
    "characters": "incomplete",
    "credentials": "incomplete",
    "fragment": "incomplete",
    "query": "incomplete",
    "repeated_parameter": "incomplete",
    "token": "incomplete",
    "token_undecodable": "incomplete",
    "segments": "incomplete",
    "cabin_missing": "incomplete",
    "currency_mismatch": "incomplete",
    "codes": "incomplete",
    "date": "incomplete",
    "leg": "incomplete",
    "leg_date": "incomplete",
    "connection_mismatch": "incomplete",
    "searched_places": "incomplete",
    # Google Flights' address format from before 2020.
    "old_format": "old_link",
    # A shared short link that did not lead to a Flights page.
    "shared_link": "short_link",
    "short_link_dead": "short_link",
    "short_link_network": "short_link",
    "short_link_redirect": "short_link",
    "short_link_redirects": "short_link",
    # A search or another Flights page, or a round trip with one direction chosen.
    "no_flights": "no_flight_chosen",
    "flights_page": "no_flight_chosen",
    "return_missing": "return_not_chosen",
    # What the collector can price.
    "multi_city": "trip_type",
    "open_jaw": "open_jaw",
    "connections": "connections",
    "too_many_legs": "connections",
    "cabin": "cabin",
    "adults": "passengers",
    "children": "passengers",
    "currency": "currency",
    "country": "country",
    "country_unstated": "country_unstated",
    "search_trip": "search_trip",
    "search_passengers": "search_passengers",
    "search_stops": "search_stops",
    "search_cabin": "search_cabin",
    "search_basic": "search_cabin",
    "search_currency": "search_currency",
    "search_country": "country",
    "search_places": "search_places",
    "departed": "departed",
}


class LinkRefused(ValueError):
    """A link Fareflare will not watch. ``str()`` is the sentence people see.

    The check must be in the vocabulary: an unknown one is a programming error and
    raises ``KeyError``, which no surface mistakes for a refusal.
    """

    def __init__(self, check: str):
        self.check = check
        self.reason = CHECKS[check]
        super().__init__(REASONS[self.reason])


DAY = 86400
# Where the admin report lists checks this release no longer makes.
RETIRED = "retired"
_RETIRED_SENTENCE = "Checks an earlier release made, which this one no longer does."
# Refusals are kept long enough to show the admin panel's thirty days.
RETAINED_DAYS = 40
_ATTEMPTS = 3


class RefusalLog:
    """Counts refusals per day by check: a diagnostic, never the link itself."""

    def __init__(self, store: Store, clock: Callable[[], float] = time.time):
        self.store, self.clock = store, clock

    def record(self, check: str) -> None:
        reason = CHECKS[check]
        log.info("Link refused reason=%s check=%s", reason, check)
        now = int(self.clock())
        day = now - now % DAY
        key = f"refusals:{day}"
        for _ in range(_ATTEMPTS):
            document = self.store.get(key) or Document(
                key, "refusals", {"day": day, "checks": {}}, expires_at=day + RETAINED_DAYS * DAY
            )
            checks = dict(document.data["checks"])
            checks[check] = checks.get(check, 0) + 1
            try:
                self.store.commit([document.update({**document.data, "checks": checks})])
                return
            except Conflict:
                continue
        log.warning("Refusal not counted check=%s: the day's record kept changing", check)


def refusal_report(store: Store, now: int, days: int = 30) -> dict:
    """Refusals of the last ``days`` days by reason, each with its checks.

    Counts outlive the code that made them: a check a later release no longer makes
    is listed under its own name as retired, never dropped.
    """
    today = now - now % DAY
    totals: dict[str, int] = {}
    for index in range(days):
        document = store.get(f"refusals:{today - index * DAY}")
        for check, count in (document.data["checks"] if document else {}).items():
            totals[check] = totals.get(check, 0) + count
    reasons: dict[str, dict] = {}
    for check, count in sorted(totals.items(), key=lambda item: (-item[1], item[0])):
        entry = reasons.setdefault(CHECKS.get(check, RETIRED), {"count": 0, "checks": {}})
        entry["count"] += count
        entry["checks"][check] = count
    return {
        "days": days,
        "total": sum(totals.values()),
        "reasons": [
            {"reason": reason, "sentence": REASONS.get(reason, _RETIRED_SENTENCE), **entry}
            for reason, entry in sorted(reasons.items(), key=lambda item: -item[1]["count"])
        ],
    }
