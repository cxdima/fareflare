import io
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from gfpt_next.accounts import Accounts
from gfpt_next.portal import create_portal
from gfpt_next.product_config import ProductConfig
from gfpt_next.product_telegram import InboxSink, LegacyBotForwarder


def test_legacy_forwarding_can_only_enter_authenticated_http_handler():
    client = Mock()
    payload = io.BytesIO(b'{"statusCode":200,"body":"ok"}')
    client.invoke.return_value = {"Payload": payload}
    forward = LegacyBotForwarder(client, "arn:aws:lambda:us-east-1:111111111111:function:family", "secret-value")
    update = {"update_id": 123, "message": {"text": "/status", "chat": {"id": 111}}}
    assert forward(update)
    args = client.invoke.call_args.kwargs
    assert args["InvocationType"] == "RequestResponse"
    forwarded = json.loads(args["Payload"])
    assert forwarded["requestContext"]["http"]["method"] == "POST"
    assert forwarded["headers"] == {"x-telegram-bot-api-secret-token": "secret-value"}
    assert json.loads(forwarded["body"]) == update
    assert "source" not in forwarded
    assert payload.closed
    client.invoke.return_value = {"Payload": io.BytesIO(b'{"statusCode":403}')}
    assert not forward(update)
    client.invoke.return_value = {"Payload": io.BytesIO(b'{"statusCode":200}'), "FunctionError": "Unhandled"}
    assert not forward(update)


def test_customer_inbox_never_claims_explicit_webhook_or_family_delivery(store):
    accounts = Accounts(store)
    account = accounts.register("alice", "a long secure test password", accounts.create_invite()["token"])["account"]
    sink = InboxSink(accounts)
    assert sink.send({"tenant": account["id"]})
    assert not sink.send({"tenant": account["id"], "webhook_id": "a" * 32})
    assert not sink.send({"tenant": "family"})
    accounts.delete_account(account["id"], "a long secure test password")
    assert not sink.send({"tenant": account["id"]})


def test_telegram_webhook_authentication_and_customer_csrf(service):
    accounts = Accounts(service.store, clock=service.clock)
    login = accounts.register("alice", "a long secure test password", accounts.create_invite()["token"])
    bot = Mock()
    bot.status.return_value = {"enabled": True, "connected": False}
    bot.connect.return_value = {"url": "https://t.me/testbot?start=example", "expires_at": 123}
    bot.handle_update.return_value = True
    secret = "a" * 40
    app = create_portal(service, ProductConfig(public_url="https://app.example.com"), accounts,
                        telegram=bot, telegram_webhook_secret=secret)
    with TestClient(app, base_url="https://app.example.com") as client:
        assert client.post("/telegram/webhook", json={"update_id": 1}).status_code == 403
        headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
        assert client.post("/telegram/webhook", json={"update_id": 1}, headers=headers).status_code == 200
        bot.handle_update.assert_called_once_with({"update_id": 1})
        assert client.post("/telegram/webhook", json={}, headers=[(name, value) for name, value in headers.items()] * 2).status_code == 403
        bot.handle_update.return_value = False
        assert client.post("/telegram/webhook", json={"update_id": 2}, headers=headers).status_code == 503
        assert client.get("/v1/telegram").status_code == 401
        client.cookies.set("__Host-fareflare_session", login["session_token"])
        assert client.get("/v1/telegram").json() == {"enabled": True, "connected": False}
        assert client.post("/v1/telegram").status_code == 403
        assert client.post("/v1/telegram", headers={"X-CSRF-Token": login["csrf_token"]}).status_code == 200
        bot.connect.assert_called_once_with(login["account"]["id"])


def test_telegram_configuration_requires_secret(service):
    with pytest.raises(ValueError, match="strong Telegram"):
        create_portal(service, ProductConfig(public_url="https://app.example.com"), telegram=Mock())
