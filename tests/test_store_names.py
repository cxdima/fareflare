"""Resource-name compatibility for documented and existing deployments."""

from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from fareflare.accounts import Accounts
from fareflare.store import DynamoStore


@pytest.mark.parametrize("prefix", ["fareflare", "gfpt-next"])
@pytest.mark.parametrize("suffix", ["dev", "production", "region-2", "x" * 50])
def test_table_names_accept_both_supported_deployment_prefixes(prefix, suffix):
    client = Mock()
    store = DynamoStore(f"{prefix}-{suffix}", client=client)
    assert store.table == f"{prefix}-{suffix}"
    assert store.client is client
    assert not client.mock_calls


@pytest.mark.parametrize(
    "name",
    [
        "gfpricetracker-prices",
        "production",
        "other-fareflare-production",
        "fareflare-",
        "fareflare-ab",
        "gfpt-next-ab",
        "fareflare-" + "x" * 51,
        "gfpt-next-" + "x" * 51,
        "fareflare-Production",
        "fareflare-prod_test",
        "fareflare-prod/test",
        "fareflare-prod\n",
        " fareflare-prod",
    ],
)
def test_invalid_table_names_fail_before_aws_client_creation(name, monkeypatch):
    create_client = Mock(side_effect=AssertionError("No AWS client may be created"))
    monkeypatch.setattr(boto3, "client", create_client)
    with pytest.raises(ValueError, match="fareflare- or gfpt-next-"):
        DynamoStore(name)
    create_client.assert_not_called()


@pytest.mark.parametrize("table", ["fareflare-production", "gfpt-next-production"])
@mock_aws
def test_an_account_can_be_created_with_either_table_prefix(table):
    client = boto3.client(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    client.create_table(
        TableName=table,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
    )
    accounts = Accounts(DynamoStore(table, client=client))
    customer = accounts.register("traveler@example.com", "a long test-only password")
    assert customer["account"]["username"] == "traveler@example.com"
    with pytest.raises(ValueError, match="already uses that email"):
        accounts.register("Traveler@example.com", "a long test-only password")
