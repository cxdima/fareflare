"""What Fareflare can watch, as one table.

The checks that refuse a link, the sentence that says why, and the copy that tells
people what is supported are all written from these values, so they cannot drift.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from fareflare.contracts import CURRENCIES

# Google's codes for a cabin, a trip type and an adult traveler.
ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST = 1, 2, 3, 4
CABINS = {
    ECONOMY: "Economy",
    PREMIUM_ECONOMY: "Premium economy",
    BUSINESS: "Business",
    FIRST: "First",
}
ROUND_TRIP, ONE_WAY, MULTI_CITY = 1, 2, 3
# How many directions each trip type has.
DIRECTIONS = {ONE_WAY: 1, ROUND_TRIP: 2}
ADULT = 1

COUNTRIES = {"US": "the United States"}


@dataclass(frozen=True)
class Limits:
    """One kind of link: what its trip, cabin, travelers and prices may be."""

    name: str
    trips: tuple[int, ...]
    adults: int  # The most adults; children and infants are not supported.
    currencies: tuple[str, ...]
    cabin: int = ECONOMY
    country: str = "US"
    nonstop: bool = True
    # Route searches name two airports and compare the fares that leave Basic out.
    exact_airports: bool = False
    exclude_basic: bool = False

    @property
    def directions(self) -> frozenset[int]:
        """How many directions a link of this kind may have."""
        return frozenset(DIRECTIONS[trip] for trip in self.trips)


FLIGHTS = Limits("Chosen flights", (ONE_WAY, ROUND_TRIP), adults=2, currencies=("USD", "JPY"))
ROUTE_SEARCHES = Limits(
    "Route searches",
    (ONE_WAY,),
    adults=1,
    currencies=("USD",),
    exact_airports=True,
    exclude_basic=True,
)


def either(words: Iterable[str]) -> str:
    """``A``, ``A or B``, ``A, B or C``."""
    items = list(words)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def adults(limits: Limits) -> str:
    return either(str(count) for count in range(1, limits.adults + 1)) + (
        " adult" if limits.adults == 1 else " adults"
    )


def currencies(limits: Limits) -> str:
    return either(CURRENCIES[code].name for code in limits.currencies)


def country(limits: Limits) -> str:
    return COUNTRIES[limits.country]


def cabin(limits: Limits) -> str:
    return CABINS[limits.cabin] + (" (exclude Basic)" if limits.exclude_basic else "")


def stops(limits: Limits) -> str:
    return "nonstop" if limits.nonstop else "with any number of stops"


def trips(limits: Limits) -> str:
    return " and ".join(
        {ONE_WAY: "one-way", ROUND_TRIP: "round"}[trip] for trip in limits.trips
    ) + (" trips")


def supported(limits: Limits) -> str:
    """The one description the guide, the dashboard and the docs use for each kind."""
    airports = " between two airports on one date" if limits.exact_airports else ""
    sentence = (
        f"{limits.name}: {stops(limits)} {trips(limits)}{airports}, in {cabin(limits)}, for "
        f"{adults(limits)}, with prices for {country(limits)} in {currencies(limits)}."
    )
    if not limits.exact_airports:
        sentence += " Search by airport, city or several airports, in any language."
    if ROUND_TRIP in limits.trips:
        sentence += " For a round trip, choose both flights before copying the link."
    return sentence
