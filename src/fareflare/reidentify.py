"""Bring stored targets in line with how links are read now.

A target's identity is derived from its link (``links.import_link``). When those
rules change, a stored target can hold an identity, or an address, that its link no
longer imports to, and the collector would then refuse it as a changed itinerary.
This rewrites each such target as its link imports today. A target whose identity
changes moves to its new key with everything that names it: every monitor on it in
any state, the records that recognize a retried create request, its price history
and its place in the collection capacity. When another stored target already has
that identity, the two become one, as they would had both links been added today.

Release order (docs/OPERATIONS.md has the commands): take an on-demand backup of the
table, pause price checks, deploy, run this with ``--apply``, run it again without
``--apply`` until every target is ``unchanged``, then resume price checks.

- Without ``--apply`` it prints the plan, merges included, and writes nothing.
- ``--apply`` refuses while price checks run. Before writing anything it saves every
  document it will change to the ``--before`` file; ``--restore`` puts those back and
  removes the documents the run created.
- A target is busy while a check holds it or a watcher still has an alert to receive;
  a later run moves it. Each change is printed as it happens, and the command exits
  with status 1 if any target was busy, too large, unreadable or changed underneath it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from fareflare.links import import_link
from fareflare.refusals import LinkRefused
from fareflare.service import (
    BLOCKED,
    COLLECTING,
    EXPIRED,
    IDLE,
    TARGET_PARTITIONS,
    WATCHING,
    request_hash,
)
from fareflare.store import Conflict, Document, DynamoStore, SQLiteStore, Store

# A moved target's old key keeps only where it went, until it expires.
MOVED = "targets_moved"
_MOVED_KEPT = 30 * 86400
# One transaction holds at most 100 documents.
_MOST_WRITES = 100
CAPACITY = "capacity:collection"
PROBLEMS = frozenset({"busy", "too_large", "unreadable", "conflict"})


@dataclass(frozen=True)
class Change:
    target: str
    outcome: str  # unchanged, rewritten, moved, merged, busy, too_large, unreadable or conflict
    to: str | None = None
    monitors: int = 0  # Monitors re-pointed, in any state.
    history: int = 0  # Price observations moved to the new key.
    requests: int = 0  # Create-request records re-hashed for the new key.
    unmatched_requests: tuple[str, ...] = ()  # Records whose request cannot be rebuilt.
    check: str | None = None  # Why the link no longer imports, for an unreadable target.


@dataclass
class _Plan:
    change: Change
    old: str = ""
    new: str = ""
    writes: list[Document] = field(default_factory=list)
    # Each written key as it was before this plan; None for a document it creates.
    before: dict[str, Document | None] = field(default_factory=dict)
    history: list[Document] = field(default_factory=list)


def _documents(store: Store, partition: str) -> list[Document]:
    documents, cursor = [], None
    while True:
        page = store.page(partition, limit=1000, cursor=cursor)
        documents += page.items
        cursor = page.cursor
        if cursor is None:
            return documents


def _history(store: Store, target_id: str) -> list[Document]:
    """A target's price observations. Checks are paused while they move, and a stale
    one only makes its commit fail as a conflict, so the index is read as it is."""
    return [
        doc
        for doc in _documents(store, "history:" + target_id)
        if doc.partition == "history:" + target_id
    ]


def _observed(target: Document) -> int:
    return (target.data.get("latest") or {}).get("observed_at", -1)


class _Planner:
    """Plans every change before any is written, from fresh reads.

    A document an earlier plan writes is read as that plan leaves it, at the revision
    it will then have, so a merge follows the move it joins: if that move fails, the
    merge fails on the revision too. The shared capacity record is the exception: each
    plan only names the reservation to swap, and the swap is made on the record as it
    is when the plan is written, so one target's failure never fails another's.
    """

    def __init__(self, store: Store, now: int):
        self.store, self.now = store, now
        self.projected: dict[str, Document | None] = {}
        self.monitors: dict[str, list[str]] = defaultdict(list)  # By target id.
        self.requests: dict[str, list[str]] = defaultdict(list)  # By monitor id.
        for tenant in _documents(store, "tenants"):
            tenant_id = tenant.key.removeprefix("tenant:")
            for monitor in _documents(store, "monitors:" + tenant_id):
                self.monitors[monitor.data["target_id"]].append(monitor.key)
            for record in _documents(store, "requests:" + tenant_id):
                if record.data.get("monitor_id"):
                    self.requests[record.data["monitor_id"]].append(record.key)

    def read(self, key: str) -> Document | None:
        return self.projected[key] if key in self.projected else self.store.get(key)

    def _monitors(self, target_id: str) -> list[Document]:
        found = (self.read(key) for key in dict.fromkeys(self.monitors[target_id]))
        return [doc for doc in found if doc is not None and doc.data["target_id"] == target_id]

    def _busy(self, target: Document, monitors: list[Document]) -> bool:
        """A check holds the target, or a watcher has not yet had its latest alert."""
        sequence = target.data.get("sequence", 0)
        return target.data.get("lease_until", 0) > self.now or any(
            monitor.data["status"] in WATCHING and monitor.data.get("last_sequence", 0) < sequence
            for monitor in monitors
        )

    def _planned(self, change: Change, old: str, new: str, writes: list[Document]) -> _Plan:
        if len(writes) >= _MOST_WRITES:  # One place is kept for the capacity record.
            return _Plan(Change(old, "too_large", new, monitors=change.monitors))
        plan = _Plan(change, old, new, writes, {doc.key: self.read(doc.key) for doc in writes})
        for doc in writes:
            self.projected[doc.key] = doc.update(doc.data, revision=doc.revision + 1)
        return plan

    def plan(self, listed: Document) -> _Plan | None:
        current = self.read(listed.key)
        if current is None or current.partition != listed.partition:
            return None  # Already moved by an earlier plan.
        spec = current.data["spec"]
        old = spec["id"]
        try:
            fresh = import_link(spec["url"], allow_search=spec.get("kind") == "search")
        except LinkRefused as refusal:
            return _Plan(Change(old, "unreadable", check=refusal.check))
        if fresh == spec:
            return _Plan(Change(old, "unchanged"))
        monitors = self._monitors(old)
        if self._busy(current, monitors):
            return _Plan(Change(old, "busy", fresh["id"]))
        if fresh["id"] == old:
            writes = [current.update({**current.data, "spec": fresh})]
            return self._planned(Change(old, "rewritten", old), old, old, writes)
        return self._move(current, fresh, monitors)

    def _move(self, current: Document, spec: dict, monitors: list[Document]) -> _Plan:
        old, new = current.data["spec"]["id"], spec["id"]
        existing = self.read("target:" + new)
        joined = self._monitors(new) if existing else []
        if existing is not None and self._busy(existing, joined):
            return _Plan(Change(old, "busy", new))
        target = _merged(current, existing, spec, [*monitors, *joined])
        sequence = target.data.get("sequence", 0)
        writes = [
            target,
            current.update(
                {"moved_to": new}, partition=MOVED, due=0, expires_at=self.now + _MOVED_KEPT
            ),
        ]
        for monitor in monitors:
            data = {**monitor.data, "target_id": new}
            if existing:
                # Alerts continue from the merged sequence, never replaying either past.
                data["last_sequence"] = sequence
            writes.append(monitor.update(data))
        writes += [
            monitor.update({**monitor.data, "last_sequence": sequence})
            for monitor in joined
            if monitor.data.get("last_sequence") != sequence
        ]
        records, unmatched = self._requests(monitors, old, new)
        writes += records
        history = _history(self.store, old)
        change = Change(
            old,
            "merged" if existing else "moved",
            new,
            monitors=len(monitors),
            history=len(history),
            requests=len(records),
            unmatched_requests=tuple(unmatched),
        )
        plan = self._planned(change, old, new, writes)
        if plan.change.outcome != "too_large":
            plan.history = history
            self.monitors[new] += [monitor.key for monitor in monitors]
            capacity = self.store.get(CAPACITY)
            if capacity and old in capacity.data["targets"]:
                plan.before[CAPACITY] = capacity
        return plan

    def _requests(
        self, monitors: list[Document], old: str, new: str
    ) -> tuple[list[Document], list[str]]:
        """Re-hash each record that recognizes a retried create request.

        A record can be rebuilt only while its monitor still has the policy, interval
        and webhook it was created with; the others are listed, not guessed.
        """
        rehashed, unmatched = [], []
        for monitor in monitors:
            data = monitor.data
            asked = (data["policy"], data["interval_seconds"], data.get("webhook_id"))
            for key in self.requests[data["id"]]:
                record = self.read(key)
                if record is None:
                    continue
                if record.data["payload_hash"] != request_hash(old, *asked):
                    unmatched.append(key)
                    continue
                rehashed.append(
                    record.update({**record.data, "payload_hash": request_hash(new, *asked)})
                )
        return rehashed, unmatched

    def unfinished(self) -> list[_Plan]:
        """History a stopped run left behind a moved target."""
        plans = []
        for moved in _documents(self.store, MOVED):
            old, new = moved.key.removeprefix("target:"), moved.data["moved_to"]
            history = _history(self.store, old)
            if history:
                change = Change(old, "moved", new, history=len(history))
                plans.append(_Plan(change, old, new, history=history))
        return plans


def _merged(
    current: Document, existing: Document | None, spec: dict, monitors: list[Document]
) -> Document:
    """The new key's document: this target's state, or the two targets as one."""
    new = spec["id"]
    if existing is None:
        data = {**current.data, "spec": spec}
        if current.data.get("latest"):
            data["latest"] = {**current.data["latest"], "target_id": new}
        return Document("target:" + new, current.partition, data, due=current.due)
    both = (current, existing)
    newest = max(both, key=_observed)
    blocked = next((doc for doc in both if doc.partition == BLOCKED), None)
    subscribers = existing.data.get("subscribers", [])
    data = {
        **existing.data,
        "subscribers": subscribers
        + [s for s in current.data.get("subscribers", []) if s not in subscribers],
        "interval_seconds": min(
            current.data["interval_seconds"], existing.data["interval_seconds"]
        ),
        "sequence": max(doc.data.get("sequence", 0) for doc in both),
        "lease_token": None,
        "lease_until": 0,
    }
    if newest.data.get("latest"):
        data["latest"] = {**newest.data["latest"], "target_id": new}
    if blocked:
        data["failures"], data["last_error"] = (
            blocked.data.get("failures", 0),
            blocked.data.get("last_error"),
        )
    # Where the merged target lives follows from both: departed, unreadable, watched or not.
    if any(doc.partition == EXPIRED for doc in both):
        partition = EXPIRED
    elif blocked:
        partition = BLOCKED
    elif any(monitor.data["status"] in WATCHING for monitor in monitors):
        partition = COLLECTING
    else:
        partition = IDLE
    due = min(current.due, existing.due) if partition == COLLECTING else existing.due
    return existing.update(data, partition=partition, due=due)


def plan_changes(store: Store, now: int | None = None) -> list[_Plan]:
    """Every change that would bring the stored targets up to date, in order."""
    planner = _Planner(store, int(time.time()) if now is None else now)
    plans = planner.unfinished()
    for partition in TARGET_PARTITIONS:
        for listed in _documents(store, partition):
            plan = planner.plan(listed)
            if plan is not None:
                plans.append(plan)
    return plans


def _snapshot(document: Document | None) -> dict | None:
    if document is None:
        return None
    snapshot = asdict(document)
    del snapshot["revision"], snapshot["key"]
    return snapshot


def _reservation(store: Store, plan: _Plan) -> list[Document]:
    """The capacity record with this target's reservation moved to its new key."""
    capacity = store.get(CAPACITY)
    if capacity is None or plan.old not in capacity.data["targets"] or plan.old == plan.new:
        return []
    reserved = [identifier for identifier in capacity.data["targets"] if identifier != plan.old]
    if plan.new not in reserved:
        reserved.append(plan.new)
    return [capacity.update({**capacity.data, "targets": reserved})]


