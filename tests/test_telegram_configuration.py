import copy
import importlib.util
import json
import logging
import os
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "configure_telegram", Path(__file__).parents[1] / "scripts/configure_telegram.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

ACCOUNT = "111111111111"
ARN = f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:shared-bot-example"
TOKEN = "123456:" + "x" * 30


@pytest.fixture
def environment(tmp_path):
    state = {
        "name": "Old display name",
        "description": "Original description",
        "short_description": "Original short description",
        "commands": [{"command": "help", "description": "Old help"}],
        "menu_button": {
            "type": "web_app",
            "text": "Open dashboard",
            "web_app": {"url": "https://example.com/app"},
        },
    }
    original = copy.deepcopy(state)
    other_scopes = {
        "default": [{"command": "hello", "description": "Other scope"}],
        "all_private_chats:es": [{"command": "ayuda", "description": "Ayuda"}],
    }
    calls, clients = [], []
    snapshot = tmp_path / "private" / "configuration.json"
    sts, secret = Mock(), Mock()
    sts.get_caller_identity.return_value = {"Account": ACCOUNT}
    secret.get_secret_value.return_value = {
        "SecretString": json.dumps(
            {
                "bot_token": TOKEN,
                "bot_username": "fareflare_bot",
            }
        )
    }
    bot = {"id": 123456, "is_bot": True, "username": "fareflare_bot"}
    controls = {"fail_method": None, "ignore_write": False, "change_before_write": False}
    getters = {
        "getMyName": "name",
        "getMyDescription": "description",
        "getMyShortDescription": "short_description",
        "getMyCommands": "commands",
        "getChatMenuButton": "menu_button",
    }
    setters = {
        "setMyName": "name",
        "setMyDescription": "description",
        "setMyShortDescription": "short_description",
        "setMyCommands": "commands",
        "setChatMenuButton": "menu_button",
        "deleteMyCommands": "commands",
    }

    def aws_client(service, **kwargs):
        clients.append(service)
        assert kwargs == {"region_name": "us-east-1"}
        if service == "sts":
            return sts
        assert service == "secretsmanager"
        return secret

    def transport(request):
        assert request.url.host == "api.telegram.org"
        assert request.url.path.startswith("/bot" + TOKEN + "/")
        method, payload = request.url.path.rsplit("/", 1)[1], json.loads(request.content)
        calls.append((method, payload))
        if method == controls["fail_method"]:
            return httpx.Response(429, json={"ok": False, "description": TOKEN})
        if method == "getMe":
            assert payload == {}
            return httpx.Response(200, json={"ok": True, "result": bot})
        field = getters.get(method, setters.get(method))
        assert field is not None, "Only bot metadata methods may be called"
        if field == "commands":
            assert payload["scope"] == {"type": "all_private_chats"}
        if field != "menu_button":
            assert payload["language_code"] == ""
        else:
            assert "chat_id" not in payload  # Per-chat menu settings stay untouched.
        if method in getters:
            if (
                controls["change_before_write"]
                and method == "getMyName"
                and sum(item[0] == "getMyName" for item in calls) == 2
            ):
                state["name"] = "Changed concurrently"
            result = copy.deepcopy(state[field])
            if field not in {"commands", "menu_button"}:
                result = {field: result}
        else:
            assert snapshot.exists(), "Snapshot must exist before the first write"
            assert os.stat(snapshot).st_mode & 0o777 == 0o600
            assert TOKEN not in snapshot.read_text()
            if not controls["ignore_write"]:
                state[field] = [] if method == "deleteMyCommands" else copy.deepcopy(payload[field])
            result = True
        return httpx.Response(200, json={"ok": True, "result": result})

    kwargs = {
        "secret_arn": ARN,
        "aws_account": ACCOUNT,
        "region": "us-east-1",
        "aws_client": aws_client,
        "transport": httpx.MockTransport(transport),
    }
    return {
        "kwargs": kwargs,
        "snapshot": snapshot,
        "state": state,
        "original": original,
        "calls": calls,
        "clients": clients,
        "sts": sts,
        "secret": secret,
        "bot": bot,
        "controls": controls,
        "other_scopes": other_scopes,
    }


