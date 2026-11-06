"""Resource-name compatibility for documented and existing deployments."""
import json
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from gfpt_next.accounts import Accounts
from gfpt_next.product_cli import main
from gfpt_next.store import DynamoStore


@pytest.mark.parametrize("prefix", ["fareflare", "gfpt-next"])
@pytest.mark.parametrize("suffix", ["dev", "production", "region-2", "x" * 50])
def test_table_names_accept_both_supported_deployment_prefixes(prefix, suffix):
    client = Mock()
    store = DynamoStore(f"{prefix}-{suffix}", client=client)
    assert store.table == f"{prefix}-{suffix}"
    assert store.client is client
    assert not client.mock_calls


@pytest.mark.parametrize("name", [
    "gfpricetracker-prices", "production", "other-fareflare-production",
    "fareflare-", "fareflare-ab", "gfpt-next-ab", "fareflare-" + "x" * 51,
    "gfpt-next-" + "x" * 51, "fareflare-Production", "fareflare-prod_test",
    "fareflare-prod/test", "fareflare-prod\n", " fareflare-prod",
])
def test_invalid_table_names_fail_before_aws_client_creation(name, monkeypatch):
    create_client = Mock(side_effect=AssertionError("No AWS client may be created"))
    monkeypatch.setattr(boto3, "client", create_client)
    with pytest.raises(ValueError, match="fareflare- or gfpt-next-"):
        DynamoStore(name)
    create_client.assert_not_called()


@pytest.mark.parametrize("table", ["fareflare-production", "gfpt-next-production"])
@mock_aws
def test_deployed_invitation_can_be_redeemed_with_either_table_prefix(table, tmp_path, capsys):
    client = boto3.client("dynamodb", region_name="us-east-1",
                          aws_access_key_id="testing", aws_secret_access_key="testing")
    client.create_table(
        TableName=table, BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
    )
    path = tmp_path / "friend.json"
    main([
        "--public-url", "https://fareflare.example", "invite", str(path),
        "--table", table, "--aws-account", "123456789012", "--region", "us-east-1",
    ])
    invitation = json.loads(path.read_text())
    assert invitation["url"] == "https://fareflare.example/?invite=" + invitation["token"]
    assert invitation["token"] not in capsys.readouterr().out
    assert path.stat().st_mode & 0o777 == 0o600

    accounts = Accounts(DynamoStore(table, client=client))
    customer = accounts.register("traveler", "a long test-only password", invitation["token"])
    assert customer["account"]["username"] == "traveler"
    with pytest.raises(ValueError, match="unused invitation"):
        accounts.register("another", "a long test-only password", invitation["token"])
