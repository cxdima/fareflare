"""Same-origin customer application: sessions, account controls, API and dashboard."""
import hashlib
import hmac
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Route

from gfpt_next.accounts import Accounts, AuthenticationFailed
from gfpt_next.api import create_app
from gfpt_next.credentials import RateLimiter
from gfpt_next.hosted_mcp import make_hosted_mcp
from gfpt_next.oauth import OAuthProvider
from gfpt_next.product_config import ProductConfig
from gfpt_next.service import MonitoringService

if TYPE_CHECKING:
    from gfpt_next.telegram_accounts import TelegramConnections


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


def create_portal(service: MonitoringService, config: ProductConfig,
                  accounts: Accounts | None = None, static_dir: Path | None = None,
                  telegram: "TelegramConnections | None" = None, telegram_webhook_secret: str | None = None):
    accounts = accounts or Accounts(service.store, config, clock=service.clock)
    public_url = config.public_url.rstrip("/")
    origin = urlsplit(public_url)
    secure = origin.scheme == "https"
    cookie_name = "__Host-fareflare_session" if secure else "fareflare_session"
    limiter = RateLimiter(service.store, service.clock)
    auth_limiter = RateLimiter(service.store, service.clock, per_minute=8)
    oauth = OAuthProvider(service.store, accounts, public_url, clock=service.clock)
    if telegram is not None and (not telegram_webhook_secret or len(telegram_webhook_secret) < 32):
        raise ValueError("Configure a strong Telegram webhook secret")

    def check_origin(request: Request) -> None:
        supplied = request.headers.get("origin")
        if ((supplied and supplied != public_url)
                or request.headers.get("sec-fetch-site") == "cross-site"):
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
        return result

    def principal(request: Request) -> str | None:
        authorization = request.headers.get("authorization")
        if authorization:
            parts = authorization.split(" ", 1)
            if len(parts) != 2 or parts[0].lower() != "bearer":
                return None
            tenant = accounts.authenticate_api_key(parts[1])
            if tenant is None and request.scope.get("gfpt.mcp_internal"):
                tenant = oauth.bearer_to_tenant(parts[1])
            return tenant
        return session(request)["account"]["id"]

    app = create_app(service, principal_resolver=principal, limiter=limiter, live_collection=True)
    app.title = config.product_name + " API"
    # The default Swagger/ReDoc pages require remote scripts and inline code.
    # Serve a small same-origin reference that works with the application CSP.
    app.router.routes = [route for route in app.router.routes
                         if getattr(route, "path", "") not in ("/docs", "/docs/oauth2-redirect", "/redoc")]

    @app.exception_handler(RequestValidationError)
    async def validation_failed(request, exc):
        return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                                        for error in exc.errors()]}, status_code=422)

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def reference():
        routes = "".join("<tr><td><code>" + escape(method.upper()) + "</code></td><td><code>" +
                         escape(path) + "</code></td><td>" + escape(operation.get("summary", "")) + "</td></tr>"
                         for path, methods in app.openapi()["paths"].items()
                         for method, operation in methods.items())
        return ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                "<title>" + escape(config.product_name) + " API reference</title><main><h1>" + escape(config.product_name) +
                " API reference</h1><p>Create a revocable API key in the dashboard and send it as "
                "<code>Authorization: Bearer YOUR_KEY</code>. Creating monitors and webhooks also requires a unique "
                "<code>Idempotency-Key</code> header (8–128 characters); reuse it when retrying the same request.</p>"
                "<p>Prices use integer minor units: USD 123.45 is <code>12345</code>. History and alerts are paginated "
                "using <code>limit</code> and <code>cursor</code>. Honor <code>Retry-After</code> on HTTP 429.</p>"
                "<p><a href='/openapi.json'>Download the OpenAPI schema</a> for request fields and response types. "
                "Connect an MCP client to <code>" + escape(public_url) + "/mcp</code> using OAuth or a bearer API key.</p>"
                "<table><caption>Available endpoints</caption><thead><tr><th>Method</th><th>Path</th><th>Purpose</th>"
                "</tr></thead><tbody>" + routes + "</tbody></table><p><a href='/'>Back to dashboard</a></p></main></html>")

    @app.exception_handler(AuthenticationFailed)
    async def authentication_failed(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=401)

    @app.middleware("http")
    async def product_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    if origin.hostname:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[origin.hostname])

    def auth_attempt(request: Request) -> None:
        check_origin(request)
        # request.client comes from API Gateway's trusted request context in Lambda;
        # forwarded headers never determine this rate-limit key.
        address = request.client.host if request.client else "unknown"
        auth_limiter.consume("auth_" + hashlib.sha256(address.encode()).hexdigest())

    def signed_in(result: dict, response: Response) -> dict:
        response.set_cookie(cookie_name, result["session_token"],
                            max_age=max(0, result["expires_at"] - int(service.clock())),
                            secure=secure, httponly=True, samesite="lax", path="/")
        return {key: result[key] for key in ("account", "csrf_token", "recovery_code") if key in result}

    @app.get("/v1/config")
    def public_config():
        return config.public()

    @app.post("/auth/register", status_code=201)
    def register(body: RegisterInput, request: Request, response: Response):
        auth_attempt(request)
        return signed_in(accounts.register(body.username, body.password, body.invite_token), response)

    @app.post("/auth/login")
    def login(body: LoginInput, request: Request, response: Response):
        auth_attempt(request)
        return signed_in(accounts.login(body.username, body.password), response)

    @app.post("/auth/recover")
    def recover(body: RecoveryInput, request: Request, response: Response):
        auth_attempt(request)
        return signed_in(accounts.recover(body.username, body.recovery_code, body.new_password), response)

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
    def delete_account(body: DeleteAccountInput, response: Response,
                       identity: Annotated[dict, Depends(session)]):
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
        return telegram.status(identity["account"]["id"]) if telegram else {"enabled": False, "connected": False}

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
        if len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode(), telegram_webhook_secret.encode()):
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
    def connected_apps(identity: Annotated[dict, Depends(session)], limit: int = Query(100, ge=1, le=100),
                       cursor: str | None = Query(None, max_length=4096)):
        return oauth.list_grants(identity["account"]["id"], limit=limit, cursor=cursor)

    @app.delete("/v1/oauth/grants/{identifier}")
    def disconnect_app(identifier: str, identity: Annotated[dict, Depends(session)]):
        oauth.revoke_grant(identity["account"]["id"], identifier)
        return {"revoked": True}

    app.mount("/oauth", oauth.build_app())
    app.router.routes.extend(oauth.discovery_routes())
    mcp = make_hosted_mcp(app, lambda token: accounts.authenticate_api_key(token) or oauth.bearer_to_tenant(token),
                         allowed_hosts=[origin.netloc], allowed_origins=[public_url],
                         resource_metadata_url=public_url + "/.well-known/oauth-protected-resource/mcp")
    app.router.routes.append(Route("/mcp", endpoint=mcp))

    if static_dir and static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-store"})

        @app.get("/favicon.svg", include_in_schema=False)
        def favicon():
            return FileResponse(static_dir / "favicon.svg", media_type="image/svg+xml")

    app.state.accounts = accounts
    app.state.oauth = oauth
    app.state.config = config
    app.state.session_identity = session
    return app
