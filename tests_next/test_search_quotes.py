"""Real anonymous route-search evidence; never contact Google in unit tests."""
import base64
import copy
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from fareflare.links import InvalidLink, import_link
from fareflare.public_quotes import PageEvidence, QuoteUnavailable
from fareflare.search_links import SearchMessage, offer_matches_search
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
    message = SearchMessage()
    message.ParseFromString(base64.urlsafe_b64decode(params["tfs"] + "=" * (-len(params["tfs"]) % 4)))
    mutate(message, params)
    params["tfs"] = base64.urlsafe_b64encode(message.SerializeToString()).decode().rstrip("=")
    return "https://www.google.com/travel/flights/search?" + urlencode(params)


def test_search_requires_opt_in_and_preserves_a_distinct_identity(evidence):
    target, search, selected, _ = evidence
    with pytest.raises(InvalidLink, match="Select every flight"):
        import_link(search.url)
    assert target["kind"] == "search" and target["id"] != selected["id"]
    assert target["search"]["max_stops"] == 0
    assert target["segments"][0]["legs"][0]["airline"] is None
    assert import_link(target["url"], allow_search=True) == target
    # Price sorting changes navigation, not the priced set of flights.
    changed = altered_url(search.url, lambda m, p: p.update(tfu="EgYIABAAGAA"))
    assert import_link(changed, allow_search=True)["id"] == target["id"]


@pytest.mark.parametrize("mutate", [
    lambda m, p: m.passengers.append(1),
    lambda m, p: setattr(m, "cabin", 2),
    lambda m, p: setattr(m.segments[0], "max_stops", 1),
    lambda m, p: m.segments[0].ClearField("max_stops"),
    lambda m, p: setattr(m.segments[0].origins[0], "kind", 2),
    lambda m, p: setattr(m.segments[0], "date", "2027-02-30"),
    lambda m, p: p.update(curr="JPY"),
    lambda m, p: p.update(gsas="0"),
    lambda m, p: p.update(tfu="unverifiedopaqueconstraint"),
])
def test_unvalidated_search_variants_are_rejected(evidence, mutate):
    _, search, _, _ = evidence
    with pytest.raises(InvalidLink):
        import_link(altered_url(search.url, mutate), allow_search=True)


def test_unknown_pricing_constraints_are_never_merged_or_lost(evidence):
    target, search, selected, _ = evidence
    params = dict(parse_qsl(urlsplit(search.url).query))
    raw = base64.urlsafe_b64decode(params["tfs"] + "=" * (-len(params["tfs"]) % 4))
    params["tfs"] = base64.urlsafe_b64encode(raw + b"\xa0\x06\x01").decode().rstrip("=")
    changed = import_link("https://www.google.com/travel/flights/search?" + urlencode(params), allow_search=True)
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


@pytest.mark.parametrize("changes", [
    {"sort_label": "Sorted by top flights, Change sort order."},
    {"stops_label": "Stops, Not selected"},
    {"passenger_label": "2 passengers"},
    {"more_results": True},
    {"body": "Loading results"},
])
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
    increased = replace(booking, summary_prices=["192 US dollars"],
                        matching_options=[item.replace("191 US dollars", "192 US dollars") for item in booking.matching_options])
    with pytest.raises(QuoteUnavailable, match="price_disagreement"):
        verified_search_reading(target, search, selected, increased, 1)
