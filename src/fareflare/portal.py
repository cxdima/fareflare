"""Same-origin customer application: sessions, account controls, API and dashboard."""

import hashlib
import hmac
import re
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal
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

from fareflare.accounts import (
    MAX_PASSWORD_LENGTH,
    MAX_USERNAME_LENGTH,
    MIN_PASSWORD_LENGTH,
    Accounts,
    AuthenticationFailed,
    IncorrectPassword,
)
from fareflare.admin import ACTIONS, Admin, AdminDenied
from fareflare.api import create_app
from fareflare.api_reference import render_api_reference
from fareflare.credentials import RateLimiter
from fareflare.edge import client_address
from fareflare.hosted_mcp import make_hosted_mcp
from fareflare.oauth import OAuthProvider
from fareflare.passkeys import PasskeyRejected
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

# Python 3.12's built-in type table, which is all the Lambda image has, does not know
# these, so they would go out as application/octet-stream.
MEDIA_TYPES = {
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH)
    password: str = Field(min_length=1, max_length=128)


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    email: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH)
    password: str = Field(min_length=1, max_length=128)


class TwoFactorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=32)


class PasskeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    challenge_id: str = Field(min_length=1, max_length=64)
    credential: dict


class NewPasskeyInput(PasskeyInput):
    name: str | None = Field(default=None, max_length=60)


class NameInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=60)


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    email: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH)


class TokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: str = Field(min_length=1, max_length=64)


class ResetInput(TokenInput):
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    code: str | None = Field(default=None, max_length=32)


class EmailChangeInput(EmailInput):
    password: str = Field(min_length=1, max_length=128)


class CodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(min_length=1, max_length=32)


class PasswordAndCodeInput(CodeInput):
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class PasswordConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    password: str = Field(min_length=1, max_length=128)


class KeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)


class DeleteAccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    password: str = Field(min_length=1, max_length=128)


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    approve: bool


class AdminActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: str = Field(default="", max_length=500)


class AdminDeleteInput(AdminActionInput):
    confirm: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH)


class AdminFlightInput(AdminActionInput):
    status: Literal["paused", "active", "cancelled"]


class AdminSwitchesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    registration_paused: bool | None = None
    collection_paused: bool | None = None


# While a temporary password is in use, a session may only replace it.
_PASSWORD_CHANGE_ONLY = {
    ("GET", "/v1/account"),
    ("POST", "/auth/password"),
    ("POST", "/auth/logout"),
}


