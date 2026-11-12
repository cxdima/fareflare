"""SDK OAuth 2.1 endpoints with persistent, revocable MCP authorization grants.

The SDK owns the authorization-code protocol and S256 verification. This module
owns account consent, opaque token storage, audience policy, and atomic rotation.
Only hashes of authorization codes, access tokens, and refresh tokens are stored.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import (
    build_metadata,
    cors_middleware,
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import RequestBodyLimitMiddleware
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fareflare.accounts import Accounts
from fareflare.credentials import RateLimited, RateLimiter
from fareflare.edge import client_address
from fareflare.product_config import ProductConfig
from fareflare.store import Conflict, Document, Store

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_CLIENT = re.compile(r"[A-Za-z0-9_-]{1,80}")
_ACCESS_LIFETIME = 900
_GRANT_LIFETIME = 30 * 86400
_MAX_CLIENTS = 1000


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class OAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(
        self,
        store: Store,
        accounts: Accounts,
        public_url: str,
        clock: Callable[[], float] = time.time,
    ):
        ProductConfig(public_url=public_url)
        if not public_url:
            raise ValueError("OAuth requires the configured public origin")
        self.store, self.accounts, self.clock = store, accounts, clock
        self.public_url = public_url.rstrip("/")
        self.issuer = self.public_url + "/oauth"
        self.resource = self.public_url + "/mcp"
        self.registration = ClientRegistrationOptions(
            enabled=True, valid_scopes=["monitor"], default_scopes=["monitor"]
        )
        self.revocation = RevocationOptions(enabled=True)

    def _now(self) -> int:
        return int(self.clock())

    def _get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if not _CLIENT.fullmatch(client_id):
            return None
        doc = self.store.get("oauth-client:" + client_id)
        return OAuthClientInformationFull.model_validate(doc.data) if doc else None

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await run_in_threadpool(self._get_client, client_id)

    def _register_client(self, client: OAuthClientInformationFull) -> None:
        if (
            not client.client_id
            or not _CLIENT.fullmatch(client.client_id)
            or client.token_endpoint_auth_method != "none"  # noqa: S105 - a protocol value
            or client.client_secret
            or set(client.grant_types) - {"authorization_code", "refresh_token"}
            or client.response_types != ["code"]
            or not client.redirect_uris
            or len(client.redirect_uris) > 5
            or not client.client_name
            or not 1 <= len(client.client_name) <= 100
            or any(ord(c) < 32 for c in client.client_name)
        ):
            raise RegistrationError(
                "invalid_client_metadata",
                "Register a named public client using PKCE and auth method none",
            )
        for uri in client.redirect_uris:
            parsed = urlsplit(str(uri))
            if (
                len(str(uri)) > 2048
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.scheme not in ("https", "http")
                or (
                    parsed.scheme == "http"
                    and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                )
            ):
                raise RegistrationError(
                    "invalid_redirect_uri",
                    "Use HTTPS or a loopback HTTP callback without credentials or fragments",
                )
        for _ in range(5):
            count = self.store.get("oauth-client-count") or Document(
                "oauth-client-count", "oauth-control", {"count": 0}
            )
            if count.data["count"] >= _MAX_CLIENTS:
                raise RegistrationError(
                    "invalid_client_metadata", "Client registration capacity reached"
                )
            try:
                self.store.commit(
                    [
                        count.update({"count": count.data["count"] + 1}),
                        Document(
                            "oauth-client:" + client.client_id,
                            "oauth-clients",
                            client.model_dump(mode="json"),
                        ),
                    ]
                )
                return
            except Conflict:
                continue
        raise RegistrationError("invalid_client_metadata", "Registration busy; retry later")

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await run_in_threadpool(self._register_client, client_info)

    def _authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource != self.resource:
            raise AuthorizeError("invalid_target", "Use this server's MCP resource URL")
        if set(params.scopes or []) != {"monitor"}:
            raise AuthorizeError("invalid_scope", "The monitor scope is required")
        if not _TOKEN.fullmatch(params.code_challenge) or (
            params.state and len(params.state) > 1024
        ):
            raise AuthorizeError("invalid_request", "Invalid PKCE challenge or state")
        # The SDK checks the registered redirect before this hook. Repeat the
        # exact check so direct provider use cannot bypass that trust boundary.
        client.validate_redirect_uri(params.redirect_uri)
        request_id = secrets.token_urlsafe(32)
        expires = self._now() + 600
        self.store.commit(
            [
                Document(
                    "oauth-request:" + _digest(request_id),
                    "oauth-requests",
                    {
                        "client_id": client.client_id,
                        "params": params.model_dump(mode="json"),
                        "tenant": None,
                        "used": False,
                        "expires_at": expires,
                    },
                    expires_at=expires,
                )
            ]
        )
        return self.public_url + "/?" + urlencode({"authorize": request_id})

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        return await run_in_threadpool(self._authorize, client, params)

    def _request(self, request_id: str) -> Document:
        doc = (
            self.store.get("oauth-request:" + _digest(request_id))
            if _TOKEN.fullmatch(request_id)
            else None
        )
        if not doc or doc.data["used"] or doc.data["expires_at"] <= self._now():
            raise ValueError("Authorization request unavailable or expired")
        return doc

    def consent_request(self, tenant: str, request_id: str) -> dict:
        """Bind the pending request to the signed-in account before showing consent."""
        self.accounts.auth_epoch(tenant)
        for _ in range(5):
            request = self._request(request_id)
            if request.data["tenant"] not in (None, tenant):
                raise ValueError("Authorization request unavailable")
            if request.data["tenant"] is None:
                try:
                    self.store.commit([request.update({**request.data, "tenant": tenant})])
                except Conflict:
                    continue
            client = self._get_client(request.data["client_id"])
            if not client:
                raise ValueError("Authorization client unavailable")
            return {
                "client_id": client.client_id,
                "client_name": client.client_name,
                "scopes": request.data["params"]["scopes"],
                "resource": self.resource,
                "redirect_uri": request.data["params"]["redirect_uri"],
            }
        raise ValueError("Authorization request busy; retry")

    def complete_consent(self, tenant: str, request_id: str, approve: bool) -> dict:
        """Called only behind the portal's authenticated session and CSRF checks."""
        epoch = self.accounts.auth_epoch(tenant)
        request = self._request(request_id)
        if request.data["tenant"] != tenant or type(approve) is not bool:
            raise ValueError("Read the authorization request before approving it")
        params = AuthorizationParams.model_validate(request.data["params"])
        documents = [request.update({**request.data, "used": True})]
        fields = {"state": params.state, "iss": self.issuer}
        if approve:
            code = secrets.token_urlsafe(32)
            expires = self._now() + 120
            documents.append(
                Document(
                    "oauth-code:" + _digest(code),
                    "oauth-codes",
                    {
                        "tenant": tenant,
                        "auth_epoch": epoch,
                        "client_id": request.data["client_id"],
                        "params": params.model_dump(mode="json"),
                        "used": False,
                        "expires_at": expires,
                    },
                    expires_at=expires,
                )
            )
            fields["code"] = code
        else:
            fields["error"] = "access_denied"
        try:
            self.store.commit(documents)
        except Conflict:
            raise ValueError("Authorization request was already completed") from None
        return {"redirect_url": construct_redirect_uri(str(params.redirect_uri), **fields)}

    def _code(self, raw: str, client_id: str) -> Document | None:
        doc = self.store.get("oauth-code:" + _digest(raw)) if _TOKEN.fullmatch(raw) else None
        if (
            not doc
            or doc.data["used"]
            or doc.data["expires_at"] <= self._now()
            or doc.data["client_id"] != client_id
            or not self.accounts.validate_account_active(doc.data["tenant"], doc.data["auth_epoch"])
        ):
            return None
        return doc

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        doc = await run_in_threadpool(self._code, authorization_code, client.client_id or "")
        if not doc:
            return None
        params = doc.data["params"]
        return AuthorizationCode(
            code=authorization_code,
            client_id=doc.data["client_id"],
            expires_at=doc.data["expires_at"],
            subject=doc.data["tenant"],
            **{
                key: params[key]
                for key in (
                    "scopes",
                    "code_challenge",
                    "redirect_uri",
                    "redirect_uri_provided_explicitly",
                    "resource",
                )
            },
        )

    def _tokens(self, grant: Document, *, scopes: list[str]) -> tuple[OAuthToken, list[Document]]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        access_expiry = min(self._now() + _ACCESS_LIFETIME, grant.data["expires_at"])
        common = {key: grant.data[key] for key in ("tenant", "auth_epoch", "client_id", "resource")}
        common.update({"grant": grant.key, "scopes": scopes})
        documents = [
            grant.update({**grant.data, "refresh_digest": _digest(refresh)}),
            Document(
                "oauth-access:" + _digest(access),
                "oauth-tokens",
                {
                    **common,
                    "expires_at": access_expiry,
                },
                expires_at=access_expiry,
            ),
            Document(
                "oauth-refresh:" + _digest(refresh),
                "oauth-tokens",
                {
                    **common,
                    "expires_at": grant.data["expires_at"],
                    "used": False,
                },
                expires_at=grant.data["expires_at"],
            ),
        ]
        return OAuthToken(
            access_token=access,
            token_type="Bearer",  # noqa: S106 - a protocol value
            expires_in=access_expiry - self._now(),
            refresh_token=refresh,
            scope=" ".join(scopes),
        ), documents

    def _exchange_code(self, client_id: str, code: str) -> OAuthToken:
        doc = self._code(code, client_id)
        if not doc:
            raise TokenError("invalid_grant", "Authorization code unavailable")
        grant = Document(
            "oauth-grant:" + secrets.token_hex(16),
            "oauth-grants:" + doc.data["tenant"],
            {
                **{key: doc.data[key] for key in ("tenant", "auth_epoch", "client_id")},
                "resource": self.resource,
                "expires_at": self._now() + _GRANT_LIFETIME,
                "revoked": False,
                "created_at": self._now(),
            },
            expires_at=self._now() + _GRANT_LIFETIME,
        )
        tokens, documents = self._tokens(grant, scopes=doc.data["params"]["scopes"])
        try:
            self.store.commit([doc.update({**doc.data, "used": True}), *documents])
        except Conflict:
            raise TokenError("invalid_grant", "Authorization code already used") from None
        return tokens

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        return await run_in_threadpool(
            self._exchange_code, client.client_id or "", authorization_code.code
        )

    def _grant(self, data: dict) -> Document | None:
        grant = self.store.get(data["grant"])
        if (
            not grant
            or grant.data["revoked"]
            or grant.data["expires_at"] <= self._now()
            or data["resource"] != self.resource
            or data["scopes"] != ["monitor"]
            or not self.accounts.validate_account_active(data["tenant"], data["auth_epoch"])
        ):
            return None
        return grant

    def _access(self, raw: str) -> Document | None:
        doc = self.store.get("oauth-access:" + _digest(raw)) if _TOKEN.fullmatch(raw) else None
        if not doc or doc.data["expires_at"] <= self._now() or not self._grant(doc.data):
            return None
        return doc

    def bearer_to_tenant(self, token: str) -> str | None:
        doc = self._access(token)
        return doc.data["tenant"] if doc else None

    def list_grants(self, tenant: str, *, limit: int = 100, cursor: str | None = None) -> dict:
        epoch = self.accounts.auth_epoch(tenant)
        page = self.store.page("oauth-grants:" + tenant, limit=limit, cursor=cursor, reverse=True)
        items = []
        for candidate in page.items:
            grant = self.store.get(candidate.key)
            if grant is None or grant.data["tenant"] != tenant:
                continue
            client = self._get_client(grant.data["client_id"])
            items.append(
                {
                    "id": grant.key.removeprefix("oauth-grant:"),
                    "client_name": client.client_name if client else "Unavailable application",
                    "created_at": grant.data["created_at"],
                    "expires_at": grant.data["expires_at"],
                    "revoked": grant.data["revoked"] or grant.data["auth_epoch"] != epoch,
                }
            )
        return {"items": items, "next_cursor": page.cursor}

    def revoke_grant(self, tenant: str, identifier: str) -> None:
        self.accounts.auth_epoch(tenant)
        grant = (
            self.store.get("oauth-grant:" + identifier)
            if re.fullmatch(r"[a-f0-9]{32}", identifier)
            else None
        )
        if not grant or grant.data["tenant"] != tenant:
            raise ValueError("Connected application unavailable")
        self._revoke_grant(grant.key)

    async def load_access_token(self, token: str) -> AccessToken | None:
        doc = await run_in_threadpool(self._access, token)
        if not doc:
            return None
        return AccessToken(
            token=token,
            client_id=doc.data["client_id"],
            scopes=doc.data["scopes"],
            expires_at=doc.data["expires_at"],
            resource=self.resource,
            subject=doc.data["tenant"],
            claims={"iss": self.issuer},
        )

    def _revoke_grant(self, key: str) -> None:
        for _ in range(5):
            grant = self.store.get(key)
            if not grant or grant.data["revoked"]:
                return
            try:
                self.store.commit([grant.update({**grant.data, "revoked": True})])
                return
            except Conflict:
                continue
        raise TokenError("invalid_grant", "Grant changed; retry revocation")

    def _refresh(self, raw: str, client_id: str) -> Document | None:
        doc = self.store.get("oauth-refresh:" + _digest(raw)) if _TOKEN.fullmatch(raw) else None
        if not doc or doc.data["client_id"] != client_id or doc.data["expires_at"] <= self._now():
            return None
        grant = self._grant(doc.data)
        if not grant:
            return None
        if doc.data["used"] or grant.data["refresh_digest"] != _digest(raw):
            self._revoke_grant(grant.key)
            return None
        return doc

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        doc = await run_in_threadpool(self._refresh, refresh_token, client.client_id or "")
        if not doc:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=doc.data["client_id"],
            scopes=doc.data["scopes"],
            expires_at=doc.data["expires_at"],
            resource=self.resource,
            subject=doc.data["tenant"],
        )

    def _exchange_refresh(self, client_id: str, raw: str, scopes: list[str]) -> OAuthToken:
        doc = self._refresh(raw, client_id)
        if not doc:
            raise TokenError("invalid_grant", "Refresh token unavailable")
        if scopes != ["monitor"]:
            raise TokenError("invalid_scope", "The monitor scope is required")
        grant = self._grant(doc.data)
        if not grant:
            raise TokenError("invalid_grant", "Authorization grant unavailable")
        tokens, documents = self._tokens(grant, scopes=scopes)
        try:
            self.store.commit([doc.update({**doc.data, "used": True}), *documents])
        except Conflict:
            self._revoke_grant(grant.key)
            raise TokenError("invalid_grant", "Refresh token already used") from None
        return tokens

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        return await run_in_threadpool(
            self._exchange_refresh, client.client_id or "", refresh_token.token, scopes
        )

    def _revoke_token(self, token: AccessToken | RefreshToken) -> None:
        prefix = "oauth-access:" if isinstance(token, AccessToken) else "oauth-refresh:"
        doc = self.store.get(prefix + _digest(token.token))
        if doc and doc.data["client_id"] == token.client_id:
            self._revoke_grant(doc.data["grant"])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await run_in_threadpool(self._revoke_token, token)

    def authorization_metadata(self) -> dict:
        metadata = build_metadata(AnyHttpUrl(self.issuer), None, self.registration, self.revocation)
        result = metadata.model_dump(mode="json", exclude_none=True)
        result.update(
            token_endpoint_auth_methods_supported=["none"],
            revocation_endpoint_auth_methods_supported=["none"],
            authorization_response_iss_parameter_supported=True,
        )
        return result

    async def _metadata(self, request: Request) -> JSONResponse:
        return JSONResponse(self.authorization_metadata(), headers={"Cache-Control": "no-store"})

    def discovery_routes(self) -> list[Route]:
        return [
            Route(
                "/.well-known/oauth-authorization-server/oauth",
                endpoint=cors_middleware(self._metadata, ["GET", "OPTIONS"]),
                methods=["GET", "OPTIONS"],
            ),
            *create_protected_resource_routes(
                AnyHttpUrl(self.resource),
                [AnyHttpUrl(self.issuer)],
                scopes_supported=["monitor"],
                resource_name="Fareflare",
            ),
        ]

    def build_app(self) -> ASGIApp:
        routes = create_auth_routes(
            self,
            AnyHttpUrl(self.issuer),
            client_registration_options=self.registration,
            revocation_options=self.revocation,
        )
        routes[0] = Route(
            "/.well-known/oauth-authorization-server",
            endpoint=cors_middleware(self._metadata, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        )
        guard = _OAuthRequestGuard(Starlette(routes=routes), self)
        return RequestBodyLimitMiddleware(guard, max_body_size=16_384)


class _OAuthRequestGuard:
    """Bound unauthenticated traffic and enforce resource indicators on token requests."""

    def __init__(self, app: ASGIApp, provider: OAuthProvider):
        self.app, self.provider = app, provider
        self.limiter = RateLimiter(provider.store, provider.clock, per_minute=60)
        self.registration_limiter = RateLimiter(provider.store, provider.clock, per_minute=5)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        route = scope["path"].rsplit("/", 1)[-1]

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Content-Type-Options"] = "nosniff"
                location = headers.get("location")
                if (
                    route == "authorize"
                    and location
                    and "error" in parse_qs(urlsplit(location).query)
                ):
                    # SDK-generated error redirects must match the issuer
                    # guarantee advertised for our success/denial responses.
                    headers["Location"] = construct_redirect_uri(location, iss=self.provider.issuer)
            await send(message)

        async def reject(error: str, description: str, status: int = 400) -> None:
            await JSONResponse(
                {"error": error, "error_description": description}, status_code=status
            )(scope, receive, secure_send)

        if request.method == "OPTIONS":
            await self.app(scope, receive, secure_send)
            return
        peer = client_address(request)
        try:
            await run_in_threadpool(self.limiter.consume, "oauth:" + _digest(peer))
            if route == "register":
                await run_in_threadpool(
                    self.registration_limiter.consume, "oauth-register:" + _digest(peer)
                )
        except RateLimited:
            await reject("temporarily_unavailable", "Request limit reached; retry later", 429)
            return
        if route in ("token", "authorize", "revoke"):
            if request.method == "POST":
                if (
                    request.headers.get("content-type", "").split(";", 1)[0].lower()
                    != "application/x-www-form-urlencoded"
                ):
                    await reject("invalid_request", "Use application/x-www-form-urlencoded")
                    return
                body = await request.body()
                try:
                    params = parse_qs(
                        body.decode("utf-8"), keep_blank_values=True, max_num_fields=32
                    )
                except (ValueError, UnicodeDecodeError):
                    await reject("invalid_request", "Invalid form encoding")
                    return

                async def replay() -> Message:
                    return {"type": "http.request", "body": body}

                receive = replay
            else:
                params = {key: request.query_params.getlist(key) for key in request.query_params}
            if any(len(values) != 1 for values in params.values()):
                await reject("invalid_request", "Repeated form parameters are not supported")
                return
            if route == "revoke" and request.method == "POST" and "client_secret" not in params:
                # SDK 2.3's revocation model marks this nullable field required,
                # although a public client's RFC 7009 request has no secret.
                # Our registry only admits auth method 'none'; SDK client/token
                # ownership checks still run unchanged after this normalization.
                body = urlencode(
                    {**{key: values[0] for key, values in params.items()}, "client_secret": ""}
                ).encode()
            if route in ("token", "authorize") and params.get("resource") != [
                self.provider.resource
            ]:
                await reject("invalid_target", "Use this server's MCP resource URL")
                return
            if route == "authorize" and params.get("code_challenge_method") != ["S256"]:
                await reject("invalid_request", "PKCE S256 is required")
                return
            if route == "token" and params.get("grant_type") == ["authorization_code"]:
                verifier = params.get("code_verifier", [""])[0]
                if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
                    await reject("invalid_request", "Invalid PKCE verifier")
                    return
        await self.app(scope, receive, secure_send)
