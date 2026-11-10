"""Webhook identity, reply retry, and callback-edit boundaries without Telegram access."""

import json
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from fareflare.accounts import Accounts
from fareflare.product_config import ProductConfig
from fareflare.telegram_accounts import TelegramConnections
from fareflare.telegram_messages import TelegramMessage

PASSWORD = "private development passphrase"
TOKEN = "123456:" + "x" * 30


def message(text="/flights", identifier=2):
    return {
        "update_id": identifier,
        "message": {
            "text": text,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 123, "is_bot": False},
        },
    }


def callback(identifier=2):
    return {
        "update_id": identifier,
        "callback_query": {
            "id": "query-" + str(identifier),
            "from": {"id": 123, "is_bot": False},
            "data": "ff:example",
            "message": {
                "message_id": 77,
                "date": 1793653200,
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 123456, "is_bot": True},
            },
        },
    }


class Controls:
    def __init__(self):
        self.calls = []

    def handle(self, *args):
        self.calls.append(args)
        return TelegramMessage("Private flight details", "<b>Private flight details</b>")


@pytest.fixture
def case(store, clock, service):
    accounts = Accounts(store, ProductConfig(registration_mode="open"), lambda: clock[0])
    user = accounts.register("traveler", PASSWORD)
    requests = []
    failures = {}

    def transport(request):
        method = request.url.path.rsplit("/", 1)[-1]
        requests.append((method, json.loads(request.content)))
        if method in failures:
            code, data = failures[method]
            return httpx.Response(code, json=data)
        return httpx.Response(200, json={"ok": True})

    bot = TelegramConnections(
        store,
        accounts,
        TOKEN,
        "fareflare_bot",
        "https://fareflare.test",
        clock=lambda: clock[0],
        service=service,
        transport=httpx.MockTransport(transport),
    )
    controls = Controls()
    bot._bot = controls
    link = bot.connect(user["account"]["id"])
    token = parse_qs(urlsplit(link["url"]).query)["start"][0]
    assert bot.handle_update(message("/start " + token, identifier=1))
    requests.clear()
    controls.calls.clear()
    return bot, controls, accounts, user, requests, failures


def test_callback_uses_human_identity_but_edits_the_bot_message(case):
    bot, controls, _, _, requests, _ = case
    update = callback()
    assert bot.handle_update(update)
    assert [method for method, _ in requests] == ["answerCallbackQuery", "editMessageText"]
    assert requests[-1][1]["message_id"] == 77
    assert requests[-1][1]["chat_id"] == "123"
    assert requests[-1][1]["parse_mode"] == "HTML"
    assert controls.calls[0][3:5] == (None, "ff:example")
    assert bot.handle_update(update)
    assert len(requests) == 2 and len(controls.calls) == 1


@pytest.mark.parametrize(
    "change", ["sender", "group", "author", "bot", "inaccessible", "long", "no_message", "unicode"]
)
def test_invalid_callbacks_are_acknowledged_without_account_reads_or_edits(case, change):
    bot, controls, _, _, requests, _ = case
    update = callback()
    query = update["callback_query"]
    if change == "sender":
        query["from"]["id"] = 456
    elif change == "group":
        query["message"]["chat"]["type"] = "group"
    elif change == "author":
        query["message"]["from"]["id"] = 789
    elif change == "bot":
        query["from"]["is_bot"] = True
    elif change == "inaccessible":
        query["message"]["date"] = 0
    elif change == "long":
        query["data"] = "x" * 65
    elif change == "unicode":
        query["data"] = "\ud800"
    else:
        del query["message"]
    assert bot.handle_update(update)
    assert [method for method, _ in requests] == ["answerCallbackQuery"]
    assert not controls.calls


