"""Exercise the real application/worker composition with isolated AWS clients."""
import hashlib
import json
from unittest.mock import Mock

from fastapi.testclient import TestClient

from gfpt_next import product_runtime, product_telegram, runtime
from gfpt_next.telegram_accounts import TelegramConnections
from gfpt_next.webhooks import RoutedSink

BOT_TOKEN = "123456:" + "x" * 30
SECRET_ARN = "arn:aws:secretsmanager:us-east-1:111111111111:secret:fareflare-bot-example"
WEBHOOK_SECRET = hashlib.sha256(("gfpt-webhook:" + BOT_TOKEN).encode()).hexdigest()[:40]


def aws_config(monkeypatch):
    monkeypatch.setenv("GFPT_NEXT_TABLE", "gfpt-next-tests")
    monkeypatch.setenv("GFPT_NEXT_PUBLIC_URL", "https://app.example.com")
    monkeypatch.setenv("GFPT_NEXT_CUSTOMER_TELEGRAM_SECRET_ARN", SECRET_ARN)
    secret = Mock()
    secret.get_secret_value.return_value = {"SecretString": json.dumps({
        "bot_token": BOT_TOKEN, "bot_username": "fareflare_bot",
        "webhook_secret": WEBHOOK_SECRET,
    })}
    clients = []

    def client(service, **kwargs):
        clients.append(service)
        if service == "secretsmanager":
            return secret
        raise AssertionError("Unexpected AWS client requested: " + service)

    monkeypatch.setattr(product_telegram.boto3, "client", client)
    return secret, clients


def test_application_reads_bot_secret_and_handles_only_verified_webhook(store, monkeypatch, tmp_path):
    secret, clients = aws_config(monkeypatch)
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))
    monkeypatch.setattr(product_runtime, "DynamoStore", lambda *args, **kwargs: store)
    replies = []
    monkeypatch.setattr(TelegramConnections, "_reply", lambda self, chat, text: replies.append((chat, text)))
    app = product_runtime.build_application()
    update = {"update_id": 100, "message": {"text": "/help", "chat": {"id": 999, "type": "private"},
                                           "from": {"id": 999}}}
    with TestClient(app, base_url="https://app.example.com") as client:
        assert client.post("/telegram/webhook", json=update).status_code == 403
        assert not replies
        headers = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}
        assert client.post("/telegram/webhook", json=update, headers=headers).status_code == 200
        assert client.post("/telegram/webhook", json=update, headers=headers).status_code == 200
    secret.get_secret_value.assert_called_once_with(SecretId=SECRET_ARN)
    assert clients == ["secretsmanager"]
    assert len(replies) == 1
    assert replies[0][0] == "999"
    assert "Connect Telegram" in replies[0][1]


def test_product_worker_loads_bot_using_only_secrets_manager(store, monkeypatch):
    secret, clients = aws_config(monkeypatch)
    monkeypatch.setenv("GFPT_NEXT_DELIVERY", "product")
    monkeypatch.setattr(runtime, "DynamoStore", lambda *args, **kwargs: store)
    worker = runtime.build_worker()
    assert isinstance(worker.sink, RoutedSink)
    assert isinstance(worker.sink.default, TelegramConnections)
    assert worker.sink.default.bot_username == "fareflare_bot"
    secret.get_secret_value.assert_called_once_with(SecretId=SECRET_ARN)
    assert clients == ["secretsmanager"]
