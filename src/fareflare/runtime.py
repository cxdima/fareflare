"""Additive production worker entry point. Defaults to notification suppression."""

from __future__ import annotations

import json
import os
import time

import boto3

from fareflare.accounts import Accounts
from fareflare.delivery import TelegramSink
from fareflare.health import record_run
from fareflare.link_resolver import GoogleLinkResolver
from fareflare.product_telegram import InboxSink, build_telegram
from fareflare.public_browser import PublicGoogleFlightsProvider
from fareflare.public_quotes import supported_target
from fareflare.service import MonitoringService
from fareflare.store import DynamoStore
from fareflare.webhooks import RoutedSink
from fareflare.worker import Worker


def build_worker() -> Worker:
    region = os.environ.get("AWS_REGION", "us-east-1")
    store = DynamoStore(os.environ["FAREFLARE_TABLE"], region=region)
    service = MonitoringService(
        store, link_importer=GoogleLinkResolver(), capability_check=supported_target
    )
    sink = None
    mode = os.environ.get("FAREFLARE_DELIVERY", "shadow")
    if mode not in ("shadow", "telegram", "webhooks", "routed", "product"):
        raise ValueError("Unsupported notification delivery mode")
    if mode in ("telegram", "routed"):
        # Secret contains bot_token + recipients, scoped by the worker IAM role.
        secret = boto3.client("secretsmanager", region_name=region).get_secret_value(
            SecretId=os.environ["FAREFLARE_TELEGRAM_SECRET_ARN"]
        )
        config = json.loads(secret["SecretString"])
        sink = TelegramSink(config["bot_token"], config["recipients"])
    if mode in ("webhooks", "routed"):
        sink = RoutedSink(service.webhooks, sink)
    if mode == "product":
        accounts = Accounts(store)
        telegram = build_telegram(
            store, accounts, os.environ.get("FAREFLARE_PUBLIC_URL", ""), service=service
        )
        sink = RoutedSink(
            service.webhooks, telegram.connections if telegram else InboxSink(accounts)
        )
    provider = PublicGoogleFlightsProvider(
        os.environ.get("CHROME_BINARY"), os.environ.get("CHROMEDRIVER_PATH")
    )
    return Worker(service, provider, sink)


def handler(event, context):
    if event.get("source") != "fareflare.scheduler":
        raise ValueError("Unsupported worker event")
    budget = min(150, max(1, int(context.get_remaining_time_in_millis() / 1000) - 10))
    worker = build_worker()
    result = worker.tick(
        max_targets=int(os.environ.get("FAREFLARE_MAX_TARGETS", "1")), budget_seconds=budget
    )
    record_run(worker.service.store, int(time.time()), result)
    # No itinerary, account, cookies, credentials, or provider exception messages.
    metrics = [
        {"Name": name, "Unit": "Milliseconds" if name == "runtime_ms" else "Count"}
        for name in (
            "collected",
            "failed",
            "skipped",
            "alerts_sent",
            "alerts_suppressed",
            "notices_sent",
            "browser_launches",
            "browser_reuses",
            "runtime_ms",
        )
        if name in result
    ]
    print(
        json.dumps(
            {
                "service": "fareflare",
                "ServiceName": os.environ.get("FAREFLARE_TABLE", "fareflare"),
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "Fareflare",
                            "Dimensions": [["ServiceName"]],
                            "Metrics": metrics,
                        }
                    ],
                },
                **result,
            }
        )
    )
    return result