def writes(environment):
    return [method for method, _ in environment["calls"] if not method.startswith("get")]


def apply(environment):
    return module.configure(**environment["kwargs"], apply=True, snapshot=environment["snapshot"])


def test_default_preview_reads_identity_and_settings_without_mutation(environment):
    result = module.configure(**environment["kwargs"])
    assert result["applied"] is False and result["bot_username"] == "fareflare_bot"
    assert set(result["changed"]) == {
        "name",
        "description",
        "short_description",
        "commands",
        "menu_button",
    }
    assert result["desired"]["name"] == "Fareflare"
    assert not writes(environment) and not environment["snapshot"].exists()
    assert environment["state"] == environment["original"]
    assert TOKEN not in json.dumps(result)


def test_apply_snapshots_then_reads_back_each_setting_and_preserves_unrelated_scopes(
    environment, caplog
):
    other_scopes = copy.deepcopy(environment["other_scopes"])
    with caplog.at_level(logging.INFO, logger="httpx"):
        result = apply(environment)
    assert result["applied"] is True
    assert environment["state"] == module.DESIRED
    saved = json.loads(environment["snapshot"].read_text())
    assert saved["previous"] == environment["original"] and saved["desired"] == module.DESIRED
    assert saved["bot_id"] == "123456" and saved["aws_account"] == ACCOUNT
    assert environment["other_scopes"] == other_scopes
    for index, (method, _) in enumerate(environment["calls"]):
        if method.startswith("set"):
            assert environment["calls"][index - 1][0].startswith("get")
            assert environment["calls"][index + 1][0].startswith("get")
    assert TOKEN not in caplog.text and "bot[REDACTED]" in caplog.text
    assert [item["command"] for item in environment["state"]["commands"]] == [
        "start",
        "flights",
        "add",
        "settings",
        "help",
        "cancel",
        "stop",
    ]


def test_restore_reinstates_previous_values_and_a_repeated_restore_is_read_only(environment):
    apply(environment)
    assert (
        module.configure(**environment["kwargs"], restore=environment["snapshot"])["applied"]
        is True
    )
    assert environment["state"] == environment["original"]
    environment["calls"].clear()
    result = module.configure(**environment["kwargs"], restore=environment["snapshot"])
    assert result["changed"] == [] and not result["applied"] and not writes(environment)


def test_restore_deletes_empty_private_command_scope_to_reinstate_fallback(environment):
    environment["state"]["commands"] = []
    apply(environment)
    module.configure(**environment["kwargs"], restore=environment["snapshot"])
    assert environment["state"]["commands"] == []
    assert "deleteMyCommands" in writes(environment)


def test_partial_failure_keeps_snapshot_and_restore_only_changes_applied_fields(environment):
    environment["controls"]["fail_method"] = "setMyDescription"
    with pytest.raises(module.ConfigurationError, match="Telegram request failed") as error:
        apply(environment)
    assert TOKEN not in str(error.value)
    assert environment["state"]["name"] == "Fareflare"
    assert environment["state"]["description"] == environment["original"]["description"]
    assert environment["snapshot"].exists()
    environment["controls"]["fail_method"] = None
    environment["calls"].clear()
    module.configure(**environment["kwargs"], restore=environment["snapshot"])
    assert environment["state"] == environment["original"]
    assert writes(environment) == ["setMyName"]


def test_rollback_refuses_unrelated_change_before_any_mutation(environment):
    apply(environment)
    environment["state"]["description"] = "Edited outside this tool"
    environment["calls"].clear()
    with pytest.raises(module.ConfigurationError, match="changed after this snapshot"):
        module.configure(**environment["kwargs"], restore=environment["snapshot"])
    assert not writes(environment)
    assert environment["state"]["description"] == "Edited outside this tool"


