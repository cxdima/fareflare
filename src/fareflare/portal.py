"""Same-origin customer application: sessions, account controls, API and dashboard."""

import hashlib
import hmac
import re
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Route

from fareflare.accounts import Accounts, AuthenticationFailed
from fareflare.api import create_app
from fareflare.api_reference import render_api_reference
from fareflare.credentials import RateLimiter
from fareflare.hosted_mcp import make_hosted_mcp
from fareflare.oauth import OAuthProvider
from fareflare.product_config import ProductConfig
from fareflare.service import MonitoringService
from fareflare.site_content import (
    PRIVATE_PATHS,
    Page,
    content_document,
    feed,
    private_page,
    public_pages,
    render_document,
    sitemap,
)

if TYPE_CHECKING:
    from fareflare.telegram_accounts import TelegramConnections


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class RegisterInput(LoginInput):
    invite_token: str | None = Field(default=None, max_length=128)


class RecoveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=80)
    recovery_code: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


class KeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)


class DeleteAccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    password: str = Field(min_length=1, max_length=128)


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    approve: bool


def create_portal(
    service: MonitoringService,
    config: ProductConfig,
    accounts: Accounts | None = None,
    static_dir: Path | None = None,
    telegram: "TelegramConnections | None" = None,
    telegram_webhook_secret: str | None = None,
):
    accounts = accounts or Accounts(service.store, config, clock=service.clock)
    public_url = config.public_url.rstrip("/")
    origin = urlsplit(public_url)
    secure = origin.scheme == "https"
    cookie_name = "__Host-fareflare_session" if secure else "fareflare_session"
    limiter = RateLimiter(service.store, service.clock)
    auth_limiter = RateLimiter(service.store, service.clock, per_minute=8)
    signup_limiter = RateLimiter(service.store, service.clock, per_minute=3)
    oauth = OAuthProvider(service.store, accounts, public_url, clock=service.clock)
    if telegram is not None and (not telegram_webhook_secret or len(telegram_webhook_secret) < 32):
        raise ValueError("Configure a strong Telegram webhook secret")

    def check_origin(request: Request) -> None:
        supplied = request.headers.get("origin")
        if (supplied and supplied != public_url) or request.headers.get(
            "sec-fetch-site"
        ) == "cross-site":
            raise HTTPException(403, "Use this application's own origin")

    def session(request: Request) -> dict:
        result = accounts.authenticate_session(request.cookies.get(cookie_name, ""))
        if not result:
            raise HTTPException(401, "Sign in to continue")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            check_origin(request)
            supplied = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(supplied.encode(), result["csrf_token"].encode()):
                raise HTTPException(403, "Refresh the page before trying again")
        limiter.consume("session_" + result["account"]["id"])
        return result

    def principal(request: Request) -> str | None:
        authorization = request.headers.get("authorization")
        if authorization:
            parts = authorization.split(" ", 1)
            if len(parts) != 2 or parts[0].lower() != "bearer":
                return None
            tenant = accounts.authenticate_api_key(parts[1])
            if tenant is None and request.scope.get("fareflare.mcp_internal"):
                tenant = oauth.bearer_to_tenant(parts[1])
            return tenant
        return session(request)["account"]["id"]

    app = create_app(
        service,
        principal_resolver=principal,
        limiter=limiter,
        live_collection=True,
        public_url=config.public_url,
    )
    app.title = config.product_name + " API"
    # Use the same script-free API reference with the portal navigation and stylesheet.
    app.router.routes = [
        route for route in app.router.routes if getattr(route, "path", "") != "/docs"
    ]

    @app.exception_handler(RequestValidationError)
    async def validation_failed(request, exc):
        return JSONResponse(
            {
                "detail": [
                    {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                    for error in exc.errors()
                ]
            },
            status_code=422,
        )

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def reference():
        return render_api_reference(
            app.openapi(), config.product_name, static_dir=static_dir, public_url=public_url
        )

    @app.exception_handler(AuthenticationFailed)
    async def authentication_failed(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=401)

    @app.middleware("http")
    async def product_headers(request: Request, call_next):
        # Preserve old API integrations and Telegram ingress, while browser pages
        # move to the canonical origin. Never build a redirect from request headers.
        if (
            request.url.hostname in config.additional_hosts
            and request.method in ("GET", "HEAD")
            and not request.url.path.startswith(("/v1/", "/oauth/", "/telegram/", "/.well-known/"))
            and request.url.path != "/mcp"
        ):
            return RedirectResponse(
                public_url
                + request.url.path
                + ("?" + request.url.query if request.url.query else ""),
                status_code=308,
            )
        request.state.csp_nonce = secrets.token_urlsafe(24)
        response = await call_next(request)
        nonce = request.state.csp_nonce
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'nonce-{nonce}'; "
            "style-src-attr 'none'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if response.status_code == 200 and getattr(request.state, "asset_cache", None):
            response.headers["Cache-Control"] = request.state.asset_cache
        if (
            request.url.path.startswith(("/v1/", "/auth/", "/oauth/", "/telegram/"))
            or request.url.path in ("/mcp", "/site-content.json", "/docs")
            or any(key in request.query_params for key in ("invite", "authorize", "code", "token"))
        ):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    if origin.hostname:
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=[origin.hostname, *config.additional_hosts]
        )

    def auth_attempt(request: Request) -> None:
        check_origin(request)
        # request.client comes from API Gateway's trusted request context in Lambda;
        # forwarded headers never determine this rate-limit key.
        address = request.client.host if request.client else "unknown"
        auth_limiter.consume("auth_" + hashlib.sha256(address.encode()).hexdigest())

    def signed_in(result: dict, response: Response) -> dict:
        response.set_cookie(
            cookie_name,
            result["session_token"],
            max_age=max(0, result["expires_at"] - int(service.clock())),
            secure=secure,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return {
            key: result[key] for key in ("account", "csrf_token", "recovery_code") if key in result
        }

    @app.get("/v1/config")
    def public_config():
        return config.public()

    @app.post("/auth/register", status_code=201)
    def register(body: RegisterInput, request: Request, response: Response):
        auth_attempt(request)
        address = request.client.host if request.client else "unknown"
        signup_limiter.consume("signup_" + hashlib.sha256(address.encode()).hexdigest())
        return signed_in(
            accounts.register(body.username, body.password, body.invite_token), response
        )

    @app.post("/auth/login")
    def login(body: LoginInput, request: Request, response: Response):
        auth_attempt(request)
        return signed_in(accounts.login(body.username, body.password), response)

    @app.post("/auth/recover")
    def recover(body: RecoveryInput, request: Request, response: Response):
        auth_attempt(request)
        return signed_in(
            accounts.recover(body.username, body.recovery_code, body.new_password), response
        )

    @app.post("/auth/logout")
    def logout(request: Request, response: Response):
        session(request)
        accounts.logout(request.cookies.get(cookie_name, ""))
        response.delete_cookie(cookie_name, secure=secure, httponly=True, samesite="lax", path="/")
        return {"ok": True}

    @app.get("/v1/account")
    def account(identity: Annotated[dict, Depends(session)]):
        return {"account": identity["account"], "csrf_token": identity["csrf_token"]}

    @app.delete("/v1/account")
    def delete_account(
        body: DeleteAccountInput, response: Response, identity: Annotated[dict, Depends(session)]
    ):
        accounts.delete_account(identity["account"]["id"], body.password)
        response.delete_cookie(cookie_name, secure=secure, httponly=True, samesite="lax", path="/")
        return {"deleted": True}

    @app.get("/v1/api-keys")
    def list_keys(identity: Annotated[dict, Depends(session)]):
        return accounts.list_api_keys(identity["account"]["id"])

    @app.post("/v1/api-keys", status_code=201)
    def create_key(body: KeyInput, identity: Annotated[dict, Depends(session)]):
        return accounts.issue_api_key(identity["account"]["id"], body.name)

    @app.delete("/v1/api-keys/{identifier}")
    def revoke_key(identifier: str, identity: Annotated[dict, Depends(session)]):
        accounts.revoke_api_key(identity["account"]["id"], identifier)
        return {"revoked": True}

    @app.get("/v1/telegram")
    def telegram_status(identity: Annotated[dict, Depends(session)]):
        return (
            telegram.status(identity["account"]["id"])
            if telegram
            else {"enabled": False, "connected": False}
        )

    @app.post("/v1/telegram")
    def telegram_connect(identity: Annotated[dict, Depends(session)]):
        if telegram is None:
            raise HTTPException(503, "Telegram is not configured")
        return telegram.connect(identity["account"]["id"])

    @app.delete("/v1/telegram")
    def telegram_disconnect(identity: Annotated[dict, Depends(session)]):
        if telegram:
            telegram.disconnect(identity["account"]["id"])
        return {"connected": False}

    @app.post("/telegram/webhook", include_in_schema=False)
    def telegram_update(body: dict, request: Request):
        if telegram is None or telegram_webhook_secret is None:
            raise HTTPException(404, "Not found")
        supplied = request.headers.getlist("x-telegram-bot-api-secret-token")
        if len(supplied) != 1 or not hmac.compare_digest(
            supplied[0].encode(), telegram_webhook_secret.encode()
        ):
            raise HTTPException(403, "Invalid webhook credential")
        if not telegram.handle_update(body):
            raise HTTPException(503, "Retry this update")
        return {"ok": True}

    @app.get("/v1/oauth/requests/{request_id}")
    def consent_request(request_id: str, identity: Annotated[dict, Depends(session)]):
        return oauth.consent_request(identity["account"]["id"], request_id)

    @app.post("/v1/oauth/requests/{request_id}")
    def consent(request_id: str, body: ConsentInput, identity: Annotated[dict, Depends(session)]):
        return oauth.complete_consent(identity["account"]["id"], request_id, body.approve)

    @app.get("/v1/oauth/grants")
    def connected_apps(
        identity: Annotated[dict, Depends(session)],
        limit: int = Query(100, ge=1, le=100),
        cursor: str | None = Query(None, max_length=4096),
    ):
        return oauth.list_grants(identity["account"]["id"], limit=limit, cursor=cursor)

    @app.delete("/v1/oauth/grants/{identifier}")
    def disconnect_app(identifier: str, identity: Annotated[dict, Depends(session)]):
        oauth.revoke_grant(identity["account"]["id"], identifier)
        return {"revoked": True}

    app.mount("/oauth", oauth.build_app())
    app.router.routes.extend(oauth.discovery_routes())
    mcp = make_hosted_mcp(
        app,
        lambda token: accounts.authenticate_api_key(token) or oauth.bearer_to_tenant(token),
        allowed_hosts=[origin.netloc],
        allowed_origins=[public_url],
        resource_metadata_url=public_url + "/.well-known/oauth-protected-resource/mcp",
    )
    app.router.routes.append(Route("/mcp", endpoint=mcp))

    if static_dir and static_dir.is_dir():
        shell = (static_dir / "index.html").read_text()
        pages = {page.path: page for page in public_pages(config)}
        # Only packaged public assets are reachable. Never expose source maps,
        # dotfiles, deployment configuration, or a path outside the build root.
        root = static_dir.resolve()
        allowed_suffixes = {
            ".js",
            ".css",
            ".svg",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".avif",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
            ".webmanifest",
        }
        files = {
            "/" + path.relative_to(static_dir).as_posix(): path
            for path in static_dir.rglob("*")
            if path.is_file()
            and (path.suffix.lower() in allowed_suffixes or path.name == "3rdpartylicenses.txt")
            and not any(part.startswith(".") for part in path.relative_to(static_dir).parts)
            and path.resolve().is_relative_to(root)
        }

        @app.get("/site-content.json", include_in_schema=False)
        def site_content():
            return content_document(config)

        @app.get("/sitemap.xml", include_in_schema=False)
        def site_map():
            return Response(sitemap(config), media_type="application/xml")

        @app.get("/feed.xml", include_in_schema=False)
        def site_feed():
            return Response(feed(config), media_type="application/rss+xml")

        @app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
        def robots():
            # Account HTML is crawlable so crawlers can observe its noindex
            # directive. Authentication remains the data-access boundary.
            return "User-agent: *\nAllow: /\nSitemap: " + public_url + "/sitemap.xml\n"

        @app.api_route("/{site_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def site(site_path: str, request: Request):
            path = "/" + site_path
            if path in files:
                asset = files[path]
                fingerprinted = re.search(r"[.-](?:[A-Z0-9]{8,}|[a-f0-9]{8,})\.[^.]+$", asset.name)
                cache = (
                    "public, max-age=31536000, immutable"
                    if fingerprinted
                    else "public, max-age=3600"
                )
                request.state.asset_cache = cache
                return FileResponse(asset, headers={"Cache-Control": cache})
            secret_query = any(
                key in request.query_params for key in ("invite", "authorize", "code", "token")
            )
            if path in pages and not secret_query:
                page, indexable, status = pages[path], True, 200
            elif path in PRIVATE_PATHS or path in pages and secret_query:
                page, indexable, status = private_page(path), False, 200
            else:
                page = Page(
                    "/404",
                    "Page not found — Fareflare",
                    "This page is not available.",
                    "404",
                    "Page not found.",
                    "Check the address or return to Fareflare.",
                )
                indexable, status = False, 404
            headers = {"Cache-Control": "no-store"}
            if not indexable:
                headers["X-Robots-Tag"] = "noindex, nofollow"
            return HTMLResponse(
                render_document(shell, page, config, request.state.csp_nonce, indexable=indexable),
                status_code=status,
                headers=headers,
            )

    app.state.accounts = accounts
    app.state.oauth = oauth
    app.state.config = config
    app.state.session_identity = session
    return app
