"""Exercise a deployed release with a disposable account and optional live itinerary.

Usage: PYTHONPATH=src .venv/bin/python examples/product_smoke.py https://fareflare.dev
Add --flight-url to validate scheduled collection. Credentials are written only to
a new private file, and the account is deleted after verification, including on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("origin", help="The deployed HTTPS application origin")
    parser.add_argument("--flight-url")
    parser.add_argument(
        "--wait-seconds", type=int, default=180, choices=range(30, 901), metavar="30-900"
    )
    parser.add_argument("--credentials", type=Path, default=Path(".fareflare/smoke-account.json"))
    parser.add_argument("--report", type=Path, default=Path(".fareflare/product-smoke-report.json"))
    args = parser.parse_args()
    url = urlsplit(args.origin)
    origin = f"{url.scheme}://{url.netloc}"
    if url.scheme != "https":
        raise ValueError("Use the deployed HTTPS application origin")
    credentials = {
        # A reserved example domain: no confirmation email is delivered anywhere.
        "email": "release-" + secrets.token_hex(6) + "@example.com",
        "password": secrets.token_urlsafe(32),
    }
    fd = os.open(args.credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(credentials, output)
    report = {"origin": origin, "verified_at": int(time.time()), "checks": []}
    csrf = None
    with httpx.Client(
        base_url=origin, timeout=35, trust_env=False, follow_redirects=False
    ) as client:

        def require(response, code=200):
            if response.status_code != code:
                raise RuntimeError(
                    f"Release check failed: HTTP {response.status_code} for {response.request.url.path}"
                )
            return response.json()

        try:
            assert client.get("/").status_code == 200
            config = require(client.get("/v1/config"))
            assert config["billing_enabled"] is False and config["registration_mode"] == "open"
            assert client.get("/v1/monitors").status_code == 401
            signed_in = require(
                client.post("/auth/register", json=credentials),
                201,
            )
            csrf = signed_in["csrf_token"]
            session_headers = {"X-CSRF-Token": csrf}
            assert (
                client.post("/v1/api-keys", json={"name": "denied without CSRF"}).status_code == 403
            )
            key = require(
                client.post(
                    "/v1/api-keys", headers=session_headers, json={"name": "Release verification"}
                ),
                201,
            )
            auth = {"Authorization": "Bearer " + key["api_key"]}
            assert key["api_key"] not in client.get("/v1/api-keys").text
            require(client.get("/v1/monitors", headers=auth))
            report["checks"].append("signup-session-csrf-api-key")
            mcp_headers = {
                **auth,
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            }
            tools = require(
                client.post(
                    "/mcp",
                    headers=mcp_headers,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )
            )
            report["mcp_tools"] = len(tools["result"]["tools"])
            for _ in range(2):
                listed = require(
                    client.post(
                        "/mcp",
                        headers=mcp_headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {"name": "list_monitors", "arguments": {}},
                        },
                    )
                )
                assert not listed["result"].get("isError")
            report["checks"].append("warm-hosted-mcp")
            metadata = require(client.get("/.well-known/oauth-protected-resource/mcp"))
            assert metadata["resource"] == origin + "/mcp"
            report["checks"].append("oauth-discovery")
            if args.flight_url:
                monitor = require(
                    client.post(
                        "/v1/monitors",
                        headers={**auth, "Idempotency-Key": "release-" + secrets.token_hex(8)},
                        json={"url": args.flight_url},
                    ),
                    202,
                )
                report["monitor_id"] = monitor["id"]
                report["provider_errors_seen"] = []
                deadline = time.monotonic() + args.wait_seconds
                while time.monotonic() < deadline:
                    current = require(client.get("/v1/monitors/" + monitor["id"], headers=auth))
                    if (
                        current["last_error"]
                        and current["last_error"] not in report["provider_errors_seen"]
                    ):
                        report["provider_errors_seen"].append(current["last_error"])
                    if (
                        current["latest"]
                        and current["latest"]["observed_at"] >= monitor["created_at"]
                    ):
                        observation = current["latest"]
                        assert observation["evidence"]["identity_verified"]
                        assert observation["evidence"]["party_verified"]
                        report["observation"] = observation
                        report["checks"].append("live-scheduled-price-collection")
                        break
                    time.sleep(3)
                else:
                    raise RuntimeError(
                        "No verified price within the release check's bounded observation window"
                    )
            require(client.delete("/v1/api-keys/" + key["id"], headers=session_headers))
            assert client.get("/v1/monitors", headers=auth).status_code == 401
            report["checks"].append("api-key-revocation")
        finally:
            if csrf:
                require(
                    client.request(
                        "DELETE",
                        "/v1/account",
                        headers={"X-CSRF-Token": csrf},
                        json={"password": credentials["password"]},
                    )
                )
                report["account_deleted"] = True
            args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
