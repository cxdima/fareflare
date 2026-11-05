import hashlib
import json
import logging
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from gfpt_next.accounts import Accounts
from gfpt_next.delivery import TelegramSink
from gfpt_next.product_config import ProductConfig
from gfpt_next.store import Conflict
from gfpt_next.telegram_accounts import TelegramConnections

PASSWORD = "a long development passphrase"
BOT_TOKEN = "123456:" + "x" * 30


@pytest.fixture
def telegram(store, clock):
    accounts = Accounts(store, ProductConfig(registration_mode="open"), lambda: clock[0])
    user = accounts.register("traveler", PASSWORD)
    sent, forwarded = [], []

    def transport(request):
        assert request.url.host == "api.telegram.org"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    connections = TelegramConnections(store, accounts, BOT_TOKEN, "fareflare_bot", "https://fareflare.test",
        legacy_forward=lambda update: forwarded.append(update) is None,
        legacy_chat_ids=[999], transport=httpx.MockTransport(transport), clock=lambda: clock[0])
    return connections, accounts, user, sent, forwarded


def start(connections, tenant):
    link = connections.connect(tenant)
    payload = parse_qs(urlsplit(link["url"]).query)["start"][0]
    return payload


def update(text, *, chat=123, sender=None, kind="private", identifier=1):
    return {"update_id": identifier, "message": {"text": text,
        "chat": {"id": chat, "type": kind}, "from": {"id": chat if sender is None else sender}}}


def bind(connections, tenant, *, chat=123, identifier=1):
    payload = start(connections, tenant)
    assert connections.handle_update(update("/start " + payload, chat=chat, identifier=identifier))
    return payload


def delivery(tenant, epoch=1):
    return {"id": "a" * 32, "tenant": tenant, "tenant_epoch": epoch, "reason": "new_low",
            "observation": {"amount_minor": 12000, "currency": "USD", "observed_at": 1793653200},
            "itinerary": {"url": "https://www.google.com/travel/flights", "segments": []}}


def test_private_one_use_link_hashes_credentials_and_routes_delivery(telegram, store, clock):
    connections, _, user, sent, forwarded = telegram
    tenant = user["account"]["id"]
    assert connections.status(tenant) == {"enabled": True, "connected": False, "bot_username": "fareflare_bot"}
    payload = bind(connections, tenant)
    assert len(payload) <= 64
    challenge = store.get("telegram-connect:" + hashlib.sha256(payload[3:].encode()).hexdigest())
    assert challenge.data["used"] and challenge.data["expires_at"] == clock[0] + 600
    assert payload[3:] not in json.dumps(challenge.data)
    assert connections.status(tenant)["connected"]
    assert not forwarded
    assert sent[0]["chat_id"] == "123"
    assert connections.send(delivery(tenant))
    assert "USD 120.00" in sent[-1]["text"]
    assert "parse_mode" not in sent[-1]
    assert connections.handle_update(update("/start " + payload, chat=456, identifier=2))
    assert store.get("telegram-account:" + tenant).data["chat_id"] == "123"


def test_duplicate_updates_do_not_reply_or_forward_twice(telegram):
    connections, _, user, sent, forwarded = telegram
    payload = bind(connections, user["account"]["id"])
    assert connections.handle_update(update("/start " + payload))
    assert len(sent) == 1
    family = update("/status", chat=999, identifier=2)
    assert connections.handle_update(family)
    assert connections.handle_update(family)
    assert forwarded == [family]


def test_only_private_matching_human_sender_can_bind(telegram):
    connections, _, user, sent, forwarded = telegram
    tenant = user["account"]["id"]
    payload = start(connections, tenant)
    candidates = [update("/start " + payload, sender=456),
                  update("/start " + payload, chat=-123, kind="group"),
                  update("/start " + payload, chat=True),
                  update("/start@another_bot " + payload)]
    bot = update("/start " + payload)
    bot["message"]["from"]["is_bot"] = True
    candidates.append(bot)
    for identifier, candidate in enumerate(candidates):
        candidate["update_id"] = identifier
        assert connections.handle_update(candidate)
    assert not connections.status(tenant)["connected"]
    assert not sent and not forwarded


def test_expired_replaced_and_disconnected_links_cannot_bind(telegram, clock):
    connections, _, user, _, _ = telegram
    tenant = user["account"]["id"]
    old = start(connections, tenant)
    current = start(connections, tenant)
    assert connections.handle_update(update("/start " + old))
    assert not connections.status(tenant)["connected"]
    clock[0] += 600
    assert connections.handle_update(update("/start " + current, identifier=2))
    assert not connections.status(tenant)["connected"]
    pending = start(connections, tenant)
    connections.disconnect(tenant)
    assert connections.handle_update(update("/start " + pending, identifier=3))
    assert not connections.status(tenant)["connected"]


