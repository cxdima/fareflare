"""Message styles: built-in presets, account templates and the values they can show."""

from html.parser import HTMLParser

import pytest
from pydantic import ValidationError

from fareflare.links import import_link
from fareflare.message_templates import TemplateError, parse_template
from fareflare.preferences import (
    Preferences,
    merge_preferences,
    short_date,
    short_price,
    stored_preferences,
)
from fareflare.telegram_messages import (
    PREVIEW_KINDS,
    alert_message,
    collection_notice,
    flight_list,
    flight_list_page_size,
    preview_message,
)
from fareflare.telegram_templates import (
    ALERT_KEYS,
    PRESETS,
    TEMPLATE_KEYS,
    VOCABULARY,
    template_catalog,
    templates_for,
    validate_templates,
)

NOW = 1793952000  # 2026-11-06 08:00 UTC


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


def monitor(number, amount, low, status="active", origin="DEN", destination="DFW", **extra):
    return {
        "status": status,
        "stale": False,
        "collection_status": "ready",
        "rule_state": {"low_minor": low} if low else {},
        "latest": {"amount_minor": amount, "currency": "USD", "observed_at": NOW}
        if amount
        else None,
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


def test_every_preset_is_valid_for_its_own_vocabulary():
    assert set(PRESETS) == {"detailed", "compact", "classic"}
    for style, templates in PRESETS.items():
        assert set(templates) == set(TEMPLATE_KEYS), style
        for key, template in templates.items():
            parse_template(template, VOCABULARY[key])
        assert validate_templates({k: v for k, v in templates.items() if v}) is not None


def test_classic_new_low_shows_what_changed_the_way_people_read_it(flight_url):
    message = alert_message(alert(flight_url), Preferences(telegram_style="classic"))
    assert message.text.split("\n") == [
        "📉 New low!  $246  (was $254, −$8 · −3%)",
        "🛫 DEN → DFW",
        "United  ·  UA 414",
        "Mar 14, 2027",
        "Open in Google Flights",
        "",
        "11/06/2026 8:00 AM UTC",
    ]
    markup = Markup(message.html)
    assert markup.tags == ["b", "b", "i", "b", "code", "a", "i"]
    assert markup.links == [import_link(flight_url)["url"]]


def test_classic_wording_for_each_kind_of_alert(flight_url):
    classic = Preferences(telegram_style="classic", time_zone="America/Chicago")
    started = alert_message(
        alert(flight_url, "tracking_started", previous=(None, None)), classic
    ).text
    assert started.startswith("✈️ Now tracking  ·  $246\n🛫 DEN → DFW")
    target = alert_message(alert(flight_url, "below_price"), classic).text
    assert target.startswith("🎯 Target reached  $246  (was $259, −$13 · −5%)")
    rebound = alert_message(
        alert(flight_url, "rebound", amount=26600, previous=(24600, 24600)), classic
    ).text
    assert rebound.startswith("📈 Rebounding  $266  (was at low $246, +$20)")
    assert "The discount window may be closing." in rebound
    # A saved time zone is the reader's own, so the short stamp needs no label.
    assert rebound.endswith("11/06/2026 2:00 AM")


def test_an_alert_queued_before_comparisons_existed_simply_omits_them(flight_url):
    legacy = alert(flight_url)
    del legacy["previous"]
    text = alert_message(legacy, Preferences(telegram_style="classic")).text
    assert text.startswith("📉 New low!  $246\n")
    assert "was" not in text


@pytest.mark.parametrize("previous", [(None, None), (0, 0), ("254", "254"), (True, True)])
def test_implausible_comparison_data_is_ignored(flight_url, previous):
    text = alert_message(
        alert(flight_url, previous=previous), Preferences(telegram_style="classic")
    ).text
    assert "was" not in text and "$246" in text


def test_detailed_and_compact_keep_their_established_layout(flight_url):
    detailed = alert_message(alert(flight_url), Preferences()).text
    assert detailed.split("\n") == [
        "USD 246.00",
        "New observed low",
        "",
        "DEN → DFW · 03/14/2027 · UA 414",
        "",
        "Total for 1 adult",
        "Fare: Economy",
        "",
        "Observed 11/06/2026 8:00 AM UTC",
    ]
    compact = alert_message(alert(flight_url), Preferences(telegram_style="compact")).text
    assert "Total for 1 adult · Fare: Economy" in compact
    assert len(compact.split("\n")) == len(detailed.split("\n")) - 1


def test_checkboxes_tune_presets_but_a_custom_template_states_its_own_content(flight_url):
    hidden = {
        "telegram_show_flight_numbers": False,
        "telegram_show_fare": False,
        "telegram_show_observed_time": False,
    }
    classic = alert_message(alert(flight_url), Preferences(telegram_style="classic", **hidden))
    assert classic.text.split("\n")[2:4] == ["United", "Mar 14, 2027"]
    assert "UA 414" not in classic.text and "11/06/2026" not in classic.text
    custom = Preferences(
        telegram_style="custom",
        telegram_templates={"new_low": "{flights} · {fare} · {observed}"},
        **hidden,
    )
    assert alert_message(alert(flight_url), custom).text == (
        "UA 414 · Economy · 11/06/2026 8:00 AM UTC"
    )


def test_custom_templates_apply_per_message_and_others_use_the_detailed_preset(flight_url):
    prefs = Preferences(
        telegram_style="custom",
        telegram_templates={"new_low": "{emoji} {route} is **{price_short}**[ ({change})]"},
    )
    low = alert_message(alert(flight_url), prefs)
    assert low.text == "📉 DEN → DFW is $246 (−$8)"
    assert low.html == "📉 DEN → DFW is <b>$246</b> (−$8)"
    rebound = alert_message(alert(flight_url, "rebound", 26600, (24600, 24600)), prefs).text
    assert rebound.startswith("USD 266.00\nPrice rose from its low")
    assert templates_for("custom", {})["new_low"] == PRESETS["detailed"]["new_low"]


def test_a_template_that_would_say_nothing_falls_back_instead_of_failing_delivery(flight_url):
    event = alert(flight_url, fare_name=None)
    prefs = Preferences(telegram_style="custom", telegram_templates={"new_low": "[Fare: {fare}]"})
    message = alert_message(event, prefs)
    assert message.text.startswith("USD 246.00\nNew observed low")
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
    classic = Preferences(telegram_style="classic")
    assert labels(alert_message(alert(flight_url), classic, url)) == ["Open Fareflare"]
    quiet = Preferences(telegram_style="classic", telegram_show_buttons=False)
    without = alert_message(alert(flight_url), quiet, url)
    assert without.reply_markup is None and "reply_markup" not in without.payload()


def test_round_trips_show_both_dates_and_a_two_way_route(flight_url):
    event = alert(flight_url)
    outbound = event["itinerary"]["segments"][0]
    leg = outbound["legs"][0]
    back = {
        "date": "2027-03-21",
        "legs": [{**leg, "origin": leg["destination"], "destination": leg["origin"]}],
    }
    event["itinerary"]["segments"] = [outbound, back]
    classic = alert_message(event, Preferences(telegram_style="classic")).text
    assert "🛫 DEN ⇄ DFW" in classic and "Mar 14, 2027 – Mar 21, 2027" in classic
    detailed = alert_message(event, Preferences()).text
    assert "DEN → DFW · 03/14/2027 · UA 414\nDFW → DEN · 03/21/2027 · UA 414" in detailed


def test_provider_text_cannot_inject_markup_or_extra_lines_into_any_style(flight_url):
    event = alert(flight_url, fare_name='<a href="https://evil.test">Economy</a>\nFREE‮')
    for style in ("detailed", "compact", "classic"):
        message = alert_message(event, Preferences(telegram_style=style))
        markup = Markup(message.html)
        assert all("evil.test" not in link for link in markup.links)
        assert "\nFREE" not in message.text and "‮" not in message.text


def test_classic_flight_list_groups_a_route_and_marks_the_low_with_fire():
    flights = [
        monitor("1429", 32900, 24500),
        monitor("1430", 16400, 16400),
        monitor("1066", 26900, 25500, origin="DEN", destination="DAL", status="paused"),
    ]
    plain, markup = flight_list(flights, Preferences(telegram_style="classic"), 2026)
    assert plain == [
        "🛫 DEN → DFW  Jan 10, 2027",
        "  • WN 1429 · $329 (low $245)",
        "  • WN 1430 · $164 🔥 at the low",
        "",
        "🛫 DEN → DAL  Jan 10, 2027",
        "  • WN 1066 · $269 (low $255) · Paused",
    ]
    assert len(markup) == len(plain)
    assert markup[2] == "  • <code>WN 1430</code> · <b>$164</b> <i>🔥 at the low</i>"
    for line in markup:
        Markup(line)
    # In the year of travel the date needs no year.
    assert flight_list(flights, Preferences(telegram_style="classic"), 2027)[0][0] == (
        "🛫 DEN → DFW  Jan 10"
    )


def test_detailed_and_compact_flight_lists_identify_each_flight():
    flights = [monitor("1429", 32900, 24500), monitor("1430", 0, 0, status="pending")]
    detailed, _ = flight_list(flights, Preferences())
    assert detailed == [
        "DEN → DFW  01/10/2027",
        "WN 1429 · Watching",
        "Last observed USD 329.00",
        "Lowest observed USD 245.00",
        "",
        "DEN → DFW  01/10/2027",
        "WN 1430 · Awaiting check",
    ]
    compact, _ = flight_list(flights, Preferences(telegram_style="compact"), 2027)
    assert compact == [
        "DEN → DFW · Jan 10 · WN 1429 · USD 329.00",
        "DEN → DFW · Jan 10 · WN 1430 · Awaiting check",
    ]


def test_flight_rows_flag_delays_and_describe_route_searches():
    delayed = monitor("1429", 32900, 24500, collection_status="blocked")
    plain, _ = flight_list([delayed], Preferences(telegram_style="classic"), 2027)
    assert plain[1].endswith("· Check delayed")
    search = monitor("1", 0, 0, status="pending")
    search["target"]["kind"] = "search"
    search["target"]["segments"][0]["legs"][0].update(airline=None, number=None)
    assert "Route search" in flight_list([search], Preferences(), 2027)[0][1]
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
    assert "F9 22" in flight_list([search], Preferences(), 2027)[0][1]


def test_custom_list_templates_and_page_size_follow_the_row_shape():
    prefs = Preferences(
        telegram_style="custom",
        telegram_templates={
            "flight_group": "**{route}**",
            "flight_row": "{flights}: {price_short}[ {low_note}]",
        },
    )
    plain, markup = flight_list([monitor("1429", 16400, 16400)], prefs, 2027)
    assert plain == ["DEN → DFW", "WN 1429: $164 🔥 at the low"]
    assert markup[0] == "<b>DEN → DFW</b>"
    assert flight_list_page_size(prefs) == 8
    assert flight_list_page_size(Preferences()) == 5
    assert flight_list_page_size(Preferences(telegram_style="classic")) == 8


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
    assert restored.telegram_style == "detailed" and restored.telegram_templates == {}
    assert stored_preferences(None) == Preferences()
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
        (24650, "USD", "de-DE", "246,50 $"),
        (24600, "EUR", "fr-FR", "246 €"),
        (25000, "JPY", "en-US", "¥25,000"),
        (24600, "GBP", "en-GB", "£246"),
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
    from datetime import date

    assert short_date(date(2027, 3, 4)) == "Mar 4"
    assert short_date(date(2027, 3, 4), 2027) == "Mar 4"
    assert short_date(date(2027, 3, 4), 2026) == "Mar 4, 2027"


def test_every_preview_renders_for_every_style_without_sending_anything():
    assert PREVIEW_KINDS == (*ALERT_KEYS, "flight_list")
    for style in ("detailed", "compact", "classic", "custom"):
        prefs = Preferences(telegram_style=style)
        for kind in PREVIEW_KINDS:
            message = preview_message(kind, prefs, "https://fareflare.example", NOW)
            message.payload()
            Markup(message.html)
    assert (
        "🔥 at the low"
        in preview_message("flight_list", Preferences(telegram_style="classic"), None, NOW).text
    )
    with pytest.raises(ValueError):
        preview_message("anything", Preferences(), None, NOW)


def test_catalog_describes_every_template_for_an_editor():
    catalog = template_catalog()
    assert [item["key"] for item in catalog["templates"]] == list(TEMPLATE_KEYS)
    assert [item["key"] for item in catalog["templates"] if item["optional"]] == ["flight_group"]
    for key in TEMPLATE_KEYS:
        names = {item["name"] for item in catalog["placeholders"][key]}
        assert names == VOCABULARY[key]
        assert all(item["description"] and item["example"] for item in catalog["placeholders"][key])
    assert catalog["presets"]["classic"]["flight_row"] == PRESETS["classic"]["flight_row"]
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
    blocked = collection_notice(
        {"kind": "collection_blocked", "code": "challenge", "failures": 1}, flight, Preferences()
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


def test_an_oversized_rendering_falls_back_to_the_detailed_wording(flight_url):
    prefs = Preferences(
        telegram_style="custom", telegram_templates={"new_low": "{link} " * 39 + "{price}"}
    )
    event = alert(flight_url)
    # A long but valid Google Flights address, repeated by the template above.
    event["itinerary"]["url"] += "&utm_source=" + "x" * 600
    message = alert_message(event, prefs)
    assert message.text.startswith("USD 246.00\nNew observed low")
    assert len(message.html) < 4096
    message.payload()
