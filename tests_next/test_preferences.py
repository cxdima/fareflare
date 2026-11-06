"""Account preference contracts, delivery fences and regional formatting."""
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gfpt_next.api import create_app
from gfpt_next.preferences import Preferences, observed_time, regional_price, telegram_text
from gfpt_next.service import Reading
from gfpt_next.store import Conflict
from tests_next.test_hosted_mcp import application, tool


def instant(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


def sample():
    return {"id": "a" * 32, "reason": "new_low", "observation": {
        "amount_minor": 123456, "currency": "USD", "observed_at": instant("2026-11-01T06:30:00"),
        "fare_name": '<b>Economy & "basic"</b>', "price_basis": "total"},
        "itinerary": {"adults": 2, "url": "https://www.google.com/travel/flights",
                      "segments": [{"date": "2027-03-14", "legs": [{
                          "origin": "DEN", "destination": "DFW", "airline": "UA", "number": "414"}]}]}}


def test_old_mute_updates_preserve_display_settings_and_are_tenant_scoped(service):
    settings = service.set_preferences("alice", time_zone="America/Chicago", locale="fr-FR",
                                       hour_cycle="h23", telegram_silent=True)
    assert settings["muted"] is False
    assert service.tenant_notification_epoch("alice") == 0
    updated = service.set_preferences("alice", True, ["SFO-NRT", "DEN-DFW", "DEN-DFW"])
    assert updated["muted_routes"] == ["DEN-DFW", "SFO-NRT"]
    assert updated["time_zone"] == "America/Chicago" and updated["telegram_silent"] is True
    assert updated["locale"] == "fr-FR"
    assert service.tenant_notification_epoch("alice") == 1
    assert service.preferences("bob") == Preferences().model_dump()
    service.set_preferences("alice", time_zone=None)
    assert service.preferences("alice")["time_zone"] is None
    assert service.tenant_notification_epoch("alice") == 1


def test_presentation_changes_keep_queued_alerts_deliverable(service, clock, flight_url):
    monitor = service.create_monitor("alice", flight_url, "prefs-queued-alert")
    service.record(Reading(monitor["target_id"], 30000, "USD", clock[0], "fixture"), "first")
    service.process_events()
    service.set_preferences("alice", time_zone="Europe/Kyiv", telegram_style="compact",
                            telegram_show_fare=False, telegram_silent=True)
    sink = Mock()
    sink.send.return_value = True
    assert service.deliver_due(sink) == 1
    assert service.get_monitor("alice", monitor["id"])["status"] == "active"


def test_real_mute_edits_still_fence_pending_alerts(service, clock, flight_url):
    monitor = service.create_monitor("alice", flight_url, "prefs-mute-fence")
    service.record(Reading(monitor["target_id"], 30000, "USD", clock[0], "fixture"), "first")
    service.process_events()
    service.set_preferences("alice", muted=True)
    service.set_preferences("alice", locale="de-DE")
    service.set_preferences("alice", muted=False)
    sink = Mock()
    assert service.deliver_due(sink) == 0
    sink.send.assert_not_called()
    assert service.preferences("alice")["locale"] == "de-DE"


def test_concurrent_updates_merge_only_explicit_fields(service, store, monkeypatch, flight_url):
    service.create_monitor("alice", flight_url, "prefs-concurrent")
    commit, raced = store.commit, False

    def race(documents):
        nonlocal raced
        if not raced:
            raced = True
            service.set_preferences("alice", locale="de-DE", muted=True)
        return commit(documents)

    monkeypatch.setattr(store, "commit", race)
    preferences = service.set_preferences("alice", time_zone="America/Chicago")
    assert preferences["locale"] == "de-DE" and preferences["muted"] is True
    assert preferences["time_zone"] == "America/Chicago"
    assert service.tenant_notification_epoch("alice") == 1
    assert store.get("tenant:alice").data["monitors"] == 1


def test_unchanged_preferences_do_not_write_or_change_notification_epoch(service, store, monkeypatch):
    service.set_preferences("alice", telegram_silent=True)
    commit = Mock(wraps=store.commit)
    monkeypatch.setattr(store, "commit", commit)
    service.set_preferences("alice", telegram_silent=True)
    service.set_preferences("alice")
    commit.assert_not_called()
    assert service.tenant_notification_epoch("alice") == 0


def test_persistent_revision_conflicts_have_a_bounded_retry(service, store, monkeypatch):
    commit = Mock(side_effect=Conflict("conflict"))
    monkeypatch.setattr(store, "commit", commit)
    with pytest.raises(Conflict, match="Concurrent settings update"):
        service.set_preferences("alice", telegram_silent=True)
    assert commit.call_count == 5


@pytest.mark.parametrize("body", [
    {"time_zone": "Mars/Phobos"}, {"time_zone": "../UTC"}, {"time_zone": "/etc/passwd"},
    {"time_zone": "America/../UTC"}, {"time_zone": "posix/America/Chicago"},
    {"time_zone": "localtime"}, {"time_zone": "posixrules"},
    {"time_zone": ""}, {"time_zone": "a" * 81}, {"time_zone": 1},
    {"locale": "xx-XX"}, {"hour_cycle": "24"}, {"telegram_style": "html"},
    {"telegram_silent": "false"}, {"muted": None}, {"muted_routes": None},
    {"telegram_show_fare": 0}, {"telegram_show_observed_time": None},
    {"muted_routes": ["bad-route"]}, {"template": "arbitrary template"},
])
def test_api_rejects_invalid_preferences_without_writing(service, store, body):
    with TestClient(create_app(service, {"alice": "a" * 40})) as client:
        response = client.put("/v1/preferences", json=body,
                              headers={"Authorization": "Bearer " + "a" * 40})
    assert response.status_code == 422
    assert store.get("tenant:alice") is None


def test_preview_is_authenticated_uses_unsaved_values_and_has_no_side_effect(service, store):
    service.set_preferences("alice", muted=True, locale="fr-FR")
    saved = store.get("tenant:alice")
    with TestClient(create_app(service, {"alice": "a" * 40})) as client:
        assert client.post("/v1/preferences/telegram-preview", json={}).status_code == 401
        response = client.post("/v1/preferences/telegram-preview", json={
            "time_zone": "America/Chicago", "telegram_silent": True,
            "telegram_show_flight_numbers": False, "hour_cycle": "h23"},
            headers={"Authorization": "Bearer " + "a" * 40})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["text"].startswith("Example alert — sample data\n\n")
        assert "America/Chicago" in data["text"] and "UA414" not in data["text"]
        assert "USD 191,00" in data["text"]
        assert data["silent"] is True and data["time_zone"] == "America/Chicago"
        assert client.put("/v1/preferences", json={"telegram_silent": True},
                          headers={"Authorization": "Bearer " + "a" * 40}).json()["muted"] is True
    # Preview made no revision or state change; only the final explicit save did.
    assert store.get("tenant:alice").revision == saved.revision + 1
    assert service.preferences("alice")["time_zone"] is None


def test_mcp_new_settings_and_old_mute_arguments_share_partial_update_semantics(service):
    with TestClient(application(service)) as client:
        result = tool(client, "set_preferences", {"settings": {
            "time_zone": "Asia/Kathmandu", "telegram_style": "compact", "hour_cycle": "h23"}})
        assert result["structuredContent"]["time_zone"] == "Asia/Kathmandu"
        updated = tool(client, "set_preferences", {"muted": True})["structuredContent"]
        assert updated["time_zone"] == "Asia/Kathmandu" and updated["muted"] is True
        assert tool(client, "set_preferences", {})["structuredContent"] == updated
        assert tool(client, "get_preferences", tenant="bob")["structuredContent"]["time_zone"] is None
        reset = tool(client, "set_preferences", {"settings": {"time_zone": None}})["structuredContent"]
        assert reset["time_zone"] is None and reset["muted"] is True


def test_dst_fall_back_has_distinct_offsets_for_repeated_local_times():
    prefs = Preferences(time_zone="America/Chicago", hour_cycle="h23")
    first = observed_time(instant("2026-11-01T06:30:00"), prefs)
    second = observed_time(instant("2026-11-01T07:30:00"), prefs)
    assert first == "11/01/2026 01:30 America/Chicago (UTC-05:00)"
    assert second == "11/01/2026 01:30 America/Chicago (UTC-06:00)"


def test_dst_spring_forward_skips_nonexistent_time_and_date_changes_are_local():
    prefs = Preferences(time_zone="America/Chicago", hour_cycle="h23", locale="en-GB")
    assert "01:59" in observed_time(instant("2026-03-08T07:59:00"), prefs)
    assert "03:00" in observed_time(instant("2026-03-08T08:00:00"), prefs)
    assert observed_time(instant("2026-11-06T01:00:00"), prefs).startswith("05/11/2026 19:00")
    assert observed_time(instant("2026-11-06T01:00:00"), Preferences(
        time_zone="Asia/Kathmandu", locale="en-GB", hour_cycle="h23")).endswith("06:45 Asia/Kathmandu (UTC+05:45)")


def test_clock_overrides_and_null_zone_have_explicit_fallback():
    seconds = instant("2026-11-06T00:05:00")
    assert observed_time(seconds, Preferences()) == "11/06/2026 12:05 AM UTC"
    assert observed_time(seconds, Preferences(locale="en-GB")) == "06/11/2026 00:05 UTC"
    assert observed_time(seconds, Preferences(locale="de-DE", hour_cycle="h12")) == "06.11.2026 12:05 AM UTC"


@pytest.mark.parametrize(("locale", "currency", "amount", "expected"), [
    ("en-US", "USD", 123456, "USD 1,234.56"),
    ("en-GB", "GBP", 123456, "GBP 1,234.56"),
    ("de-DE", "EUR", 123456, "EUR 1.234,56"),
    ("es-ES", "EUR", 123456, "EUR 1.234,56"),
    ("fr-FR", "EUR", 123456, "EUR 1\u202f234,56"),
    ("uk-UA", "EUR", 123456, "EUR 1\u00a0234,56"),
    ("en-US", "JPY", 48706, "JPY 48,706"),
])
def test_regional_amounts_keep_original_currency_and_minor_unit_precision(locale, currency, amount, expected):
    assert regional_price(amount, currency, locale) == expected


def test_compact_message_respects_independent_fields_and_keeps_trip_party(flight_url):
    from gfpt_next.telegram_messages import alert_message
    value = sample()
    value["itinerary"]["url"] = flight_url
    detailed = telegram_text(value, Preferences())
    compact = telegram_text(value, Preferences(telegram_style="compact", telegram_show_flight_numbers=False,
                                              telegram_show_fare=False, telegram_show_observed_time=False))
    assert "UA414" in detailed and "Fare: <b>Economy" in detailed
    assert "03/14/2027" in compact  # Airport-local calendar date, never zone shifted.
    assert "Total for 2 adults" in compact
    assert all(text not in compact for text in ("UA414", "Fare:", "Observed", "Alert "))
    assert len(compact.splitlines()) < len(detailed.splitlines())
    assert "https://" not in compact
    assert alert_message(value, Preferences()).reply_markup["inline_keyboard"][0][0]["url"].startswith(
        "https://www.google.com/travel/flights/booking?")


def test_preferences_do_not_accept_timezone_path_or_markup_settings():
    with pytest.raises(ValidationError):
        Preferences(time_zone="right/UTC")
    with pytest.raises(ValidationError):
        Preferences(telegram_style="<b>compact</b>")


def test_telegram_send_escapes_provider_text_and_honors_silent_transport_flag():
    from gfpt_next.delivery import TelegramSink
    sent = []

    def transport(request):
        import json
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    sink = TelegramSink("123:" + "x" * 25, {"alice": "123"}, httpx.MockTransport(transport),
                        preferences=Preferences(time_zone="America/Chicago", telegram_silent=True))
    assert sink.send({**sample(), "tenant": "alice"})
    assert sent[0]["disable_notification"] is True
    assert sent[0]["parse_mode"] == "HTML"
    assert '&lt;b&gt;Economy &amp; &quot;basic&quot;&lt;/b&gt;' in sent[0]["text"]
    assert "America/Chicago" in sent[0]["text"]
