"""Fareflare tests use isolated stores and do not load local credentials."""

import json
import os
from pathlib import Path

import boto3
import pytest
from hypothesis import settings
from moto import mock_aws

from fareflare.service import MonitoringService
from fareflare.store import DynamoStore, SQLiteStore

EXAMPLE = Path(__file__).parents[1] / "examples/demo.json"

# Generated cases are fixed in CI, so a failure there can be reproduced; locally they
# vary from run to run. HYPOTHESIS_PROFILE=thorough searches much harder.
settings.register_profile("ci", derandomize=True, deadline=None)
settings.register_profile("dev", deadline=None)
settings.register_profile("thorough", deadline=None, max_examples=3000)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci" if os.environ.get("CI") else "dev"))


@pytest.fixture
def flight_url():
    return json.loads(EXAMPLE.read_text())["url"]


@pytest.fixture
def clock():
    return [1793653200]  # 2026-11-02, before the real sample itinerary departs.


@pytest.fixture(params=["sqlite", "dynamo"])
def store(request, tmp_path):
    if request.param == "sqlite":
        yield SQLiteStore(tmp_path / "next.sqlite3")
        return
    with mock_aws():
        client = boto3.client(
            "dynamodb",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        client.create_table(
            TableName="fareflare-tests",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": name, "AttributeType": kind}
                for name, kind in (("id", "S"), ("partition", "S"), ("due", "N"))
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "partition-due",
                    "KeySchema": [
                        {"AttributeName": "partition", "KeyType": "HASH"},
                        {"AttributeName": "due", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        yield DynamoStore("fareflare-tests", client=client)


@pytest.fixture
def service(store, clock):
    return MonitoringService(store, lambda: clock[0])
