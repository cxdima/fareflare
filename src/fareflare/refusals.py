"""Why Fareflare will not watch a link: one finite vocabulary for every surface.

The Telegram bot, the dashboard and API, MCP and the command line show the same
sentence for the same reason. The finer check names exactly what was wrong: it is
shown only to accounts with diagnostics on, and the admin panel counts refusals by
it. Neither ever carries the link.
"""

from __future__ import annotations

import logging

from fareflare.store import Conflict, Document, Store

log = logging.getLogger(__name__)

# One sentence per reason: what Fareflare cannot do, and what to do instead.
REASONS: dict[str, str] = {
    "not_flights": "This isn't a Google Flights link. Open your flight in Google Flights "
    "and send its link.",
    "incomplete": "This Google Flights link is incomplete. Copy it again from the address bar "
    "and send the whole link.",
    "old_link": "This is an old Google Flights link. Open it, then send the link Google Flights "
    "shows.",
    "short_link": "This short link didn't open. Open it, then send the full Google Flights link.",
    "no_flight_chosen": "This link doesn't name a flight. Choose your flights in Google "
    "Flights, then send the link.",
    "return_not_chosen": "Choose your return flight too, then send the link again.",
    "trip_type": "Fareflare watches one-way and round trips only for now. Search one of those "
    "and send its link.",
    "connections": "Fareflare watches nonstop flights only for now. Choose a nonstop flight "
    "and send its link.",
    "cabin": "Fareflare watches Economy fares only for now. Choose Economy and send the link "
    "again.",
    "passengers": "Fareflare watches trips for one or two adults only for now. Change the "
    "passengers and send the link again.",
    "currency": "Fareflare checks prices in US dollars or Japanese yen only for now. Change "
    "the currency and send the link again.",
    "country": "Fareflare checks prices for the United States only for now. Set the location "
    "to the United States and send the link again.",
    "route_search": "Fareflare watches route searches only for one adult, one way and nonstop, "
    "in Economy, between two airports, in US dollars. Change the search and send the link "
    "again.",
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
    "old_format": "old_link",
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
    # A shared short link that did not lead to a Flights page.
    "shared_link": "short_link",
    "short_link_unreachable": "short_link",
    "short_link_redirect": "short_link",
    "short_link_redirects": "short_link",
    # A search or another Flights page, or a round trip with one direction chosen.
    "no_flights": "no_flight_chosen",
    "flights_page": "no_flight_chosen",
    "return_missing": "return_not_chosen",
    # What the collector can price.
    "multi_city": "trip_type",
    "open_jaw": "trip_type",
    "connections": "connections",
    "too_many_legs": "connections",
    "cabin": "cabin",
    "adults": "passengers",
    "children": "passengers",
    "currency": "currency",
    "country": "country",
    "search_shape": "route_search",
    "search_passengers": "route_search",
    "search_cabin": "route_search",
    "search_currency": "route_search",
    "search_country": "route_search",
    "search_stops": "route_search",
    "search_places": "route_search",
    "departed": "departed",
}


class LinkRefused(ValueError):
    """A link Fareflare will not watch. ``str()`` is the sentence people see."""

    def __init__(self, check: str):
        self.check = check
        self.reason = CHECKS[check]
        super().__init__(REASONS[self.reason])


DAY = 86400
# Refusals are kept long enough to show the admin panel's thirty days.
RETAINED_DAYS = 40
_ATTEMPTS = 3


def record_refusal(store: Store, now: int, check: str) -> None:
    """Count one refusal on its day. A diagnostic only: it never fails the request."""
    log.info("Link refused reason=%s check=%s", CHECKS[check], check)
    day = now - now % DAY
    key = f"refusals:{day}"
    for _ in range(_ATTEMPTS):
        document = store.get(key) or Document(
            key, "refusals", {"day": day, "checks": {}}, expires_at=day + RETAINED_DAYS * DAY
        )
        checks = dict(document.data["checks"])
        checks[check] = checks.get(check, 0) + 1
        try:
            store.commit([document.update({**document.data, "checks": checks})])
            return
        except Conflict:
            continue


def refusal_report(store: Store, now: int, days: int = 30) -> dict:
    """Refusals of the last ``days`` days by reason, each with its checks."""
    today = now - now % DAY
    totals: dict[str, int] = {}
    for index in range(days):
        document = store.get(f"refusals:{today - index * DAY}")
        for check, count in (document.data["checks"] if document else {}).items():
            # A day recorded by an older release can name a check that was renamed.
            if check in CHECKS:
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
