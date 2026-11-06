"""Bounded scheduled work. Durable state, not this process, owns retries."""
from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import cast

from fareflare.contracts import DeliverySink, PriceProvider
from fareflare.service import MonitoringService


class Worker:
    def __init__(self, service: MonitoringService, provider: PriceProvider,
                 sink: DeliverySink | None = None, monotonic: Callable[[], float] = time.monotonic):
        self.service, self.provider, self.sink, self.monotonic = service, provider, sink, monotonic

    def tick(self, max_targets: int = 1, budget_seconds: int = 150) -> dict:
        if not 1 <= max_targets <= 20 or not 1 <= budget_seconds <= 900:
            raise ValueError("Invalid worker budget")
        started = self.monotonic()
        counts = {"collected": 0, "failed": 0, "skipped": 0, "events_processed": 0, "alerts_sent": 0, "alerts_suppressed": 0,
                  "shadow": self.sink is None, "browser_launches": 0, "browser_reuses": 0}
        event_ids = []
        # Batching is an explicit provider capability; ordinary providers retain
        # their collect-only contract. The scope closes before dispatch/delivery.
        batch_factory = getattr(type(self.provider), "batch", None)
        scope = (cast(AbstractContextManager[PriceProvider], batch_factory(self.provider))
                 if callable(batch_factory) else nullcontext(self.provider))
        with scope as provider:
            # Discover candidates once, then reserve a full collection's budget
            # before each one. A stale index head cannot consume the whole batch.
            batch = self.service.collect_batch(provider, limit=max_targets,
                should_continue=lambda: self.monotonic() - started <= budget_seconds - 120)
            event_ids.extend(batch.event_ids)
            for key, value in batch.counts.items():
                counts[key] += value
            if callable(batch_factory):
                counts["browser_launches"] = getattr(provider, "browser_launches", 0)
                counts["browser_reuses"] = getattr(provider, "browser_reuses", 0)
        events = self.service.process_event_batch(limit=100, event_ids=tuple(event_ids))
        counts["events_processed"] = events.processed
        for _ in range(100):
            if self.monotonic() - started >= budget_seconds - 12:
                break
            if self.sink is None:
                done = self.service.outbox.deliver(None, limit=1, force_suppress=True, delivery_ids=events.delivery_ids)
                counts["alerts_suppressed"] += done
            else:
                done = self.service.outbox.deliver(self.sink, limit=1, delivery_ids=events.delivery_ids)
                counts["alerts_sent"] += done
            if not done:
                break
        counts["runtime_ms"] = int((self.monotonic() - started) * 1000)
        return counts
