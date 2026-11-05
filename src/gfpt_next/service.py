"""Shared application use cases for HTTP, MCP and background workers."""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from gfpt_next.contracts import (
    CollectionFailure,
    DeliverySink,
    ObservedOffer,
    PriceProvider,
    Reading,
)
from gfpt_next.domain import AlertPolicy, evaluate
from gfpt_next.links import import_link
from gfpt_next.outbox import DeliveryOutbox
from gfpt_next.store import Conflict, Document, Store
from gfpt_next.webhooks import WebhookRegistry, WebhookTransport


class NotFound(LookupError):
    """Missing resource, including a resource owned by another tenant."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class CollectionBatch:
    counts: dict[str, int]
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class EventBatch:
    processed: int
    delivery_ids: tuple[str, ...]


class MonitoringService:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time,
                 link_importer: Callable[[str], dict] = import_link,
                 capability_check: Callable[[dict], None] | None = None, *,
                 webhook_transport: WebhookTransport | None = None,
                 monitor_limit: int = 100, min_interval_seconds: int = 300,
                 global_target_limit: int | None = None):
        self.store, self.clock = store, clock
        self.outbox = DeliveryOutbox(self)
        self.webhooks = WebhookRegistry(self, webhook_transport)
        self.link_importer, self.capability_check = link_importer, capability_check
        if (not 1 <= monitor_limit <= 100 or not 300 <= min_interval_seconds <= 86400
                or global_target_limit is not None and not 1 <= global_target_limit <= 1000):
            raise ValueError("Invalid development capacity limits")
        self.monitor_limit, self.min_interval_seconds = monitor_limit, min_interval_seconds
        self.global_target_limit = global_target_limit

    def _now(self) -> int:
        return int(self.clock())

    def _departure_day_elapsed(self, target: dict) -> bool:
        # The imported link has airport-local dates but no departure timezone.
        # Leave a whole UTC day of grace rather than expire a US evening flight
        # as soon as UTC crosses midnight. A validated collector can refine this.
        cutoff = datetime.fromtimestamp(self._now(), UTC).date() - timedelta(days=1)
        return target["segments"][0]["date"] < cutoff.isoformat()

    @staticmethod
    def _tenant(tenant: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", tenant):
            raise ValueError("Invalid tenant identifier")

    def create_monitor(self, tenant: str, url: str, request_key: str,
                       policy: AlertPolicy | None = None, interval_seconds: int = 900, *,
                       baseline: dict | None = None, initially_paused: bool = False,
                       webhook_id: str | None = None) -> dict:
        self._tenant(tenant)
        if baseline is not None and (set(baseline) != {"price_minor", "low_minor", "last_alert_minor"}
                or any(type(v) is not int or not 0 < v <= 100_000_000 for v in baseline.values())
                or baseline["low_minor"] > baseline["price_minor"]
                or baseline["low_minor"] > baseline["last_alert_minor"]):
            raise ValueError("Invalid migration price baseline")
        if not re.fullmatch(r"[a-zA-Z0-9_.:-]{8,128}", request_key):
            raise ValueError("Provide an 8–128 character idempotency key")
        if type(interval_seconds) is not int or not self.min_interval_seconds <= interval_seconds <= 86400:
            raise ValueError(f"Check interval must be {self.min_interval_seconds}–86400 seconds")
        target = self.link_importer(url)
        if self.capability_check:
            self.capability_check(target)
        if self._departure_day_elapsed(target):
            raise ValueError("The selected itinerary has already departed")
        policy = policy or AlertPolicy()
        request_payload = [target["id"], asdict(policy), interval_seconds, baseline, initially_paused]
        if webhook_id is not None:
            request_payload.append(webhook_id)
        payload_hash = _digest(json.dumps(request_payload, sort_keys=True))
        request_id = "request:" + _digest(tenant + ":" + request_key)
        for _ in range(5):
            existing = self.store.get(request_id)
            if existing:
                if existing.data["payload_hash"] != payload_hash:
                    raise Conflict("Idempotency key was already used with a different request")
                return self.get_monitor(tenant, existing.data["monitor_id"])
            endpoint = self.webhooks.active_document(tenant, webhook_id) if webhook_id is not None else None
            account = self.store.get("account:" + tenant) if tenant.startswith("acct_") else None
            if tenant.startswith("acct_") and (account is None or account.data.get("status") != "active"):
                raise ValueError("Account is not active")
            monitor_id = uuid.uuid4().hex
            target_doc = self.store.get("target:" + target["id"])
            current = target_doc.data if target_doc else {"spec": target, "sequence": 0}
            target_doc = target_doc or Document("target:" + target["id"], "targets", current)
            subscribers = current.get("subscribers", [])
            tenant_doc = self.store.get("tenant:" + tenant) or Document("tenant:" + tenant, "tenants", {"monitors": 0})
            if tenant_doc.data["monitors"] >= self.monitor_limit or len(subscribers) >= 1000:
                raise ValueError("Monitor quota reached")
            current = {**current, "subscribers": [*subscribers, monitor_id],
                       "interval_seconds": min(interval_seconds, current.get("interval_seconds", interval_seconds))}
            monitor = {"id": monitor_id, "tenant": tenant, "target_id": target["id"],
                       "policy": asdict(policy), "interval_seconds": interval_seconds,
                       "status": "paused" if initially_paused else "pending", "created_at": self._now(),
                       "last_sequence": current["sequence"], "rule_state": baseline or {},
                       "webhook_id": webhook_id}
            writes = [
                target_doc.update(current, partition="targets", due=min(target_doc.due, self._now())),
                Document("monitor:" + monitor_id, "monitors:" + tenant, monitor),
                tenant_doc.update({**tenant_doc.data, "monitors": tenant_doc.data["monitors"] + 1}),
                Document(request_id, "requests:" + tenant,
                         {"payload_hash": payload_hash, "monitor_id": monitor_id},
                         expires_at=self._now() + 30 * 86400),
            ]
            if endpoint:
                # Fence registration against a concurrent endpoint disable/delete.
                writes.append(endpoint.update(endpoint.data))
            if account:
                writes.append(account.update(account.data))
            if self.global_target_limit is not None:
                capacity = self.store.get("capacity:collection")
                if capacity is None:
                    # Seed from existing live targets when the product is first enabled.
                    reserved = [d.data["spec"]["id"] for d in self.store.query("targets")
                                if d.data.get("subscribers")]
                    capacity = Document("capacity:collection", "configuration", {"targets": reserved})
                reserved = capacity.data["targets"]
                if target["id"] not in reserved:
                    if len(reserved) >= self.global_target_limit:
                        raise ValueError("Development collection capacity reached; try again later")
                    reserved = [*reserved, target["id"]]
                writes.append(capacity.update({"targets": reserved}))
            try:
                self.store.commit(writes)
                return self.get_monitor(tenant, monitor_id)
            except Conflict:
                continue
        raise Conflict("Concurrent monitor creation; retry with the same idempotency key")

    def _monitor(self, tenant: str, monitor_id: str) -> Document:
        self._tenant(tenant)
        doc = self.store.get("monitor:" + monitor_id)
        if not doc or doc.data["tenant"] != tenant:
            raise NotFound("Monitor not found")
        return doc

    def get_monitor(self, tenant: str, monitor_id: str) -> dict:
        monitor = self._monitor(tenant, monitor_id).data
        target = self.store.get("target:" + monitor["target_id"])
        assert target is not None
        return {**monitor, "target": target.data["spec"],
                "latest": target.data.get("latest"), "last_error": target.data.get("last_error"),
                "next_check_at": None if target.partition in ("targets_blocked", "targets_expired") else target.due,
                "collection_status": "blocked" if target.partition == "targets_blocked" else
                "backoff" if target.data.get("last_error") else "ready",
                "stale": not target.data.get("latest") or
                self._now() - target.data["latest"]["observed_at"] > monitor["interval_seconds"] * 2}

    def list_monitors(self, tenant: str) -> list[dict]:
        self._tenant(tenant)
        return [self.get_monitor(tenant, d.data["id"]) for d in self.store.page("monitors:" + tenant, limit=1000).items]

    def set_status(self, tenant: str, monitor_id: str, status: str) -> dict:
        if status not in ("paused", "active", "cancelled"):
            raise ValueError("Unsupported monitor status")
        return self._transition_status(tenant, monitor_id, status)

    def _transition_status(self, tenant: str, monitor_id: str, status: str) -> dict:
        monitor = self._monitor(tenant, monitor_id)
        if monitor.data["status"] == "cancelled" and status != "cancelled":
            raise ValueError("A cancelled monitor cannot be reactivated")
        if (monitor.data["status"] == status or
                status == "active" and monitor.data["status"] in ("pending", "active", "degraded")):
            return self.get_monitor(tenant, monitor_id)
        if monitor.data["status"] == "expired" and status not in ("expired", "cancelled"):
            raise ValueError("An expired itinerary cannot be reactivated")
        data = {**monitor.data, "status": status}
        if status in ("paused", "cancelled", "expired"):
            data["notification_epoch"] = data.get("notification_epoch", 0) + 1
        writes = []
        if status == "active":
            target = self.store.get("target:" + data["target_id"])
            assert target is not None
            data.update(last_sequence=target.data["sequence"], status="pending")
            writes.append(target.update(target.data, partition="targets", due=self._now()))
        if status in ("cancelled", "expired") and not monitor.data.get("quota_released", False):
            target = self.store.get("target:" + data["target_id"])
            tenant_doc = self.store.get("tenant:" + tenant)
            assert target is not None and tenant_doc is not None
            subscribers = [mid for mid in target.data["subscribers"] if mid != monitor_id]
            writes.append(target.update({**target.data, "subscribers": subscribers}))
            capacity = self.store.get("capacity:collection")
            if not subscribers and capacity and data["target_id"] in capacity.data["targets"]:
                writes.append(capacity.update({"targets": [identifier for identifier in capacity.data["targets"]
                                                            if identifier != data["target_id"]]}))
            writes.append(tenant_doc.update({**tenant_doc.data, "monitors": max(0, tenant_doc.data["monitors"] - 1)}))
            data["quota_released"] = True
        writes.append(monitor.update(data))
        self.store.commit(writes)
        return self.get_monitor(tenant, monitor_id)

    def history(self, tenant: str, monitor_id: str, limit: int = 100) -> list[dict]:
        monitor = self._monitor(tenant, monitor_id)
        docs = self.store.page("history:" + monitor.data["target_id"], limit=min(max(limit, 1), 1000), reverse=True).items
        return [d.data for d in reversed(docs)]

    def _active_subscribers(self, target_id: str) -> list[Document]:
        # Strong reads are required here. GSI lag must never drop an event or
        # strand a monitor's sequence cursor. Bounded to 1000 subscriptions.
        target = self.store.get("target:" + target_id)
        assert target is not None
        monitors = [self.store.get("monitor:" + mid) for mid in target.data.get("subscribers", [])]
        active = []
        for monitor in monitors:
            if not monitor or monitor.data["status"] not in ("pending", "active", "degraded"):
                continue
            if monitor.data["tenant"].startswith("acct_"):
                account = self.store.get("account:" + monitor.data["tenant"])
                if not account or account.data.get("status") != "active":
                    continue
            active.append(monitor)
        return active

    def record(self, reading: Reading, run_id: str, lease_token: str | None = None) -> bool:
        """Commit a checked observation and pending event atomically; no delivery I/O."""
        if (type(reading.amount_minor) is not int or not 0 < reading.amount_minor <= 100_000_000
                or type(reading.observed_at) is not int or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", reading.source)
                or reading.price_basis not in ("unspecified", "total")
                or (reading.fare_name is not None and (
                    not isinstance(reading.fare_name, str) or not 1 <= len(reading.fare_name) <= 120))
                or reading.observed_at > self._now() + 60 or reading.observed_at < 0
                or not 1 <= len(run_id) <= 128):
            raise ValueError("Invalid price observation")
        if reading.evidence is not None and (
                reading.evidence.identity_verified is not True
                or reading.evidence.eligibility_verified is not True
                or reading.evidence.party_verified is not True
                or reading.price_basis != "total"
                or reading.evidence.display_precision_minor not in (1, 100)):
            raise ValueError("Unverified price evidence")
        target = self.store.get("target:" + reading.target_id)
        if target is None:
            raise NotFound("Target not found")
        if reading.currency != target.data["spec"]["currency"]:
            raise ValueError("Observation currency does not match the target")
        self._verify_observed_offer(target.data["spec"], reading)
        event_id = _digest(reading.target_id + ":" + run_id)
        # Normalize immutable offer tuples to the JSON shape used by both stores.
        observation = json.loads(json.dumps(asdict(reading)))
        prior = self.store.get("observation:" + event_id)
        if prior:
            if prior.data != observation:
                raise Conflict("A run ID cannot be reused with a different observation")
            return False
        if (target.data.get("lease_token") != lease_token or
                lease_token is not None and target.data.get("lease_until", 0) <= self._now()):
            raise Conflict("Collector lease was superseded")
        if target.data.get("latest", {}).get("observed_at", -1) >= reading.observed_at:
            raise ValueError("Observation must be newer than the last successful observation")
        sequence = target.data["sequence"] + 1
        data = {**target.data, "latest": observation, "sequence": sequence,
                "failures": 0, "last_error": None, "lease_token": None, "lease_until": 0}
        self.store.commit([
            target.update(data, due=self._now() + data["interval_seconds"]),
            Document("observation:" + event_id, "history:" + reading.target_id, observation,
                     due=reading.observed_at, expires_at=self._now() + 365 * 86400),
            Document("event:" + event_id, "events_pending",
                     {"id": event_id, "sequence": sequence, "observation": observation}, due=reading.observed_at),
        ])
        return True

    @staticmethod
    def _verify_observed_offer(target: dict, reading: Reading) -> None:
        offer = reading.observed_offer
        if offer is None:
            if target.get("kind") == "search":
                raise ValueError("A route-search price requires its verified selected offer")
            return
        if not isinstance(offer, ObservedOffer) or reading.evidence is None:
            raise ValueError("An observed offer requires verified price evidence")
        selected = import_link(offer.url)
        serialized = json.loads(json.dumps(asdict(offer)))
        if (selected["id"] != offer.target_id or selected["segments"] != serialized["segments"]
                or any(selected[key] != target[key] for key in ("adults", "cabin", "currency", "market"))
                or offer.adults != selected["adults"] or offer.cabin != selected["cabin"]):
            raise ValueError("Observed offer does not match its selected itinerary")
        if target.get("kind") == "search":
            from gfpt_next.search_links import offer_matches_search
            if not offer_matches_search(target, selected):
                raise ValueError("Observed offer does not match the route search")
        elif offer.target_id != target["id"]:
            raise ValueError("Observed offer does not match the monitored itinerary")

    def collect_due(self, provider: PriceProvider, limit: int = 20) -> dict:
        return self.collect_batch(provider, limit).counts

    def collect_batch(self, provider: PriceProvider, limit: int = 20, *,
                      should_continue: Callable[[], bool] | None = None) -> CollectionBatch:
        event_ids = []
        counts = {"collected": 0, "failed": 0, "skipped": 0}
        # Discover one bounded page. Re-querying its head after each collection
        # can return the same stale GSI row and starve other due targets.
        for candidate in self.store.page("targets", self._now(), limit=limit).items:
            if should_continue is not None and not should_continue():
                break
            target = self.store.get(candidate.key)
            if (target is None or target.partition != "targets" or target.due > self._now()
                    or target.data.get("lease_until", 0) > self._now()):
                counts["skipped"] += 1
                continue
            subscribers = self._active_subscribers(target.data["spec"]["id"])
            if not subscribers:
                # Do not remove customer intent. A future reactivation requeues it.
                self.store.commit([target.update(target.data, partition="targets_idle", due=self._now() + 3600)])
                counts["skipped"] += 1
                continue
            if self._departure_day_elapsed(target.data["spec"]):
                # Release account/global reservations, including paused subscribers.
                # Each transition is atomic and idempotent across worker retries.
                for identifier in target.data.get("subscribers", []):
                    for _ in range(5):
                        monitor = self.store.get("monitor:" + identifier)
                        if not monitor or monitor.data["status"] in ("cancelled", "expired"):
                            break
                        try:
                            self._transition_status(monitor.data["tenant"], identifier, "expired")
                            break
                        except Conflict:
                            continue
                current = self.store.get(target.key)
                if current and not current.data.get("subscribers"):
                    try:
                        self.store.commit([current.update(current.data, partition="targets_expired")])
                    except Conflict:
                        pass  # A later tick finishes the state transition.
                continue
            token = uuid.uuid4().hex
            leased = {**target.data, "lease_token": token, "lease_until": self._now() + 120,
                      "interval_seconds": min(d.data["interval_seconds"] for d in subscribers)}
            try:
                self.store.commit([target.update(leased, due=self._now() + 120)])
            except Conflict:
                counts["skipped"] += 1
                continue
            try:
                reading = provider.collect(leased["spec"])
                if reading.target_id != leased["spec"]["id"]:
                    raise ValueError("Provider returned a different itinerary")
                self.record(reading, token, lease_token=token)
                event_ids.append(_digest(reading.target_id + ":" + token))
                counts["collected"] += 1
            except Exception as exc:
                failure = exc if isinstance(exc, CollectionFailure) else CollectionFailure("collection_failed")
                current = self.store.get(target.key)
                if current and current.data.get("lease_token") == token:
                    failures = current.data.get("failures", 0) + 1
                    # Do not persist exception text: provider errors can contain cookies/URLs.
                    data = {**current.data, "failures": failures, "last_error": failure.code,
                            "lease_token": None, "lease_until": 0}
                    try:
                        self.store.commit([current.update(data,
                            partition="targets" if failure.retryable else "targets_blocked",
                            due=self._now() + random.randint(30, min(60 * 2 ** min(failures, 6), 3600)))])
                    except Conflict:
                        pass
                counts["failed"] += 1
        return CollectionBatch(counts, tuple(event_ids))

    def process_events(self, limit: int = 100) -> int:
        return self.process_event_batch(limit).processed

    def process_event_batch(self, limit: int = 100, *, event_ids: tuple[str, ...] = ()) -> EventBatch:
        processed, delivery_ids = 0, []
        candidates = {d.key: d for d in self.store.page("events_pending", limit=limit).items}
        for identifier in event_ids:
            doc = self.store.get("event:" + identifier)
            if doc and doc.partition == "events_pending":
                candidates[doc.key] = doc
        examined = 0
        for candidate in candidates.values():
            event = self.store.get(candidate.key)
            if not event or event.partition != "events_pending":
                continue
            if examined >= limit:
                break
            examined += 1
            observation, sequence = event.data["observation"], event.data["sequence"]
            complete = True
            for monitor in self._active_subscribers(observation["target_id"]):
                data = monitor.data
                if data["last_sequence"] >= sequence:
                    continue
                if data["last_sequence"] + 1 != sequence:
                    complete = False  # An earlier event must be consumed first.
                    continue
                state, reason = evaluate(AlertPolicy(**data["policy"]), data["rule_state"], observation["amount_minor"])
                endpoint = self.store.get("webhook:" + data["webhook_id"]) if data.get("webhook_id") else None
                destination_ready = data.get("webhook_id") is None or bool(endpoint
                    and endpoint.data["tenant"] == data["tenant"] and endpoint.data["status"] == "active")
                queue_alert = bool(reason and destination_ready and not self.notifications_muted(data))
                if reason and not queue_alert:
                    if "last_alert_minor" in data["rule_state"]:
                        state["last_alert_minor"] = data["rule_state"]["last_alert_minor"]
                    else:
                        state.pop("last_alert_minor", None)
                writes = [monitor.update({**data, "rule_state": state, "last_sequence": sequence, "status": "active"})]
                if queue_alert:
                    delivery_id = _digest(event.data["id"] + ":" + data["id"])
                    target = self.store.get("target:" + data["target_id"])
                    assert target is not None
                    spec = observation.get("observed_offer") or target.data["spec"]
                    payload = {"itinerary": {k: spec[k] for k in ("segments", "adults", "cabin", "url")},
                               "id": delivery_id, "event_id": event.data["id"], "tenant": data["tenant"],
                               "monitor_id": data["id"], "reason": reason, "observation": observation,
                               "status": "pending", "attempts": 0, "sequence": sequence,
                               "predecessor": data.get("delivery_tail"),
                               "predecessor_sequence": data.get("delivery_tail_sequence", 0),
                               "notification_epoch": data.get("notification_epoch", 0),
                               "tenant_epoch": self.tenant_notification_epoch(data["tenant"])}
                    if endpoint:
                        payload.update(webhook_id=endpoint.data["id"], webhook_generation=endpoint.data["generation"])
                        writes.append(endpoint.update(endpoint.data))
                    writes[0] = writes[0].update({**writes[0].data, "delivery_tail": delivery_id, "delivery_tail_sequence": sequence})
                    predecessor = self.store.get("delivery:" + data["delivery_tail"]) if data.get("delivery_tail") else None
                    waiting = predecessor is not None and predecessor.data["status"] not in ("sent", "suppressed")
                    if waiting and predecessor:
                        writes.append(predecessor.update({**predecessor.data, "successor": delivery_id}))
                    writes.extend([
                        Document("delivery:" + delivery_id, "deliveries_waiting" if waiting else "deliveries_pending", payload, due=observation["observed_at"]),
                        Document("delivery-index:" + delivery_id, "deliveries:" + data["tenant"],
                                 {"id": delivery_id}, due=observation["observed_at"]),
                    ])
                try:
                    self.store.commit(writes)
                    if queue_alert:
                        delivery_ids.append(delivery_id)
                except Conflict:
                    complete = False
            if complete:
                try:
                    self.store.commit([event.update(event.data, partition="events_processed", expires_at=self._now() + 7 * 86400)])
                    processed += 1
                except Conflict:
                    pass
        return EventBatch(processed, tuple(delivery_ids))

    def list_deliveries(self, tenant: str) -> list[dict]:
        return self.outbox.list(tenant)

    def deliver_due(self, sink: DeliverySink, limit: int = 100) -> int:
        return self.outbox.deliver(sink, limit)

    def retry_delivery(self, tenant: str, delivery_id: str) -> dict:
        return self.outbox.retry(tenant, delivery_id)

    @staticmethod
    def _delivery_missing() -> None:
        raise NotFound("Delivery not found")

    def retry_collection(self, tenant: str, monitor_id: str) -> dict:
        monitor = self._monitor(tenant, monitor_id)
        target = self.store.get("target:" + monitor.data["target_id"])
        assert target is not None
        if target.partition != "targets_blocked":
            raise ValueError("Only blocked collection can be retried")
        self.store.commit([target.update({**target.data, "last_error": None, "failures": 0},
                                        partition="targets", due=self._now())])
        return self.get_monitor(tenant, monitor_id)

    def history_page(self, tenant: str, monitor_id: str, limit: int = 100,
                     cursor: str | None = None) -> dict:
        monitor = self._monitor(tenant, monitor_id)
        page = self.store.page("history:" + monitor.data["target_id"], limit=limit, cursor=cursor, reverse=True)
        return {"items": [d.data for d in page.items], "next_cursor": page.cursor}

    def alerts_page(self, tenant: str, limit: int = 100, cursor: str | None = None) -> dict:
        self._tenant(tenant)
        page = self.store.page("deliveries:" + tenant, limit=limit, cursor=cursor, reverse=True)
        items = [self.store.get("delivery:" + d.data["id"]) for d in page.items]
        return {"items": [d.data for d in items if d and d.data["tenant"] == tenant], "next_cursor": page.cursor}

    def preferences(self, tenant: str) -> dict:
        self._tenant(tenant)
        doc = self.store.get("tenant:" + tenant)
        return {"muted": False, "muted_routes": [], **(doc.data.get("preferences", {}) if doc else {})}

    def set_preferences(self, tenant: str, muted: bool, muted_routes: list[str]) -> dict:
        self._tenant(tenant)
        if (type(muted) is not bool or len(muted_routes) > 100 or
                any(not re.fullmatch(r"[A-Z]{3}-[A-Z]{3}", route) for route in muted_routes)):
            raise ValueError("Invalid alert preferences")
        doc = self.store.get("tenant:" + tenant) or Document("tenant:" + tenant, "tenants", {"monitors": 0})
        preferences = {"muted": muted, "muted_routes": sorted(set(muted_routes))}
        if self.preferences(tenant) == preferences:
            return preferences
        # A preference revision prevents queued alerts resurfacing after unmute.
        self.store.commit([doc.update({**doc.data, "preferences": preferences,
                                       "notification_epoch": doc.data.get("notification_epoch", 0) + 1})])
        return preferences

    def notifications_muted(self, monitor: dict) -> bool:
        preferences = self.preferences(monitor["tenant"])
        target = self.store.get("target:" + monitor["target_id"])
        assert target is not None
        legs = target.data["spec"]["segments"][0]["legs"]
        route = legs[0]["origin"] + "-" + legs[-1]["destination"]
        return bool(preferences["muted"] or route in preferences["muted_routes"])

    def tenant_notification_epoch(self, tenant: str) -> int:
        doc = self.store.get("tenant:" + tenant)
        return doc.data.get("notification_epoch", 0) if doc else 0

    def set_policy(self, tenant: str, monitor_id: str, policy: AlertPolicy) -> dict:
        monitor = self._monitor(tenant, monitor_id)
        if monitor.data["status"] in ("cancelled", "expired"):
            raise ValueError("Cannot change a terminal monitor")
        self.store.commit([monitor.update({**monitor.data, "policy": asdict(policy)})])
        return self.get_monitor(tenant, monitor_id)

    def monitors_page(self, tenant: str, limit: int = 100, cursor: str | None = None) -> dict:
        self._tenant(tenant)
        page = self.store.page("monitors:" + tenant, limit=limit, cursor=cursor)
        return {"items": [self.get_monitor(tenant, d.data["id"]) for d in page.items],
                "next_cursor": page.cursor}