def test_rebinding_requires_disconnect_and_chat_cannot_take_another_account(telegram, store):
    connections, accounts, user, _, _ = telegram
    tenant = user["account"]["id"]
    bind(connections, tenant)
    with pytest.raises(ValueError, match="Disconnect"):
        connections.connect(tenant)
    other = accounts.register("traveler-two", PASSWORD)["account"]["id"]
    payload = start(connections, other)
    assert connections.handle_update(update("/start " + payload, identifier=2))
    assert not connections.status(other)["connected"]
    assert connections.status(tenant)["connected"]
    connections.disconnect(tenant)
    assert connections.handle_update(update("/start " + payload, identifier=3))
    assert connections.status(other)["connected"]
    assert store.get("telegram-chat:123").data["tenant"] == other


def test_family_commands_are_forwarded_even_when_family_has_product_binding(telegram):
    connections, _, user, sent, forwarded = telegram
    tenant = user["account"]["id"]
    bind(connections, tenant, chat=999)
    assert "Fareflare Account settings" in sent[-1]["text"]
    assert "/stop" not in sent[-1]["text"]
    for identifier, command in enumerate(["/stop", "/help", "/status"], start=2):
        item = update(command, chat=999, identifier=identifier)
        assert connections.handle_update(item)
        assert forwarded[-1] == item
    assert connections.status(tenant)["connected"]
    assert len(sent) == 1


def test_consumer_help_and_stop_preserve_dashboard_and_invalidate_old_alerts(telegram, store):
    connections, _, user, sent, forwarded = telegram
    tenant = user["account"]["id"]
    bind(connections, tenant)
    assert connections.handle_update(update("/help@fareflare_bot", identifier=2))
    assert "https://fareflare.test" in sent[-1]["text"]
    assert connections.handle_update(update("/stop", identifier=3))
    assert not connections.status(tenant)["connected"]
    assert store.get("tenant:" + tenant).data["notification_epoch"] == 2
    assert connections.handle_update(update("/stop", identifier=3))
    assert not forwarded
    before = len(sent)
    assert connections.send(delivery(tenant, epoch=1))
    assert len(sent) == before
    bind(connections, tenant, chat=456, identifier=4)
    before = len(sent)
    assert connections.send(delivery(tenant, epoch=1))
    assert len(sent) == before
    assert connections.send(delivery(tenant, epoch=3))
    assert sent[-1]["chat_id"] == "456"


def test_unknown_updates_do_not_reply_or_leak_connection_tokens_to_legacy(telegram):
    connections, _, _, sent, forwarded = telegram
    item = update("/help")
    assert connections.handle_update(item)
    assert forwarded == [item]
    cases = [update("/start ff_broken", identifier=2),
             {"update_id": 3, "edited_message": {"text": "/start ff_secret"}},
             {"update_id": 4, "callback_query": {"data": "ff_secret"}}]
    for item in cases:
        assert connections.handle_update(item)
    assert len(forwarded) == 1
    assert not sent


def test_recovery_fences_links_bindings_and_reconnecting_fences_pending_delivery(telegram, store):
    connections, accounts, user, sent, _ = telegram
    tenant = user["account"]["id"]
    bind(connections, tenant)
    accounts.recover("traveler", user["recovery_code"], "another long password phrase")
    assert not connections.status(tenant)["connected"]
    before = len(sent)
    assert connections.send(delivery(tenant))
    assert len(sent) == before
    bind(connections, tenant, chat=456, identifier=2)
    assert connections.status(tenant)["connected"]
    assert store.get("tenant:" + tenant).data["notification_epoch"] == 2
    assert store.get("telegram-chat:123").data == {"connected": False}
    before = len(sent)
    assert connections.send(delivery(tenant, epoch=1))
    assert len(sent) == before


def test_recovery_cancels_unredeemed_connection_link(telegram):
    connections, accounts, user, _, _ = telegram
    tenant = user["account"]["id"]
    payload = start(connections, tenant)
    accounts.recover("traveler", user["recovery_code"], "another long password phrase")
    assert connections.handle_update(update("/start " + payload))
    assert not connections.status(tenant)["connected"]


