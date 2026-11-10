"""Authenticated API over the shared application service. No collection side effects."""

import hmac
import re
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from fareflare import __version__
from fareflare.api_reference import render_api_reference
from fareflare.credentials import Credentials, RateLimited, RateLimiter
from fareflare.domain import AlertPolicy
from fareflare.preferences import Preferences as PreferencesInput
from fareflare.preferences import merge_preferences, sends_silently
from fareflare.service import MonitoringService, NotFound
from fareflare.store import Conflict
from fareflare.telegram_messages import preview_message
from fareflare.telegram_templates import template_catalog


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["new_low", "below_price"] = "new_low"
    min_drop_minor: int = Field(default=0, ge=0, le=100_000_000)
    threshold_minor: int | None = Field(default=None, gt=0, le=100_000_000)
    notify_rebounds: bool = False


class MonitorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=8192)
    interval_seconds: int = Field(default=900, ge=300, le=86400)
    policy: PolicyInput = Field(default_factory=PolicyInput)
    webhook_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class WebhookInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=2048)


class WebhookVerificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class WebhookView(BaseModel):
    id: str
    url: str
    status: Literal["pending", "active", "disabled", "deleted"]
    created_at: int
    verified_at: int | None = None


class WebhookRegistrationView(WebhookView):
    signing_secret: str | None = None


class WebhookList(BaseModel):
    items: list[WebhookView]
    next_cursor: str | None = None


class WebhookChallengeView(BaseModel):
    delivered: bool
    expires_at: int


class StatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["paused", "active", "cancelled"]


class EvidenceView(BaseModel):
    adapter_version: str
    identity_verified: bool
    eligibility_verified: bool
    party_verified: bool
    display_precision_minor: int


class LegView(BaseModel):
    origin: str
    destination: str
    date: str
    airline: str | None
    number: str | None


class SegmentView(BaseModel):
    date: str
    legs: list[LegView]


class TargetView(BaseModel):
    kind: Literal["selected", "search"] = "selected"
    id: str
    segments: list[SegmentView]
    adults: int
    cabin: int
    currency: str
    market: str
    url: str


class ObservedOfferView(BaseModel):
    target_id: str
    segments: list[SegmentView]
    adults: int
    cabin: int
    url: str


class SliceTimesView(BaseModel):
    """Airport-local clock times for one direction, in 24-hour HH:MM."""

    departs: str
    arrives: str
    arrival_day_offset: int = 0
    duration_minutes: int | None = None


class ObservationView(BaseModel):
    target_id: str
    amount_minor: int
    currency: str
    observed_at: int
    source: str
    evidence: EvidenceView | None = None
    fare_name: str | None = None
    price_basis: Literal["total", "unspecified"] = "unspecified"
    observed_offer: ObservedOfferView | None = None
    schedule: list[SliceTimesView] | None = None


class MonitorView(BaseModel):
    id: str
    target_id: str
    status: Literal["pending", "active", "paused", "cancelled", "expired", "degraded"]
    policy: PolicyInput
    interval_seconds: int
    created_at: int
    target: TargetView
    latest: ObservationView | None
    last_error: str | None
    collection_failures: int = 0
    next_check_at: int | None
    stale: bool
    collection_status: str
    webhook_id: str | None = None


class MonitorList(BaseModel):
    items: list[MonitorView]
    next_cursor: str | None = None
    active_count: int


class ObservationList(BaseModel):
    items: list[ObservationView]
    next_cursor: str | None = None


class PreviousView(BaseModel):
    """The monitor's own recorded state just before the alerting observation."""

    price_minor: int | None = None
    low_minor: int | None = None


class AlertView(BaseModel):
    id: str
    event_id: str
    monitor_id: str
    reason: str
    observation: ObservationView
    previous: PreviousView | None = None
    status: Literal["pending", "sent", "dead_letter", "suppressed"]
    attempts: int
    webhook_id: str | None = None


PreviewKind = Literal["tracking_started", "new_low", "below_price", "rebound", "flight_list"]


class AlertList(BaseModel):
    items: list[AlertView]
    next_cursor: str | None = None


