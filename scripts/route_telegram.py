#!/usr/bin/env python3
"""Switch the shared bot's webhook with an exclusive private rollback snapshot."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

from fareflare.delivery import install_telegram_log_redaction
from fareflare.webhook_http import normalize_webhook_url


class RouteError(ValueError):
    """An operator-safe error that contains no credentials or remote response body."""


def validate_url(value: str, *, product: bool = False) -> str:
    try:
        normalized = normalize_webhook_url(value)
        parsed = urlsplit(normalized)
        if parsed.query or product and parsed.path != "/telegram/webhook":
            raise ValueError
        if normalized != value:
            raise ValueError
        return normalized
    except (ValueError, TypeError):
        raise RouteError("Use a canonical public HTTPS URL without a query; the new route must be /telegram/webhook") from None


def _private_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(data, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _private_read(path: Path) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RouteError("Rollback snapshot must be a private regular file (mode 0600)")
        encoded = source.read(65_537)
    if len(encoded) > 65_536:
        raise RouteError("Rollback snapshot exceeds the size limit")
    try:
        value = json.loads(encoded)
    except ValueError:
        raise RouteError("Invalid rollback snapshot") from None
    if not isinstance(value, dict):
        raise RouteError("Invalid rollback snapshot")
    return value


def _settings(info: dict) -> dict:
    if not isinstance(info, dict) or info.get("has_custom_certificate") is not False:
        raise RouteError("Only existing webhooks without custom certificates can be restored by this tool")
    url = validate_url(info.get("url", ""))
    connections = info.get("max_connections", 40)
    updates = info.get("allowed_updates", [])
    if (type(connections) is not int or not 1 <= connections <= 100
            or not isinstance(updates, list) or len(updates) > 100
            or any(not isinstance(item, str) or not re.fullmatch(r"[a-z_]{1,64}", item) for item in updates)):
        raise RouteError("Invalid saved webhook settings")
    return {"url": url, "max_connections": connections, "allowed_updates": updates}


def _same_settings(left: dict, right: dict) -> bool:
    # Telegram update filters are a set; their response order is not contractual.
    return (left["url"] == right["url"] and left["max_connections"] == right["max_connections"]
            and set(left["allowed_updates"]) == set(right["allowed_updates"]))


def route(*, secret_arn: str, aws_account: str, region: str, url: str | None = None,
          snapshot: Path | None = None, restore: Path | None = None,
          enable_callbacks: bool = False, aws_client=None, transport=None) -> None:
    """Mutate one bot only after checking AWS identity and durable rollback data."""
    if not re.fullmatch(r"[0-9]{12}", aws_account):
        raise RouteError("Provide the expected 12-digit AWS account ID")
    arn = secret_arn.split(":", 5)
    if (len(arn) != 6 or arn[:3] != ["arn", "aws", "secretsmanager"] or arn[3] != region
            or arn[4] != aws_account or not arn[5].startswith("secret:") or len(arn[5]) <= 7):
        raise RouteError("The secret ARN must belong to the expected account and region")
    if (restore is None and (url is None or snapshot is None)
            or restore is not None and (url is not None or snapshot is not None or enable_callbacks)):
        raise RouteError("Choose --url with --snapshot, or --restore")
    if url is not None:
        validate_url(url, product=True)
    saved = _private_read(restore) if restore is not None else None
    client_factory = aws_client or boto3.client
    try:
        identity = client_factory("sts", region_name=region).get_caller_identity()
        if identity.get("Account") != aws_account:
            raise RouteError("AWS identity does not match the expected account")
        result = client_factory("secretsmanager", region_name=region).get_secret_value(SecretId=secret_arn)
        config = json.loads(result["SecretString"])
        token, secret = config["bot_token"], config["webhook_secret"]
        if (not isinstance(token, str) or not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token)
                or not isinstance(secret, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret)):
            raise RouteError("Shared bot credentials are invalid")
    except (BotoCoreError, ClientError, KeyError, TypeError, json.JSONDecodeError):
        raise RouteError("Unable to load the configured shared bot credentials") from None
    bot_id = token.partition(":")[0]
    fingerprint = hashlib.sha256(secret.encode()).hexdigest()
    if saved is not None:
        if (saved.get("version") not in (1, 2) or saved.get("aws_account") != aws_account
                or saved.get("secret_arn") != secret_arn or saved.get("bot_id") != bot_id
                or not isinstance(saved.get("webhook_secret_sha256"), str)
                or not hmac.compare_digest(saved["webhook_secret_sha256"], fingerprint)):
            raise RouteError("Snapshot does not match this account, bot and unchanged webhook secret")
        validate_url(saved.get("target_url", ""), product=True)
        desired = _settings(saved.get("previous_webhook", {}))
        if saved["version"] == 2 and not isinstance(saved.get("target_webhook"), dict):
            raise RouteError("Invalid saved webhook settings")
        expected = (_settings({"has_custom_certificate": False, **saved.get("target_webhook", {})})
                    if saved["version"] == 2 else None)
    else:
        desired = None
    install_telegram_log_redaction()
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False, transport=transport) as client:
        def call(method: str, payload: dict | None = None):
            try:
                response = client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {})
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or data.get("ok") is not True or "result" not in data:
                    raise ValueError
                return data["result"]
            except (httpx.HTTPError, ValueError):
                raise RouteError("Telegram request failed; inspect the saved snapshot before retrying") from None

        previous = call("getWebhookInfo")
        current = _settings(previous)
        if saved is not None:
            assert desired is not None
            if _same_settings(current, desired):
                return  # A repeated rollback is an authenticated, read-only no-op.
            if (current["url"] != saved["target_url"]
                    or expected is not None and not _same_settings(current, expected)):
                raise RouteError("Webhook changed after this snapshot; refusing to replace a different route")
        else:
            assert url is not None and snapshot is not None
            if current["url"] == url and not enable_callbacks:
                raise RouteError("This webhook already uses the requested route")
            desired = {**current, "url": url,
                       "max_connections": current["max_connections"] if enable_callbacks else 4}
            if enable_callbacks and current["allowed_updates"]:
                desired["allowed_updates"] = list(dict.fromkeys([*current["allowed_updates"], "callback_query"]))
            if _same_settings(current, desired):
                return  # The default empty filter already includes callbacks.
            _private_write(snapshot, {
                "version": 2, "created_at": datetime.now(UTC).isoformat(), "aws_account": aws_account,
                "secret_arn": secret_arn, "bot_id": bot_id, "webhook_secret_sha256": fingerprint,
                "target_url": url, "previous_webhook": previous, "target_webhook": desired,
            })
        if call("setWebhook", {**desired, "secret_token": secret, "drop_pending_updates": False}) is not True:
            raise RouteError("Telegram did not confirm the route change; use the saved snapshot to recover")
        if not _same_settings(_settings(call("getWebhookInfo")), desired):
            raise RouteError("Webhook readback did not match; use the saved snapshot to recover")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--aws-account", required=True)
    parser.add_argument("--region", default="us-east-1")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--url")
    mode.add_argument("--restore", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--enable-callbacks", action="store_true",
                        help="Preserve existing webhook settings and enable inline-button callbacks")
    args = parser.parse_args(argv)
    try:
        route(**vars(args))
    except (RouteError, OSError) as exc:
        # Do not render HTTP/AWS exceptions: their URLs can contain credentials.
        parser.exit(1, f"Route change failed: {exc if isinstance(exc, RouteError) else 'Cannot access private snapshot file'}\n")
    print("Webhook route verified. No pending updates were discarded.")


if __name__ == "__main__":
    main()
