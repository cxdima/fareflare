"""Real anonymous route-search evidence; never contact Google in unit tests."""

import base64
import copy
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from fareflare.links import ItineraryMessage, import_link
from fareflare.public_quotes import PageEvidence, QuoteUnavailable
from fareflare.refusals import LinkRefused
from fareflare.search_links import offer_matches_search
from fareflare.search_quotes import (
    SearchPageEvidence,
    verified_search_minimum,
    verified_search_reading,
)

FIXTURE = Path(__file__).parent / "fixtures/search_nonstop_oneway_usd.json"


@pytest.fixture
def evidence():
    data = json.loads(FIXTURE.read_text())
    search, booking = SearchPageEvidence(**data["search"]), PageEvidence(**data["booking"])
    return import_link(search.url, allow_search=True), search, import_link(booking.url), booking


def altered_url(url, mutate):
    params = dict(parse_qsl(urlsplit(url).query))
    message = ItineraryMessage()
    message.ParseFromString(
        base64.urlsafe_b64decode(params["tfs"] + "=" * (-len(params["tfs"]) % 4))
    )
    mutate(message, params)
    params["tfs"] = base64.urlsafe_b64encode(message.SerializeToString()).decode().rstrip("=")
    return "https://www.google.com/travel/flights/search?" + urlencode(params)


def test_search_requires_opt_in_and_preserves_a_distinct_identity(evidence):
    target, search, selected, _ = evidence
    with pytest.raises(LinkRefused) as refused:
        import_link(search.url)
    assert refused.value.check == "no_flights"
    assert target["kind"] == "search" and target["id"] != selected["id"]
    assert target["search"]["max_stops"] == 0
    assert target["segments"][0]["legs"][0]["airline"] is None
    assert import_link(target["url"], allow_search=True) == target
    # How results are shown changes navigation, not the priced set of flights.
    for view in ("EgYIABAAGAA", "EgQIABABIgA", "EgoIAhAAGAAgAigB"):
        changed = altered_url(search.url, lambda m, p, view=view: p.update(tfu=view))
        assert import_link(changed, allow_search=True) == target
    # gsas only marks a link Google built itself: the same search without it is the same.
    without = altered_url(search.url, lambda m, p: p.pop("gsas"))
    assert import_link(without, allow_search=True) == target
    # A parameter of unknown meaning is kept: the same search with it is another target.
    unknown = altered_url(search.url, lambda m, p: p.update(futureFareOption="1"))
    assert import_link(unknown, allow_search=True)["id"] != target["id"]
    # Where the link was made is not part of what was searched.
    shared = altered_url(search.url, lambda m, p: setattr(m, "made_by", 2))
    assert import_link(shared, allow_search=True)["id"] == target["id"]


def test_a_search_reads_the_country_in_either_case(evidence):
    target, search, _, _ = evidence
    lower = altered_url(search.url, lambda m, p: p.update(gl="us"))
    assert import_link(lower, allow_search=True) == target


@pytest.mark.parametrize(
    ("mutate", "check"),
    [
        (lambda m, p: m.passengers.append(1), "search_passengers"),
        (lambda m, p: setattr(m, "cabin", 2), "search_cabin"),
        (lambda m, p: setattr(m.segments[0], "max_stops", 1), "search_stops"),
        (lambda m, p: m.segments[0].ClearField("max_stops"), "search_stops"),
        (lambda m, p: setattr(m.segments[0].origins[0], "kind", 2), "search_places"),
        (lambda m, p: setattr(m.segments[0].destinations[0], "code", "DEN"), "search_places"),
        (lambda m, p: m.segments[0].destinations.add(kind=1, code="DAL"), "search_places"),
        (lambda m, p: setattr(m.segments[0], "date", "2027-02-30"), "date"),
        (lambda m, p: p.update(curr="JPY"), "search_currency"),
        (lambda m, p: p.update(gl="CA"), "search_country"),
        # The reader verifies fares that leave Basic out; no real search link sets this.
        (lambda m, p: m.ClearField("exclude_basic"), "search_basic"),
        (lambda m, p: setattr(m, "exclude_basic", 0), "search_basic"),
    ],
)
def test_a_search_outside_route_search_limits_names_the_limit(evidence, mutate, check):
    _, search, _, _ = evidence
    with pytest.raises(LinkRefused) as refused:
        import_link(altered_url(search.url, mutate), allow_search=True)
    assert refused.value.check == check


