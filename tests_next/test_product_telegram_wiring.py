"""Exercise the real application/worker composition with isolated AWS clients."""
import hashlib
import io
import json
from unittest.mock import Mock

from fastapi.testclient import TestClient

from gfpt_next import product_runtime, product_telegram, runtime
from gfpt_next.telegram_accounts import TelegramConnections
from gfpt_next.webhooks import RoutedSink

BOT_TOKEN = "123456:" + "x" * 30
SECRET_ARN = "arn:aws:secretsmanager:us-east-1:111111111111:secret:shared-bot-example"
FAMILY_ARN = "arn:aws:lambda:us-east-1:111111111111:function:family"
WEBHOOK_SECRET = hashlib.sha256(("gfpt-webhook:" + BOT_TOKEN).encode()).hexdigest()[:40]


def aws_config(monkeypatch):
    monkeypatch.setenv("GFPT_NEXT_TABLE", "gfpt-next-tests")
    monkeypatch.setenv("GFPT_NEXT_PUBLIC_URL", "https://app.example.com")
    monkeypatch.setenv("GFPT_NEXT_CUSTOMER_TELEGRAM_SECRET_ARN", SECRET_ARN)
    monkeypatch.setenv("GFPT_NEXT_LEGACY_BOT_FUNCTION_ARN", FAMILY_ARN)
    secret = Mock()
    secret.get_secret_value.return_value = {"SecretString": json.dumps({
        "bot_token": BOT_TOKEN, "bot_username": "fareflare_bot", "legacy_chat_ids": [999],
        "webhook_secret": WEBHOOK_SECRET,
    })}
    legacy = Mock()
    legacy.invoke.side_effect = lambda **kwargs: {"Payload": io.BytesIO(b'{"statusCode":200,"body":"ok"}')}
    clients = []

    def client(service, **kwargs):
        clients.append(service)
        if service == "secretsmanager":
            return secret
        if service == "lambda":
            assert kwargs["config"].read_timeout == 20
            assert kwargs["config"].retries == {"total_max_attempts": 1}
            return legacy
        raise AssertionError("Unexpected AWS client requested: " + service)

    monkeypatch.setattr(product_telegram.boto3, "client", client)
    return secret, legacy, clients


def test_application_reads_shared_secret_and_forwards_only_verified_webhook(store, monkeypatch, tmp_path):
    secret, legacy, clients = aws_config(monkeypatch)
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))
    monkeypatch.setattr(product_runtime, "DynamoStore", lambda *args, **kwargs: store)
    app = product_runtime.build_application()
    update = {"update_id": 100, "message": {"text": "/status", "chat": {"id": 999, "type": "private"},
                                           "from": {"id": 999}}}
    with TestClient(app, base_url="https://app.example.com") as client:
        assert client.post("/telegram/webhook", json=update).status_code == 403
        legacy.invoke.assert_not_called()
        headers = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}
        assert client.post("/telegram/webhook", json=update, headers=headers).status_code == 200
        assert client.post("/telegram/webhook", json=update, headers=headers).status_code == 200
    secret.get_secret_value.assert_called_once_with(SecretId=SECRET_ARN)
    assert clients == ["secretsmanager", "lambda"]
    legacy.invoke.assert_called_once()
    invocation = legacy.invoke.call_args.kwargs
    assert invocation["FunctionName"] == FAMILY_ARN
    assert invocation["InvocationType"] == "RequestResponse"
    forwarded = json.loads(invocation["Payload"])
    assert forwarded["requestContext"] == {"http": {"method": "POST"}}
    assert forwarded["headers"] == {"x-telegram-bot-api-secret-token": WEBHOOK_SECRET}
    assert json.loads(forwarded["body"]) == update
    assert "source" not in forwarded


def test_product_worker_loads_shared_bot_without_creating_legacy_lambda_client(store, monkeypatch):
    secret, legacy, clients = aws_config(monkeypatch)
    monkeypatch.setenv("GFPT_NEXT_DELIVERY", "product")
    monkeypatch.setattr(runtime, "DynamoStore", lambda *args, **kwargs: store)
    worker = runtime.build_worker()
    assert isinstance(worker.sink, RoutedSink)
    assert isinstance(worker.sink.default, TelegramConnections)
    assert worker.sink.default.bot_username == "fareflare_bot"
    secret.get_secret_value.assert_called_once_with(SecretId=SECRET_ARN)
    assert clients == ["secretsmanager"]
    legacy.invoke.assert_not_called()
