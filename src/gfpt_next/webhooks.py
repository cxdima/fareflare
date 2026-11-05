"""Customer-owned webhook destinations and signed delivery over the durable outbox."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from typing import TYPE_CHECKING, Protocol

from gfpt_next.contracts import DeliverySink
from gfpt_next.store import Conflict, Document
from gfpt_next.webhook_http import (
    WebhookHTTPTransport,
    new_signing_secret,
    normalize_webhook_url,
    sign_webhook,
)

if TYPE_CHECKING:
    from gfpt_next.service import MonitoringService


class WebhookTransport(Protocol):
    def send(self, url: str, payload: bytes, headers: dict[str, str]) -> bool: ...


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _encode(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


class WebhookRegistry:
    """URLs are immutable; replacing a destination requires ownership verification."""

    def __init__(self, owner: MonitoringService, transport: WebhookTransport | None = None):
        self.owner, self.store, self._now = owner, owner.store, owner._now
        self.transport = transport if transport is not None else WebhookHTTPTransport()

    @staticmethod
    def _public(document: Document) -> dict:
        return {key: document.data.get(key) for key in
                ("id", "url", "status", "created_at", "verified_at")}

    def _document(self, tenant: str, identifier: str) -> Document:
        from gfpt_next.service import NotFound

        self.owner._tenant(tenant)
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise NotFound("Webhook not found")
        document = self.store.get("webhook:" + identifier)
        if not document or document.data["tenant"] != tenant:
            raise NotFound("Webhook not found")
        return document

    def active_document(self, tenant: str, identifier: str) -> Document:
        document = self._document(tenant, identifier)
        if document.data["status"] != "active":
            raise ValueError("Verify an active webhook before attaching it to a monitor")
        return document

    def get(self, tenant: str, identifier: str) -> dict:
        return self._public(self._document(tenant, identifier))

    def list(self, tenant: str, limit: int = 100, cursor: str | None = None) -> dict:
        self.owner._tenant(tenant)
        page = self.store.page("webhooks:" + tenant, limit=limit, cursor=cursor)
        # GSI rows can lag disable/delete; never return private data from the index.
        current = [self._document(tenant, doc.data["id"]) for doc in page.items]
        return {"items": [self._public(doc) for doc in current], "next_cursor": page.cursor}

    def register(self, tenant: str, url: str, request_key: str) -> dict:
        self.owner._tenant(tenant)
        url = normalize_webhook_url(url)
        if not isinstance(request_key, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{8,128}", request_key):
            raise ValueError("Provide an 8–128 character idempotency key")
        request_id = "webhook-request:" + _hash(tenant + ":" + request_key)
        for _ in range(5):
            previous = self.store.get(request_id)
            if previous:
                if previous.data["payload_hash"] != _hash(url):
                    raise Conflict("Idempotency key was already used with a different request")
                return self.get(tenant, previous.data["webhook_id"])
            account = self.store.get("tenant:" + tenant) or Document("tenant:" + tenant, "tenants", {"monitors": 0})
            count = account.data.get("webhooks", 0)
            if count >= 10:
                raise ValueError("Webhook quota reached (10 destinations per customer)")
            identifier, secret = uuid.uuid4().hex, new_signing_secret()
            endpoint = Document("webhook:" + identifier, "webhooks:" + tenant, {
                "id": identifier, "tenant": tenant, "url": url, "status": "pending",
                "created_at": self._now(), "verified_at": None, "generation": 1,
                "signing_secret": secret,
            }, due=self._now())
            try:
                self.store.commit([
                    endpoint,
                    account.update({**account.data, "webhooks": count + 1}),
                    Document(request_id, "webhook-requests:" + tenant,
                             {"payload_hash": _hash(url), "webhook_id": identifier},
                             expires_at=self._now() + 30 * 86400),
                ])
                return {**self._public(endpoint), "signing_secret": secret}
            except Conflict:
                continue
        raise Conflict("Concurrent webhook creation; retry with the same idempotency key")

    def challenge(self, tenant: str, identifier: str) -> dict:
        endpoint = self._document(tenant, identifier)
        if endpoint.data["status"] not in ("pending", "disabled"):
            raise ValueError("Only pending or disabled webhooks need verification")
        now = self._now()
        if endpoint.data.get("challenge_after", 0) > now:
            from gfpt_next.credentials import RateLimited
            raise RateLimited("Wait 60 seconds before requesting another webhook challenge")
        token, event_id = secrets.token_urlsafe(32), uuid.uuid4().hex
        expires_at = now + 600
        # Store before I/O so retries and competing requests cannot bypass cooldown.
        self.store.commit([endpoint.update({**endpoint.data, "challenge_hash": _hash(token),
            "challenge_expires_at": expires_at, "challenge_after": now + 60,
            "verification_attempts": 0})])
        payload = _encode({"id": event_id, "type": "webhook.verification", "created_at": now,
                           "data": {"webhook_id": identifier, "token": token, "expires_at": expires_at}})
        headers = sign_webhook(endpoint.data["signing_secret"], event_id, now, payload)
        try:
            delivered = self.transport.send(endpoint.data["url"], payload, headers)
        except Exception:
            delivered = False
        # A successful HTTP response is not proof that this customer controls it.
        return {"delivered": bool(delivered), "expires_at": expires_at}

    def verify(self, tenant: str, identifier: str, token: str) -> dict:
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ValueError("Invalid or expired webhook verification token")
        for _ in range(5):
            endpoint = self._document(tenant, identifier)
            if (endpoint.data["status"] not in ("pending", "disabled")
                    or endpoint.data.get("challenge_expires_at", 0) <= self._now()
                    or endpoint.data.get("verification_attempts", 0) >= 5):
                raise ValueError("Invalid or expired webhook verification token")
            valid = hmac.compare_digest(_hash(token), endpoint.data.get("challenge_hash", ""))
            data = {**endpoint.data, "verification_attempts": endpoint.data.get("verification_attempts", 0) + 1}
            if valid:
                data.update(status="active", verified_at=self._now(), challenge_hash=None, challenge_expires_at=0)
            try:
                self.store.commit([endpoint.update(data)])
            except Conflict:
                continue
            if not valid:
                raise ValueError("Invalid or expired webhook verification token")
            return self._public(endpoint.update(data))
        raise Conflict("Concurrent webhook verification; retry the request")

    def disable(self, tenant: str, identifier: str) -> dict:
        return self._retire(tenant, identifier, delete=False)

    def delete(self, tenant: str, identifier: str) -> dict:
        return self._retire(tenant, identifier, delete=True)

    def _retire(self, tenant: str, identifier: str, *, delete: bool) -> dict:
        for _ in range(5):
            endpoint = self._document(tenant, identifier)
            if (endpoint.data["status"] == "deleted" or endpoint.data["status"] == "disabled"
                    and not delete and not endpoint.data.get("challenge_hash")):
                return self._public(endpoint)
            data = {**endpoint.data, "status": "deleted" if delete else "disabled",
                    "generation": endpoint.data["generation"] + 1,
                    "challenge_hash": None, "challenge_expires_at": 0}
            writes = []
            if delete:
                data.pop("signing_secret", None)
                account = self.store.get("tenant:" + tenant)
                assert account is not None
                writes.append(account.update({**account.data, "webhooks": account.data["webhooks"] - 1}))
            writes.append(endpoint.update(data))
            try:
                self.store.commit(writes)
                return self._public(endpoint.update(data))
            except Conflict:
                continue
        raise Conflict("Concurrent webhook update; retry the request")

    def accepts(self, delivery: dict) -> bool:
        identifier = delivery.get("webhook_id")
        if identifier is None:
            return True
        from gfpt_next.service import NotFound

        try:
            endpoint = self._document(delivery["tenant"], identifier)
        except NotFound:
            return False
        return (endpoint.data["status"] == "active"
                and endpoint.data["generation"] == delivery.get("webhook_generation"))


class WebhookSink:
    def __init__(self, registry: WebhookRegistry):
        self.registry = registry

    def send(self, delivery: dict) -> bool:
        if delivery.get("webhook_id") is None or not self.registry.accepts(delivery):
            return False
        endpoint = self.registry.active_document(delivery["tenant"], delivery["webhook_id"])
        if endpoint.data["generation"] != delivery["webhook_generation"]:
            return False
        # Stable public event body across retries. Never expose lease, tenant, or secrets.
        payload = _encode({"id": delivery["id"], "type": "flight.price_alert",
            "created_at": delivery["observation"]["observed_at"],
            "data": {key: delivery[key] for key in ("monitor_id", "reason", "observation", "itinerary")}})
        headers = sign_webhook(endpoint.data["signing_secret"], delivery["id"], self.registry._now(), payload)
        return self.registry.transport.send(endpoint.data["url"], payload, headers)


class RoutedSink:
    """An explicitly selected webhook never falls back to a different destination."""

    def __init__(self, registry: WebhookRegistry, default: DeliverySink | None = None):
        self.webhook, self.default = WebhookSink(registry), default

    def send(self, delivery: dict) -> bool:
        if delivery.get("webhook_id") is not None:
            return self.webhook.send(delivery)
        return self.default.send(delivery) if self.default else False
