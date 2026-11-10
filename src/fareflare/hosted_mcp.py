"""Authenticated, stateless MCP over HTTP using the same API as the stdio adapter."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Sequence

import httpx
from mcp.server.transport_security import (
    RequestBodyLimitMiddleware,
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fareflare.mcp_server import make_server

Authenticator = Callable[[str], str | None | Awaitable[str | None]]
MAX_BODY_BYTES = 16_384


class HostedMCP:
    """An ASGI endpoint; mount with ``Route('/mcp', endpoint=adapter)``.

    The SDK session manager has a single-use lifespan. Request-local instances
    support both concurrent HTTP requests and repeated warm Lambda invocations.
    Tool definitions are shared with stdio; the in-process API enforces tenant
    ownership, input validation, rate limits, and public response projections.
    """

    def __init__(
        self,
        api_app: ASGIApp,
        authenticate: Authenticator,
        *,
        allowed_hosts: Sequence[str],
        allowed_origins: Sequence[str] = (),
        resource_metadata_url: str | None = None,
    ):
        if not allowed_hosts or "*" in allowed_hosts or "*" in allowed_origins:
            raise ValueError("Hosted MCP requires explicit allowed hosts and origins")
        self.api_app = api_app
        self.authenticate = authenticate
        self.resource_metadata_url = resource_metadata_url
        self.security = TransportSecurityMiddleware(
            TransportSecuritySettings(
                allowed_hosts=list(allowed_hosts), allowed_origins=list(allowed_origins)
            )
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        # Ambiguous security headers must never be interpreted differently by
        # the edge adapter, SDK, and authenticated API.
        if any(
            len(request.headers.getlist(name)) > 1 for name in ("authorization", "host", "origin")
        ):
            await Response("Ambiguous request headers", status_code=400)(
                scope, receive, secure_send
            )
            return
        rejected = await self.security.validate_request(request)
        if rejected:
            await rejected(scope, receive, secure_send)
            return
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        tenant = None
        if (
            scheme.lower() == "bearer"
            and 32 <= len(token) <= 8192
            and re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token)
        ):
            tenant = await run_in_threadpool(self.authenticate, token)
            if inspect.isawaitable(tenant):
                tenant = await tenant
        if not tenant:
            challenge = "Bearer"
            if self.resource_metadata_url:
                challenge += f' resource_metadata="{self.resource_metadata_url}"'
            await JSONResponse(
                {"detail": "Valid bearer credentials required"},
                status_code=401,
                headers={"WWW-Authenticate": challenge},
            )(scope, receive, secure_send)
            return
        # This endpoint has no server-initiated stream or persisted sessions.
        if request.method != "POST":
            await Response(status_code=405, headers={"Allow": "POST"})(scope, receive, secure_send)
            return

        async def serve(inner_scope: Scope, inner_receive: Receive, inner_send: Send) -> None:
            async def internal_api(api_scope: Scope, api_receive: Receive, api_send: Send) -> None:
                # Scope state is set by this server, never by a caller header.
                # It lets the API accept an MCP-audience OAuth token only here.
                await self.api_app(
                    {**api_scope, "fareflare.mcp_internal": True}, api_receive, api_send
                )

            # ASGITransport never opens a socket. Use the validated public host
            # so parent Host middleware applies exactly as on ordinary API calls.
            server = make_server(
                f"https://{request.headers['host']}", token, httpx.ASGITransport(app=internal_api)
            )
            app = server.streamable_http_app(
                streamable_http_path=request.url.path,
                json_response=True,
                stateless_http=True,
                max_request_body_size=MAX_BODY_BYTES,
                transport_security=self.security.settings,
            )
            async with app.router.lifespan_context(app):
                await app(inner_scope, inner_receive, inner_send)

        await RequestBodyLimitMiddleware(serve, MAX_BODY_BYTES)(scope, receive, secure_send)


def make_hosted_mcp(
    api_app: ASGIApp,
    authenticate: Authenticator,
    *,
    allowed_hosts: Sequence[str],
    allowed_origins: Sequence[str] = (),
    resource_metadata_url: str | None = None,
) -> HostedMCP:
    return HostedMCP(
        api_app,
        authenticate,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        resource_metadata_url=resource_metadata_url,
    )
