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


@dataclass(frozen=True)
class Money:
    amount_minor: int
    currency: str

    @property
    def exponent(self) -> int:
        # Only currencies with an explicitly supported exponent may be formatted.
        if self.currency == "JPY":
            return 0
        if self.currency in ("USD", "CAD", "EUR", "GBP", "AUD"):
            return 2
        raise ValueError("Unsupported currency exponent")

    def display(self) -> str:
        exponent = self.exponent
        whole, fraction = divmod(self.amount_minor, 10**exponent)
        return f"{self.currency} {whole:,}" + (f".{fraction:02d}" if exponent else "")


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


class PriceProvider(Protocol):
    def collect(self, target: dict) -> Reading: ...


class DeliverySink(Protocol):
    """send must finish within the 60-second delivery lease; use bounded I/O."""

    def send(self, delivery: dict) -> bool: ...


class CollectionFailure(ValueError):
    """Safe, finite error vocabulary. Never expose provider exception strings."""

    BLOCKING = frozenset(
        {"unsupported_itinerary", "consent_required", "login_required", "challenge"}
    )
    CODES = BLOCKING | frozenset(
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

    def __init__(self, code: str):
        self.code = code if code in self.CODES else "collection_failed"
        super().__init__(f"A verified quote is unavailable ({self.code})")

    @property
    def retryable(self) -> bool:
        return self.code not in self.BLOCKING
