"""Hosted API/dashboard composition; no browser collection in request handlers."""

from __future__ import annotations

import os
from pathlib import Path

from mangum import Mangum

from fareflare.accounts import Accounts
from fareflare.link_resolver import GoogleLinkResolver
from fareflare.portal import create_portal
from fareflare.product_config import ProductConfig
from fareflare.product_telegram import build_telegram
from fareflare.public_quotes import supported_target
from fareflare.service import MonitoringService
from fareflare.store import DynamoStore


def build_application():
    config = ProductConfig.from_env()
    if not config.public_url:
        raise ValueError("Configure the public application URL")
    store = DynamoStore(
        os.environ["FAREFLARE_TABLE"], region=os.environ.get("AWS_REGION", "us-east-1")
    )
    service = MonitoringService(
        store,
        link_importer=GoogleLinkResolver(allow_search=config.search_enabled),
        capability_check=supported_target,
        monitor_limit=config.monitor_limit,
        min_interval_seconds=config.min_interval_seconds,
        global_target_limit=config.global_target_limit,
    )
    accounts = Accounts(store, config)
    telegram = build_telegram(store, accounts, config.public_url, service=service)
    return create_portal(
        service,
        config,
        accounts,
        static_dir=Path(os.environ.get("LAMBDA_TASK_ROOT", ".")) / "web",
        telegram=telegram.connections if telegram else None,
        telegram_webhook_secret=telegram.webhook_secret if telegram else None,
    )


_adapter = None


def handler(event, context):
    global _adapter
    if _adapter is None:
        _adapter = Mangum(build_application(), lifespan="off")
    return _adapter(event, context)
