"""Compose account-owned Telegram connections and inbox delivery."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3

from gfpt_next.accounts import Accounts
from gfpt_next.store import Store

if TYPE_CHECKING:
    from gfpt_next.service import MonitoringService
    from gfpt_next.telegram_accounts import TelegramConnections


class InboxSink:
    """An account's durable alert history is its default inbox."""
    def __init__(self, accounts: Accounts):
        self.accounts = accounts

    def send(self, delivery: dict) -> bool:
        return (delivery.get("webhook_id") is None
                and self.accounts.validate_account_active(delivery.get("tenant", "")))


@dataclass(frozen=True)
class TelegramRuntime:
    connections: TelegramConnections
    webhook_secret: str


def build_telegram(store: Store, accounts: Accounts, public_url: str, *, service: MonitoringService | None = None):
    arn = os.environ.get("GFPT_NEXT_CUSTOMER_TELEGRAM_SECRET_ARN")
    if not arn:
        return None
    from gfpt_next.telegram_accounts import TelegramConnections
    region = os.environ.get("AWS_REGION", "us-east-1")
    config = json.loads(boto3.client("secretsmanager", region_name=region)
                        .get_secret_value(SecretId=arn)["SecretString"])
    connections = TelegramConnections(store, accounts, config["bot_token"], config["bot_username"], public_url,
                                      clock=accounts.clock, service=service)
    return TelegramRuntime(connections, config["webhook_secret"])
