"""Through CloudFront, limits apply to the visitor, and only CloudFront can say who that is."""

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from fareflare.accounts import Accounts
from fareflare.edge import client_address
from fareflare.portal import create_portal
from fareflare.product_config import ProductConfig
from fareflare.service import MonitoringService

SECRET = "s" * 40
ORIGIN = "https://app.example.com"


def connection(headers: dict[str, str], peer: str = "203.0.113.9") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": (peer, 443),
        }
    )


def test_the_visitor_is_believed_only_with_the_edge_secret():
    viewer = {"CloudFront-Viewer-Address": "198.51.100.7:51234"}
    assert client_address(connection(viewer), SECRET) == "203.0.113.9"
    forged = {**viewer, "X-Fareflare-Edge": "not the secret"}
    assert client_address(connection(forged), SECRET) == "203.0.113.9"
    trusted = {**viewer, "X-Fareflare-Edge": SECRET}
    assert client_address(connection(trusted), SECRET) == "198.51.100.7"
    ipv6 = {"CloudFront-Viewer-Address": "2001:db8::42:443", "X-Fareflare-Edge": SECRET}
    assert client_address(connection(ipv6), SECRET) == "2001:db8::42"
    for bad in ("", "not-an-address:80", "198.51.100.7", "198.51.100.7:port"):
        broken = {"CloudFront-Viewer-Address": bad, "X-Fareflare-Edge": SECRET}
        assert client_address(connection(broken), SECRET) == "203.0.113.9"
    # Without a configured secret (no CDN), no header is believed at all.
    assert client_address(connection(trusted), "") == "203.0.113.9"
    assert client_address(connection({**trusted}), "short") == "203.0.113.9"


def test_visitors_behind_one_edge_keep_separate_sign_in_limits(store, clock, monkeypatch):
    monkeypatch.setenv("FAREFLARE_EDGE_SECRET", SECRET)
    config = ProductConfig(public_url=ORIGIN)
    service = MonitoringService(store, lambda: clock[0])
    accounts = Accounts(store, config, lambda: clock[0])
    with TestClient(
        create_portal(service, config, accounts, auth_attempts_per_minute=2), base_url=ORIGIN
    ) as client:

        def sign_in(viewer: str) -> int:
            return client.post(
                "/auth/login",
                json={"username": "nobody@example.com", "password": "not a real password"},
                headers={"X-Fareflare-Edge": SECRET, "CloudFront-Viewer-Address": viewer + ":1"},
            ).status_code

        assert [sign_in("198.51.100.1") for _ in range(3)] == [401, 401, 429]
        assert sign_in("198.51.100.2") == 401  # Another visitor at the same edge is unaffected.


@pytest.mark.parametrize("header", ["X-Forwarded-For", "CloudFront-Viewer-Address"])
def test_a_forwarded_header_alone_never_moves_the_limit(store, clock, monkeypatch, header):
    monkeypatch.setenv("FAREFLARE_EDGE_SECRET", SECRET)
    config = ProductConfig(public_url=ORIGIN)
    service = MonitoringService(store, lambda: clock[0])
    accounts = Accounts(store, config, lambda: clock[0])
    with TestClient(
        create_portal(service, config, accounts, auth_attempts_per_minute=2), base_url=ORIGIN
    ) as client:
        codes = [
            client.post(
                "/auth/login",
                json={"username": "nobody@example.com", "password": "not a real password"},
                headers={header: f"198.51.100.{number}:1"},
            ).status_code
            for number in range(3)
        ]
        assert codes == [401, 401, 429]
