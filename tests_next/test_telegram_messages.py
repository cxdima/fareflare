"""Telegram presentation keeps safe, useful actions and an exact text preview."""
import json
from copy import deepcopy
from html.parser import HTMLParser

import httpx
import pytest

from gfpt_next.delivery import TelegramSink
from gfpt_next.links import import_link
from gfpt_next.preferences import Preferences, telegram_text
from gfpt_next.telegram_messages import (
    TelegramMessage,
    alert_message,
    safe_dashboard_url,
    safe_flight_url,
)


class ParsedMessage(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.fragments, self.tags = [], []
        self.feed(value)

    def handle_data(self, data):
        self.fragments.append(data)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    @property
    def text(self):
        return "".join(self.fragments)


def delivery(flight_url):
    return {"id": "f" * 32, "tenant": "alice", "reason": "new_low",
            "observation": {"amount_minor": 19100, "currency": "USD", "observed_at": 1793952000,
                            "fare_name": "Economy", "price_basis": "total"},
            "itinerary": {**import_link(flight_url), "adults": 2}}


def test_alert_has_price_route_hierarchy_exact_plain_preview_and_validated_buttons(flight_url):
    event = delivery(flight_url)
    message = alert_message(event, Preferences(), "https://fareflare.example")
    payload = message.payload()
    assert message.text.startswith("USD 191.00\nNew observed low\n\nDEN → DFW")
    assert payload["text"].startswith("<b>USD 191.00</b>\nNew observed low\n\n<b>DEN → DFW</b>")
    assert ParsedMessage(payload["text"]).text == message.text == telegram_text(event, Preferences())
    assert "Alert " not in message.text and "https://" not in message.text
    assert payload["link_preview_options"] == {"is_disabled": True}
    assert payload["reply_markup"] == {"inline_keyboard": [[
        {"text": "View flight", "url": import_link(flight_url)["url"], "style": "primary"},
        {"text": "Open Fareflare", "url": "https://fareflare.example/app#monitors"},
    ]]}


@pytest.mark.parametrize("malicious", [
    '<a href="tg://user?id=1">Trusted fare</a>', '<b>Premium & "Flexible"</b>',
    "&lt;b&gt;literal entity&lt;/b&gt;", "Economy\nUSD 1.00\x00\u202eFareflare",
    "✈" * 150,
])
def test_provider_fare_is_literal_bounded_text_not_telegram_markup(flight_url, malicious):
    event = delivery(flight_url)
    event["observation"]["fare_name"] = malicious
    original = deepcopy(event)
    message = alert_message(event, Preferences())
    parsed = ParsedMessage(message.html)
    assert parsed.text == message.text
    assert set(parsed.tags) == {"b"}
    fare = next(line for line in message.text.splitlines() if line.startswith("Fare: "))
    assert len(fare) <= 126 and "\x00" not in fare and "\u202e" not in fare
    assert event == original


@pytest.mark.parametrize("value", [
    "javascript:alert(1)", "https://evil.example/travel/flights", "https://google.com.evil.example/travel/flights",
    "https://www.google.com@evil.example/travel/flights", "https://user:secret@www.google.com/travel/flights",
    "http://www.google.com/travel/flights", "https://www.google.com/url?q=https://evil.example",
    "https://www.google.com/travel/flights#javascript:alert(1)",
    "https://www.google.com/travel/flights?tfs=not-a-trip", "https://www.google.com/travel/flights\n",
    "https://www.google.com:999999/travel/flights", None, 12, "a" * 8193,
])
def test_invalid_booking_destinations_are_not_rendered_or_linked(flight_url, value):
    event = delivery(flight_url)
    event["itinerary"]["url"] = value
    message = alert_message(event, Preferences())
    assert safe_flight_url(value) is None
    assert "reply_markup" not in message.payload()
    assert "javascript:" not in message.text and "evil.example" not in message.text


@pytest.mark.parametrize("value", [
    "javascript:alert(1)", "https://fareflare.example/app", "https://fareflare.example?token=secret",
    "https://user:secret@fareflare.example", "https://fareflare.example/#settings",
    "https://fareflare.example\n", "https://fareflare.example:70000", "http://fareflare.example",
    "", None,
])
def test_invalid_dashboard_origins_do_not_make_buttons(value):
    assert safe_dashboard_url(value) is None


def test_plain_message_payload_and_local_development_dashboard_are_supported():
    markup = {"inline_keyboard": [[{"text": "My flights", "callback_data": "ff:example"}]]}
    message = TelegramMessage("My flights", reply_markup=markup)
    first = message.payload()
    assert "parse_mode" not in first
    first["reply_markup"]["inline_keyboard"][0][0]["text"] = "changed"
    assert message.payload()["reply_markup"]["inline_keyboard"][0][0]["text"] == "My flights"
    assert safe_dashboard_url("http://127.0.0.1:8001/") == "http://127.0.0.1:8001/app#monitors"


@pytest.mark.parametrize("text", ["", " \n", "a" * 4097, "🛫" * 2049])
def test_empty_or_oversized_messages_fail_before_transport(text):
    with pytest.raises(ValueError, match="1–4096"):
        TelegramMessage(text).payload()
    assert TelegramMessage("🛫" * 2048).payload()["text"] == "🛫" * 2048


@pytest.mark.parametrize(("currency", "minor", "expected"), [
    ("USD", 123456, "USD 1.234,56"), ("JPY", 48706, "JPY 48.706"),
])
def test_delivery_respects_compact_visibility_regional_format_and_silent_mode(flight_url, currency, minor, expected):
    event = delivery(flight_url)
    event["observation"].update(currency=currency, amount_minor=minor)
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    preferences = Preferences(telegram_style="compact", telegram_show_flight_numbers=False,
                              telegram_show_fare=False, telegram_show_observed_time=False,
                              telegram_silent=True, locale="de-DE")
    sink = TelegramSink("123:" + "x" * 25, {"alice": "123"}, httpx.MockTransport(transport),
                        preferences=preferences, public_url="https://fareflare.example")
    assert sink.send(event)
    payload = sent[0]
    assert payload["disable_notification"] is True and payload["chat_id"] == "123"
    plain = ParsedMessage(payload["text"]).text
    assert plain.startswith(expected)
    assert "14.03.2027" in plain and "Total for 2 adults" in plain
    assert all(value not in plain for value in ("UA414", "Fare:", "Observed", "Alert "))
    assert len(payload["reply_markup"]["inline_keyboard"][0]) == 2


def test_compact_keeps_optional_details_together_without_losing_observation_zone(flight_url):
    prefs = Preferences(telegram_style="compact", time_zone="Asia/Kolkata", hour_cycle="h23")
    message = alert_message(delivery(flight_url), prefs)
    assert "Total for 2 adults · Fare: Economy" in message.text
    assert "Asia/Kolkata (UTC+05:30)" in message.text
    assert ParsedMessage(message.html).text == message.text


def test_rendering_failure_never_reaches_telegram(flight_url):
    event = delivery(flight_url)
    event["observation"]["currency"] = "XYZ"
    attempts = []
    sink = TelegramSink("123:" + "x" * 25, {"alice": "123"}, httpx.MockTransport(
        lambda request: attempts.append(request)))
    assert not sink.send(event)
    assert attempts == []
