"""Quiet hours: inside a daily window, Telegram messages arrive without sound."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fareflare.api import create_app
from fareflare.delivery import TelegramSink
from fareflare.preferences import (
    Preferences,
    in_quiet_hours,
    quiet_hours_label,
    sends_silently,
    stored_preferences,
)
from fareflare.webhooks import RoutedSink
from tests.test_diagnostics import connected, fail  # noqa: F401
from tests.test_preferences import sample
from tests.test_telegram_accounts import bind
from tests.test_telegram_bot import _call, _press, native_bot  # noqa: F401

KEY = {"Authorization": "Bearer " + "a" * 40}


def at(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


@pytest.mark.parametrize("value", ["22:00-07:00", "00:00-23:59", "13:00-13:01"])
def test_a_window_is_two_different_24_hour_times(value):
    assert Preferences(quiet_hours=value).quiet_hours == value


@pytest.mark.parametrize(
    "value",
    [
        "22:00",
        "22:00-22:00",  # An empty window, or a whole day? Neither is said plainly.
        "24:00-07:00",
        "7:00-22:00",
        "22:00–07:00",  # An en dash.
        "22:00-07:00 ",
        "10:00 PM-7:00 AM",
        "",
        2200,
    ],
)
def test_anything_else_is_refused(value):
    with pytest.raises(ValidationError):
        Preferences(quiet_hours=value)


def test_a_window_past_midnight_includes_its_start_and_stops_before_its_end():
    night = Preferences(quiet_hours="22:00-07:00")
    assert not in_quiet_hours(night, at("2026-11-02T21:59:59"))
    assert in_quiet_hours(night, at("2026-11-02T22:00:00"))
    assert in_quiet_hours(night, at("2026-11-03T00:00:00"))
    assert in_quiet_hours(night, at("2026-11-03T06:59:59"))
    assert not in_quiet_hours(night, at("2026-11-03T07:00:00"))
    assert not in_quiet_hours(night, at("2026-11-03T12:00:00"))


def test_a_window_within_one_day():
    nap = Preferences(quiet_hours="13:00-15:00")
    assert not in_quiet_hours(nap, at("2026-11-02T12:59:00"))
    assert in_quiet_hours(nap, at("2026-11-02T13:00:00"))
    assert in_quiet_hours(nap, at("2026-11-02T14:59:00"))
    assert not in_quiet_hours(nap, at("2026-11-02T15:00:00"))


def test_the_window_is_read_in_the_account_time_zone():
    # 04:30 UTC is 22:30 the evening before in Chicago, and 13:30 in Tokyo.
    moment = at("2026-11-03T04:30:00")
    assert in_quiet_hours(
        Preferences(quiet_hours="22:00-07:00", time_zone="America/Chicago"), moment
    )
    assert not in_quiet_hours(
        Preferences(quiet_hours="22:00-07:00", time_zone="Asia/Tokyo"), moment
    )
    assert in_quiet_hours(Preferences(quiet_hours="22:00-07:00"), moment)  # UTC when unset.


def test_without_a_window_nothing_is_quiet_and_always_silent_still_wins():
    assert not in_quiet_hours(Preferences(), at("2026-11-03T03:00:00"))
    assert not sends_silently(Preferences(), at("2026-11-03T03:00:00"))
    noon = at("2026-11-03T12:00:00")
    assert sends_silently(Preferences(telegram_silent=True, quiet_hours="22:00-07:00"), noon)
    assert not sends_silently(Preferences(quiet_hours="22:00-07:00"), noon)


def test_the_window_is_shown_in_the_readers_clock_style():
    assert quiet_hours_label("22:00-07:00", Preferences()) == "10:00 PM – 7:00 AM"
    assert quiet_hours_label("22:00-07:00", Preferences(hour_cycle="h23")) == "22:00 – 07:00"
    assert quiet_hours_label("00:15-12:00", Preferences(locale="de-DE")) == "00:15 – 12:00"


def test_an_unreadable_saved_window_falls_back_to_none_without_losing_other_settings():
    saved = stored_preferences({"quiet_hours": "sometime", "locale": "de-DE", "muted": True})
    assert saved.quiet_hours is None and saved.locale == "de-DE" and saved.muted is True


@pytest.mark.parametrize(
    "moment, silent",
    [("2026-11-03T05:00:00", True), ("2026-11-03T18:00:00", False)],
)
def test_an_alert_inside_the_window_is_sent_without_sound(moment, silent):
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    sink = TelegramSink(
        "123:" + "x" * 25,
        {"alice": "123"},
        httpx.MockTransport(transport),
        preferences=Preferences(quiet_hours="22:00-07:00", time_zone="America/Chicago"),
        clock=lambda: at(moment),
    )
    assert sink.send({**sample(), "tenant": "alice"})
    # The alert itself is unchanged and is never held back.
    assert sent[0]["disable_notification"] is silent and "USD" in sent[0]["text"]


def test_connected_accounts_get_quiet_alerts_and_notices(connected, service, flight_url, clock):  # noqa: F811
    connections, tenant, sent = connected
    bind(connections, tenant)
    service.set_preferences(tenant, diagnostics=True, quiet_hours="20:00-06:00")
    service.create_monitor(tenant, flight_url, "quiet-notice")
    clock[0] = at("2026-11-02T21:00:00")
    fail(service, clock, code="challenge")
    clock[0] = at("2026-11-03T02:00:00")
    sent.clear()
    assert service.deliver_notices(RoutedSink(service.webhooks, connections)) == 1
    assert sent[-1]["disable_notification"] is True

    def alert():
        epoch = service.store.get("tenant:" + tenant).data.get("notification_epoch", 0)
        sent.clear()
        assert connections.send({**sample(), "tenant": tenant, "tenant_epoch": epoch}) is True
        return sent[-1]

    assert alert()["disable_notification"] is True
    service.set_preferences(tenant, quiet_hours=None)
    assert alert()["disable_notification"] is False


def test_the_api_saves_validates_and_previews_the_window(service, clock):
    with TestClient(create_app(service, {"alice": "a" * 40})) as client:
        saved = client.put("/v1/preferences", json={"quiet_hours": "20:00-06:00"}, headers=KEY)
        assert saved.status_code == 200 and saved.json()["quiet_hours"] == "20:00-06:00"
        assert client.get("/v1/preferences", headers=KEY).json()["quiet_hours"] == "20:00-06:00"
        refused = client.put("/v1/preferences", json={"quiet_hours": "20:00"}, headers=KEY)
        assert refused.status_code == 422
        # The shared test clock reads 21:00 UTC: inside the saved window.
        preview = client.post("/v1/preferences/telegram-preview", json={}, headers=KEY).json()
        assert preview["silent"] is True
        daytime = client.post(
            "/v1/preferences/telegram-preview", json={"quiet_hours": "01:00-05:00"}, headers=KEY
        ).json()
        assert daytime["silent"] is False
        cleared = client.put("/v1/preferences", json={"quiet_hours": None}, headers=KEY)
        assert cleared.json()["quiet_hours"] is None


def test_the_bot_turns_quiet_hours_on_and_off_with_one_tap(native_bot, service):  # noqa: F811
    tenant = native_bot[1]
    settings = _call(native_bot, "/settings")
    assert "Quiet hours: off" in settings.text
    on = _press(native_bot, settings, "Quiet hours: 10:00 PM – 7:00 AM")
    assert "Quiet hours: 10:00 PM – 7:00 AM, no sound" in on.text
    assert service.preferences(tenant)["quiet_hours"] == "22:00-07:00"
    off = _press(native_bot, on, "Turn off quiet hours")
    assert "Quiet hours: off" in off.text
    assert service.preferences(tenant)["quiet_hours"] is None

    # A window chosen on the website is shown in the reader's own clock style.
    service.set_preferences(tenant, quiet_hours="23:30-06:15", hour_cycle="h23")
    assert "Quiet hours: 23:30 – 06:15, no sound" in _call(native_bot, "/settings").text
