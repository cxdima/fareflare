import copy
import importlib.util
import json
import logging
import os
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location("route_telegram", Path(__file__).parents[1] / "scripts/route_telegram.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

ACCOUNT = "111111111111"
ARN = f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:shared-bot-example"
TOKEN = "123456:" + "x" * 30
SECRET = "s" * 40
NEW_URL = "https://example.execute-api.us-east-1.amazonaws.com/telegram/webhook"
OLD_URL = "https://example.lambda-url.us-east-1.on.aws/"


@pytest.fixture
def environment(tmp_path):
    info = {"url": OLD_URL, "max_connections": 40, "allowed_updates": ["message", "edited_message"],
            "has_custom_certificate": False, "pending_update_count": 3, "ip_address": "8.8.8.8"}
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": ACCOUNT}
    secrets = Mock()
    secrets.get_secret_value.return_value = {"SecretString": json.dumps({
        "bot_token": TOKEN, "bot_username": "fareflare_bot", "webhook_secret": SECRET,
    })}
    clients, calls = [], []
    snapshot = tmp_path / "private" / "route.json"

    def aws_client(service, **kwargs):
        clients.append(service)
        assert kwargs["region_name"] == "us-east-1"
        if service == "sts":
            return sts
        if service == "secretsmanager":
            return secrets
        raise AssertionError("Unexpected service")

    def transport(request):
        assert request.url.host == "api.telegram.org"
        assert request.url.path.startswith("/bot" + TOKEN + "/")
        method = request.url.path.rsplit("/", 1)[1]
        payload = json.loads(request.content)
        calls.append((method, payload))
        if method == "getWebhookInfo":
            return httpx.Response(200, json={"ok": True, "result": copy.deepcopy(info)})
        assert method == "setWebhook"
        assert snapshot.is_file(), "Rollback snapshot must be durable before mutation"
        assert os.stat(snapshot).st_mode & 0o777 == 0o600
        assert TOKEN not in snapshot.read_text() and SECRET not in snapshot.read_text()
        assert payload["secret_token"] == SECRET
        assert payload["drop_pending_updates"] is False
        assert "ip_address" not in payload  # Observed DNS IP is not a fixed routing setting.
        info.update({name: payload[name] for name in ("url", "max_connections", "allowed_updates")})
        return httpx.Response(200, json={"ok": True, "result": True})

    kwargs = {"secret_arn": ARN, "aws_account": ACCOUNT, "region": "us-east-1",
              "aws_client": aws_client, "transport": httpx.MockTransport(transport)}
    return kwargs, snapshot, info, calls, clients, sts, secrets


def test_cutover_and_idempotent_rollback_preserve_pending_updates_and_credentials(environment, caplog):
    kwargs, snapshot, info, calls, clients, _, secrets = environment
    with caplog.at_level(logging.INFO, logger="httpx"):
        module.route(**kwargs, url=NEW_URL, snapshot=snapshot)
        assert json.loads(snapshot.read_text())["previous_webhook"]["url"] == OLD_URL
        assert [call[0] for call in calls] == ["getWebhookInfo", "setWebhook", "getWebhookInfo"]
        assert info["url"] == NEW_URL and info["max_connections"] == 4
        assert info["allowed_updates"] == ["message", "edited_message"]
        assert info["pending_update_count"] == 3
        module.route(**kwargs, restore=snapshot)
        assert info["url"] == OLD_URL and info["max_connections"] == 40
        module.route(**kwargs, restore=snapshot)
    assert sum(method == "setWebhook" for method, _ in calls) == 2
    assert calls[-1][0] == "getWebhookInfo"
    assert clients == ["sts", "secretsmanager"] * 3
    secrets.get_secret_value.assert_called_with(SecretId=ARN)
    assert TOKEN not in caplog.text and SECRET not in caplog.text
    assert "bot[REDACTED]" in caplog.text


def test_account_mismatch_never_reads_secret_or_contacts_bot(environment):
    kwargs, snapshot, _, calls, clients, sts, secrets = environment
    sts.get_caller_identity.return_value = {"Account": "222222222222"}
    with pytest.raises(module.RouteError, match="identity"):
        module.route(**kwargs, url=NEW_URL, snapshot=snapshot)
    assert clients == ["sts"] and not calls and not snapshot.exists()
    secrets.get_secret_value.assert_not_called()


def test_foreign_secret_arn_is_rejected_before_aws_or_bot_access(environment):
    kwargs, snapshot, _, calls, clients, _, _ = environment
    with pytest.raises(module.RouteError, match="account and region"):
        module.route(**{**kwargs, "secret_arn": ARN.replace(ACCOUNT, "222222222222")}, url=NEW_URL, snapshot=snapshot)
    assert not calls and not clients


@pytest.mark.parametrize("url", [
    "http://example.com/telegram/webhook", "https://example.com/", "https://example.com/telegram/webhook?secret=x",
    "https://example.com/telegram/webhook#fragment", "https://user:password@example.com/telegram/webhook",
    "https://127.0.0.1/telegram/webhook", "https://example.com:8443/telegram/webhook",
    "https://example.com/telegram/../telegram/webhook", "https://example.com/telegram/webhook\n",
])
def test_invalid_target_never_contacts_aws_or_telegram(environment, url):
    kwargs, snapshot, _, calls, clients, _, _ = environment
    with pytest.raises(module.RouteError):
        module.route(**kwargs, url=url, snapshot=snapshot)
    assert not calls and not clients and not snapshot.exists()


def test_existing_snapshot_is_never_overwritten_or_used_for_cutover(environment):
    kwargs, snapshot, _, calls, _, _, _ = environment
    snapshot.parent.mkdir()
    snapshot.write_text("keep this existing file")
    with pytest.raises(FileExistsError):
        module.route(**kwargs, url=NEW_URL, snapshot=snapshot)
    assert snapshot.read_text() == "keep this existing file"
    assert [item[0] for item in calls] == ["getWebhookInfo"]


def test_snapshot_symlink_is_rejected_before_mutation(environment, tmp_path):
    kwargs, snapshot, _, calls, _, _, _ = environment
    snapshot.parent.mkdir()
    target = tmp_path / "existing.json"
    target.write_text("keep")
    snapshot.symlink_to(target)
    with pytest.raises(FileExistsError):
        module.route(**kwargs, url=NEW_URL, snapshot=snapshot)
    assert target.read_text() == "keep"
    assert all(method != "setWebhook" for method, _ in calls)


def test_custom_certificate_route_cannot_be_silently_lost(environment):
    kwargs, snapshot, info, calls, _, _, _ = environment
    info["has_custom_certificate"] = True
    with pytest.raises(module.RouteError, match="custom certificates"):
        module.route(**kwargs, url=NEW_URL, snapshot=snapshot)
    assert not snapshot.exists() and len(calls) == 1


def test_rollback_refuses_other_bot_changed_secret_or_public_snapshot(environment):
    kwargs, snapshot, _, calls, _, _, secrets = environment
    module.route(**kwargs, url=NEW_URL, snapshot=snapshot)
    calls.clear()
    config = json.loads(secrets.get_secret_value.return_value["SecretString"])
    for changed in ({**config, "bot_token": TOKEN.replace("123456", "654321")},
                    {**config, "webhook_secret": "t" * 40}):
        secrets.get_secret_value.return_value = {"SecretString": json.dumps(changed)}
        with pytest.raises(module.RouteError, match="Snapshot does not match"):
            module.route(**kwargs, restore=snapshot)
        assert not calls
    snapshot.chmod(0o644)
    with pytest.raises(module.RouteError, match="private regular file"):
        module.route(**kwargs, restore=snapshot)
    assert not calls


def test_rollback_does_not_replace_newer_unrelated_route(environment):
    kwargs, snapshot, info, calls, _, _, _ = environment
    module.route(**kwargs, url=NEW_URL, snapshot=snapshot)
    info["url"] = "https://another.example.com/telegram/webhook"
    calls.clear()
    with pytest.raises(module.RouteError, match="changed after this snapshot"):
        module.route(**kwargs, restore=snapshot)
    assert [method for method, _ in calls] == ["getWebhookInfo"]


def test_failed_mutation_leaves_rollback_snapshot_and_hides_bot_error_body(environment):
    kwargs, snapshot, info, calls, _, _, _ = environment

    def transport(request):
        method = request.url.path.rsplit("/", 1)[1]
        calls.append((method, {}))
        if method == "getWebhookInfo":
            return httpx.Response(200, json={"ok": True, "result": info})
        assert snapshot.exists()
        return httpx.Response(400, json={"ok": False, "description": TOKEN + SECRET})

    with pytest.raises(module.RouteError) as error:
        module.route(**{**kwargs, "transport": httpx.MockTransport(transport)}, url=NEW_URL, snapshot=snapshot)
    assert TOKEN not in str(error.value) and SECRET not in str(error.value)
    assert snapshot.exists() and info["url"] == OLD_URL


def test_readback_mismatch_reports_failure_without_automatic_second_mutation(environment):
    kwargs, snapshot, info, calls, _, _, _ = environment

    def transport(request):
        method = request.url.path.rsplit("/", 1)[1]
        calls.append((method, {}))
        return httpx.Response(200, json={"ok": True, "result": info if method == "getWebhookInfo" else True})

    with pytest.raises(module.RouteError, match="readback"):
        module.route(**{**kwargs, "transport": httpx.MockTransport(transport)}, url=NEW_URL, snapshot=snapshot)
    assert snapshot.exists()
    assert sum(method == "setWebhook" for method, _ in calls) == 1


def test_enable_callbacks_on_existing_route_preserves_filters_connections_and_is_reversible(environment):
    kwargs, snapshot, info, calls, _, _, _ = environment
    info["url"], info["max_connections"] = NEW_URL, 17
    module.route(**kwargs, url=NEW_URL, snapshot=snapshot, enable_callbacks=True)
    assert info["url"] == NEW_URL and info["max_connections"] == 17
    assert info["allowed_updates"] == ["message", "edited_message", "callback_query"]
    assert info["pending_update_count"] == 3
    saved = json.loads(snapshot.read_text())
    assert saved["version"] == 2
    assert saved["previous_webhook"]["url"] == NEW_URL
    assert saved["target_webhook"]["allowed_updates"] == info["allowed_updates"]
    module.route(**kwargs, restore=snapshot)
    assert info["url"] == NEW_URL and info["max_connections"] == 17
    assert info["allowed_updates"] == ["message", "edited_message"]
    assert sum(method == "setWebhook" for method, _ in calls) == 2


@pytest.mark.parametrize("updates", [[], ["message", "callback_query"]])
def test_callback_enable_is_read_only_when_already_allowed(environment, updates):
    kwargs, snapshot, info, calls, _, _, _ = environment
    info["url"], info["allowed_updates"] = NEW_URL, updates
    module.route(**kwargs, url=NEW_URL, snapshot=snapshot, enable_callbacks=True)
    assert info["allowed_updates"] == updates and not snapshot.exists()
    assert [method for method, _ in calls] == ["getWebhookInfo"]


@pytest.mark.parametrize("change", [{"max_connections": 11}, {"allowed_updates": ["message"]}])
def test_new_snapshot_refuses_rollback_over_unrelated_webhook_configuration(environment, change):
    kwargs, snapshot, info, calls, _, _, _ = environment
    module.route(**kwargs, url=NEW_URL, snapshot=snapshot, enable_callbacks=True)
    info.update(change)
    calls.clear()
    with pytest.raises(module.RouteError, match="changed after this snapshot"):
        module.route(**kwargs, restore=snapshot)
    assert [method for method, _ in calls] == ["getWebhookInfo"]


def test_legacy_route_snapshot_still_restores(environment):
    kwargs, snapshot, info, _, _, _, _ = environment
    module.route(**kwargs, url=NEW_URL, snapshot=snapshot)
    saved = json.loads(snapshot.read_text())
    saved["version"] = 1
    saved.pop("target_webhook")
    snapshot.write_text(json.dumps(saved))
    module.route(**kwargs, restore=snapshot)
    assert info["url"] == OLD_URL and info["max_connections"] == 40


def test_callbacks_cannot_be_combined_with_restore(environment):
    kwargs, snapshot, _, calls, clients, _, _ = environment
    with pytest.raises(module.RouteError, match="Choose"):
        module.route(**kwargs, restore=snapshot, enable_callbacks=True)
    assert not calls and not clients


def test_update_filter_readback_ignores_telegram_list_order(environment):
    kwargs, snapshot, info, _, _, _, _ = environment
    info["allowed_updates"] = ["message", "my_chat_member"]
    original_transport = kwargs["transport"]

    def reordered(request):
        response = original_transport.handle_request(request)
        if request.url.path.endswith("/getWebhookInfo"):
            body = response.json()
            body["result"]["allowed_updates"] = list(reversed(body["result"]["allowed_updates"]))
            return httpx.Response(200, json=body)
        return response

    module.route(**{**kwargs, "transport": httpx.MockTransport(reordered)},
                 url=NEW_URL, snapshot=snapshot, enable_callbacks=True)
    assert set(info["allowed_updates"]) == {"message", "my_chat_member", "callback_query"}
    module.route(**{**kwargs, "transport": httpx.MockTransport(reordered)}, restore=snapshot)
    assert set(info["allowed_updates"]) == {"message", "my_chat_member"}
