"""System health for the public status page.

The worker folds each run into hourly counters on the ``health:worker`` record,
and the status report is read from that one record. Counters only: no account,
itinerary or provider text reaches this module.
"""

from __future__ import annotations

from contextlib import suppress

from fareflare.store import Conflict, Document, Store

KEY = "health:worker"
HOUR = 3600
RETAINED_HOURS = 48
REPORT_HOURS = 24
# The scheduler runs every one to five minutes, so this is several missed runs.
STALLED_AFTER = 20 * 60
# With fewer checks than this, the share that failed says little.
MIN_CHECKS = 4
# A failed check is retried within minutes, and about one in ten fails on an
# ordinary day; these shares mark an hour that is clearly worse than that.
DEGRADED_SHARE = 0.4
MAJOR_SHARE = 0.9
_COUNTERS = ("collected", "failed", "alerts_sent")
_SEVERITY = ("operational", "unknown", "degraded", "major")


def record_run(store: Store, now: int, result: dict) -> None:
    """Fold one worker run into the rolling hourly record. Never fails a run."""
    record = store.get(KEY) or Document(KEY, "health", {})
    hour = now - now % HOUR
    hours = {
        start: counts
        for start, counts in (record.data.get("hours") or {}).items()
        if hour - RETAINED_HOURS * HOUR < int(start) <= hour
    }
    bucket = dict(hours.get(str(hour)) or {})
    bucket["runs"] = bucket.get("runs", 0) + 1
    for name in _COUNTERS:
        bucket[name] = bucket.get(name, 0) + int(result.get(name) or 0)
    hours[str(hour)] = bucket
    with suppress(Conflict):
        store.commit([record.update({**result, "last_worker_at": now, "hours": hours})])


def _state(collected: int, failed: int) -> str:
    checks = collected + failed
    if checks < MIN_CHECKS:
        return "operational"
    share = failed / checks
    if share >= MAJOR_SHARE:
        return "major"
    return "degraded" if share >= DEGRADED_SHARE else "operational"


def status_report(store: Store, now: int) -> dict:
    """What a visitor may know: whether checks run, and how the last day went."""
    record = store.get(KEY)
    data = record.data if record else {}
    last = data.get("last_worker_at")
    recorded = data.get("hours") or {}
    current = now - now % HOUR
    hours = []
    for index in range(REPORT_HOURS - 1, -1, -1):
        start = current - index * HOUR
        counts = recorded.get(str(start)) or {}
        runs, collected, failed, sent = (int(counts.get(name, 0)) for name in ("runs", *_COUNTERS))
        hours.append(
            {
                "start": start,
                "runs": runs,
                "collected": collected,
                "failed": failed,
                "alerts_sent": sent,
                "status": _state(collected, failed) if runs else "none",
            }
        )
    stalled = last is not None and now - last > STALLED_AFTER
    recent = hours[-3:]
    if last is None:
        checks, reason = "unknown", None
    elif stalled:
        checks, reason = "major", "stalled"
    else:
        checks = _state(sum(h["collected"] for h in recent), sum(h["failed"] for h in recent))
        reason = None if checks == "operational" else "failing"
    collected = sum(h["collected"] for h in hours)
    components = [
        {"id": "website", "status": "operational", "reason": None},
        {
            "id": "price_checks",
            "status": checks,
            "reason": reason,
            "last_run_at": last,
            "checks": collected + sum(h["failed"] for h in hours),
            "succeeded": collected,
        },
        {
            # Alerts leave in the same run that records a price change.
            "id": "alerts",
            "status": "unknown" if last is None else "major" if stalled else "operational",
            "reason": "stalled" if stalled else None,
            "sent": sum(h["alerts_sent"] for h in hours),
        },
    ]
    return {
        "status": max((item["status"] for item in components), key=_SEVERITY.index),
        "updated_at": now,
        "window_hours": REPORT_HOURS,
        "components": components,
        "hours": hours,
    }
