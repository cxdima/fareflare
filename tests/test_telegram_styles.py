"""Message styles: built-in presets, account templates and the values they can show."""

from datetime import date
from html.parser import HTMLParser
from typing import get_args

import pytest
from pydantic import ValidationError

from fareflare.links import import_link
from fareflare.message_templates import TemplateError, parse_template, plain_text, telegram_html
from fareflare.preferences import (
    Preferences,
    clock_range,
    merge_preferences,
    short_date,
    short_dates,
    short_price,
    stored_preferences,
)
from fareflare.telegram_messages import (
    LATE_SECONDS,
    PREVIEWS,
    PreviewSample,
    alert_message,
    collection_notice,
    flight_list,
    ordered_flights,
    preview_choices,
    preview_message,
)
from fareflare.telegram_templates import (
    ALERT_KEYS,
    DEFAULT_STYLE,
    PRESETS,
    STYLES,
    SWITCHES,
    TEMPLATE_KEYS,
    VOCABULARY,
    style_switches,
    template_catalog,
    template_hints,
    templates_for,
    validate_templates,
)

NOW = 1793952000  # 2026-11-06 08:00 UTC
TODAY = date(2026, 11, 6)
COMPACT = Preferences()
DETAILED = Preferences(telegram_style="detailed")


class Markup(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.stack, self.tags, self.links = [], [], []
        self.feed(value)
        self.close()
        assert not self.stack

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        self.tags.append(tag)
        self.links += [value for name, value in attrs if name == "href"]

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag


def alert(flight_url, reason="new_low", amount=24600, previous=(25900, 25400), **observation):
    return {
        "id": "f" * 32,
        "tenant": "alice",
        "reason": reason,
        "previous": {"price_minor": previous[0], "low_minor": previous[1]},
        "observation": {
            "amount_minor": amount,
            "currency": "USD",
            "observed_at": NOW,
            "fare_name": "Economy",
            "price_basis": "total",
            **observation,
        },
        "itinerary": {**import_link(flight_url), "adults": 1},
    }


def monitor(
    number,
    amount,
    low,
    status="active",
    origin="DEN",
    destination="DFW",
    latest_schedule=None,
    **extra,
):
    latest = {"amount_minor": amount, "currency": "USD", "observed_at": NOW} if amount else None
    if latest and latest_schedule:
        latest["schedule"] = [{"departs": latest_schedule[0], "arrives": latest_schedule[1]}]
    return {
        "status": status,
        "stale": False,
        "collection_status": "ready",
        "rule_state": {"low_minor": low} if low else {},
        "latest": latest,
        "target": {
            "adults": 1,
            "currency": "USD",
            "segments": [
                {
                    "date": "2027-01-10",
                    "legs": [
                        {
                            "origin": origin,
                            "destination": destination,
                            "airline": "WN",
                            "number": number,
                        }
                    ],
                }
            ],
        },
        **extra,
    }


def rows(flights, prefs, today=TODAY, **options):
    """A flight list as the lines of text a reader sees."""
    return plain_text(flight_list(flights, prefs, today, **options)[0]).split("\n")


def test_every_preset_is_valid_for_its_own_vocabulary():
    assert set(PRESETS) == {"compact", "detailed"} == set(STYLES) - {"custom"}
    assert DEFAULT_STYLE == "compact" == Preferences().telegram_style
    for style, templates in PRESETS.items():
        assert set(templates) == set(TEMPLATE_KEYS), style
        for key, template in templates.items():
            parse_template(template, VOCABULARY[key])
        assert validate_templates({k: v for k, v in templates.items() if v}) is not None


def test_a_compact_alert_says_what_happened_the_price_and_the_flight(flight_url):
    message = alert_message(alert(flight_url), Preferences())
    assert message.text.split("\n") == [
        "🔥 New low · $246 (was $254)",
        "DEN → DFW · Mar 14 · UA 414",
    ]
    assert message.html.split("\n")[0] == "🔥 <b>New low</b> · <b>$246</b> <i>(was $254)</i>"
    assert Markup(message.html).tags == ["b", "b", "i"]
    # Times join the alert once a check has recorded them.
    timed = alert(flight_url, schedule=[{"departs": "15:35", "arrives": "18:39"}])
    assert alert_message(timed, Preferences()).text.split("\n")[2:] == ["3:35 PM → 6:39 PM"]


def test_a_detailed_alert_adds_the_airline_fare_and_time_of_the_check(flight_url):
    timed = alert(
        flight_url, schedule=[{"departs": "15:35", "arrives": "18:39", "duration_minutes": 124}]
    )
    message = alert_message(timed, DETAILED)
    assert message.text.split("\n") == [
        "🔥 New low · $246 (was $254, −$8 · −3%)",
        "DEN → DFW · Mar 14 · UA 414",
        "3:35 PM → 6:39 PM · 2 hr 4 min",
        "United · Economy · Total for 1 adult",
        "Checked 11/06/2026 8:00 AM UTC",
    ]
    assert Markup(message.html).tags == ["b", "b", "i", "i"]
    # A saved time zone is the reader's own, so the time of the check needs no label.
    local = alert_message(
        timed, Preferences(telegram_style="detailed", time_zone="America/Chicago")
    )
    assert local.text.endswith("Checked 11/06/2026 2:00 AM")


@pytest.mark.parametrize("style", sorted(PRESETS))
def test_no_built_in_style_writes_a_currency_code(flight_url, style):
    prefs = Preferences(telegram_style=style)
    for reason in ALERT_KEYS:
        assert "USD" not in alert_message(alert(flight_url, reason), prefs).text
    listed = "\n".join(rows([monitor("1429", 32900, 24500), monitor("1430", 16400, 16400)], prefs))
    assert "USD" not in listed and "$329" in listed and "$164" in listed


def test_wording_for_each_kind_of_alert(flight_url):
    def first(event, prefs=COMPACT):
        return alert_message(event, prefs).text.split("\n")[0]

    assert first(alert(flight_url, "tracking_started", previous=(None, None))) == (
        "✈️ Now tracking · $246"
    )
    assert first(alert(flight_url, "below_price")) == "🎯 Target reached · $246 (was $259)"
    assert first(alert(flight_url, "below_price"), DETAILED) == (
        "🎯 Target reached · $246 (was $259, −$13 · −5%)"
    )
    rebound = alert(flight_url, "rebound", amount=26600, previous=(24600, 24600))
    assert first(rebound) == "📈 Price rose · $266 (low $246)"
    assert first(rebound, DETAILED) == "📈 Price rose · $266 (was at low $246, +$20)"


def test_an_alert_queued_before_comparisons_existed_simply_omits_them(flight_url):
    legacy = alert(flight_url)
    del legacy["previous"]
    for prefs in (Preferences(), DETAILED):
        text = alert_message(legacy, prefs).text
        assert text.startswith("🔥 New low · $246\n")
        assert "was" not in text


@pytest.mark.parametrize("previous", [(None, None), (0, 0), ("254", "254"), (True, True)])
def test_implausible_comparison_data_is_ignored(flight_url, previous):
    for prefs in (Preferences(), DETAILED):
        text = alert_message(alert(flight_url, previous=previous), prefs).text
        assert "was" not in text and "$246" in text


def test_an_alert_that_arrives_late_says_when_its_price_was_checked(flight_url):
    event = alert(flight_url)
    on_time = alert_message(event, Preferences(), now=NOW + LATE_SECONDS - 1).text
    assert "Checked" not in on_time
    late = alert_message(event, Preferences(), now=NOW + LATE_SECONDS).text
    assert late.split("\n")[-1] == "Checked 11/06/2026 8:00 AM UTC"
    # Leaving the time of the check out of alerts does not apply to a late one.
    quiet = Preferences(telegram_style="detailed", telegram_show_observed_time=False)
    assert "Checked" not in alert_message(event, quiet, now=NOW).text
    assert alert_message(event, quiet, now=NOW + 3600).text.count("Checked 11/06/2026") == 1
    # Without a sending time, as in a list of past alerts, nothing is called late.
    assert "Checked" not in alert_message(event, Preferences()).text


def test_switches_tune_built_in_styles_but_a_custom_template_states_its_own_content(flight_url):
    hidden = {
        "telegram_show_flight_numbers": False,
        "telegram_show_times": False,
        "telegram_show_fare": False,
        "telegram_show_observed_time": False,
    }
    timed = alert(flight_url, schedule=[{"departs": "15:35", "arrives": "18:39"}])
    assert alert_message(timed, Preferences(**hidden)).text.split("\n") == [
        "🔥 New low · $246 (was $254)",
        "DEN → DFW · Mar 14",
    ]
    assert alert_message(timed, Preferences(telegram_style="detailed", **hidden)).text.split(
        "\n"
    ) == [
        "🔥 New low · $246 (was $254, −$8 · −3%)",
        "DEN → DFW · Mar 14",
        "United · Total for 1 adult",
    ]
    custom = Preferences(
        telegram_style="custom",
        telegram_templates={"new_low": "{flights} · {fare} · {observed}"},
        **hidden,
    )
    assert alert_message(alert(flight_url), custom).text == (
        "UA 414 · Economy · 11/06/2026 8:00 AM UTC"
    )


def test_each_style_reports_the_switches_that_change_it():
    assert style_switches("compact") == ["telegram_show_flight_numbers", "telegram_show_times"]
    assert style_switches("detailed") == [
        "telegram_show_flight_numbers",
        "telegram_show_times",
        "telegram_show_observed_time",
        "telegram_show_fare",
    ]
    # Every switch named is a real preference, so an editor can bind to it.
    assert set(style_switches("detailed")) <= set(Preferences.model_fields)


def test_custom_templates_apply_per_message_and_others_use_the_default_style(flight_url):
    prefs = Preferences(
        telegram_style="custom",
        telegram_templates={"new_low": "{emoji} {route} is **{price_short}**[ ({change})]"},
    )
    low = alert_message(alert(flight_url), prefs)
    assert low.text == "🔥 DEN → DFW is $246 (−$8)"
    assert low.html == "🔥 DEN → DFW is <b>$246</b> (−$8)"
    rebound = alert_message(alert(flight_url, "rebound", 26600, (24600, 24600)), prefs).text
    assert rebound.startswith("📈 Price rose · $266 (low $246)")
    assert templates_for("custom", {})["new_low"] == PRESETS[DEFAULT_STYLE]["new_low"]
    assert templates_for("custom", None) == PRESETS[DEFAULT_STYLE]


def test_templates_written_with_currency_codes_keep_rendering_them(flight_url):
    # Placeholder names are an account's saved data: each keeps the meaning it was saved with.
    prefs = Preferences(
        telegram_style="custom",
        telegram_templates={
            "new_low": "{price}[ (was {previous_low})]",
            "flight_row": "{flights} {price}[ low {low}]",
        },
    )
    assert alert_message(alert(flight_url), prefs).text == "USD 246.00 (was USD 254.00)"
    assert rows([monitor("1429", 32900, 24500)], prefs)[-1] == ("WN 1429 USD 329.00 low USD 245.00")


def test_a_template_that_would_say_nothing_falls_back_instead_of_failing_delivery(flight_url):
    event = alert(flight_url, fare_name=None)
    prefs = Preferences(telegram_style="custom", telegram_templates={"new_low": "[Fare: {fare}]"})
    message = alert_message(event, prefs)
    assert message.text.startswith("🔥 New low · $246")
    message.payload()  # A sendable message, never an empty one.


def test_an_inline_link_replaces_the_duplicate_flight_button(flight_url):
    url = "https://fareflare.example"
    labels = lambda message: [  # noqa: E731
        button["text"]
        for row in (message.reply_markup or {}).get("inline_keyboard", [])
        for button in row
    ]
    assert labels(alert_message(alert(flight_url), Preferences(), url)) == [
        "View flight",
        "Open Fareflare",
    ]
    linked = {"telegram_style": "custom", "telegram_templates": {"new_low": "{price_short} {link}"}}
    message = alert_message(alert(flight_url), Preferences(**linked), url)
    assert labels(message) == ["Open Fareflare"]
    assert Markup(message.html).links == [import_link(flight_url)["url"]]
    quiet = Preferences(telegram_show_buttons=False, **linked)
    without = alert_message(alert(flight_url), quiet, url)
    assert without.reply_markup is None and "reply_markup" not in without.payload()


def test_round_trips_show_both_dates_a_two_way_route_and_the_return_times(flight_url):
    event = alert(
        flight_url,
        schedule=[
            {"departs": "23:23", "arrives": "05:00", "arrival_day_offset": 1},
            {"departs": "09:05", "arrives": "12:14", "duration_minutes": 129},
        ],
    )
    outbound = event["itinerary"]["segments"][0]
    leg = outbound["legs"][0]
    back = {
        "date": "2027-03-21",
        "legs": [
            {**leg, "origin": leg["destination"], "destination": leg["origin"], "number": "2049"}
        ],
    }
    event["itinerary"]["segments"] = [outbound, back]
    assert alert_message(event, Preferences()).text.split("\n")[1:] == [
        "DEN ⇄ DFW · Mar 14 – Mar 21 · UA 414, UA 2049",
        "11:23 PM → 5:00 AM +1",
        "↩ 9:05 AM → 12:14 PM",
    ]
    assert alert_message(event, DETAILED).text.split("\n")[2:4] == [
        "11:23 PM → 5:00 AM +1",
        "↩ 9:05 AM → 12:14 PM · 2 hr 9 min",
    ]


def test_provider_text_cannot_inject_markup_or_extra_lines_into_any_style(flight_url):
    event = alert(flight_url, fare_name='<a href="https://evil.test">Economy</a>\nFREE\u202e')
    for style in PRESETS:
        message = alert_message(event, Preferences(telegram_style=style))
        markup = Markup(message.html)
        assert all("evil.test" not in link for link in markup.links)
        assert "\nFREE" not in message.text and "\u202e" not in message.text


def test_compact_flight_list_groups_a_route_and_marks_the_low_with_fire():
    flights = [
        monitor("1429", 32900, 24500, latest_schedule=("23:23", "05:00")),
        monitor("1430", 16400, 16400),
        monitor("1066", 26900, 25500, origin="DEN", destination="DAL", status="paused"),
    ]
    lines, count = flight_list(flights, Preferences(), TODAY)
    assert count == 3
    assert plain_text(lines).split("\n") == [
        "🛫 DEN → DFW · Jan 10",
        "• WN 1429 11:23 PM→5:00 AM · $329 (low $245)",
        "• WN 1430 · $164 🔥 at the low",
        "",
        "🛫 DEN → DAL · Jan 10",
        "• WN 1066 · $269 (low $255) · Paused",
    ]
    markup = telegram_html(lines).split("\n")
    assert markup[0] == "🛫 <b>DEN → DFW</b> · Jan 10"
    assert markup[2] == "• <code>WN 1430</code> · <b>$164</b> <i>🔥 at the low</i>"
    Markup(telegram_html(lines))
    # A date more than a few months off names its year.
    assert rows(flights, Preferences(), date(2025, 6, 1))[0] == "🛫 DEN → DFW · Jan 10, 2027"


def test_detailed_flight_list_gives_each_flight_its_own_block():
    flights = [
        monitor("1429", 32900, 24500, latest_schedule=("15:35", "18:39")),
        monitor("1430", 16400, 16400),
        monitor("1431", 0, 0, status="pending"),
    ]
    assert rows(flights, DETAILED) == [
        "DEN → DFW · Jan 10",
        "WN 1429 · 3:35 PM → 6:39 PM · $329",
        "Lowest $245",
        "",
        "DEN → DFW · Jan 10",
        "WN 1430 · $164",
        "🔥 At its lowest",
        "",
        "DEN → DFW · Jan 10",
        "WN 1431",
        "Awaiting check",
    ]


def test_a_round_trip_row_adds_its_return_times():
    flight = monitor("1429", 32900, 24500)
    leg = flight["target"]["segments"][0]["legs"][0]
    flight["target"]["segments"].append(
        {"date": "2027-01-17", "legs": [{**leg, "origin": "DFW", "destination": "DEN"}]}
    )
    flight["latest"]["schedule"] = [
        {"departs": "07:05", "arrives": "10:02"},
        {"departs": "17:09", "arrives": "20:02"},
    ]
    assert rows([flight], Preferences(hour_cycle="h23")) == [
        "🛫 DEN ⇄ DFW · Jan 10 – Jan 17",
        "• WN 1429, WN 1429 07:05→10:02 · $329 (low $245)",
        "   ↩ 17:09→20:02",
    ]


def test_flight_rows_flag_delays_and_describe_route_searches():
    delayed = monitor("1429", 32900, 24500, collection_status="blocked")
    assert rows([delayed], Preferences())[1].endswith("· Check delayed")
    search = monitor("1", 0, 0, status="pending")
    search["target"]["kind"] = "search"
    search["target"]["segments"][0]["legs"][0].update(airline=None, number=None)
    assert "Route search" in rows([search], DETAILED)[1]
    # Once a search has matched an offer, that flight is what the row names.
    search["latest"] = {
        "amount_minor": 19100,
        "currency": "USD",
        "observed_at": NOW,
        "observed_offer": {
            "segments": [
                {
                    "date": "2027-01-10",
                    "legs": [
                        {"origin": "DEN", "destination": "DFW", "airline": "F9", "number": "22"}
                    ],
                }
            ]
        },
    }
    assert "F9 22" in rows([search], DETAILED)[1]


def test_custom_list_templates_choose_their_own_heading_and_row():
    prefs = Preferences(
        telegram_style="custom",
        telegram_templates={
            "flight_group": "**{route}**",
            "flight_row": "{flights}: {price_short}[ {low_note}]",
        },
    )
    lines, _ = flight_list([monitor("1429", 16400, 16400), monitor("1430", 20000, 16400)], prefs)
    assert plain_text(lines).split("\n") == [
        "DEN → DFW",
        "WN 1429: $164 🔥 at the low",
        "WN 1430: $200 (low $164)",
    ]
    assert telegram_html(lines).split("\n")[0] == "<b>DEN → DFW</b>"
    # No heading at all is a valid choice.
    bare = prefs.model_copy(
        update={"telegram_templates": {**prefs.telegram_templates, "flight_group": ""}}
    )
    assert rows([monitor("1429", 16400, 16400)], bare) == ["WN 1429: $164 🔥 at the low"]


def test_a_list_stops_before_the_flight_that_would_not_fit_its_budget():
    flights = [monitor(str(1400 + index), 32900, 24500) for index in range(40)]
    lines, count = flight_list(flights, DETAILED, TODAY, budget=600)
    assert 1 < count < 40
    assert len(plain_text(lines)) <= 600
    # The next page starts with the first flight that was left out.
    following = rows(flights[count:], DETAILED, budget=600)
    assert following[1].startswith(f"WN {1400 + count}")
    assert f"WN {1400 + count}" not in plain_text(lines)
    # One flight is always shown, however small the budget.
    assert flight_list(flights, DETAILED, TODAY, budget=1)[1] == 1
    # A row an account wrote far too long is replaced by the default one, never cut short.
    long = Preferences(
        telegram_style="custom",
        telegram_templates={"flight_group": "", "flight_row": "{flights} " + "padding " * 90},
    )
    assert rows(flights[:1], long) == ["🛫 DEN → DFW · Jan 10", "• WN 1400 · $329 (low $245)"]


def test_lists_are_ordered_by_day_route_and_departure():
    late = monitor("3", 100, 100, latest_schedule=("19:00", "21:00"))
    early = monitor("2", 100, 100, latest_schedule=("06:00", "08:00"))
    untimed = monitor("4", 100, 100)
    other = monitor("1", 100, 100, origin="DEN", destination="DAL")
    sooner = monitor("9", 100, 100)
    sooner["target"]["segments"][0]["date"] = "2027-01-02"
    flights = [late, untimed, other, early, sooner]

    def numbers(preferences):
        return [
            flight["target"]["segments"][0]["legs"][0]["number"]
            for flight in ordered_flights(flights, preferences)
        ]

    assert numbers(Preferences()) == ["9", "1", "2", "3", "4"]


def test_a_list_ordered_by_price_keeps_its_headings_and_puts_the_cheapest_first():
    dear = monitor("1", 30000, 100, latest_schedule=("06:00", "08:00"))
    cheap = monitor("2", 10000, 100, latest_schedule=("19:00", "21:00"))
    same = monitor("3", 10000, 100, latest_schedule=("12:00", "14:00"))
    unpriced = monitor("4", 100, 100, latest_schedule=("05:00", "07:00"))
    unpriced["latest"] = None
    # A flight on another day keeps its place however cheap it is: headings come first.
    later = monitor("5", 100, 100, latest_schedule=("05:00", "07:00"))
    later["target"]["segments"][0]["date"] = "2027-02-01"
    by_price = Preferences(telegram_list_order="price")
    ordered = ordered_flights([dear, cheap, same, unpriced, later], by_price)
    assert [flight["target"]["segments"][0]["legs"][0]["number"] for flight in ordered] == [
        "3",  # the same price as the next one, and it leaves earlier
        "2",
        "1",
        "4",  # nothing recorded yet
        "5",
    ]
    with pytest.raises(ValidationError):
        Preferences(telegram_list_order="alphabetical")


def test_templates_are_validated_when_preferences_are_saved():
    saved = Preferences(telegram_templates={"new_low": "\r\n{price}  \r\n"})
    assert saved.telegram_templates == {"new_low": "{price}"}
    for templates, message in (
        ({"new_low": "{nope}"}, "New low: Unknown placeholder {nope}"),
        ({"new_low": "   "}, "New low: the template cannot be empty"),
        ({"surprise": "{price}"}, "Unknown message template: surprise"),
        ({"flight_row": "{headline}"}, "Flight list row: Unknown placeholder"),
        ({"rebound": "**{price}"}, "Price rebound: Close"),
    ):
        with pytest.raises(ValidationError) as error:
            Preferences(telegram_templates=templates)
        assert message in str(error.value)
    # A list heading is the one template that may be left blank.
    assert Preferences(telegram_templates={"flight_group": ""}).telegram_templates == {
        "flight_group": ""
    }
    with pytest.raises(TemplateError):
        validate_templates(["new_low"])  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Preferences(telegram_style="fancy")  # type: ignore[arg-type]


def test_saved_preferences_from_another_release_never_block_reading_them():
    saved = {
        "locale": "de-DE",
        "telegram_style": "holographic",  # written by some future release
        "telegram_templates": {"new_low": "{field_added_later}"},
        "field_added_later": True,
        "muted_routes": ["DEN-DFW"],
    }
    restored = stored_preferences(saved)
    assert restored.locale == "de-DE" and restored.muted_routes == ["DEN-DFW"]
    assert restored.telegram_style == DEFAULT_STYLE and restored.telegram_templates == {}
    assert stored_preferences(None) == Preferences()
    # A style that was offered before this release reads as the default one.
    assert stored_preferences({"telegram_style": "classic"}).telegram_style == DEFAULT_STYLE
    assert stored_preferences({"telegram_style": "detailed"}).telegram_style == "detailed"
    # Updates are still strict: a bad new value is an error, not a silent default.
    assert merge_preferences(saved, {"telegram_silent": True}).telegram_silent is True
    with pytest.raises(ValidationError):
        merge_preferences(saved, {"telegram_style": "holographic"})


@pytest.mark.parametrize(
    "amount, currency, locale, expected",
    [
        (24600, "USD", "en-US", "$246"),
        (24650, "USD", "en-US", "$246.50"),
        (123456700, "USD", "en-US", "$1,234,567"),
        (24650, "USD", "de-DE", "246,50\N{NO-BREAK SPACE}$"),
        (24600, "EUR", "fr-FR", "246\N{NO-BREAK SPACE}€"),
        (25000, "JPY", "en-US", "¥25,000"),
        (24600, "GBP", "en-GB", "£246"),
        (24605, "CAD", "en-US", "CA$246.05"),
        (24600, "AUD", "en-GB", "A$246"),
    ],
)
def test_short_prices_use_a_symbol_and_drop_empty_cents(amount, currency, locale, expected):
    assert short_price(amount, currency, locale) == expected


def test_signed_amounts_and_short_dates():
    assert short_price(-800, "USD", "en-US", signed=True) == "−$8"
    assert short_price(2000, "USD", "en-US", signed=True) == "+$20"
    assert short_price(0, "USD", "en-US", signed=True) == "$0"
    with pytest.raises(ValueError):
        short_price(100, "XYZ", "en-US")
    day = date(2027, 3, 4)
    assert short_date(day) == "Mar 4"
    assert short_date(day, date(2027, 1, 1)) == "Mar 4"
    # The coming months need no year, even across New Year.
    assert short_date(day, date(2026, 11, 6)) == "Mar 4"
    assert short_date(day, date(2026, 3, 1)) == "Mar 4, 2027"
    # A day already behind the reader in another year is never ambiguous.
    assert short_date(date(2026, 12, 30), date(2027, 1, 2)) == "Dec 30, 2026"
    assert short_dates(day, None, TODAY) == "Mar 4"
    assert short_dates(day, day, TODAY) == "Mar 4"
    assert short_dates(day, date(2027, 3, 11), TODAY) == "Mar 4 – Mar 11"
    assert short_dates(day, date(2027, 3, 11), date(2025, 1, 1)) == "Mar 4 – Mar 11, 2027"
    assert short_dates(date(2027, 12, 28), date(2028, 1, 4), date(2025, 1, 1)) == (
        "Dec 28, 2027 – Jan 4, 2028"
    )


@pytest.mark.parametrize(
    "departs, arrives, hour_cycle, expected",
    [
        ("15:35", "18:39", "h12", "3:35→6:39 PM"),
        ("07:05", "10:02", "h12", "7:05→10:02 AM"),
        ("11:50", "13:05", "h12", "11:50 AM→1:05 PM"),
        ("23:23", "05:00", "h12", "11:23 PM→5:00 AM"),
        ("15:35", "18:39", "h23", "15:35→18:39"),
    ],
)
def test_a_time_range_names_am_or_pm_once_when_both_ends_share_it(
    departs, arrives, hour_cycle, expected
):
    assert clock_range(departs, arrives, Preferences(hour_cycle=hour_cycle)) == expected


def test_every_preview_renders_for_every_style_and_sample_without_sending_anything():
    assert tuple(PREVIEWS) == (*ALERT_KEYS, "flight_list")
    choices = preview_choices()
    assert [item["value"] for item in choices["previews"]] == list(PREVIEWS)
    assert [item["value"] for item in choices["samples"]] == list(get_args(PreviewSample))
    assert all(item["label"] for item in choices["previews"] + choices["samples"])
    for style in STYLES:
        prefs = Preferences(telegram_style=style)
        for kind in PREVIEWS:
            for sample in get_args(PreviewSample):
                preview = preview_message(kind, prefs, "https://fareflare.example", NOW, sample)
                preview.message.payload()
                Markup(preview.message.html)
                # The styled lines an editor draws are the message that would be sent.
                assert plain_text(preview.lines) == preview.message.text
                assert telegram_html(preview.lines) == preview.message.html
                assert "USD" not in preview.message.text
                assert preview.hints == ()


def sample(kind, name="one_way", prefs=COMPACT):
    return preview_message(kind, prefs, "https://fareflare.example", NOW, name).message


def test_the_sample_trip_is_always_ahead_and_carries_its_own_link():
    # Sixteen weeks after the preview is made: never in the past, never in need of a year.
    assert sample("new_low").text.split("\n") == [
        "🔥 New low · $191 (was $199)",
        "DEN → DFW · Feb 26 · UA 414",
        "3:50 PM → 6:54 PM",
    ]
    much_later = preview_message("new_low", COMPACT, None, NOW + 400 * 86400).message
    assert "DEN → DFW · Apr 1 · UA 414" in much_later.text
    # The button opens the flights the message names, on the day it names.
    for name, days in (("one_way", ["2027-02-26"]), ("round_trip", ["2027-02-26", "2027-03-05"])):
        url = sample("new_low", name).reply_markup["inline_keyboard"][0][0]["url"]
        target = import_link(url)
        assert [segment["date"] for segment in target["segments"]] == days
        assert target["segments"][0]["legs"][0]["number"] == "414"
    assert import_link(url)["adults"] == 2


def test_samples_show_wording_where_details_are_added_or_missing():
    assert sample("new_low", "round_trip").text.split("\n") == [
        "🔥 New low · $382 for 2 adults (was $398)",
        "DEN ⇄ DFW · Feb 26 – Mar 5 · UA 414, UA 2231",
        "3:50 PM → 6:54 PM",
        "↩ 5:09 PM → 6:14 PM",
    ]
    assert sample("new_low", "untimed").text.split("\n") == [
        "🔥 New low · $191 (was $199)",
        "DEN → DFW · Feb 26 · UA 414",
    ]
    # Only an alert that arrives late says when its price was checked.
    assert "Checked" not in sample("new_low").text
    assert sample("new_low", "late").text.split("\n")[-1] == "Checked 11/06/2026 7:35 AM UTC"
    assert sample("flight_list", "late").text == sample("flight_list").text
    assert sample("flight_list").text.split("\n") == [
        "🛫 DEN → DFW · Feb 26",
        "• UA 1565 7:05→10:02 AM · $214 (low $199)",
        "• UA 414 3:50→6:54 PM · $191 🔥 at the low",
        "• UA 1832 7:40→10:41 PM · $269 (low $219) · Paused",
    ]
    by_price = Preferences(telegram_list_order="price")
    assert [
        line.split(" ")[2] for line in sample("flight_list", prefs=by_price).text.split("\n")[1:]
    ] == ["414", "1565", "1832"]
    assert sample("flight_list", "round_trip").text.split("\n")[:3] == [
        "🛫 DEN ⇄ DFW · Feb 26 – Mar 5",
        "• UA 1565, UA 2231 7:05→10:02 AM · $428 (low $398)",
        "   ↩ 5:09→6:14 PM",
    ]
    assert sample("flight_list", "untimed").text.split("\n")[1] == "• UA 1565 · $214 (low $199)"


def test_trip_and_flight_details_for_custom_wording(flight_url):
    wording = "{weekday} {days_until} · {stops} · {cabin}[ / {return_weekday} {return_stops}]"
    custom = Preferences(telegram_style="custom", telegram_templates={"new_low": wording})
    assert sample("new_low", prefs=custom).text == "Fri in 112 days · Nonstop · Economy"
    assert (
        sample("new_low", "round_trip", custom).text
        == "Fri in 112 days · Nonstop · Economy / Fri Nonstop"
    )
    # How soon a trip starts is counted from the reader's day.
    connecting = alert(flight_url)
    connecting["itinerary"]["segments"][0]["legs"] = [
        {"origin": "DEN", "destination": "ORD", "airline": "UA", "number": "1"},
        {"origin": "ORD", "destination": "DFW", "airline": "UA", "number": "2"},
    ]
    connecting["itinerary"]["segments"][0]["date"] = "2026-11-07"
    connecting["itinerary"]["cabin"] = 3
    text = alert_message(connecting, custom, now=NOW).text
    assert text.startswith("Sat tomorrow · 1 stop · Business")
    connecting["itinerary"]["segments"][0]["date"] = "2026-11-06"
    assert "Fri today" in alert_message(connecting, custom, now=NOW).text
    # A day that has passed is not counted, and a flight that is not known has no stops.
    connecting["itinerary"]["segments"][0]["date"] = "2026-11-01"
    del connecting["itinerary"]["segments"][0]["legs"][1]["number"]
    del connecting["itinerary"]["cabin"]
    assert alert_message(connecting, custom, now=NOW).text.split(" / ")[0] == "Sun"


def test_hints_name_what_a_reader_would_miss_and_never_block_saving():
    for style in PRESETS:
        for kind in PREVIEWS:
            assert template_hints(kind, PRESETS[style]) == []
    bare = validate_templates({"new_low": "{headline}", "flight_row": "{times}"})
    wording = templates_for("custom", {**bare, "flight_group": ""})
    assert template_hints("new_low", wording) == [
        "This alert does not show the price.",
        "This alert does not show which flight it is about.",
    ]
    assert template_hints("flight_list", wording) == [
        "A flight in the list does not show the price.",
        "A flight in the list does not show which flight it is about.",
    ]
    # Another alert of the same account keeps the default wording, which has both.
    assert template_hints("rebound", wording) == []
    # A heading that names the route speaks for the rows under it.
    headed = templates_for("custom", {"flight_group": "{route}", "flight_row": "{price}"})
    assert template_hints("flight_list", headed) == []
    preview = preview_message(
        "new_low",
        Preferences(telegram_style="custom", telegram_templates=bare),
        None,
        NOW,
    )
    assert preview.hints == (
        "This alert does not show the price.",
        "This alert does not show which flight it is about.",
    )


def test_catalog_describes_every_template_for_an_editor():
    catalog = template_catalog()
    assert [item["key"] for item in catalog["templates"]] == list(TEMPLATE_KEYS)
    assert [item["key"] for item in catalog["templates"] if item["optional"]] == ["flight_group"]
    for key in TEMPLATE_KEYS:
        listed = [item["name"] for item in catalog["placeholders"][key]]
        assert set(listed) == VOCABULARY[key] and len(listed) == len(set(listed))
        assert all(
            item["description"] and item["example"] and item["group"]
            for item in catalog["placeholders"][key]
        )
    # The symbol form of a price is the first thing an editor offers.
    assert catalog["placeholders"]["new_low"][0]["name"] == "price_short"
    assert catalog["placeholders"]["flight_row"][0]["name"] == "price_short"
    assert catalog["presets"] == PRESETS
    assert catalog["default_style"] == DEFAULT_STYLE
    assert [style["value"] for style in catalog["styles"]] == ["compact", "detailed", "custom"]
    assert all(style["label"] and style["description"] for style in catalog["styles"])
    assert [style["switches"] for style in catalog["styles"]] == [
        style_switches("compact"),
        style_switches("detailed"),
        [],
    ]
    # Every switch is a preference with a name an editor can show.
    assert [item["name"] for item in catalog["switches"]] == list(SWITCHES)
    assert all(item["label"] for item in catalog["switches"])
    assert set(SWITCHES) < set(Preferences.model_fields)
    assert catalog["limits"] == {"characters": 800, "lines": 20, "placeholders": 40}


def test_diagnostic_notices_use_plain_words_and_name_the_code_once():
    flight = monitor("1429", 32900, 24500)
    failing = collection_notice(
        {"kind": "collection_failing", "code": "timeout", "failures": 5},
        flight,
        Preferences(),
        "https://fareflare.example",
    )
    assert failing.text.split("\n")[:2] == ["⚠️ Price checks are failing", "DEN → DFW · 01/10/2027"]
    assert "The last 5 checks could not finish because the page took too long to load." in (
        failing.text
    )
    assert failing.text.count("timeout") == 1 and "diagnostic notices are on" in failing.text
    assert failing.reply_markup["inline_keyboard"][0][0]["text"] == "Open Fareflare"
    google = collection_notice(
        {"kind": "collection_failing", "code": "provider_error", "failures": 5},
        flight,
        Preferences(),
    )
    assert "could not finish because Google Flights showed an error page." in google.text
    blocked = collection_notice(
        {"kind": "collection_blocked", "code": "unsupported_itinerary", "failures": 1},
        flight,
        Preferences(),
    )
    assert "have stopped" in blocked.text and "Retry collection" in blocked.text
    assert blocked.reply_markup is None
    recovered = collection_notice(
        {"kind": "collection_recovered", "code": None, "failures": 0}, flight, Preferences()
    )
    assert recovered.text.startswith("✅ Price checks are working again")
    unknown = collection_notice(
        {"kind": "collection_failing", "code": "<b>x</b>\n", "failures": None},
        flight,
        Preferences(),
    )
    assert "Recent checks could not finish because the fare could not be verified." in unknown.text
    for message in (failing, blocked, recovered, unknown):
        message.payload()
        Markup(message.html)


def test_an_oversized_rendering_falls_back_to_the_default_wording(flight_url):
    prefs = Preferences(
        telegram_style="custom", telegram_templates={"new_low": "{link} " * 39 + "{price}"}
    )
    event = alert(flight_url)
    # A long but valid Google Flights address, repeated by the template above.
    event["itinerary"]["url"] += "&utm_source=" + "x" * 600
    message = alert_message(event, prefs)
    assert message.text.startswith("🔥 New low · $246 (was $254)")
    assert len(message.html) < 4096
    message.payload()
