"""Paged monitor lists retain the account-wide quota count without a full scan."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from fareflare.api import create_app


@pytest.mark.parametrize("status,expected_count", [("paused", 2), ("cancelled", 1), ("expired", 1)])
def test_monitor_pages_report_account_quota_across_status_changes(
    service, flight_url, status, expected_count
):
    first = service.create_monitor("alice", flight_url, "first-monitor")
    second = service.create_monitor("alice", flight_url, "second-monitor")
    service.create_monitor("bob", flight_url, "another-account")
    service._transition_status("alice", first["id"], status)

    with patch.object(
        service.store, "query", side_effect=AssertionError("Do not scan account history")
    ):
        page = service.monitors_page("alice", limit=1)
        following = service.monitors_page("alice", limit=1, cursor=page["next_cursor"])
    assert page["active_count"] == following["active_count"] == expected_count
    assert page["next_cursor"] is not None
    assert following["next_cursor"] is None
    assert {page["items"][0]["id"], following["items"][0]["id"]} == {first["id"], second["id"]}
    assert service.monitors_page("bob")["active_count"] == 1
    assert service.monitors_page("charlie") == {"items": [], "next_cursor": None, "active_count": 0}


def test_api_pagination_exposes_active_count_for_monitors_beyond_first_page(service, flight_url):
    stopped = service.create_monitor("alice", flight_url, "stopped-monitor")
    service.set_status("alice", stopped["id"], "cancelled")
    for number in range(3):
        service.create_monitor("alice", flight_url, f"active-{number}")

    with TestClient(create_app(service, {"alice": "a" * 40, "bob": "b" * 40})) as client:
        first = client.get("/v1/monitors?limit=1", headers={"Authorization": "Bearer " + "a" * 40})
        assert first.status_code == 200
        assert len(first.json()["items"]) == 1
        assert first.json()["active_count"] == 3
        assert first.json()["next_cursor"]
        assert first.headers["cache-control"] == "no-store"
        other = client.get("/v1/monitors", headers={"Authorization": "Bearer " + "b" * 40})
        assert other.json() == {"items": [], "next_cursor": None, "active_count": 0}
        assert client.get("/v1/monitors").status_code == 401