def test_failed_reply_retries_saved_result_without_repeating_the_command(case, clock, store):
    bot, controls, _, _, requests, failures = case
    failures["sendMessage"] = (503, {"ok": False, "error_code": 503})
    update = message()
    assert not bot.handle_update(update)
    cached = deepcopy(store.get("telegram-update:2").data["reply"])
    assert len(controls.calls) == 1
    assert not bot.handle_update(update)  # Lease/retry delay prevents a hot loop.
    assert len(requests) == 1
    failures.clear()
    clock[0] += 2
    assert bot.handle_update(update)
    assert len(controls.calls) == 1
    assert requests[-1][1]["text"] == cached["html"]
    assert store.get("telegram-update:2").data["done"] is True


def test_flood_control_honors_retry_after_and_cached_reply(case, clock):
    bot, controls, _, _, requests, failures = case
    failures["sendMessage"] = (
        429,
        {"ok": False, "error_code": 429, "parameters": {"retry_after": 17}},
    )
    update = message()
    assert not bot.handle_update(update)
    clock[0] += 16
    assert not bot.handle_update(update)
    assert len(requests) == 1
    failures.clear()
    clock[0] += 1
    assert bot.handle_update(update)
    assert len(controls.calls) == 1


@pytest.mark.parametrize("change", ["disconnect", "recover", "rebind"])
def test_queued_reply_cannot_cross_connection_or_account_boundaries(case, clock, change):
    bot, controls, accounts, user, requests, failures = case
    failures["sendMessage"] = (503, {"ok": False})
    update = message()
    assert not bot.handle_update(update)
    tenant = user["account"]["id"]
    if change == "recover":
        accounts.recover("traveler", user["recovery_code"], "replacement private passphrase")
    else:
        bot.disconnect(tenant)
        if change == "rebind":
            other = accounts.register("another", PASSWORD)["account"]["id"]
            failures.clear()
            token = parse_qs(urlsplit(bot.connect(other)["url"]).query)["start"][0]
            assert bot.handle_update(message("/start " + token, identifier=3))
    before = len(requests)
    calls = len(controls.calls)
    failures.clear()
    clock[0] += 2
    assert bot.handle_update(update)
    assert len(requests) == before and len(controls.calls) == calls


def test_update_identifier_cannot_be_reused_with_different_payload(case, clock):
    bot, controls, _, _, requests, failures = case
    failures["sendMessage"] = (503, {"ok": False})
    assert not bot.handle_update(message())
    clock[0] += 2
    failures.clear()
    assert bot.handle_update(message("/settings"))
    assert len(controls.calls) == 1 and len(requests) == 1
    assert bot.handle_update(message())
    assert len(requests) == 2


@pytest.mark.parametrize(
    "description, expected",
    [
        ("Bad Request: message is not modified", ["answerCallbackQuery", "editMessageText"]),
        (
            "Bad Request: message can't be edited",
            ["answerCallbackQuery", "editMessageText", "sendMessage"],
        ),
    ],
)
def test_old_inline_message_edit_outcomes_are_handled(case, description, expected):
    bot, _, _, _, requests, failures = case
    failures["editMessageText"] = (
        400,
        {"ok": False, "error_code": 400, "description": description},
    )
    assert bot.handle_update(callback())
    assert [method for method, _ in requests] == expected


def test_callback_reply_failure_retries_edit_without_repeating_action(case, clock):
    bot, controls, _, _, requests, failures = case
    failures["editMessageText"] = (500, {"ok": False, "error_code": 500})
    assert not bot.handle_update(callback())
    failures.clear()
    clock[0] += 2
    assert bot.handle_update(callback())
    assert len(controls.calls) == 1
    assert [method for method, _ in requests] == ["answerCallbackQuery", "editMessageText"] * 2


def test_blocked_bot_does_not_retry_an_undeliverable_reply(case, clock):
    bot, controls, _, _, requests, failures = case
    failures["sendMessage"] = (403, {"ok": False, "error_code": 403})
    assert bot.handle_update(message())
    clock[0] += 30
    assert bot.handle_update(message())
    assert len(controls.calls) == 1 and len(requests) == 1