def apply(
    store: Store, plans: list[_Plan], before: Path, emit: Callable[[Change], None]
) -> list[Change]:
    """Save what each plan will change, then carry the plans out one target at a time."""
    switches = store.get("configuration:admin")
    if not (switches and switches.data.get("collection_paused")):
        raise ValueError("Pause price checks first (admin_cli pause-checks)")
    with before.open("x") as saved:  # Never overwrite an earlier run's record.
        for plan in plans:
            for key, prior in plan.before.items():
                saved.write(
                    json.dumps({"target": plan.old, "key": key, "before": _snapshot(prior)}) + "\n"
                )
            for doc in plan.history:
                saved.write(
                    json.dumps({"target": plan.old, "key": doc.key, "before": _snapshot(doc)})
                    + "\n"
                )
        saved.flush()
        changes = []
        for plan in plans:
            change = plan.change
            if plan.writes or plan.history:
                try:
                    if plan.writes:
                        store.commit([*plan.writes, *_reservation(store, plan)])
                    saved.write(json.dumps({"target": plan.old, "applied": True}) + "\n")
                    saved.flush()
                    for start in range(0, len(plan.history), 100):
                        store.commit(
                            [
                                doc.update(
                                    {**doc.data, "target_id": plan.new},
                                    partition="history:" + plan.new,
                                )
                                for doc in plan.history[start : start + 100]
                            ]
                        )
                except Conflict:
                    change = Change(plan.old, "conflict", plan.new)
            changes.append(change)
            emit(change)
    return changes