def test_unknown_pricing_constraints_are_never_merged_or_lost(evidence):
    target, search, selected, _ = evidence
    params = dict(parse_qsl(urlsplit(search.url).query))
    raw = base64.urlsafe_b64decode(params["tfs"] + "=" * (-len(params["tfs"]) % 4))
    params["tfs"] = base64.urlsafe_b64encode(raw + b"\xa0\x06\x01").decode().rstrip("=")
    changed = import_link(
        "https://www.google.com/travel/flights/search?" + urlencode(params), allow_search=True
    )
    assert changed["id"] != target["id"]
    assert not offer_matches_search(changed, selected)


def test_cheapest_scoped_result_is_verified_against_eligible_booking(evidence):
    target, search, selected, booking = evidence
    reading = verified_search_reading(target, search, selected, booking, 123)
    assert reading.amount_minor == 19100 and reading.fare_name == "Economy Bundle"
    assert reading.target_id == target["id"] and reading.source == "google-flights-public-search"
    assert reading.evidence.adapter_version == "public-search-v1"
    assert reading.observed_offer.target_id == selected["id"]
    assert reading.observed_offer.segments[0].legs[0].airline == "F9"
    assert reading.observed_offer.url == selected["url"]
    # These are real lower distractors in the captured pages, not valid minima.
    assert "$159" in booking.body and "Basic Fare" in booking.body
    assert "$134" in search.body and "Mar 15" in search.body


@pytest.mark.parametrize(
    "changes",
    [
        {"sort_label": "Sorted by top flights, Change sort order."},
        {"stops_label": "Stops, Not selected"},
        {"passenger_label": "2 passengers"},
        {"more_results": True},
        {"body": "Loading results"},
    ],
)
def test_search_context_requires_complete_sorted_filtered_results(evidence, changes):
    target, search, _, _ = evidence
    with pytest.raises(QuoteUnavailable, match="incomplete_trip_context"):
        verified_search_minimum(target, replace(search, **changes))


def test_sort_transition_missing_rows_and_mixed_prices_fail_closed(evidence):
    target, search, _, _ = evidence
    rows = copy.deepcopy(search.rows)
    rows[0], rows[-1] = rows[-1], rows[0]
    with pytest.raises(QuoteUnavailable, match="incomplete_trip_context"):
        verified_search_minimum(target, replace(search, rows=rows))
    with pytest.raises(QuoteUnavailable, match="incomplete_trip_context"):
        verified_search_minimum(target, replace(search, rows=search.rows[:-1]))
    rows = copy.deepcopy(search.rows)
    rows[0]["prices"] = ["134 US dollars"]
    with pytest.raises(QuoteUnavailable, match="price_disagreement"):
        verified_search_minimum(target, replace(search, rows=rows))
    rows = copy.deepcopy(search.rows)
    rows[0]["label"] = rows[0]["label"].replace("March 14", "March 15")
    with pytest.raises(QuoteUnavailable, match="flight_identity_mismatch"):
        verified_search_minimum(target, replace(search, rows=rows))


def test_changed_route_flight_date_currency_or_booking_price_is_not_a_quote(evidence):
    target, search, selected, booking = evidence
    for field, value in (("currency", "JPY"), ("adults", 2)):
        with pytest.raises(QuoteUnavailable, match="itinerary_changed"):
            verified_search_reading(target, search, {**selected, field: value}, booking, 1)
    changed = copy.deepcopy(selected)
    changed["segments"][0]["legs"][0]["date"] = "2027-03-15"
    assert not offer_matches_search(target, changed)
    increased = replace(
        booking,
        summary_prices=["192 US dollars"],
        matching_options=[
            item.replace("191 US dollars", "192 US dollars") for item in booking.matching_options
        ],
    )
    with pytest.raises(QuoteUnavailable, match="price_disagreement"):
        verified_search_reading(target, search, selected, increased, 1)
