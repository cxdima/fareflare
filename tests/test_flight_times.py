"""Departure and arrival times: read from the page, validated, stored and displayed."""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from fareflare.contracts import QuoteEvidence, Reading, SliceTimes
from fareflare.links import import_link
from fareflare.message_templates import plain_text
from fareflare.preferences import Preferences, clock_time
from fareflare.public_quotes import PageEvidence, slice_times, verified_reading
from fareflare.telegram_messages import (
    alert_message,
    flight_list,
    monitor_times,
    preview_message,
    recorded_times,
    schedule_lines,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = 1793952000  # 2026-11-06 08:00 UTC
TODAY = date(2026, 11, 6)
EVIDENCE = QuoteEvidence("test", True, True, True, 1)
OUTBOUND = SliceTimes("15:50", "18:54", 0, 124)


def page(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["page"]


def reading(target, times, observed_at):
    return Reading(
        target["id"],
        24600,
        "USD",
        observed_at,
        "test",
        fare_name="Economy",
        price_basis="total",
        evidence=EVIDENCE,
        schedule=times,
    )


def delivery(flight_url, schedule, segments=None):
    itinerary = {**import_link(flight_url), "adults": 1}
    if segments is not None:
        itinerary["segments"] = segments
    return {
        "id": "f" * 32,
        "tenant": "alice",
        "reason": "new_low",
        "previous": {"price_minor": 25900, "low_minor": 25400},
        "observation": {
            "amount_minor": 24600,
            "currency": "USD",
            "observed_at": NOW,
            "fare_name": "Economy",
            "price_basis": "total",
            "schedule": schedule,
        },
        "itinerary": itinerary,
    }


def round_trip(flight_url):
    outbound = import_link(flight_url)["segments"][0]
    leg = outbound["legs"][0]
    back = {
        "date": "2027-03-21",
        "legs": [{**leg, "origin": leg["destination"], "destination": leg["origin"]}],
    }
    return [outbound, back]


# --- Reading the page -------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["public_booking_usd", "selected_jpy", "selected_two_adults", "selected_roundtrip"]
)
def test_captured_pages_yield_times_for_every_direction(name):
    evidence = PageEvidence(**page(name))
    target = import_link(evidence.url)
    result = verified_reading(target, evidence, NOW)
    assert result.schedule is not None and len(result.schedule) == len(target["segments"])
    assert result.schedule[0] == OUTBOUND
    if len(target["segments"]) == 2:
        assert result.schedule[1] == SliceTimes("11:20", "12:38", 0, 138)


@pytest.mark.parametrize(
    "text, expected",
    [
        # Midnight and noon are the two places a 12-hour clock is easy to get wrong.
        (
            "12:05 AMDenver (DEN) Travel time: 45 min 12:50 AMColorado Springs (COS)",
            SliceTimes("00:05", "00:50", 0, 45),
        ),
        (
            "12:30 PMDenver (DEN) Travel time: 3 hr 1:30 PMColorado Springs (COS)",
            SliceTimes("12:30", "13:30", 0, 180),
        ),
        # An overnight arrival is marked with the number of days later.
        (
            "11:59 PMDenver (DEN) Travel time: 5 hr 11 min 5:10 AM+1Colorado Springs (COS)",
            SliceTimes("23:59", "05:10", 1, 311),
        ),
        ("9:00 AMDenver (DEN) 10:15 AM +2 Colorado Springs (COS)", SliceTimes("09:00", "10:15", 2)),
        # Narrow no-break spaces, as Chrome renders them.
        (
            "3:50 PMDenver\xa0(DEN)\nTravel time: 2 hr 4 min\n6:54 PMSprings\xa0(COS)",
            SliceTimes("15:50", "18:54", 0, 124),
        ),
    ],
)
def test_clock_times_are_read_exactly(text, expected):
    assert slice_times(text, "DEN", "COS") == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "3:50 PMDenver (DEN) Travel time: 2 hr 6:54 PMElsewhere (ABQ)",  # A different airport.
        "Denver (DEN) Travel time: 2 hr 6:54 PMColorado Springs (COS)",  # No departure time.
        "3:50 PMDenver (DEN) Travel time: 2 hr Colorado Springs (COS)",  # No arrival time.
        "1:00 PM 3:50 PMDenver (DEN) 6:54 PMColorado Springs (COS)",  # Two candidate departures.
        "3:50 PMDenver (DEN) 5:00 PM 6:54 PMColorado Springs (COS)",  # Two candidate arrivals.
        "3:50 PM+1Denver (DEN) 6:54 PMColorado Springs (COS)",  # A departure cannot be a day later.
        "13:50 PMDenver (DEN) 6:54 PMColorado Springs (COS)",  # Not a 12-hour time.
        "3:75 PMDenver (DEN) 6:54 PMColorado Springs (COS)",
        "6:54 PMColorado Springs (COS) 3:50 PMDenver (DEN)",  # Airports in the wrong order.
    ],
)
def test_anything_ambiguous_is_reported_as_unknown_rather_than_guessed(text):
    assert slice_times(text, "DEN", "COS") is None


