"""Native Telegram flows use real use cases and isolated transactional stores."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from fareflare.accounts import Accounts
from fareflare.contracts import QuoteEvidence, Reading, SliceTimes
from fareflare.links import ItineraryMessage
from fareflare.product_config import ProductConfig
from fareflare.refusals import REASONS, refusal_report
from fareflare.store import Document
from fareflare.telegram_bot import TelegramBot
from fareflare.telegram_rules import parse_amount

PASSWORD = "private native bot test password"
SAFARI_CITY = Path(__file__).parent / "fixtures/selected_city_safari.json"


@pytest.fixture
def native_bot(service, store, clock):
    accounts = Accounts(store, ProductConfig(), lambda: clock[0])
    user = accounts.register("native-traveler@example.com", PASSWORD)["account"]
    tenant, chat = user["id"], "123456"
    _bind(store, tenant, chat)
    bot = TelegramBot(service, accounts, "https://fareflare.test", clock=lambda: clock[0])
    return bot, tenant, chat


def _bind(store, tenant, chat, generation="connection-a"):
    data = {
        "tenant": tenant,
        "chat_id": chat,
        "auth_epoch": 1,
        "connected": True,
        "connection_id": generation,
        "connected_at": 123,
    }
    for key, partition in (
        ("telegram-account:" + tenant, "telegram-accounts"),
        ("telegram-chat:" + chat, "telegram-chats"),
    ):
        doc = store.get(key) or Document(key, partition, {})
        store.commit([doc.update(data)])


def _call(native, text=None, callback=None):
    bot, tenant, chat = native
    message = bot.handle(tenant, chat, 1, text=text, callback_data=callback, update_id=1)
    assert len(message.text.encode("utf-16-le")) // 2 <= 4096
    for row in (message.reply_markup or {}).get("inline_keyboard", []):
        for button in row:
            if "callback_data" in button:
                assert len(button["callback_data"].encode()) <= 64
                assert tenant not in button["callback_data"]
                assert chat not in button["callback_data"]
    message.payload()
    return message


def _token(message, label):
    matches = [
        button["callback_data"]
        for row in message.reply_markup["inline_keyboard"]
        for button in row
        if button["text"] == label
    ]
    assert len(matches) == 1, (label, message.text, message.reply_markup)
    return matches[0]


def _press(native, message, label):
    return _call(native, callback=_token(message, label))


def _labels(message):
    return [button["text"] for row in message.reply_markup["inline_keyboard"] for button in row]


def _detail(native, monitor):
    """Open a flight the way a reader does: from the list, through the picker if there is one."""
    flights = _call(native, "/flights")
    if "Manage this flight" in _labels(flights):
        return _press(native, flights, "Manage this flight")
    leg = monitor["target"]["segments"][0]["legs"][0]
    picker = _press(native, flights, "Manage a flight")
    return _press(native, picker, f"DEN → DFW · Mar 14 · {leg['airline']} {leg['number']}")


def test_add_requires_confirmation_and_replay_never_duplicates(
    native_bot, service, store, flight_url
):
    _, tenant, _ = native_bot
    preview = _call(native_bot, flight_url)
    assert "UA 414" in preview.text and "Economy" in preview.text and "1 adult" in preview.text
    assert "Checks requested every 10 min." in preview.text
    assert service.monitors_page(tenant)["active_count"] == 0
    token = _token(preview, "Start watching")
    added = _call(native_bot, callback=token)
    assert "Flight added" in added.text and "Waiting for the first price check" in added.text
    assert service.monitors_page(tenant)["active_count"] == 1
    assert service.monitors_page(tenant)["items"][0]["interval_seconds"] == 600
    assert "already applied" in _call(native_bot, callback=token).text
    assert service.monitors_page(tenant)["active_count"] == 1
    action = store.get("telegram-action:" + hashlib.sha256(token[3:].encode()).hexdigest())
    assert action.data["used"] is True
    assert token[3:] not in json.dumps(action.data)


def test_cancel_and_replaced_preview_invalidate_prior_confirmation(native_bot, service, flight_url):
    first = _call(native_bot, "/add " + flight_url)
    second = _call(native_bot, flight_url)
    assert "no longer current" in _press(native_bot, first, "Start watching").text
    _call(native_bot, "/cancel")
    assert "no longer current" in _press(native_bot, second, "Start watching").text
    assert service.monitors_page(native_bot[1])["active_count"] == 0


def test_old_inline_cancel_cannot_cancel_a_newer_add_confirmation(native_bot, service, flight_url):
    first = _call(native_bot, flight_url)
    second = _call(native_bot, flight_url)
    assert "newer request is unchanged" in _press(native_bot, first, "Cancel").text
    assert "Flight added" in _press(native_bot, second, "Start watching").text
    assert service.monitors_page(native_bot[1])["active_count"] == 1


def test_old_inline_cancel_cannot_cancel_a_newer_price_prompt_or_confirmation(
    native_bot, service, flight_url
):
    monitor = service.create_monitor(native_bot[1], flight_url, "scoped-cancel")
    rules = _press(native_bot, _detail(native_bot, monitor), "Alert rules")
    first_prompt = _press(native_bot, rules, "Set target price")
    second_prompt = _press(native_bot, rules, "Set target price")
    assert "newer request is unchanged" in _press(native_bot, first_prompt, "Cancel").text
    confirmation = _call(native_bot, "150.00")
    assert "newer request is unchanged" in _press(native_bot, second_prompt, "Cancel").text
    _press(native_bot, confirmation, "Save alert rule")
    assert service.get_monitor(native_bot[1], monitor["id"])["policy"]["threshold_minor"] == 15000


def test_inline_cancel_uses_a_revision_fence_when_a_new_draft_arrives(
    native_bot, service, store, flight_url, monkeypatch
):
    _, tenant, _ = native_bot
    first = _call(native_bot, flight_url)
    real_commit, replacement = store.commit, []

    def racing_commit(documents):
        if not replacement and any(
            doc.key == "telegram-draft:" + tenant and doc.data == {"action": None}
            for doc in documents
        ):
            draft = store.get("telegram-draft:" + tenant)
            replacement.append(
                draft.update({"action": "newer-request", "generation": "newer-generation"})
            )
            real_commit(replacement)
        real_commit(documents)

    monkeypatch.setattr(store, "commit", racing_commit)
    assert "changed" in _press(native_bot, first, "Cancel").text
    assert store.get("telegram-draft:" + tenant).data["action"] == "newer-request"
    assert service.monitors_page(tenant)["active_count"] == 0


def test_a_refused_link_says_why_and_adds_nothing(native_bot, service, store, flight_url, clock):
    message = _call(native_bot, "https://example.com/?token=private")
    assert message.text.startswith("Fareflare can't watch this link")
    assert REASONS["not_flights"] in message.text and "Nothing has been added." in message.text
    assert "private" not in message.text and "Diagnostic code" not in message.text
    # The exact fault is for accounts that asked for technical detail.
    service.set_preferences(native_bot[1], diagnostics=True)
    refused = _call(native_bot, "https://example.com/?token=private").text
    assert "Diagnostic code: not_google" in refused
    assert refusal_report(store, clock[0])["reasons"][0]["checks"] == {"not_google": 2}
    clock[0] += 86400 * 500
    assert REASONS["departed"] in _call(native_bot, flight_url).text
    assert service.monitors_page(native_bot[1])["active_count"] == 0
    assert refusal_report(store, clock[0])["reasons"][0]["checks"] == {"departed": 1}


def test_a_link_shared_from_safari_after_a_city_search_is_offered(native_bot):
    message = _call(native_bot, json.loads(SAFARI_CITY.read_text())["url"])
    assert message.text.startswith("Watch ")
    assert "Start watching" in _labels(message)


def test_quota_error_is_useful_and_retains_the_confirmation(native_bot, service, flight_url):
    service.monitor_limit = 1
    service.create_monitor(native_bot[1], flight_url, "existing-flight")
    preview = _call(native_bot, flight_url)
    assert "watch 1 flight" in _press(native_bot, preview, "Start watching").text
    assert service.monitors_page(native_bot[1])["active_count"] == 1


def test_flights_and_history_are_bounded_and_paginate(
    native_bot, service, flight_url, clock, monkeypatch
):
    tenant = native_bot[1]
    for i in range(6):
        service.create_monitor(tenant, flight_url, f"flight-page-{i}")
    whole = _call(native_bot, "/flights")
    assert whole.text.split("\n")[:3] == ["Your flights (6)", "", "🛫 DEN → DFW · Mar 14"]
    assert whole.text.count("• UA 414") == 6 and "Next flights" not in _labels(whole)
    # A page holds what fits in one message, not a fixed number of flights.
    monkeypatch.setattr("fareflare.telegram_bot._LIST_BUDGET", 150)
    flights = _call(native_bot, "/flights")
    assert flights.text.count("• UA 414") == 4 and "Flights 1–4 of 6" in flights.text
    next_page = _press(native_bot, flights, "Next flights")
    assert next_page.text.count("• UA 414") == 2 and "Flights 5–6 of 6" in next_page.text
    assert next_page.text.count("🛫 DEN → DFW") == 1 and "Next flights" not in _labels(next_page)
    assert _press(native_bot, next_page, "First page").text.count("• UA 414") == 4
    monitor = service.monitors_page(tenant)["items"][0]
    for i in range(12):
        clock[0] += 1
        service.record(
            Reading(monitor["target_id"], 10000 + i * 100, "USD", clock[0], "test"), f"reading-{i}"
        )
    picker = _press(native_bot, _call(native_bot, "/flights"), "Manage a flight")
    assert picker.text == "Choose a flight" and len(_labels(picker)) == 7
    detail = _call(
        native_bot, callback=picker.reply_markup["inline_keyboard"][0][0]["callback_data"]
    )
    prices = _press(native_bot, detail, "Recent prices")
    assert prices.text.split("\n")[0] == "Recorded prices: DEN → DFW"
    assert "$111 · " in prices.text and "$102 · " in prices.text and "$101 · " not in prices.text
    assert "Lowest of these: $102" in prices.text and "USD" not in prices.text
    previous = _press(native_bot, prices, "Earlier prices")
    assert "$100 · " in previous.text and "$111 · " not in previous.text
    assert "$111 · " in _press(native_bot, previous, "Latest prices").text


def test_the_list_shows_current_flights_only_and_one_flight_opens_directly(
    native_bot, service, flight_url, clock
):
    tenant = native_bot[1]
    empty = _call(native_bot, "/flights")
    assert empty.text.startswith("Your flights\n\nNo flights yet.")
    assert "Manage a flight" not in _labels(empty) and "Watch a flight" in _labels(empty)
    kept = service.create_monitor(tenant, _other_flight(flight_url, "100"), "kept-flight")
    stopped = service.create_monitor(tenant, _other_flight(flight_url, "200"), "stopped-flight")
    paused = service.create_monitor(tenant, _other_flight(flight_url, "300"), "paused-flight")
    service.set_status(tenant, stopped["id"], "cancelled")
    service.set_status(tenant, paused["id"], "paused")
    flights = _call(native_bot, "/flights")
    assert flights.text.startswith("Your flights (2)")
    assert "UA 100" in flights.text and "UA 300 · Paused" in flights.text
    assert "UA 200" not in flights.text
    assert service.current_monitors(tenant) != []
    assert len(service.monitors_page(tenant)["items"]) == 3
    picker = _press(native_bot, flights, "Manage a flight")
    assert _labels(picker) == [
        "DEN → DFW · Mar 14 · UA 100",
        "DEN → DFW · Mar 14 · UA 300",
        "Back to my flights",
    ]
    service.set_status(tenant, paused["id"], "cancelled")
    alone = _call(native_bot, "/flights")
    assert "Manage a flight" not in _labels(alone)
    detail = _press(native_bot, alone, "Manage this flight")
    assert detail.text.split("\n")[:3] == ["DEN → DFW · Mar 14", "", "UA 100"]
    assert kept["id"] == service.current_monitors(tenant)[0]["id"]


def test_choosing_a_flight_is_paged_when_there_are_many(native_bot, service, flight_url):
    tenant = native_bot[1]
    for number in range(100, 111):
        service.create_monitor(tenant, _other_flight(flight_url, str(number)), f"many-{number}")
    picker = _press(native_bot, _call(native_bot, "/flights"), "Manage a flight")
    assert "Flights 1–8 of 11" in picker.text
    assert _labels(picker)[:1] == ["DEN → DFW · Mar 14 · UA 100"] and len(_labels(picker)) == 10
    more = _press(native_bot, picker, "More flights")
    assert "Flights 9–11 of 11" in more.text
    assert _labels(more) == [
        "DEN → DFW · Mar 14 · UA 108",
        "DEN → DFW · Mar 14 · UA 109",
        "DEN → DFW · Mar 14 · UA 110",
        "First flights",
        "Back to my flights",
    ]
    assert "Flights 1–8 of 11" in _press(native_bot, more, "First flights").text


def _other_flight(url, number):
    params = parse_qs(urlsplit(url).query)
    message, token = ItineraryMessage(), params["tfs"][0]
    message.ParseFromString(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    message.segments[0].legs[0].number = number
    params["tfs"] = [base64.urlsafe_b64encode(message.SerializeToString()).decode().rstrip("=")]
    return "https://www.google.com/travel/flights?" + urlencode(params, doseq=True)


def test_a_day_is_listed_by_departure_time_and_detail_shows_the_times(
    native_bot, service, flight_url, clock
):
    tenant = native_bot[1]
    evidence = QuoteEvidence("test", True, True, True, 1)
    # Added latest-first, so only the recorded times can put them in order.
    for number, departs in (("900", "19:40"), ("414", "15:50"), ("100", "07:05")):
        monitor = service.create_monitor(
            tenant, _other_flight(flight_url, number), f"same-day-{number}"
        )
        clock[0] += 1
        service.record(
            Reading(
                monitor["target_id"],
                20000,
                "USD",
                clock[0],
                "test",
                price_basis="total",
                evidence=evidence,
                schedule=(SliceTimes(departs, "22:41", 0, 121),),
            ),
            f"run-{number}",
        )
    service.process_events()
    untimed = service.create_monitor(tenant, _other_flight(flight_url, "555"), "same-day-untimed")
    service.set_preferences(tenant, hour_cycle="h23")
    flights = _call(native_bot, "/flights")
    rows = [line for line in flights.text.split("\n") if line.startswith("• ")]
    assert [row.split()[2] for row in rows] == ["100", "414", "900", "555"]
    assert "• UA 100 07:05→22:41 · $200 🔥 at the low" in rows
    assert untimed["latest"] is None and rows[-1] == "• UA 555 · Awaiting check"
    assert "<code>UA 100</code> 07:05→22:41 · <b>$200</b> <i>🔥 at the low</i>" in flights.html
    # The line under the list says when the newest of these prices was checked.
    assert flights.text.split("\n")[-1] == "Latest check 11/02/2026 21:00 UTC"
    assert flights.html.split("\n")[-1] == "<i>Latest check 11/02/2026 21:00 UTC</i>"
    detail = _detail(native_bot, monitor)
    assert detail.text.split("\n")[:6] == [
        "DEN → DFW · Mar 14",
        "",
        "UA 100 · 07:05 → 22:41 · 2 hr 1 min",
        "1 adult · Economy",
        "",
        "$200 🔥 at the low",
    ]
    # The same flights in the other built-in style: one block each, in the same order.
    service.set_preferences(tenant, telegram_style="detailed")
    blocks = _call(native_bot, "/flights").text.split("\n\n")[1:-1]
    assert blocks[0] == "DEN → DFW · Mar 14\nUA 100 · 07:05 → 22:41 · $200\n🔥 At its lowest"
    assert [block.split("\n")[1].split(" · ")[0] for block in blocks] == [
        "UA 100",
        "UA 414",
        "UA 900",
        "UA 555",
    ]


def test_pause_resume_and_stop_confirmations_use_shared_service(native_bot, service, flight_url):
    monitor = service.create_monitor(native_bot[1], flight_url, "control-flight")
    detail = _detail(native_bot, monitor)
    unused_old_pause = _detail(native_bot, monitor)
    paused = _press(native_bot, detail, "Pause watching")
    assert service.get_monitor(native_bot[1], monitor["id"])["status"] == "paused"
    resumed = _press(native_bot, paused, "Resume watching")
    assert service.get_monitor(native_bot[1], monitor["id"])["status"] == "pending"
    assert "no longer current" in _press(native_bot, unused_old_pause, "Pause watching").text
    confirmation = _press(native_bot, resumed, "Stop watching…")
    assert service.get_monitor(native_bot[1], monitor["id"])["status"] == "pending"
    _press(native_bot, confirmation, "Stop watching")
    assert service.get_monitor(native_bot[1], monitor["id"])["status"] == "cancelled"
    assert service.monitors_page(native_bot[1])["active_count"] == 0


def test_settings_keep_localization_and_explicit_actions_are_single_use(native_bot, service):
    tenant = native_bot[1]
    service.set_preferences(
        tenant, time_zone="America/Chicago", locale="de-DE", muted_routes=["SFO-NRT"]
    )
    settings = _call(native_bot, "/settings")
    assert "America/Chicago" in settings.text and "de-DE" in settings.text
    muted = _press(native_bot, settings, "Mute alerts")
    unmuted = _press(native_bot, muted, "Turn alerts on")
    assert "already applied" in _press(native_bot, settings, "Mute alerts").text
    silent = _press(native_bot, unmuted, "Send silently")
    styles = _press(native_bot, silent, "Message style")
    assert "Compact: an example with sample data." in styles.text
    assert "🔥 New low · 191" in styles.text and "🔥 <b>New low</b>" in styles.html
    # Only styles that have wording are offered; custom wording is written on the website.
    # Under them: what this style's alerts can leave out, then the buttons beneath alerts.
    assert _labels(styles) == [
        "✓ Compact",
        "Detailed",
        "✓ Flight numbers",
        "✓ Departure and arrival times",
        "✓ Buttons under alerts",
        "Write your own messages",
        "Back to alert settings",
    ]
    chosen = _press(native_bot, styles, "Detailed")
    assert "Message settings saved." in chosen.text
    assert "Detailed: an example with sample data." in chosen.text
    assert _labels(chosen)[:6] == [
        "Compact",
        "✓ Detailed",
        "✓ Flight numbers",
        "✓ Departure and arrival times",
        "✓ Time the price was checked",
        "✓ Fare name",
    ]
    prefs = service.preferences(tenant)
    assert (
        prefs["muted"] is False
        and prefs["telegram_silent"] is True
        and prefs["telegram_style"] == "detailed"
    )
    assert prefs["locale"] == "de-DE" and prefs["muted_routes"] == ["SFO-NRT"]


def test_message_options_are_switched_where_the_example_shows_their_effect(native_bot, service):
    tenant = native_bot[1]
    styles = _press(native_bot, _call(native_bot, "/settings"), "Message style")
    assert "UA 414" in styles.text
    hidden = _press(native_bot, styles, "✓ Flight numbers")
    # The example is drawn again without what was switched off, and the mark is gone.
    assert "Message settings saved." in hidden.text and "UA 414" not in hidden.text
    assert "Flight numbers" in _labels(hidden) and "✓ Flight numbers" not in _labels(hidden)
    assert service.preferences(tenant)["telegram_show_flight_numbers"] is False
    shown = _press(native_bot, hidden, "Flight numbers")
    assert "UA 414" in shown.text and "✓ Flight numbers" in _labels(shown)
    plain = _press(native_bot, shown, "✓ Buttons under alerts")
    assert "Buttons under alerts" in _labels(plain)
    assert service.preferences(tenant)["telegram_show_buttons"] is False
    # Own wording decides for itself what it shows, so it has no switches.
    service.set_preferences(
        tenant, telegram_style="custom", telegram_templates={"new_low": "{price_short} {route}"}
    )
    custom = _call(native_bot, "/settings")
    custom = _press(native_bot, custom, "Message style")
    assert _labels(custom) == [
        "Compact",
        "Detailed",
        "✓ Custom",
        "Buttons under alerts",
        "Write your own messages",
        "Back to alert settings",
    ]
    assert custom.text.split("\n")[-1] == "$191 DEN → DFW"


def test_the_flight_list_is_sorted_by_departure_or_by_price(native_bot, service, flight_url, clock):
    tenant = native_bot[1]
    first = service.create_monitor(tenant, _other_flight(flight_url, "100"), "sort-first")
    alone = _call(native_bot, "/flights")
    # One flight has no order to choose.
    assert not any(label.startswith("Sort by") for label in _labels(alone))
    second = service.create_monitor(tenant, _other_flight(flight_url, "200"), "sort-second")
    for monitor, amount in ((first, 30000), (second, 20000)):
        reading = Reading(monitor["target_id"], amount, "USD", clock[0], "test")
        service.record(reading, f"sort-{amount}")
    service.process_events()
    flights = _call(native_bot, "/flights")
    assert flights.text.index("UA 100") < flights.text.index("UA 200")
    assert "Sort by price" in _labels(flights) and "Sort by departure" not in _labels(flights)
    by_price = _press(native_bot, flights, "Sort by price")
    assert "Flight list order saved." in by_price.text
    assert by_price.text.index("UA 200") < by_price.text.index("UA 100")
    assert service.preferences(tenant)["telegram_list_order"] == "price"
    # The order is the account's: every later list and the picker use it.
    again = _call(native_bot, "/flights")
    assert again.text.index("UA 200") < again.text.index("UA 100")
    picker = _press(native_bot, again, "Manage a flight")
    assert _labels(picker)[:2] == ["DEN → DFW · Mar 14 · UA 200", "DEN → DFW · Mar 14 · UA 100"]
    back = _press(native_bot, again, "Sort by departure")
    assert back.text.index("UA 100") < back.text.index("UA 200")
    assert service.preferences(tenant)["telegram_list_order"] == "departure"


def test_forged_foreign_and_expired_callbacks_never_mutate(
    native_bot, service, store, flight_url, clock
):
    bot, tenant, chat = native_bot
    preview = _call(native_bot, flight_url)
    token = _token(preview, "Start watching")
    other = bot.accounts.register("different-traveler@example.com", PASSWORD)["account"]["id"]
    _bind(store, other, "987654", "different-connection")
    assert "belongs to another" in bot.handle(other, "987654", 1, callback_data=token).text
    assert service.monitors_page(other)["active_count"] == 0
    assert "expired" in _call(native_bot, callback="ff:" + "x" * 24).text
    assert "expired" in _call(native_bot, callback="ff:" + "x" * 10000).text
    clock[0] += 900
    assert "expired" in bot.handle(tenant, chat, 1, callback_data=token).text
    assert service.monitors_page(tenant)["active_count"] == 0


@pytest.mark.parametrize("change", ["disconnect", "reconnect", "recover", "chat-owner"])
def test_changed_connection_or_account_cannot_use_old_menu(
    native_bot, service, store, flight_url, change
):
    _, tenant, chat = native_bot
    preview = _call(native_bot, flight_url)
    if change == "disconnect":
        doc = store.get("telegram-account:" + tenant)
        store.commit([doc.update({**doc.data, "connected": False})])
    elif change == "reconnect":
        _bind(store, tenant, chat, "new-connection-same-second")
    elif change == "recover":
        doc = store.get("account:" + tenant)
        store.commit([doc.update({**doc.data, "auth_epoch": 2})])
    else:
        doc = store.get("telegram-chat:" + chat)
        store.commit([doc.update({**doc.data, "tenant": "acct_someone_else"})])
    result = _press(native_bot, preview, "Start watching")
    assert "no longer current" in result.text or "another session" in result.text
    assert service.monitors_page(tenant)["active_count"] == 0


def test_disconnect_race_rolls_back_monitor_and_action_atomically(
    native_bot, service, store, flight_url, monkeypatch
):
    tenant = native_bot[1]
    monitor = service.create_monitor(tenant, flight_url, "racing-flight")
    detail = _detail(native_bot, monitor)
    token = _token(detail, "Pause watching")
    real_commit, injected = store.commit, []

    def racing_commit(documents):
        if not injected and any(
            doc.key == "monitor:" + monitor["id"] and doc.data.get("status") == "paused"
            for doc in documents
        ):
            injected.append(True)
            binding = store.get("telegram-account:" + tenant)
            real_commit([binding.update({**binding.data, "connected": False})])
        real_commit(documents)

    monkeypatch.setattr(store, "commit", racing_commit)
    result = _call(native_bot, callback=token)
    assert "changed" in result.text
    assert service.get_monitor(tenant, monitor["id"])["status"] == "pending"
    action = store.get("telegram-action:" + hashlib.sha256(token[3:].encode()).hexdigest())
    assert action.data["used"] is False


def test_provider_text_is_escaped_and_observed_times_use_saved_zone(
    native_bot, service, flight_url, clock
):
    monitor = service.create_monitor(native_bot[1], flight_url, "escaped-fare")
    service.set_preferences(native_bot[1], time_zone="America/Chicago", hour_cycle="h23")
    service.record(
        Reading(
            monitor["target_id"],
            12345,
            "USD",
            clock[0],
            "test",
            fare_name='<b>Fare</b>\n<a href="https://bad.test">Click</a>',
        ),
        "escaped-reading",
    )
    detail = _detail(native_bot, monitor)
    # 21:00 UTC is 15:00 in Chicago, and a saved zone is the reader's own, so it has no label.
    assert "$123.45" in detail.text and "Checked 11/02/2026 15:00\n" in detail.text
    assert "USD" not in detail.text and "America/Chicago" not in detail.text
    assert "<b>$123.45</b>" in detail.html
    assert "&lt;b&gt;Fare&lt;/b&gt;" in detail.html
    assert '<a href="https://bad.test">' not in detail.html
    assert "\n<a" not in detail.text


def test_native_rule_prompt_confirms_locale_price_and_preserves_rebound_setting(
    native_bot, service, flight_url
):
    tenant = native_bot[1]
    service.set_preferences(tenant, locale="de-DE")
    monitor = service.create_monitor(tenant, flight_url, "rule-flight")
    rules = _press(native_bot, _detail(native_bot, monitor), "Alert rules")
    rules = _press(native_bot, rules, "Enable rebound alerts")
    _press(native_bot, rules, "Set target price")
    assert "valid USD amount" in _call(native_bot, "1.234,50").text
    preview = _call(native_bot, "250,50")
    assert "reaches or crosses below 250,50\xa0$." in preview.text
    assert service.get_monitor(tenant, monitor["id"])["policy"]["kind"] == "new_low"
    saved = _press(native_bot, preview, "Save alert rule")
    policy = service.get_monitor(tenant, monitor["id"])["policy"]
    assert (
        policy["kind"] == "below_price"
        and policy["threshold_minor"] == 25050
        and policy["notify_rebounds"]
    )
    assert "Notify on: a price at or below 250,50\xa0$" in saved.text
    rules = _press(native_bot, saved, "New observed lows")
    _press(native_bot, rules, "Set minimum drop")
    preview = _call(native_bot, "0")
    assert "Alert on every new observed low." in preview.text
    assert "Minimum drop: none" in _press(native_bot, preview, "Save alert rule").text
    policy = service.get_monitor(tenant, monitor["id"])["policy"]
    assert (
        policy["kind"] == "new_low" and policy["min_drop_minor"] == 0 and policy["notify_rebounds"]
    )


def test_cancelled_expired_and_rebound_after_target_change_do_not_apply_old_rule(
    native_bot, service, flight_url, clock
):
    monitor = service.create_monitor(native_bot[1], flight_url, "cancel-rule")
    rules = _press(native_bot, _detail(native_bot, monitor), "Alert rules")
    old_rebound = _token(rules, "Enable rebound alerts")
    _press(native_bot, rules, "Set target price")
    target = _call(native_bot, "100.00")
    _call(native_bot, "/cancel")
    assert "no longer current" in _press(native_bot, target, "Save alert rule").text
    rules = _press(native_bot, _detail(native_bot, monitor), "Alert rules")
    _press(native_bot, rules, "Set target price")
    _press(native_bot, _call(native_bot, "/target 120.00"), "Save alert rule")
    assert "no longer current" in _call(native_bot, callback=old_rebound).text
    rules = _press(native_bot, _detail(native_bot, monitor), "Alert rules")
    _press(native_bot, rules, "Set target price")
    clock[0] += 900
    assert "expired" in _call(native_bot, "300.00").text
    assert service.get_monitor(native_bot[1], monitor["id"])["policy"]["threshold_minor"] == 12000


@pytest.mark.parametrize(
    ("value", "currency", "locale", "amount"),
    [
        ("123.45", "USD", "en-US", 12345),
        ("123,45", "EUR", "de-DE", 12345),
        ("25000", "JPY", "en-US", 25000),
        ("1", "USD", "en-GB", 100),
        ("0.01", "USD", "en-US", 1),
    ],
)
def test_rule_money_has_exact_minor_units(value, currency, locale, amount):
    assert parse_amount(value, currency, locale) == amount


@pytest.mark.parametrize(
    "value",
    [
        "NaN",
        "Infinity",
        "-1",
        "+1",
        "1e3",
        "1,000.00",
        "1.234",
        "1,00",
        "0",
        "1000000.01",
        "$100",
        "١٢",
    ],
)
def test_rule_money_rejects_ambiguous_or_invalid_values(value):
    with pytest.raises(ValueError):
        parse_amount(value, "USD", "en-US")


def test_jpy_rejects_decimals_and_zero_is_only_allowed_for_minimum_drop():
    with pytest.raises(ValueError):
        parse_amount("123.00", "JPY", "en-US")
    assert parse_amount("0", "JPY", "en-US", allow_zero=True) == 0
