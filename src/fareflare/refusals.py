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
    trips,
)
from fareflare.store import Conflict, Document, Store

log = logging.getLogger(__name__)
_AGAIN = "then send the link again."

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
    "return_not_chosen": "Choose your return flight too, " + _AGAIN,
    "trip_type": f"Fareflare watches {trips(FLIGHTS)} only. Search a one-way or round trip, "
    "then send its link.",
    "open_jaw": "Fareflare watches round trips that fly back between the same two airports. "
    "Choose a return between them, " + _AGAIN,
    "connections": "Fareflare watches nonstop flights only. Choose a nonstop flight, then "
    "send its link.",
    "cabin": f"Fareflare watches {cabin(FLIGHTS)} fares only. Choose {cabin(FLIGHTS)} in "
    "Google Flights, " + _AGAIN,
    "passengers": f"Fareflare watches trips for {adults(FLIGHTS)} only. Set the passengers "
    f"to {adults(FLIGHTS)}, " + _AGAIN,
    "currency": f"Fareflare checks prices in {currencies(FLIGHTS)} only. Choose "
    f"{currencies(FLIGHTS)} in Google Flights, " + _AGAIN,
    "country": f"Fareflare checks prices for {country(FLIGHTS)} only. Set the location to "
    f"{country(FLIGHTS)} in Google Flights, " + _AGAIN,
    "country_unstated": "This link doesn't say which country its prices are for. Set the "
    f"location to {country(FLIGHTS)} in Google Flights, " + _AGAIN,
    "search_trip": f"Fareflare watches route searches for {trips(ROUTE_SEARCHES)} only. "
    "Search one way, " + _AGAIN,
    "search_passengers": f"Fareflare watches route searches for {adults(ROUTE_SEARCHES)} "
    f"only. Set the passengers to {adults(ROUTE_SEARCHES)}, " + _AGAIN,
    "search_stops": "Fareflare watches nonstop route searches only. Set Stops to Nonstop in "
    "Google Flights, " + _AGAIN,
    "search_cabin": f"Fareflare watches route searches in {cabin(ROUTE_SEARCHES)} only. "
    f"Choose {cabin(ROUTE_SEARCHES)} in Google Flights, " + _AGAIN,
    "search_currency": f"Fareflare watches route searches in {currencies(ROUTE_SEARCHES)} "
    f"only. Choose {currencies(ROUTE_SEARCHES)} in Google Flights, " + _AGAIN,
    "search_places": "Fareflare watches route searches between two airports only. Search "
    "from one airport to another, " + _AGAIN,
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
    """Refusals of the last ``days`` days by reason, each with its checks."""
    today = now - now % DAY
    totals: dict[str, int] = {}
    for index in range(days):
        document = store.get(f"refusals:{today - index * DAY}")
        for check, count in (document.data["checks"] if document else {}).items():
            totals[check] = totals.get(check, 0) + count
    reasons: dict[str, dict] = {}
    for check, count in sorted(totals.items(), key=lambda item: (-item[1], item[0])):
        entry = reasons.setdefault(CHECKS[check], {"count": 0, "checks": {}})
        entry["count"] += count
        entry["checks"][check] = count
    return {
        "days": days,
        "total": sum(totals.values()),
        "reasons": [
            {"reason": reason, "sentence": REASONS[reason], **entry}
            for reason, entry in sorted(reasons.items(), key=lambda item: -item[1]["count"])
        ],
    }