class _Removable(Store, Protocol):
    def remove(self, documents: list[Document]) -> None: ...


def restore(store: _Removable, before: Path) -> int:
    """Put back what a run changed and remove what it created. Returns the count."""
    lines = [json.loads(line) for line in before.read_text().splitlines() if line.strip()]
    applied = {line["target"] for line in lines if line.get("applied")}
    earliest: dict[str, dict | None] = {}
    for line in lines:
        if "key" in line and line["target"] in applied and line["key"] not in earliest:
            earliest[line["key"]] = line["before"]
    restores, removals = [], []
    for key, prior in earliest.items():
        current = store.get(key)
        if prior is None:
            if current is not None:
                removals.append(current)
        elif current is None:
            restores.append(Document(key, **prior))
        else:
            restores.append(
                current.update(
                    prior["data"], **{k: prior[k] for k in ("partition", "due", "expires_at")}
                )
            )
    for start in range(0, len(restores), 100):
        store.commit(restores[start : start + 100])
    for start in range(0, len(removals), 100):
        store.remove(removals[start : start + 100])
    return len(restores) + len(removals)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--table", help="DynamoDB table")
    where.add_argument("--database", help="SQLite database file")
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--apply",
        metavar="BEFORE",
        type=Path,
        help="Write the changes, saving what they replace to this new file",
    )
    action.add_argument(
        "--restore", metavar="BEFORE", type=Path, help="Undo the run that saved this file"
    )
    args = parser.parse_args(argv)
    if args.database and not Path(args.database).is_file():
        parser.error(f"no database at {args.database}")
    store = DynamoStore(args.table) if args.table else SQLiteStore(args.database)

    def emit(change: Change) -> None:
        print(json.dumps(asdict(change)), flush=True)

    if args.restore:
        print(json.dumps({"restored": restore(store, args.restore)}), flush=True)
        return 0
    plans = plan_changes(store)
    if args.apply:
        try:
            changes = apply(store, plans, args.apply, emit)
        except (ValueError, FileExistsError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    else:
        changes = [plan.change for plan in plans]
        for change in changes:
            emit(change)
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.outcome] = counts.get(change.outcome, 0) + 1
    print(json.dumps({"applied": bool(args.apply), "outcomes": counts}), file=sys.stderr)
    return 1 if PROBLEMS & counts.keys() else 0


if __name__ == "__main__":
    raise SystemExit(main())