def test_old_stop_command_cannot_disconnect_a_new_connection(case, monkeypatch):
    bot, _, _, user, _, _ = case
    tenant = user["account"]["id"]
    original = bot.disconnect
    raced = False

    def disconnect(owner, *, expected=None):
        nonlocal raced
        if expected is not None and not raced:
            raced = True
            original(owner)
            token = parse_qs(urlsplit(bot.connect(owner)["url"]).query)["start"][0]
            new = message("/start " + token, identifier=3)
            new["message"]["chat"]["id"] = 456
            new["message"]["from"]["id"] = 456
            assert bot.handle_update(new)
        return original(owner, expected=expected)

    monkeypatch.setattr(bot, "disconnect", disconnect)
    assert bot.handle_update(message("/stop"))
    assert raced and bot.status(tenant)["connected"]
    assert bot.store.get("telegram-account:" + tenant).data["chat_id"] == "456"


@pytest.mark.parametrize(
    "method, code, body",
    [
        (
            "editMessageText",
            500,
            {"ok": False, "error_code": 400, "description": "message is not modified"},
        ),
        ("sendMessage", 500, {"ok": False, "error_code": 403}),
        ("sendMessage", 200, {"ok": False, "error_code": 403}),
        ("editMessageText", 200, {"ok": False, "description": "message is not modified"}),
        ("sendMessage", 503, {"ok": False, "parameters": "malformed"}),
        ("sendMessage", 503, []),
    ],
)
def test_malformed_or_inconsistent_api_errors_do_not_acknowledge_a_lost_reply(
    case, method, code, body
):
    bot, controls, _, _, _, failures = case
    failures[method] = (code, body)
    update = callback() if method == "editMessageText" else message()
    assert not bot.handle_update(update)
    assert len(controls.calls) == 1


def test_connection_tokens_and_commands_share_a_limit_with_one_notice(case):
    bot, controls, _, _, requests, _ = case
    bot._commands_limit.per_minute = 1  # The connection command used this minute's allowance.
    for identifier, text in enumerate(
        ["/start ff_" + "x" * 43, "/flights", "/help", "/start ff_" + "y" * 43], 2
    ):
        assert bot.handle_update(message(text, identifier))
    assert not controls.calls
    assert len(requests) == 1
    assert "wait a minute" in requests[0][1]["text"]


def test_disconnect_is_available_even_after_the_command_limit(case):
    bot, _, _, user, requests, _ = case
    bot._commands_limit.per_minute = 1
    assert bot.handle_update(message("/stop"))
    assert not bot.status(user["account"]["id"])["connected"]
    assert "disconnected" in requests[-1][1]["text"]


def test_concurrent_reply_failures_keep_their_own_retry_delays(case, clock, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    bot, _, _, _, _, _ = case
    first_ready, second_done = Event(), Event()
    reply = bot._reply

    def transport(request):
        payload = json.loads(request.content)
        delay = 17 if payload["chat_id"] == "123" else 3
        return httpx.Response(
            429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": delay}}
        )

    def interleave(chat, value, **kwargs):
        if chat == "456":
            assert first_ready.wait(5)
        result = reply(chat, value, **kwargs)
        if chat == "123":
            first_ready.set()
            assert second_done.wait(5)
        else:
            second_done.set()
        return result

    bot._transport = httpx.MockTransport(transport)
    monkeypatch.setattr(bot, "_reply", interleave)
    other = message("/help", identifier=3)
    other["message"]["chat"]["id"] = 456
    other["message"]["from"]["id"] = 456
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(bot.handle_update, message())
        second = pool.submit(bot.handle_update, other)
        assert not first.result(timeout=10)
        assert not second.result(timeout=10)
    assert bot.store.get("telegram-update:2").due == clock[0] + 17
    assert bot.store.get("telegram-update:3").due == clock[0] + 3


def test_mismatched_binding_generation_cannot_authorize_a_command(case):
    bot, controls, _, user, requests, _ = case
    chat = bot.store.get("telegram-chat:123")
    bot.store.commit([chat.update({**chat.data, "connection_id": "different-generation"})])
    assert bot.handle_update(message())
    assert not controls.calls
    assert "Connect Telegram" in requests[-1][1]["text"]
    assert not bot.status(user["account"]["id"])["connected"]
