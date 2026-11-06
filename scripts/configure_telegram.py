#!/usr/bin/env python3
"""Preview or apply Fareflare bot metadata with a private rollback snapshot."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

from fareflare.delivery import install_telegram_log_redaction

PRIVATE_SCOPE = {"type": "all_private_chats"}
COMMANDS = [
    {"command": "start", "description": "Open your flight dashboard"},
    {"command": "flights", "description": "View flights and recent prices"},
    {"command": "add", "description": "Watch a Google Flights link"},
    {"command": "settings", "description": "Manage alert and message preferences"},
    {"command": "help", "description": "Get help using Fareflare"},
    {"command": "cancel", "description": "Cancel the current action"},
    {"command": "stop", "description": "Disconnect Telegram alerts"},
]
DESIRED = {
    "name": "Fareflare",
    "description": (
        "Track flight prices from a Google Flights link. View your flights and recent prices, "
        "manage tracking, and choose how alerts reach you. Connect your Fareflare account to get started."
    ),
    "short_description": "Flight price alerts with your flights, price history and controls in one chat.",
    "commands": COMMANDS,
    "menu_button": {"type": "commands"},
}
_METHODS = {
    "name": ("getMyName", "setMyName"),
    "description": ("getMyDescription", "setMyDescription"),
    "short_description": ("getMyShortDescription", "setMyShortDescription"),
    "commands": ("getMyCommands", "setMyCommands"),
    "menu_button": ("getChatMenuButton", "setChatMenuButton"),
}


class ConfigurationError(ValueError):
    """Operator-safe error without credentials or a remote response body."""


def _write_snapshot(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_snapshot(path: Path) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ConfigurationError("Rollback snapshot must be a private regular file (mode 0600)")
        encoded = source.read(65_537)
    if len(encoded) > 65_536:
        raise ConfigurationError("Rollback snapshot exceeds the size limit")
    try:
        result = json.loads(encoded)
    except ValueError:
        raise ConfigurationError("Invalid rollback snapshot") from None
    if not isinstance(result, dict):
        raise ConfigurationError("Invalid rollback snapshot")
    return result


def _validate_settings(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != set(_METHODS):
        raise ConfigurationError("Invalid bot metadata settings")
    for field, maximum in (("name", 64), ("description", 512), ("short_description", 120)):
        if not isinstance(value[field], str) or len(value[field]) > maximum:
            raise ConfigurationError("Invalid bot metadata settings")
    commands = value["commands"]
    if (not isinstance(commands, list) or len(commands) > 100
            or any(not isinstance(command, dict) or set(command) != {"command", "description"}
                   or not isinstance(command["command"], str)
                   or not re.fullmatch(r"[a-z0-9_]{1,32}", command["command"])
                   or not isinstance(command["description"], str)
                   or not 1 <= len(command["description"]) <= 256 for command in commands)):
        raise ConfigurationError("Invalid bot command settings")
    menu = value["menu_button"]
    if not isinstance(menu, dict) or menu.get("type") not in {"default", "commands", "web_app"}:
        raise ConfigurationError("Invalid bot menu settings")
    if menu["type"] in {"default", "commands"} and set(menu) != {"type"}:
        raise ConfigurationError("Invalid bot menu settings")
    if menu["type"] == "web_app" and (
        set(menu) != {"type", "text", "web_app"} or not isinstance(menu["text"], str)
        or not isinstance(menu["web_app"], dict) or set(menu["web_app"]) != {"url"}
        or not isinstance(menu["web_app"]["url"], str)
        or not menu["web_app"]["url"].startswith("https://")
    ):
        raise ConfigurationError("Invalid bot menu settings")
    return value


def configure(*, secret_arn: str, aws_account: str, region: str, apply: bool = False,
              snapshot: Path | None = None, restore: Path | None = None,
              aws_client=None, transport=None) -> dict:
    """Only default-language metadata, private command scope and default menu are changed."""
    if (not re.fullmatch(r"[0-9]{12}", aws_account)
            or not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region)):
        raise ConfigurationError("Provide the expected AWS account ID and region")
    arn = secret_arn.split(":", 5)
    if (len(arn) != 6 or arn[:3] != ["arn", "aws", "secretsmanager"] or arn[3] != region
            or arn[4] != aws_account or not arn[5].startswith("secret:") or len(arn[5]) <= 7):
        raise ConfigurationError("The secret ARN must belong to the expected account and region")
    if (apply and snapshot is None or snapshot is not None and not apply
            or restore is not None and (apply or snapshot is not None)):
        raise ConfigurationError("Use --apply with --snapshot, --restore, or neither to preview")
    saved = _read_snapshot(restore) if restore is not None else None
    client_factory = aws_client or boto3.client
    try:
        identity = client_factory("sts", region_name=region).get_caller_identity()
        if identity.get("Account") != aws_account:
            raise ConfigurationError("AWS identity does not match the expected account")
        response = client_factory("secretsmanager", region_name=region).get_secret_value(SecretId=secret_arn)
        config = json.loads(response["SecretString"])
        token, username = config["bot_token"], config["bot_username"]
        if (not isinstance(token, str) or not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token)
                or not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)):
            raise ConfigurationError("Configured bot credentials are invalid")
    except (BotoCoreError, ClientError, KeyError, TypeError, json.JSONDecodeError):
        raise ConfigurationError("Unable to load the configured bot credentials") from None
    bot_id = token.partition(":")[0]
    if saved is not None and (
        saved.get("version") != 1 or saved.get("aws_account") != aws_account
        or saved.get("secret_arn") != secret_arn or saved.get("bot_id") != bot_id
        or not isinstance(saved.get("bot_username"), str)
        or saved.get("bot_username", "").lower() != username.lower()
    ):
        raise ConfigurationError("Snapshot does not match the expected account and bot")
    desired = _validate_settings(saved.get("previous") if saved is not None else DESIRED)
    expected = _validate_settings(saved.get("desired")) if saved is not None else None
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
                raise ConfigurationError("Telegram request failed; inspect the snapshot before retrying") from None

        def scope(field: str) -> dict:
            if field == "menu_button":
                return {}
            return {"language_code": "", **({"scope": PRIVATE_SCOPE} if field == "commands" else {})}

        def read(field: str):
            value = call(_METHODS[field][0], scope(field))
            if field in {"commands", "menu_button"}:
                return value
            if not isinstance(value, dict) or field not in value:
                raise ConfigurationError("Telegram returned invalid bot metadata")
            return value[field]

        bot = call("getMe")
        if (not isinstance(bot, dict) or bot.get("is_bot") is not True
                or str(bot.get("id")) != bot_id or not isinstance(bot.get("username"), str)
                or bot["username"].lower() != username.lower()):
            raise ConfigurationError("Telegram identity does not match the configured bot")
        current = _validate_settings({field: read(field) for field in _METHODS})
        if expected is not None and any(current[key] not in (desired[key], expected[key]) for key in _METHODS):
            raise ConfigurationError("Bot metadata changed after this snapshot; refusing unrelated changes")
        changed = [field for field in _METHODS if current[field] != desired[field]]
        result = {"bot_username": username, "changed": changed, "applied": False, "desired": desired}
        if not changed or not apply and saved is None:
            return result
        if saved is None:
            assert snapshot is not None
            _write_snapshot(snapshot, {
                "version": 1, "created_at": datetime.now(UTC).isoformat(), "aws_account": aws_account,
                "secret_arn": secret_arn, "bot_id": bot_id, "bot_username": username,
                "previous": current, "desired": desired,
            })
        for field in changed:
            if read(field) != current[field]:
                raise ConfigurationError("Bot metadata changed during configuration; inspect the snapshot")
            method = _METHODS[field][1]
            payload = {**scope(field), field: desired[field]}
            if field == "commands" and not desired[field]:
                method, payload = "deleteMyCommands", scope(field)
            if call(method, payload) is not True:
                raise ConfigurationError("Telegram did not confirm configuration; inspect the snapshot")
            if read(field) != desired[field]:
                raise ConfigurationError("Configuration readback did not match; inspect the snapshot")
        result["applied"] = True
        return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--aws-account", required=True)
    parser.add_argument("--region", default="us-east-1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", type=Path)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args(argv)
    try:
        result = configure(**vars(args))
    except (ConfigurationError, OSError) as exc:
        parser.exit(1, f"Configuration failed: {exc if isinstance(exc, ConfigurationError) else 'Cannot access private snapshot file'}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
