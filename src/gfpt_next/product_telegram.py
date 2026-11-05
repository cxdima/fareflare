"""Wire the shared Telegram bot without replacing the family command handler."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from gfpt_next.accounts import Accounts
from gfpt_next.store import Store

if TYPE_CHECKING:
    from gfpt_next.telegram_accounts import TelegramConnections


class InboxSink:
    """An account's durable alert history is its default inbox."""
    def __init__(self, accounts: Accounts):
        self.accounts = accounts

    def send(self, delivery: dict) -> bool:
        return (delivery.get("webhook_id") is None
                and self.accounts.validate_account_active(delivery.get("tenant", "")))


class LegacyBotForwarder:
    def __init__(self, client, function_arn: str, secret: str):
        self.client, self.function_arn, self.secret = client, function_arn, secret

    def __call__(self, update: dict) -> bool:
        # The legacy handler's HTTP gate exclusively dispatches bot commands.
        # Never add an EventBridge source, and never forward caller-controlled headers.
        event = {"requestContext": {"http": {"method": "POST"}},
                 "headers": {"x-telegram-bot-api-secret-token": self.secret},
                 "body": json.dumps(update), "isBase64Encoded": False}
        try:
            result = self.client.invoke(FunctionName=self.function_arn, InvocationType="RequestResponse",
                                        Payload=json.dumps(event).encode())
            payload = result["Payload"]
            try:
                response = json.loads(payload.read(65_536))
            finally:
                payload.close()
            return not result.get("FunctionError") and response.get("statusCode") == 200
        except (BotoCoreError, ClientError, ValueError, KeyError, TypeError):
            return False


@dataclass(frozen=True)
class TelegramRuntime:
    connections: TelegramConnections
    webhook_secret: str


def build_telegram(store: Store, accounts: Accounts, public_url: str, *, allow_legacy: bool = False):
    arn = os.environ.get("GFPT_NEXT_CUSTOMER_TELEGRAM_SECRET_ARN")
    if not arn:
        return None
    from gfpt_next.telegram_accounts import TelegramConnections
    region = os.environ.get("AWS_REGION", "us-east-1")
    config = json.loads(boto3.client("secretsmanager", region_name=region)
                        .get_secret_value(SecretId=arn)["SecretString"])
    forward = None
    function_arn = os.environ.get("GFPT_NEXT_LEGACY_BOT_FUNCTION_ARN")
    if allow_legacy and function_arn:
        forward = LegacyBotForwarder(boto3.client("lambda", region_name=region,
            config=Config(connect_timeout=3, read_timeout=20, retries={"total_max_attempts": 1})),
            function_arn, config["webhook_secret"])
    connections = TelegramConnections(store, accounts, config["bot_token"], config["bot_username"], public_url,
                                      legacy_forward=forward, legacy_chat_ids=config.get("legacy_chat_ids", []),
                                      clock=accounts.clock)
    return TelegramRuntime(connections, config["webhook_secret"])