def test_account_deletion_stops_telegram_without_pre_delete_side_effects(telegram, store):
    connections, accounts, user, sent, _ = telegram
    tenant = user["account"]["id"]
    bind(connections, tenant)
    accounts.delete_account(tenant, PASSWORD)
    before = len(sent)
    assert connections.send(delivery(tenant))
    assert len(sent) == before
    assert not connections.send({**delivery(tenant), "tenant": "family"})
    assert not connections.send({**delivery(tenant), "webhook_id": "abc"})
    assert store.get("telegram-account:" + tenant).data == {"connected": False}
    assert store.get("telegram-chat:123").data == {"connected": False}


def test_deletion_cleanup_preserves_chat_rebound_to_another_account(telegram, store, monkeypatch):
    connections, accounts, user, _, _ = telegram
    tenant = user["account"]["id"]
    other = accounts.register("traveler-two", PASSWORD)["account"]["id"]
    bind(connections, tenant)
    payload = start(connections, other)
    commit = store.commit
    raced = False

    def race(documents):
        nonlocal raced
        if not raced and any(d.key == "telegram-account:" + tenant and "tenant" not in d.data for d in documents):
            raced = True
            assert connections.handle_update(update("/start " + payload, identifier=2))
        return commit(documents)

    monkeypatch.setattr(store, "commit", race)
    accounts.delete_account(tenant, PASSWORD)
    assert raced and connections.status(other)["connected"]
    assert store.get("telegram-chat:123").data["tenant"] == other
    assert store.get("telegram-account:" + tenant).data == {"connected": False}


def test_network_failure_is_retriable_for_alert_but_connection_confirmation_optional(telegram):
    connections, _, user, _, _ = telegram
    tenant = user["account"]["id"]

    def fail(request):
        raise httpx.ConnectError("unavailable", request=request)

    connections._transport = httpx.MockTransport(fail)
    bind(connections, tenant)
    assert connections.status(tenant)["connected"]
    assert not connections.send(delivery(tenant))


def test_httpx_logging_redacts_telegram_bot_credential(telegram, caplog):
    connections, _, user, _, _ = telegram
    tenant = user["account"]["id"]
    with caplog.at_level(logging.INFO, logger="httpx"):
        bind(connections, tenant)
        assert connections.send(delivery(tenant))
    assert "api.telegram.org/bot[REDACTED]/sendMessage" in caplog.text
    assert BOT_TOKEN not in caplog.text


def test_standalone_telegram_sink_also_redacts_url_credential(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("httpx"), "filters", [])
    sink = TelegramSink(BOT_TOKEN, {"family": "999"},
                        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})))
    with caplog.at_level(logging.INFO, logger="httpx"):
        assert sink.send(delivery("family"))
    assert "api.telegram.org/bot[REDACTED]/sendMessage" in caplog.text
    assert BOT_TOKEN not in caplog.text


def test_legacy_failure_retries_after_lease_without_dropping_family_update(telegram, clock):
    connections, _, _, _, forwarded = telegram
    attempts = []

    def forward(item):
        attempts.append(item)
        return len(attempts) > 1

    connections._forward = forward
    item = update("/status", chat=999)
    assert not connections.handle_update(item)
    assert not connections.handle_update(item)
    assert len(attempts) == 1
    clock[0] += 30
    assert connections.handle_update(item)
    assert connections.handle_update(item)
    assert len(attempts) == 2
    assert not forwarded


def test_concurrent_recovery_cannot_install_binding_with_old_epoch(telegram, store, monkeypatch):
    connections, _, user, _, _ = telegram
    tenant = user["account"]["id"]
    payload = start(connections, tenant)
    commit = store.commit
    raced = False

    def race(documents):
        nonlocal raced
        if not raced and any(d.key.startswith("telegram-connect:") and d.data.get("used") for d in documents):
            raced = True
            account = store.get("account:" + tenant)
            commit([account.update({**account.data, "auth_epoch": account.data["auth_epoch"] + 1})])
        return commit(documents)

    monkeypatch.setattr(store, "commit", race)
    assert connections.handle_update(update("/start " + payload))
    assert raced and not connections.status(tenant)["connected"]


def test_concurrent_disconnect_retries_and_always_invalidates_pending(telegram, store, monkeypatch):
    connections, _, user, _, _ = telegram
    tenant = user["account"]["id"]
    bind(connections, tenant)
    commit = store.commit
    raced = False

    def race(documents):
        nonlocal raced
        if not raced and any(d.key == "tenant:" + tenant for d in documents):
            raced = True
            raise Conflict("concurrent preference change")
        return commit(documents)

    monkeypatch.setattr(store, "commit", race)
    connections.disconnect(tenant)
    assert raced and not connections.status(tenant)["connected"]
    assert store.get("tenant:" + tenant).data["notification_epoch"] == 2
