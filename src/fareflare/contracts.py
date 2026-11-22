"""Provider-independent price and offer contracts; no browser or AWS imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FlightLeg:
    origin: str
    destination: str
    date: str  # Airport-local departure date, never inferred from UTC.
    airline: str  # Marketing carrier; operating carrier is not interchangeable.
    number: str


@dataclass(frozen=True)
class JourneySlice:
    date: str
    legs: tuple[FlightLeg, ...]


@dataclass(frozen=True)
class Offer:
    slices: tuple[JourneySlice, ...]
    adults: int
    cabin: int
    currency: str
    market: str
    constraints_digest: str  # Includes unknown provider pricing constraints.


#: Every currency an amount may be written in: its minor-unit digits and its symbol.
CURRENCIES: dict[str, tuple[int, str]] = {
    "USD": (2, "$"),
    "CAD": (2, "CA$"),
    "EUR": (2, "€"),
    "GBP": (2, "£"),
    "AUD": (2, "A$"),
    "JPY": (0, "¥"),
}


@dataclass(frozen=True)
class Money:
    amount_minor: int
    currency: str

    @property
    def exponent(self) -> int:
        """Digits after the decimal point. Only a listed currency may be formatted."""
        return self._currency[0]

    @property
    def symbol(self) -> str:
        return self._currency[1]

    @property
    def _currency(self) -> tuple[int, str]:
        try:
            return CURRENCIES[self.currency]
        except KeyError:
            raise ValueError("Unsupported currency") from None

    def display(self) -> str:
        exponent = self.exponent
        whole, fraction = divmod(self.amount_minor, 10**exponent)
        return f"{self.currency} {whole:,}" + (f".{fraction:0{exponent}d}" if exponent else "")


@dataclass(frozen=True)
class QuoteEvidence:
    adapter_version: str
    identity_verified: bool
    eligibility_verified: bool
    party_verified: bool
    display_precision_minor: int


@dataclass(frozen=True)
class ObservedOffer:
    """The actual selected itinerary behind a route-search price observation."""

    target_id: str
    segments: tuple[JourneySlice, ...]
    adults: int
    cabin: int
    url: str


@dataclass(frozen=True)
class SliceTimes:
    """Clock times for one direction of travel, as the provider displays them.

    Times are airport-local and carry no zone: ``departs`` is at the origin and
    ``arrives`` at the destination, so the two are not directly comparable.
    """

    departs: str  # HH:MM, 24-hour
    arrives: str  # HH:MM, 24-hour
    arrival_day_offset: int = 0  # Calendar days after the departure date.
    duration_minutes: int | None = None


@dataclass(frozen=True)
class Reading:
    target_id: str
    amount_minor: int
    currency: str
    observed_at: int
    source: str
    fare_name: str | None = None
    price_basis: str = "unspecified"
    evidence: QuoteEvidence | None = None
    observed_offer: ObservedOffer | None = None
    # One entry per direction of the priced itinerary, or None when not verified.
    schedule: tuple[SliceTimes, ...] | None = None


class PriceProvider(Protocol):
    def collect(self, target: dict) -> Reading: ...


class DeliverySink(Protocol):
    """send must finish within the 60-second delivery lease; use bounded I/O."""

    def send(self, delivery: dict) -> bool: ...


class CollectionFailure(ValueError):
    """Safe, finite error vocabulary. Never expose provider exception strings."""

    # Only an itinerary the collector cannot read stops its checks until someone
    # chooses Retry collection: checking again cannot change that answer.
    BLOCKING = frozenset({"unsupported_itinerary"})
    # Google turned the anonymous browser away: its robot check, its error page (the
    # booking options answered with an internal error while a normal browser gets
    # fares), a consent page or a sign-in page. Nobody can clear these for the worker's
    # browser and they pass by themselves, so they are retried like any failure, only
    # after a longer wait.
    REFUSED = frozenset({"challenge", "provider_error", "consent_required", "login_required"})
    CODES = (
        BLOCKING
        | REFUSED
        | frozenset(
            {
                "unexpected_page",
                "itinerary_changed",
                "incomplete_trip_context",
                "flight_identity_mismatch",
                "ambiguous_fare",
                "unrecognized_price",
                "unrecognized_fare",
                "price_disagreement",
                "timeout",
                "browser_start_failed",
                "browser_failed",
                "collection_failed",
            }
        )
    )

    def __init__(self, code: str):
        self.code = code if code in self.CODES else "collection_failed"
        super().__init__(f"A verified quote is unavailable ({self.code})")

    @property
    def retryable(self) -> bool:
        return self.code not in self.BLOCKING