def create_portal(
    service: MonitoringService,
    config: ProductConfig,
    accounts: Accounts | None = None,
    static_dir: Path | None = None,
    telegram: "TelegramConnections | None" = None,
    telegram_webhook_secret: str | None = None,
    auth_attempts_per_minute: int = 8,
):
    accounts = accounts or Accounts(service.store, config, clock=service.clock)
    public_url = config.public_url.rstrip("/")
    origin = urlsplit(public_url)
    secure = origin.scheme == "https"
    cookie_name = "__Host-fareflare_session" if secure else "fareflare_session"
    limiter = RateLimiter(service.store, service.clock)
    auth_limiter = RateLimiter(service.store, service.clock, per_minute=auth_attempts_per_minute)
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
        if (
            result["account"]["must_change_password"]
            and (request.method, request.url.path) not in _PASSWORD_CHANGE_ONLY
        ):
            raise HTTPException(403, "Choose a new password before continuing")
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

    @app.exception_handler(PasskeyRejected)
    async def passkey_rejected(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(IncorrectPassword)
    async def incorrect_password(request, exc):
        # Not 401: the session is valid, only the confirming password was wrong.
        return JSONResponse({"detail": str(exc)}, status_code=403)

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
        if request.url.path.startswith("/v1/admin/"):
            response.headers["Cache-Control"] = "no-store"
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
        # API Gateway's record of who connected, or, through CloudFront, the visitor it
        # names alongside the edge secret. A bare forwarded header never decides this.
        address = client_address(request)
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
        return {key: result[key] for key in ("account", "csrf_token")}

    @app.get("/v1/config")
    def public_config():
        return {**config.public(), "email_enabled": accounts.email_enabled}

    @app.post("/auth/register", status_code=201)
    def register(body: RegisterInput, request: Request, response: Response):
        auth_attempt(request)
        address = client_address(request)
        signup_limiter.consume("signup_" + hashlib.sha256(address.encode()).hexdigest())
        return signed_in(accounts.register(body.email, body.password), response)

    @app.post("/auth/login")
    def login(body: LoginInput, request: Request, response: Response):
        auth_attempt(request)
        result = accounts.login(body.username, body.password)
        if "two_factor_token" in result:
            return {
                "two_factor_required": True,
                "token": result["two_factor_token"],
                "expires_at": result["expires_at"],
            }
        return signed_in(result, response)

    @app.post("/auth/login/two-factor")
    def login_code(body: TwoFactorInput, request: Request, response: Response):
        auth_attempt(request)
        return signed_in(accounts.complete_login(body.token, body.code), response)

    @app.post("/auth/passkey/options")
    def passkey_options(request: Request):
        auth_attempt(request)
        return accounts.passkey_login_options()

    @app.post("/auth/passkey")
    def passkey_login(body: PasskeyInput, request: Request, response: Response):
        auth_attempt(request)
        return signed_in(accounts.passkey_login(body.challenge_id, body.credential), response)

    @app.post("/auth/password-reset", status_code=202)
    def request_reset(body: EmailInput, request: Request):
        auth_attempt(request)
        accounts.request_password_reset(body.email)
        # The same answer whether or not an account uses the address.
        return {"sent": True}

    @app.post("/auth/password-reset/check")
    def check_reset(body: TokenInput, request: Request):
        auth_attempt(request)
        return accounts.check_reset(body.token)

    @app.post("/auth/password-reset/confirm")
    def reset_password(body: ResetInput, request: Request, response: Response):
        auth_attempt(request)
        return signed_in(
            accounts.reset_password(body.token, body.new_password, body.code), response
        )

    @app.post("/auth/email/confirm")
    def confirm_email(body: TokenInput, request: Request):
        auth_attempt(request)
        return accounts.confirm_email(body.token)

    @app.post("/auth/logout")
    def logout(request: Request, response: Response):
        session(request)
        accounts.logout(request.cookies.get(cookie_name, ""))
        response.delete_cookie(cookie_name, secure=secure, httponly=True, samesite="lax", path="/")
        return {"ok": True}

    @app.post("/auth/password")
    def change_password(
        body: PasswordChangeInput, request: Request, identity: Annotated[dict, Depends(session)]
    ):
        accounts.change_password(
            identity["account"]["id"],
            request.cookies.get(cookie_name, ""),
            body.current_password,
            body.new_password,
        )
        return {"changed": True}

    @app.post("/auth/sign-out-everywhere")
    def sign_out_everywhere(
        body: PasswordConfirmation, response: Response, identity: Annotated[dict, Depends(session)]
    ):
        return signed_in(
            accounts.sign_out_everywhere(identity["account"]["id"], body.password), response
        )

    @app.get("/v1/account/security")
    def security(identity: Annotated[dict, Depends(session)]):
        return accounts.security(identity["account"]["id"])

    @app.post("/auth/email")
    def change_email(body: EmailChangeInput, identity: Annotated[dict, Depends(session)]):
        return {
            "account": accounts.change_email(identity["account"]["id"], body.password, body.email)
        }

    @app.post("/auth/email/resend", status_code=202)
    def resend_confirmation(identity: Annotated[dict, Depends(session)]):
        accounts.resend_confirmation(identity["account"]["id"])
        return {"sent": True}

    @app.post("/auth/two-factor/setup")
    def start_two_factor(body: PasswordConfirmation, identity: Annotated[dict, Depends(session)]):
        return accounts.start_two_factor(identity["account"]["id"], body.password)

    @app.post("/auth/two-factor/enable")
    def enable_two_factor(
        body: CodeInput, request: Request, identity: Annotated[dict, Depends(session)]
    ):
        return accounts.enable_two_factor(
            identity["account"]["id"], body.code, request.cookies.get(cookie_name)
        )

    @app.post("/auth/two-factor/disable")
    def disable_two_factor(body: PasswordAndCodeInput, identity: Annotated[dict, Depends(session)]):
        accounts.disable_two_factor(identity["account"]["id"], body.password, body.code)
        return {"enabled": False}

    @app.post("/auth/two-factor/backup-codes")
    def new_backup_codes(body: PasswordAndCodeInput, identity: Annotated[dict, Depends(session)]):
        return accounts.new_backup_codes(identity["account"]["id"], body.password, body.code)

    @app.post("/auth/passkeys/options")
    def new_passkey_options(
        body: PasswordConfirmation, identity: Annotated[dict, Depends(session)]
    ):
        return accounts.passkey_registration_options(identity["account"]["id"], body.password)

    @app.post("/auth/passkeys", status_code=201)
    def add_passkey(
        body: NewPasskeyInput, request: Request, identity: Annotated[dict, Depends(session)]
    ):
        return accounts.add_passkey(
            identity["account"]["id"],
            body.challenge_id,
            body.credential,
            body.name,
            request.cookies.get(cookie_name),
        )

    @app.patch("/auth/passkeys/{identifier}")
    def rename_passkey(
        identifier: str, body: NameInput, identity: Annotated[dict, Depends(session)]
    ):
        return accounts.rename_passkey(identity["account"]["id"], identifier, body.name)

    @app.delete("/auth/passkeys/{identifier}")
    def remove_passkey(identifier: str, identity: Annotated[dict, Depends(session)]):
        accounts.remove_passkey(identity["account"]["id"], identifier)
        return {"removed": True}

    @app.get("/.well-known/passkey-endpoints", include_in_schema=False)
    def passkey_endpoints():
        # Lets password managers such as 1Password offer to add or manage a passkey here.
        settings = public_url + "/app#settings?section=security"
        return {"enroll": settings, "manage": settings}

    @app.get("/.well-known/change-password", include_in_schema=False)
    def change_password_location():
        # Password managers and browsers open this to take someone to the right page.
        return RedirectResponse("/app#settings?section=security", status_code=302)

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

    panel = Admin(service.store, accounts, service, clock=service.clock, oauth=oauth)

    def administrator(identity: Annotated[dict, Depends(session)]) -> dict:
        try:
            return panel.require(identity)
        except AdminDenied as denied:
            if denied.reason == "not_admin":
                raise HTTPException(404, "Not found") from None
            raise HTTPException(403, str(denied)) from None

    @app.get("/v1/admin/gate", include_in_schema=False)
    def admin_gate(identity: Annotated[dict, Depends(session)]):
        gate = panel.gate(identity)
        if gate["reason"] == "not_admin":
            raise HTTPException(404, "Not found")
        return gate

    @app.get("/v1/admin/overview", include_in_schema=False)
    def admin_overview(admin: Annotated[dict, Depends(administrator)]):
        return panel.overview()

    @app.get("/v1/admin/users", include_in_schema=False)
    def admin_users(
        admin: Annotated[dict, Depends(administrator)],
        q: str = Query("", max_length=254),
        status: str = Query("all", max_length=20),
        sort: str = Query("newest", max_length=20),
        offset: int = Query(0, ge=0, le=100_000),
        limit: int = Query(50, ge=1, le=200),
    ):
        return panel.users(q, status, sort, offset, limit)

    @app.get("/v1/admin/users/{tenant}", include_in_schema=False)
    def admin_user(tenant: str, admin: Annotated[dict, Depends(administrator)]):
        return panel.user(tenant)

    @app.post("/v1/admin/users/{tenant}/{action}", include_in_schema=False)
    def admin_act(
        tenant: str,
        action: str,
        body: AdminActionInput,
        admin: Annotated[dict, Depends(administrator)],
    ):
        if action not in ACTIONS:
            raise HTTPException(404, "Not found")
        return panel.act(admin, tenant, action, body.reason)

    @app.delete("/v1/admin/users/{tenant}", include_in_schema=False)
    def admin_delete(
        tenant: str, body: AdminDeleteInput, admin: Annotated[dict, Depends(administrator)]
    ):
        return panel.delete(admin, tenant, body.confirm, body.reason)

    @app.patch("/v1/admin/users/{tenant}/flights/{monitor_id}", include_in_schema=False)
    def admin_flight(
        tenant: str,
        monitor_id: str,
        body: AdminFlightInput,
        admin: Annotated[dict, Depends(administrator)],
    ):
        return panel.set_flight(admin, tenant, monitor_id, body.status, body.reason)

    @app.get("/v1/admin/flights", include_in_schema=False)
    def admin_flights(admin: Annotated[dict, Depends(administrator)]):
        return panel.flights()

    @app.get("/v1/admin/audit", include_in_schema=False)
    def admin_audit(
        admin: Annotated[dict, Depends(administrator)],
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = Query(None, max_length=4096),
    ):
        return panel.audit(limit=limit, cursor=cursor)

    @app.put("/v1/admin/switches", include_in_schema=False)
    def admin_switches(body: AdminSwitchesInput, admin: Annotated[dict, Depends(administrator)]):
        return panel.set_switches(admin, body.model_dump(exclude_none=True))

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
                return FileResponse(
                    asset,
                    media_type=MEDIA_TYPES.get(asset.suffix.lower()),
                    headers={"Cache-Control": cache},
                )
            secret_query = any(
                key in request.query_params for key in ("invite", "authorize", "code", "token")
            )
            if path in pages and not secret_query:
                page, indexable, status = pages[path], True, 200
            elif path in PRIVATE_PATHS or (path in pages and secret_query):
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