def test_an_implausible_travel_time_is_dropped_but_the_clock_times_kept():
    text = "3:50 PMDenver (DEN) Travel time: 99 hr 6:54 PMColorado Springs (COS)"
    assert slice_times(text, "DEN", "COS") == SliceTimes("15:50", "18:54")


def test_times_never_decide_whether_a_price_is_accepted():
    data = page("selected_roundtrip")
    # Remove the return direction's arrival time: the price is still verified,
    # and no half-known schedule is recorded.
    data["selected_text"] = data["selected_text"].replace("12:38", "")
    evidence = PageEvidence(**data)
    result = verified_reading(import_link(evidence.url), evidence, NOW)
    assert result.amount_minor == 57700 and result.schedule is None


# --- Recording --------------------------------------------------------------


def test_recorded_times_reach_the_monitor_the_alert_and_the_history(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "times-one")
    service.record(reading(monitor["target"], (OUTBOUND,), clock[0]), "run-1")
    service.process_events()
    stored = {
        "departs": "15:50",
        "arrives": "18:54",
        "arrival_day_offset": 0,
        "duration_minutes": 124,
    }
    assert service.get_monitor("alice", monitor["id"])["latest"]["schedule"] == [stored]
    assert service.history("alice", monitor["id"])[0]["schedule"] == [stored]
    assert service.list_deliveries("alice")[0]["observation"]["schedule"] == [stored]


def test_a_price_without_times_is_still_recorded(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "times-two")
    assert service.record(reading(monitor["target"], None, clock[0]), "run-1")
    assert service.get_monitor("alice", monitor["id"])["latest"]["schedule"] is None


@pytest.mark.parametrize(
    "times",
    [
        (),
        (OUTBOUND, OUTBOUND),  # One direction was booked.
        [OUTBOUND],
        ({"departs": "15:50", "arrives": "18:54"},),
        (replace(OUTBOUND, departs="24:00"),),
        (replace(OUTBOUND, arrives="6:54"),),
        (replace(OUTBOUND, arrives="18:54\n"),),
        (replace(OUTBOUND, arrival_day_offset=4),),
        (replace(OUTBOUND, arrival_day_offset=True),),
        (replace(OUTBOUND, duration_minutes=0),),
        (replace(OUTBOUND, duration_minutes=1441),),
    ],
)
def test_a_malformed_schedule_is_rejected_before_anything_is_stored(
    service, flight_url, clock, times
):
    monitor = service.create_monitor("alice", flight_url, "times-bad")
    with pytest.raises(ValueError, match="schedule"):
        service.record(reading(monitor["target"], times, clock[0]), "run-1")
    assert service.get_monitor("alice", monitor["id"])["latest"] is None


# --- Showing ----------------------------------------------------------------

STORED = [
    {"departs": "15:50", "arrives": "18:54", "arrival_day_offset": 0, "duration_minutes": 124}
]
RETURN = {"departs": "23:20", "arrives": "00:38", "arrival_day_offset": 1, "duration_minutes": 138}


