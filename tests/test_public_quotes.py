import json
from dataclasses import replace
from pathlib import Path

import pytest

from fareflare.links import import_link
from fareflare.public_quotes import (
    PageEvidence,
    QuoteUnavailable,
    supported_target,
    verified_reading,
)


@pytest.fixture
def evidence():
    path = Path(__file__).parent / "fixtures/public_booking_usd.json"
    return PageEvidence(**json.loads(path.read_text())["page"])


def test_real_page_uses_matching_economy_not_cheaper_basic(evidence):
    assert "$292" in evidence.body
    reading = verified_reading(import_link(evidence.url), evidence, 1793653200)
    assert reading.amount_minor == 30900
    assert reading.fare_name == "Economy"
    assert reading.price_basis == "total"
    assert reading.currency == "USD"
    assert reading.observed_at == 1793653200


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("summary_prices", [], "ambiguous_fare"),
        ("summary_prices", ["309 US dollars", "292 US dollars"], "ambiguous_fare"),
        ("matching_options", [], "ambiguous_fare"),
        (
            "matching_options",
            ["Continue to book with United, Basic Economy for 292 US dollars"],
            "price_disagreement",
        ),
        ("matching_options", ["Continue anyway"], "unrecognized_fare"),
        ("flight_numbers", ["UA 415"], "flight_identity_mismatch"),
        ("flight_numbers", ["UA 414", "AA 414"], "flight_identity_mismatch"),
        ("flight_numbers", [], "flight_identity_mismatch"),
        ("departure_dates", ["2027-03-15"], "flight_identity_mismatch"),
        ("selected_text", "Economy UA 414 (DFW) (DEN)", "flight_identity_mismatch"),
        ("selected_text", "Economy UA 414 (DEN) (ORD) (DFW)", "flight_identity_mismatch"),
        ("selected_text", "First UA 414 (DEN) (DFW)", "incomplete_trip_context"),
        ("body", "Getting prices", "incomplete_trip_context"),
        ("url", "https://accounts.google.com/", "unexpected_page"),
    ],
)
def test_incomplete_or_mismatched_evidence_never_yields_a_price(evidence, field, value, code):
    with pytest.raises(QuoteUnavailable, match=code):
        verified_reading(import_link(evidence.url), replace(evidence, **{field: value}), 1793653200)


@pytest.mark.parametrize(
    "label",
    [
        "$309",
        "309 Canadian dollars",
        "309.1 US dollars",
        "0 US dollars",
        "-309 US dollars",
        "1,00 US dollars",
        "1,000,001 US dollars",
    ],
)
def test_rejects_ambiguous_currency_or_invalid_money(evidence, label):
    with pytest.raises(QuoteUnavailable, match="unrecognized_price"):
        verified_reading(import_link(evidence.url), replace(evidence, summary_prices=[label]), 1)


def test_decimal_price_uses_integer_minor_units(evidence):
    page = replace(
        evidence,
        summary_prices=["1,234.56 US dollars"],
        matching_options=["Continue to book with United, Economy for 1,234.56 US dollars"],
    )
    assert verified_reading(import_link(page.url), page, 1).amount_minor == 123456


def test_query_change_and_duplicate_eligible_fares_fail_closed(evidence):
    target = import_link(evidence.url)
    with pytest.raises(QuoteUnavailable, match="itinerary_changed"):
        verified_reading(target, replace(evidence, url=evidence.url + "&other=constraint"), 1)
    with pytest.raises(QuoteUnavailable, match="ambiguous_fare"):
        verified_reading(
            target, replace(evidence, matching_options=evidence.matching_options * 2), 1
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("adults", 3),
        ("cabin", 2),
        ("currency", "CAD"),
        ("market", "CA"),
        ("segments", []),
        ("provider_query", {"hl": "fr"}),
    ],
)
def test_unvalidated_itineraries_are_explicitly_unsupported(evidence, field, value):
    with pytest.raises(QuoteUnavailable, match="unsupported_itinerary"):
        supported_target({**import_link(evidence.url), field: value})


def test_captured_price_flows_through_durable_monitoring(service, clock, evidence):
    monitor = service.create_monitor("traveler", evidence.url, "public-quote")
    reading = verified_reading(monitor["target"], evidence, clock[0])
    assert service.record(reading, "public-test")
    assert service.process_events() == 1
    latest = service.get_monitor("traveler", monitor["id"])["latest"]
    assert latest["fare_name"] == "Economy"
    assert latest["amount_minor"] == 30900
    assert service.list_deliveries("traveler")[0]["observation"]["price_basis"] == "total"


@pytest.mark.parametrize(
    "fixture,amount,currency,precision",
    [
        ("selected_two_adults", 61700, "USD", 100),
        ("selected_jpy", 48883, "JPY", 1),
    ],
)
def test_captured_party_total_and_currency_are_not_inferred_from_unit_fare(
    fixture, amount, currency, precision
):
    page = PageEvidence(
        **json.loads((Path(__file__).parent / f"fixtures/{fixture}.json").read_text())["page"]
    )
    reading = verified_reading(import_link(page.url), page, 1793826000)
    assert reading.amount_minor == amount
    assert reading.currency == currency
    assert reading.evidence.display_precision_minor == precision
    # Converted display price must not be confused with a USD booking price on the same page.
    if currency == "JPY":
        assert "$309" in page.body
        with pytest.raises(QuoteUnavailable, match="unrecognized_price"):
            verified_reading(
                import_link(page.url), replace(page, summary_prices=["309 US dollars"]), 1
            )


def test_roundtrip_verifies_each_selected_direction_and_total():
    page = PageEvidence(
        **json.loads((Path(__file__).parent / "fixtures/selected_roundtrip.json").read_text())[
            "page"
        ]
    )
    target = import_link(page.url)
    reading = verified_reading(target, page, 1793826000)
    assert reading.amount_minor == 57700
    assert reading.price_basis == "total"
    for text in (
        page.selected_text.replace("Mar 21", "Mar 22"),
        page.selected_text.replace("2049", "2050"),
        page.selected_text.replace("Returning flight", "Other flight"),
    ):
        with pytest.raises(QuoteUnavailable):
            verified_reading(target, replace(page, selected_text=text), 1)
