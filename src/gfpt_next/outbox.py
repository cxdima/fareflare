"""Durable per-monitor FIFO delivery, independent of collection and API transports."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from gfpt_next.contracts import DeliverySink
from gfpt_next.store import Conflict, Document

if TYPE_CHECKING:
    from gfpt_next.service import MonitoringService


class DeliveryOutbox:
    def __init__(self, owner: MonitoringService):
        self.owner, self.store, self._now = owner, owner.store, owner._now

    def _complete(self, current: Document, payload: dict, status: str) -> None:
        for _ in range(5):
            # Event fan-out can append a successor while the network send runs.
            # Retry persistence only; never send the external message again here.
            payload = {**current.data, "status": status, "attempts": payload["attempts"], "lease_token": None}
            terminal = status in ("sent", "suppressed")
            writes = [current.update(payload,
                partition="deliveries_pending" if status == "pending" else "deliveries_done",
                due=self._now() + min(30 * 2**payload["attempts"], 3600),
                expires_at=self._now() + 365 * 86400 if terminal else None)]
            if terminal:
                monitor = self.owner._monitor(payload["tenant"], payload["monitor_id"])
                writes.append(monitor.update({**monitor.data, "delivery_sequence": max(payload["sequence"], monitor.data.get("delivery_sequence", 0))}))
                index = self.store.get("delivery-index:" + payload["id"])
                if index:
                    writes.append(index.update(index.data, expires_at=self._now() + 365 * 86400))
                if payload.get("successor"):
                    successor = self.store.get("delivery:" + payload["successor"])
                    if successor and successor.partition == "deliveries_waiting":
                        writes.append(successor.update(successor.data, partition="deliveries_pending", due=self._now()))
            try:
                self.store.commit(writes)
                return
            except Conflict:
                latest = self.store.get(current.key)
                if (not latest or latest.partition != "deliveries_pending"
                        or latest.data.get("lease_token") != current.data.get("lease_token")):
                    return
                current = latest
        raise Conflict("Delivery acknowledgment contention; the durable lease will recover it")

    def list(self, tenant: str) -> list[dict]:
        self.owner._tenant(tenant)
        items = [self.store.get("delivery:" + d.data["id"])
                 for d in self.store.page("deliveries:" + tenant, limit=1000).items]
        return [d.data for d in items if d and d.data["tenant"] == tenant]

    def deliver(self, sink: DeliverySink | None, limit: int = 100, *, force_suppress: bool = False,
                delivery_ids: tuple[str, ...] = ()) -> int:
        sent = 0
        candidates = {d.key: d for d in self.store.page("deliveries_pending", self._now(), limit=limit).items}
        # Strong direct reads avoid waiting for GSI propagation after event fan-out.
        for identifier in delivery_ids:
            doc = self.store.get("delivery:" + identifier)
            if doc and doc.partition == "deliveries_pending" and doc.due <= self._now():
                candidates[doc.key] = doc
        examined = 0
        for candidate in candidates.values():
            delivery = self.store.get(candidate.key)
            if not delivery or delivery.partition != "deliveries_pending" or delivery.due > self._now():
                continue
            if examined >= limit:
                break
            examined += 1
            monitor = self.owner._monitor(delivery.data["tenant"], delivery.data["monitor_id"])
            predecessor = delivery.data.get("predecessor")
            if predecessor:
                previous = self.store.get("delivery:" + predecessor)
                retired = (previous is None and monitor.data.get("delivery_sequence", 0)
                           >= delivery.data.get("predecessor_sequence", 1))
                if not retired and (not previous or previous.data["status"] not in ("sent", "suppressed")):
                    continue  # A failed or leased head blocks this monitor, never another tenant.
            if (force_suppress or monitor.data["status"] in ("paused", "cancelled", "expired") or
                    delivery.data.get("notification_epoch", 0) != monitor.data.get("notification_epoch", 0) or
                    delivery.data.get("tenant_epoch", 0) != self.owner.tenant_notification_epoch(delivery.data["tenant"]) or
                    self.owner.notifications_muted(monitor.data) or
                    not self.owner.webhooks.accepts(delivery.data)):
                self._complete(delivery, {**delivery.data, "status": "suppressed"}, "suppressed")
                sent += int(force_suppress)
                continue
            token = uuid.uuid4().hex
            try:
                self.store.commit([delivery.update({**delivery.data, "lease_token": token}, due=self._now() + 60)])
            except Conflict:
                continue
            try:
                ok = sink.send(delivery.data) if sink else False
            except Exception:
                ok = False
            current = self.store.get(delivery.key)
            if not current or current.data.get("lease_token") != token:
                continue
            attempts = current.data["attempts"] + 1
            status = "sent" if ok else "dead_letter" if attempts >= 5 else "pending"
            payload = {**current.data, "attempts": attempts, "status": status, "lease_token": None}
            self._complete(current, payload, status)
            sent += int(bool(ok))
        return sent

    def retry(self, tenant: str, delivery_id: str) -> dict:
        self.owner._tenant(tenant)
        delivery = self.store.get("delivery:" + delivery_id)
        if not delivery or delivery.data["tenant"] != tenant:
            from gfpt_next.service import NotFound
            raise NotFound("Delivery not found")
        if delivery.data["status"] != "dead_letter":
            raise ValueError("Only dead-letter deliveries can be requeued")
        data = {**delivery.data, "status": "pending", "attempts": 0}
        self.store.commit([delivery.update(data, partition="deliveries_pending", due=self._now())])
        return data