def test_clock_style_follows_the_account():
    assert clock_time("15:50", Preferences()) == "3:50 PM"
    assert clock_time("00:05", Preferences()) == "12:05 AM"
    assert clock_time("12:00", Preferences()) == "12:00 PM"
    assert clock_time("15:50", Preferences(hour_cycle="h23")) == "15:50"
    assert clock_time("00:05", Preferences(locale="de-DE")) == "00:05"
    assert clock_time("15:50", Preferences(locale="de-DE", hour_cycle="h12")) == "3:50 PM"


def test_an_alert_gives_the_times_their_own_line_in_the_account_clock_style(flight_url):
    event = delivery(flight_url, STORED)
    assert alert_message(event, Preferences(hour_cycle="h23")).text.split("\n")[1:] == [
        "DEN → DFW · Mar 14 · UA 414",
        "15:50 → 18:54",
    ]
    assert alert_message(event, Preferences()).text.split("\n")[2] == "3:50 PM → 6:54 PM"
    detailed = alert_message(event, Preferences(telegram_style="detailed")).text
    assert detailed.split("\n")[2] == "3:50 PM → 6:54 PM · 2 hr 4 min"


def test_a_round_trip_shows_the_return_times_on_their_own_line(flight_url):
    event = delivery(flight_url, [STORED[0], RETURN], round_trip(flight_url))
    compact = alert_message(event, Preferences(hour_cycle="h23")).text
    assert compact.split("\n")[1:] == [
        "DEN ⇄ DFW · Mar 14 – Mar 21 · UA 414, UA 414",
        "15:50 → 18:54",
        "↩ 23:20 → 00:38 +1",
    ]
    detailed = alert_message(event, Preferences(telegram_style="detailed")).text
    assert "\n3:50 PM → 6:54 PM · 2 hr 4 min\n↩ 11:20 PM → 12:38 AM +1 · 2 hr 18 min\n" in detailed


def test_a_return_whose_times_are_unknown_leaves_no_stray_separator(flight_url):
    # Only the outbound direction was read, so the schedule does not fit the trip.
    event = delivery(flight_url, STORED, round_trip(flight_url))
    for style in ("compact", "detailed"):
        text = alert_message(event, Preferences(telegram_style=style)).text
        assert "↩" not in text and " · \n" not in text and "\n · " not in text
        assert all(line.strip(" ·") == line for line in text.split("\n"))


def test_times_can_be_switched_off_for_built_in_styles_but_a_template_decides_for_itself(
    flight_url,
):
    event = delivery(flight_url, STORED)
    for style in ("detailed", "compact"):
        hidden = Preferences(telegram_style=style, telegram_show_times=False)
        text = alert_message(event, hidden).text
        assert "3:50" not in text and "2 hr 4 min" not in text
    custom = Preferences(
        telegram_style="custom",
        telegram_show_times=False,
        telegram_templates={
            "new_low": "{price_short} {depart_time}-{arrive_time} ({duration})[ back {return_times}]"
        },
    )
    assert alert_message(event, custom).text == "$246 3:50 PM-6:54 PM (2 hr 4 min)"


@pytest.mark.parametrize(
    "schedule",
    [
        None,
        [],
        "15:50",
        [STORED[0], STORED[0]],  # More directions than the itinerary has.
        [{"departs": "15:50"}],
        [{"departs": "15:50", "arrives": "25:00"}],
        [{"departs": 1550, "arrives": 1854}],
        ["15:50 → 18:54"],
    ],
)
def test_stored_times_that_do_not_fit_are_ignored_rather_than_shown(flight_url, schedule):
    event = delivery(flight_url, schedule)
    for style in ("detailed", "compact"):
        text = alert_message(event, Preferences(telegram_style=style)).text
        assert "→ 6:54" not in text and "→ 25" not in text and "3:50" not in text
        assert "DEN → DFW · Mar 14 · UA 414" in text
    assert recorded_times(schedule, event["itinerary"]["segments"]) == []