def test_apply_refuses_concurrent_metadata_edit_before_mutation(environment):
    environment["controls"]["change_before_write"] = True
    with pytest.raises(module.ConfigurationError, match="changed during"):
        apply(environment)
    assert not writes(environment)
    assert environment["snapshot"].exists()


def test_failed_readback_stops_after_first_write(environment):
    environment["controls"]["ignore_write"] = True
    with pytest.raises(module.ConfigurationError, match="readback"):
        apply(environment)
    assert writes(environment) == ["setMyName"] and environment["snapshot"].exists()


def test_existing_snapshot_and_symlink_are_never_overwritten(environment, tmp_path):
    snapshot = environment["snapshot"]
    snapshot.parent.mkdir()
    snapshot.write_text("existing private file")
    with pytest.raises(FileExistsError):
        apply(environment)
    assert snapshot.read_text() == "existing private file" and not writes(environment)
    snapshot.unlink()
    other = tmp_path / "keep.json"
    other.write_text("keep")
    snapshot.symlink_to(other)
    with pytest.raises(FileExistsError):
        apply(environment)
    assert other.read_text() == "keep" and not writes(environment)


def test_wrong_account_never_reads_secret_or_contacts_telegram(environment):
    environment["sts"].get_caller_identity.return_value = {"Account": "222222222222"}
    with pytest.raises(module.ConfigurationError, match="AWS identity"):
        apply(environment)
    environment["secret"].get_secret_value.assert_not_called()
    assert not environment["calls"] and not environment["snapshot"].exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret_arn": ARN.replace(ACCOUNT, "222222222222")},
        {"secret_arn": ARN.replace("us-east-1", "us-west-2")},
        {"aws_account": "invalid"},
    ],
)
def test_invalid_aws_guard_rejected_without_access(environment, overrides):
    with pytest.raises(module.ConfigurationError):
        module.configure(**{**environment["kwargs"], **overrides})
    assert not environment["clients"] and not environment["calls"]


@pytest.mark.parametrize("change", [{"id": 654321}, {"username": "another_bot"}, {"is_bot": False}])
def test_bot_identity_must_match_secret_before_reading_or_changing_profile(environment, change):
    environment["bot"].update(change)
    with pytest.raises(module.ConfigurationError, match="Telegram identity"):
        apply(environment)
    assert [method for method, _ in environment["calls"]] == ["getMe"]
    assert not environment["snapshot"].exists()


def test_public_snapshot_and_foreign_bot_snapshot_are_rejected(environment):
    apply(environment)
    environment["calls"].clear()
    snapshot = environment["snapshot"]
    snapshot.chmod(0o644)
    with pytest.raises(module.ConfigurationError, match="private regular file"):
        module.configure(**environment["kwargs"], restore=snapshot)
    assert not environment["calls"]
    snapshot.chmod(0o600)
    saved = json.loads(snapshot.read_text())
    saved["bot_id"] = "654321"
    snapshot.write_text(json.dumps(saved))
    with pytest.raises(module.ConfigurationError, match="Snapshot does not match"):
        module.configure(**environment["kwargs"], restore=snapshot)
    assert not environment["calls"]


def test_apply_requires_private_snapshot_and_restore_excludes_apply(environment):
    for options in (
        {"apply": True},
        {"snapshot": environment["snapshot"]},
        {"apply": True, "restore": environment["snapshot"]},
    ):
        with pytest.raises(module.ConfigurationError, match="Use --apply"):
            module.configure(**environment["kwargs"], **options)
    assert not environment["clients"] and not environment["calls"]


def test_already_configured_bot_does_not_create_snapshot_or_mutate(environment):
    environment["state"].update(copy.deepcopy(module.DESIRED))
    result = apply(environment)
    assert not result["changed"] and not result["applied"]
    assert not environment["snapshot"].exists() and not writes(environment)
