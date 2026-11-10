from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from fareflare.accounts import Accounts
from fareflare.portal import create_portal
from fareflare.product_config import ProductConfig
from fareflare.product_telegram import InboxSink


def test_customer_inbox_never_claims_explicit_webhook_or_unknown_account_delivery(store):
    accounts = Accounts(store)
    account = accounts.register(
        "alice", "a long secure test password", accounts.create_invite()["token"]
    )["account"]
    sink = InboxSink(accounts)
    assert sink.send({"tenant": account["id"]})
    assert not sink.send({"tenant": account["id"], "webhook_id": "a" * 32})
    assert not sink.send({"tenant": "non_account"})
    accounts.delete_account(account["id"], "a long secure test password")
    assert not sink.send({"tenant": account["id"]})


def test_telegram_webhook_authentication_and_customer_csrf(service):
    accounts = Accounts(service.store, clock=service.clock)
    login = accounts.register(
        "alice", "a long secure test password", accounts.create_invite()["token"]
    )
    bot = Mock()
    bot.status.return_value = {"enabled": True, "connected": False}
    bot.connect.return_value = {"url": "https://t.me/testbot?start=example", "expires_at": 123}
    bot.handle_update.return_value = True
    secret = "a" * 40
    app = create_portal(
        service,
        ProductConfig(public_url="https://app.example.com"),
        accounts,
        telegram=bot,
        telegram_webhook_secret=secret,
    )
    with TestClient(app, base_url="https://app.example.com") as client:
        assert client.post("/telegram/webhook", json={"update_id": 1}).status_code == 403
        headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
        assert (
            client.post("/telegram/webhook", json={"update_id": 1}, headers=headers).status_code
            == 200
        )
        bot.handle_update.assert_called_once_with({"update_id": 1})
        assert (
            client.post(
                "/telegram/webhook",
                json={},
                headers=[(name, value) for name, value in headers.items()] * 2,
            ).status_code
            == 403
        )
        bot.handle_update.return_value = False
        assert (
            client.post("/telegram/webhook", json={"update_id": 2}, headers=headers).status_code
            == 503
        )
        assert client.get("/v1/telegram").status_code == 401
        client.cookies.set("__Host-fareflare_session", login["session_token"])
        assert client.get("/v1/telegram").json() == {"enabled": True, "connected": False}
        assert client.post("/v1/telegram").status_code == 403
        assert (
            client.post("/v1/telegram", headers={"X-CSRF-Token": login["csrf_token"]}).status_code
            == 200
        )
        bot.connect.assert_called_once_with(login["account"]["id"])


def test_telegram_configuration_requires_secret(service):
    with pytest.raises(ValueError, match="strong Telegram"):
        create_portal(service, ProductConfig(public_url="https://app.example.com"), telegram=Mock())