def test_odd_stored_details_degrade_one_at_a_time(flight_url):
    event = delivery(
        flight_url,
        [
            {
                "departs": "15:50",
                "arrives": "18:54",
                "arrival_day_offset": 9,
                "duration_minutes": "x",
            }
        ],
    )
    assert schedule_lines(event["observation"]["schedule"], Preferences()) == ["3:50 PM → 6:54 PM"]


def flight(number, departs, amount=26900, low=21900, segments=None):
    segments = segments or [
        {
            "date": "2027-03-14",
            "legs": [{"origin": "DEN", "destination": "DFW", "airline": "UA", "number": number}],
        }
    ]
    schedule = [{"departs": departs, "arrives": "18:54", "duration_minutes": 124}]
    if len(segments) == 2:
        schedule.append(RETURN)
    return {
        "status": "active",
        "stale": False,
        "collection_status": "ready",
        "rule_state": {"low_minor": low},
        "latest": {
            "amount_minor": amount,
            "currency": "USD",
            "observed_at": NOW,
            "schedule": schedule,
        },
        "target": {"adults": 1, "currency": "USD", "segments": segments},
    }


def listed(monitors, prefs):
    return plain_text(flight_list(monitors, prefs, TODAY)[0]).split("\n")


def test_the_compact_flight_list_shows_times_and_a_return_line(flight_url):
    monitors = [flight("414", "15:50"), flight("900", "07:05", segments=round_trip(flight_url))]
    assert listed(monitors, Preferences(hour_cycle="h23")) == [
        "🛫 DEN → DFW · Mar 14",
        "• UA 414 15:50→18:54 · $269 (low $219)",
        "",
        "🛫 DEN ⇄ DFW · Mar 14 – Mar 21",
        "• UA 414, UA 414 07:05→18:54 · $269 (low $219)",
        "   ↩ 23:20→00:38 +1",
    ]
    # A 12-hour clock names AM or PM once when both ends of a flight share it.
    assert listed(monitors[:1], Preferences())[1] == "• UA 414 3:50→6:54 PM · $269 (low $219)"


def test_the_detailed_flight_list_shows_times_and_a_return_line(flight_url):
    monitors = [flight("900", "07:05", segments=round_trip(flight_url))]
    assert listed(monitors, Preferences(telegram_style="detailed")) == [
        "DEN ⇄ DFW · Mar 14 – Mar 21",
        "UA 414, UA 414 · 7:05 AM → 6:54 PM · $269",
        "↩ 11:20 PM → 12:38 AM +1",
        "Lowest $219",
    ]


def test_a_list_always_shows_what_tells_its_flights_apart():
    # The choices under "Include in alerts" are about alerts.
    alerts_only = Preferences(telegram_show_times=False, telegram_show_flight_numbers=False)
    assert listed([flight("414", "15:50")], alerts_only)[1] == (
        "• UA 414 3:50→6:54 PM · $269 (low $219)"
    )


def test_times_follow_the_offer_actually_priced_by_a_route_search(flight_url):
    monitor = flight("414", "15:50")
    monitor["target"]["segments"] = round_trip(flight_url)
    # The stored schedule describes one direction; the target now has two.
    assert monitor_times(monitor) == []
    monitor["latest"]["observed_offer"] = {"segments": round_trip(flight_url)[:1]}
    assert [item["departs"] for item in monitor_times(monitor)] == ["15:50"]


@pytest.mark.parametrize(
    "kind, style, shown",
    [
        ("new_low", "compact", "15:50 → 18:54"),
        ("new_low", "detailed", "15:50 → 18:54 · 2 hr 4 min"),
        ("flight_list", "compact", "UA 414 15:50→18:54"),
        ("flight_list", "detailed", "UA 414 · 15:50 → 18:54"),
    ],
)
def test_previews_include_times_so_the_editor_shows_what_they_look_like(kind, style, shown):
    prefs = Preferences(telegram_style=style, hour_cycle="h23")
    assert shown in preview_message(kind, prefs, None, NOW).message.text
