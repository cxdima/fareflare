"""Official MCP SDK adapter. Calls the authenticated API; owns no monitoring state."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from fareflare.preferences import Preferences


def make_server(api_url: str, api_key: str, transport=None) -> MCPServer:
    parts = urlsplit(api_url)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or (parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"))
        or len(api_key) < 32
    ):
        raise ValueError("MCP requires an HTTPS API URL (or local HTTP) and a service API key")
    server = MCPServer(
        "fareflare",
        instructions=(
            "Manage persistent flight monitors. Prices include observation timestamps; "
            "pending monitors have no validated observation. Monitoring runs independently "
            "of this connection when a worker is running. Stale or blocked collection is explicit. "
            "Amounts use currency minor units, and lows mean lowest observed since tracking began."
        ),
    )

    async def call(method: str, path: str, *, body=None, key: str | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_key}"}
        if key:
            headers["Idempotency-Key"] = key
        try:
            async with httpx.AsyncClient(
                base_url=api_url.rstrip("/") + "/",
                headers=headers,
                timeout=15,
                follow_redirects=False,
                transport=transport,
                trust_env=False,
            ) as client:
                response = await client.request(method, path, json=body)
        except httpx.HTTPError:
            raise ToolError(
                "Monitoring API unavailable; retry using the same request key."
            ) from None
        if not response.is_success:
            raise ToolError(f"Monitoring API rejected the request (HTTP {response.status_code})")
        return response.json()

    def identifier(value: str, resource: str = "monitor") -> str:
        if not re.fullmatch(r"[a-f0-9]{32}", value):
            raise ToolError(f"Invalid {resource} identifier")
        return value

    @server.tool()
    async def create_monitor(
        url: str,
        idempotency_key: str,
        interval_seconds: int = 900,
        policy_kind: str = "new_low",
        min_drop_minor: int = 0,
        threshold_minor: int | None = None,
        notify_rebounds: bool = False,
        webhook_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a selected-flight monitor, optionally bound to a verified webhook. Reuse the request key on retries."""
        return await call(
            "POST",
            "v1/monitors",
            body={
                "url": url,
                "interval_seconds": interval_seconds,
                "policy": {
                    "kind": policy_kind,
                    "min_drop_minor": min_drop_minor,
                    "threshold_minor": threshold_minor,
                    "notify_rebounds": notify_rebounds,
                },
                "webhook_id": identifier(webhook_id, "webhook") if webhook_id is not None else None,
            },
            key=idempotency_key,
        )

    @server.tool()
    async def register_webhook(url: str, idempotency_key: str) -> dict[str, Any]:
        """Register an HTTPS destination. Save the signing secret returned once; ownership verification is required before use."""
        return await call("POST", "v1/webhooks", body={"url": url}, key=idempotency_key)

    @server.tool()
    async def list_webhooks(limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        """List this customer's webhook destinations and verification status; secrets are excluded."""
        return await call(
            "GET",
            "v1/webhooks?" + urlencode({"limit": limit, **({"cursor": cursor} if cursor else {})}),
        )

    @server.tool()
    async def get_webhook(webhook_id: str) -> dict[str, Any]:
        """Read a webhook destination owned by this customer, without its signing secret."""
        return await call("GET", f"v1/webhooks/{identifier(webhook_id, 'webhook')}")

    @server.tool()
    async def send_webhook_challenge(webhook_id: str) -> dict[str, Any]:
        """Send a verification token to the HTTPS destination. Retrieve it from the receiver, then call verify_webhook."""
        return await call("POST", f"v1/webhooks/{identifier(webhook_id, 'webhook')}/challenge")

    @server.tool()
    async def verify_webhook(webhook_id: str, token: str) -> dict[str, Any]:
        """Activate a webhook using the verification token received at that destination."""
        return await call(
            "POST", f"v1/webhooks/{identifier(webhook_id, 'webhook')}/verify", body={"token": token}
        )

    @server.tool()
    async def disable_webhook(webhook_id: str) -> dict[str, Any]:
        """Disable a webhook and suppress its queued alerts. An HTTP delivery already in flight may complete."""
        return await call("POST", f"v1/webhooks/{identifier(webhook_id, 'webhook')}/disable")

    @server.tool()
    async def delete_webhook(webhook_id: str) -> dict[str, Any]:
        """Permanently disable a webhook and remove its signing secret. Create a new endpoint to replace it."""
        return await call("DELETE", f"v1/webhooks/{identifier(webhook_id, 'webhook')}")

    @server.tool()
    async def list_monitors(limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        """List this customer's monitors, latest observed prices and freshness."""
        return await call(
            "GET",
            "v1/monitors?" + urlencode({"limit": limit, **({"cursor": cursor} if cursor else {})}),
        )

    @server.tool()
    async def get_monitor(monitor_id: str) -> dict[str, Any]:
        """Get one monitor, including its latest observation timestamp."""
        return await call("GET", f"v1/monitors/{identifier(monitor_id)}")

    @server.tool()
    async def get_price_history(
        monitor_id: str, limit: int = 100, cursor: str | None = None
    ) -> dict[str, Any]:
        """Return observed price history for a monitor owned by this customer."""
        return await call(
            "GET",
            f"v1/monitors/{identifier(monitor_id)}/history?"
            + urlencode({"limit": limit, **({"cursor": cursor} if cursor else {})}),
        )

    @server.tool()
    async def pause_monitor(monitor_id: str) -> dict[str, Any]:
        """Pause a customer's monitor and suppress its queued alerts."""
        return await call(
            "PATCH", f"v1/monitors/{identifier(monitor_id)}", body={"status": "paused"}
        )

    @server.tool()
    async def resume_monitor(monitor_id: str) -> dict[str, Any]:
        """Resume a paused monitor. A new observation is needed before activation."""
        return await call(
            "PATCH", f"v1/monitors/{identifier(monitor_id)}", body={"status": "active"}
        )

    @server.tool()
    async def stop_monitor(monitor_id: str) -> dict[str, Any]:
        """Cancel this customer's monitor; other subscribers are unaffected."""
        return await call(
            "PATCH", f"v1/monitors/{identifier(monitor_id)}", body={"status": "cancelled"}
        )

    @server.tool()
    async def list_alerts(limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        """Inspect queued, delivered and failed alerts for this customer."""
        return await call(
            "GET",
            "v1/alerts?" + urlencode({"limit": limit, **({"cursor": cursor} if cursor else {})}),
        )

    @server.tool()
    async def retry_alert(delivery_id: str) -> dict[str, Any]:
        """Retry a failed alert; later alerts for that monitor wait behind it."""
        if not re.fullmatch(r"[a-f0-9]{64}", delivery_id):
            raise ToolError("Invalid delivery identifier")
        return await call("POST", f"v1/alerts/{delivery_id}/retry")

    @server.tool()
    async def retry_collection(monitor_id: str) -> dict[str, Any]:
        """Retry blocked collection after the underlying issue has been resolved."""
        return await call("POST", f"v1/monitors/{identifier(monitor_id)}/retry-collection")

    @server.tool()
    async def update_policy(
        monitor_id: str,
        kind: str = "new_low",
        min_drop_minor: int = 0,
        threshold_minor: int | None = None,
        notify_rebounds: bool = False,
    ) -> dict[str, Any]:
        """Set a monitor's price threshold and optional rebound alerts."""
        return await call(
            "PUT",
            f"v1/monitors/{identifier(monitor_id)}/policy",
            body={
                "kind": kind,
                "min_drop_minor": min_drop_minor,
                "threshold_minor": threshold_minor,
                "notify_rebounds": notify_rebounds,
            },
        )

    @server.tool()
    async def get_preferences() -> dict[str, Any]:
        """Read account display, Telegram message style, muting and diagnostics preferences."""
        return await call("GET", "v1/preferences")

    @server.tool()
    async def get_message_templates() -> dict[str, Any]:
        """List Telegram message templates, their placeholders, built-in presets and limits."""
        return await call("GET", "v1/preferences/telegram-templates")

    @server.tool()
    async def set_preferences(
        muted: bool | None = None,
        muted_routes: list[str] | None = None,
        settings: Preferences | None = None,
    ) -> dict[str, Any]:
        """Update only supplied preferences; routes use DEN-DFW.

        Settings include the time zone, Telegram message style and templates, and
        diagnostics. Call get_message_templates for valid template placeholders.
        """
        body = settings.model_dump(exclude_unset=True) if settings else {}
        if muted is not None:
            body["muted"] = muted
        if muted_routes is not None:
            body["muted_routes"] = muted_routes
        return await call("PUT", "v1/preferences", body=body)

    return server