def create_app(
    service: MonitoringService,
    api_keys: dict[str, str] | None = None,
    *,
    credentials: Credentials | None = None,
    limiter: RateLimiter | None = None,
    live_collection: bool = False,
    public_url: str | None = None,
    principal_resolver: Callable[[Request], str | None] | None = None,
) -> FastAPI:
    """api_keys maps tenant names to separate high-entropy service credentials."""
    api_keys = api_keys or {}
    if (
        (not api_keys and credentials is None and principal_resolver is None)
        or any(
            not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", owner)
            or not isinstance(key, str)
            or len(key) < 32
            for owner, key in api_keys.items()
        )
        or len(set(api_keys.values())) != len(api_keys)
    ):
        raise ValueError("Configure unique API keys of at least 32 characters per tenant")
    app = FastAPI(title="Fareflare API", version=__version__, docs_url=None, redoc_url=None)
    bearer = HTTPBearer(auto_error=False)

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def reference():
        return render_api_reference(app.openapi())

    def authenticate(
        request: Request,
        authorization: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        if principal_resolver:
            tenant = principal_resolver(request)
            if tenant:
                if limiter:
                    limiter.consume(tenant)
                return tenant
        supplied = authorization.credentials if authorization else ""
        for tenant, key in api_keys.items():
            if hmac.compare_digest(supplied.encode(), key.encode()):
                if limiter:
                    limiter.consume(tenant)
                return tenant
        tenant = credentials.authenticate(supplied) if credentials else None
        if tenant:
            if limiter:
                limiter.consume(tenant)
            return tenant
        raise HTTPException(401, "Invalid API credential", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def bounded_request(request: Request, call_next):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 16_384:
                return JSONResponse({"detail": "Request is too large"}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RateLimited)
    async def rate_limited(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=429, headers={"Retry-After": "60"})

    @app.exception_handler(NotFound)
    async def missing(request, exc):
        return JSONResponse({"detail": "Resource not found"}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/health")
    def health():
        health = service.store.get("health:worker")
        return {
            "ok": True,
            "service": "fareflare",
            "live_collection": live_collection,
            "last_worker_at": health.data["last_worker_at"] if health else None,
        }

    @app.post("/v1/monitors", status_code=202, response_model=MonitorView)
    def create(
        body: MonitorInput,
        tenant: Annotated[str, Depends(authenticate)],
        idempotency_key: Annotated[str, Header(min_length=8, max_length=128)],
    ):
        return service.create_monitor(
            tenant,
            body.url,
            idempotency_key,
            AlertPolicy(**body.policy.model_dump()),
            body.interval_seconds,
            webhook_id=body.webhook_id,
        )

    @app.post("/v1/webhooks", status_code=201, response_model=WebhookRegistrationView)
    def register_webhook(
        body: WebhookInput,
        tenant: Annotated[str, Depends(authenticate)],
        idempotency_key: Annotated[str, Header(min_length=8, max_length=128)],
    ):
        return service.webhooks.register(tenant, body.url, idempotency_key)

    @app.get("/v1/webhooks", response_model=WebhookList)
    def list_webhooks(
        tenant: Annotated[str, Depends(authenticate)],
        limit: int = Query(100, ge=1, le=1000),
        cursor: str | None = Query(None, max_length=4096),
    ):
        return service.webhooks.list(tenant, limit, cursor)

    @app.get("/v1/webhooks/{webhook_id}", response_model=WebhookView)
    def get_webhook(webhook_id: str, tenant: Annotated[str, Depends(authenticate)]):
        return service.webhooks.get(tenant, webhook_id)

    @app.post("/v1/webhooks/{webhook_id}/challenge", response_model=WebhookChallengeView)
    def challenge_webhook(webhook_id: str, tenant: Annotated[str, Depends(authenticate)]):
        return service.webhooks.challenge(tenant, webhook_id)

    @app.post("/v1/webhooks/{webhook_id}/verify", response_model=WebhookView)
    def verify_webhook(
        webhook_id: str,
        body: WebhookVerificationInput,
        tenant: Annotated[str, Depends(authenticate)],
    ):
        return service.webhooks.verify(tenant, webhook_id, body.token)

    @app.post("/v1/webhooks/{webhook_id}/disable", response_model=WebhookView)
    def disable_webhook(webhook_id: str, tenant: Annotated[str, Depends(authenticate)]):
        return service.webhooks.disable(tenant, webhook_id)

    @app.delete("/v1/webhooks/{webhook_id}", response_model=WebhookView)
    def delete_webhook(webhook_id: str, tenant: Annotated[str, Depends(authenticate)]):
        return service.webhooks.delete(tenant, webhook_id)

    @app.get("/v1/monitors", response_model=MonitorList)
    def list_monitors(
        tenant: Annotated[str, Depends(authenticate)],
        limit: int = Query(100, ge=1, le=1000),
        cursor: str | None = Query(None, max_length=4096),
    ):
        return service.monitors_page(tenant, limit, cursor)

    @app.get("/v1/monitors/{monitor_id}", response_model=MonitorView)
    def get_monitor(monitor_id: str, tenant: Annotated[str, Depends(authenticate)]):
        return service.get_monitor(tenant, monitor_id)

    @app.patch("/v1/monitors/{monitor_id}", response_model=MonitorView)
    def update_monitor(
        monitor_id: str, body: StatusInput, tenant: Annotated[str, Depends(authenticate)]
    ):
        return service.set_status(tenant, monitor_id, body.status)

    @app.get("/v1/monitors/{monitor_id}/history", response_model=ObservationList)
    def history(
        monitor_id: str,
        tenant: Annotated[str, Depends(authenticate)],
        limit: int = Query(100, ge=1, le=1000),
        cursor: str | None = Query(None, max_length=4096),
    ):
        return service.history_page(tenant, monitor_id, limit, cursor)

    @app.get("/v1/alerts", response_model=AlertList)
    def alerts(
        tenant: Annotated[str, Depends(authenticate)],
        limit: int = Query(100, ge=1, le=1000),
        cursor: str | None = Query(None, max_length=4096),
    ):
        return service.alerts_page(tenant, limit, cursor)

    @app.post("/v1/alerts/{delivery_id}/retry", status_code=202, response_model=AlertView)
    def retry(delivery_id: str, tenant: Annotated[str, Depends(authenticate)]):
        return service.retry_delivery(tenant, delivery_id)

    @app.post("/v1/monitors/{monitor_id}/retry-collection", response_model=MonitorView)
    def retry_collection(monitor_id: str, tenant: Annotated[str, Depends(authenticate)]):
        return service.retry_collection(tenant, monitor_id)

    @app.put("/v1/monitors/{monitor_id}/policy", response_model=MonitorView)
    def policy(monitor_id: str, body: PolicyInput, tenant: Annotated[str, Depends(authenticate)]):
        return service.set_policy(tenant, monitor_id, AlertPolicy(**body.model_dump()))

    @app.get("/v1/preferences", response_model=PreferencesInput)
    def preferences(tenant: Annotated[str, Depends(authenticate)]):
        return service.preferences(tenant)

    @app.put("/v1/preferences", response_model=PreferencesInput)
    def update_preferences(body: PreferencesInput, tenant: Annotated[str, Depends(authenticate)]):
        return service.set_preferences(tenant, **body.model_dump(exclude_unset=True))

    @app.get("/v1/preferences/telegram-templates")
    def telegram_templates(tenant: Annotated[str, Depends(authenticate)]):
        """Template names, placeholders, built-in presets and limits for message editors."""
        return template_catalog()

    @app.post("/v1/preferences/telegram-preview")
    def telegram_preview(
        body: PreferencesInput,
        tenant: Annotated[str, Depends(authenticate)],
        message: Annotated[PreviewKind, Query()] = "new_low",
    ):
        """Render sample data with the supplied settings. Nothing is saved or sent."""
        preferences = merge_preferences(
            service.preferences(tenant), body.model_dump(exclude_unset=True)
        )
        preview = preview_message(message, preferences, public_url, int(service.clock()))
        buttons = [
            {"text": button["text"], "url": button["url"]}
            for row in (preview.reply_markup or {}).get("inline_keyboard", [])
            for button in row
            if "url" in button
        ]
        heading = "Example flight list" if message == "flight_list" else "Example alert"
        return {
            "message": message,
            "text": f"{heading} — sample data\n\n" + preview.text,
            "buttons": buttons,
            # Whether a message sent at this moment would arrive without sound.
            "silent": sends_silently(preferences, service.clock()),
            "time_zone": preferences.time_zone or "UTC",
        }

    return app
