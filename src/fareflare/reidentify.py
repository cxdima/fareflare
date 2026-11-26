"""Bring stored targets in line with how links are read now.

A target's identity is derived from its link (``links.import_link``). When those
rules change, a stored target can hold an identity, or an address, that its link no
longer imports to, and the collector would then refuse it as a changed itinerary.
This rewrites each such target as its link imports today. A target whose identity
changes moves to its new key with everything that names it: every monitor on it in
any state, the records that recognize a retried create request, its price history
and its place in the collection capacity. When another stored target already has
that identity, the two become one, as they would had both links been added today.
A stored link the rules now refuse is blocked as ``unsupported_itinerary``, as the
collector blocks a flight it cannot read: its watchers see it, and it stays put.

Release order (docs/OPERATIONS.md has the commands): take an on-demand backup of the
table, pause price checks, deploy, run this with ``--apply``, run it again without
``--apply`` until it exits 0 with nothing left to move, then resume price checks.

- Without ``--apply`` it prints the plan, merges included, and writes nothing.
- ``--apply FILE`` and ``--restore FILE`` refuse while price checks run. Before writing
  anything, ``--apply`` saves every document it will change to FILE (mode 0600, in a
  directory only its owner can open). ``--restore`` undoes each target whose documents
  are still as the run left them, and lists the rest.
- A target is busy while a check holds it or a watcher still has an alert to receive;
  a later run moves it. Each change is printed as it happens, and the command exits
  with status 1 if any target was busy, too large, conflicting, missing a watcher or
  failed; status 2 means it could not start.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from fareflare.contracts import CollectionFailure
from fareflare.failures import describe_failure
from fareflare.links import import_link
from fareflare.refusals import LinkRefused
from fareflare.service import (
    BLOCKED,
    COLLECTING,
    EXPIRED,
    IDLE,
    TARGET_PARTITIONS,
    receives_alerts,
    request_hash,
)
from fareflare.store import Conflict, Document, DynamoStore, SQLiteStore, Store
from fareflare.switches import switches

# A moved target's old key keeps only where it went, until it expires.
MOVED = "targets_moved"
_MOVED_KEPT = 30 * 86400
# One transaction holds at most 100 documents; one place is kept for capacity.
_MOST_WRITES = 99
CAPACITY = "capacity:collection"
# The collector's own code for a flight it cannot read, which stops its checks.
UNREADABLE = CollectionFailure.UNREADABLE
# The only documents a run writes, and so the only ones a restore may write back.
_WRITTEN = ("target:", "monitor:", "request:", "observation:")
PROBLEMS = frozenset({"busy", "too_large", "conflict", "missing_monitor", "failed"})


class NotReady(Exception):
    """The run cannot start: something the operator must do first."""


@dataclass(frozen=True)
class Change:
    target: str
    # unchanged, rewritten, moved, merged, blocked, busy, too_large, conflict,
    # missing_monitor or failed
    outcome: str
    to: str | None = None
    monitors: int = 0  # Monitors re-pointed, in any state.
    history: int = 0  # Price observations moved to the new key.
    requests: int = 0  # Create-request records re-hashed for the new key.
    unmatched_requests: tuple[str, ...] = ()  # Records whose request cannot be rebuilt.
    check: str | None = None  # Why the link no longer imports, for a blocked target.
    error: str | None = None  # What failed, without its text, for a failed target.


@dataclass
class _Plan:
    change: Change
    old: str = ""
    new: str = ""
    writes: list[Document] = field(default_factory=list)
    # Each written key as it was before this plan; None for a document it creates.
    before: dict[str, Document | None] = field(default_factory=dict)
    history: list[Document] = field(default_factory=list)
    reserve: bool = False  # Whether the capacity record's reservation moves to ``new``.


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
    partition = "history:" + target_id
    return [doc for doc in _documents(store, partition) if doc.partition == partition]


def _observed(target: Document) -> int:
    return (target.data.get("latest") or {}).get("observed_at", -1)


def _require_paused(store: Store) -> None:
    if not switches(store)["collection_paused"]:
        raise NotReady("Pause price checks first: admin_cli pause-checks")


class _Planner:
    """Plans every change before any is written, from fresh reads.

    A document an earlier plan writes is read as that plan leaves it, at the revision
    it will then have, so a merge follows the move it joins: if that move fails, the
    merge fails on the revision too. The shared capacity record is the exception: a
    plan only says its reservation moves, and the move is made on the record as it is
    when the plan is written, so one target's failure never fails another's.
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

    def _monitors(self, target: Document) -> tuple[list[Document], list[str]]:
        """Every monitor on a target, found by the sweep or listed as its watcher, and
        the watchers that cannot be read."""
        identifier = target.data["spec"]["id"]
        keys = [
            *self.monitors[identifier],
            *("monitor:" + mid for mid in target.data.get("subscribers", [])),
        ]
        found, missing = [], []
        for key in dict.fromkeys(keys):
            monitor = self.read(key)
            if monitor is not None and monitor.data["target_id"] == identifier:
                found.append(monitor)
            elif key.removeprefix("monitor:") in target.data.get("subscribers", []):
                missing.append(key)
        return found, missing

    def _busy(self, target: Document, monitors: list[Document]) -> bool:
        """A check holds the target, or a watcher has not yet had its latest alert."""
        sequence = target.data.get("sequence", 0)
        return target.data.get("lease_until", 0) > self.now or any(
            receives_alerts(self.store, monitor) and monitor.data.get("last_sequence", 0) < sequence
            for monitor in monitors
        )

    def _planned(
        self, change: Change, old: str, new: str, writes: list[Document], reserve: bool = False
    ) -> _Plan:
        if len(writes) > _MOST_WRITES:
            return _Plan(Change(old, "too_large", new, monitors=change.monitors))
        before = {doc.key: self.read(doc.key) for doc in writes}
        for doc in writes:
            self.projected[doc.key] = doc.update(doc.data, revision=doc.revision + 1)
        return _Plan(change, old, new, writes, before, reserve=reserve)

    def plan(self, listed: Document) -> _Plan | None:
        current = self.read(listed.key)
        if current is None or current.partition != listed.partition:
            return None  # Already moved by an earlier plan.
        spec = current.data["spec"]
        old = spec["id"]
        try:
            fresh = import_link(spec["url"], allow_search=spec.get("kind") == "search")
        except LinkRefused as refusal:
            return self._block(current, refusal.check)
        if fresh == spec:
            return _Plan(Change(old, "unchanged"))
        monitors, missing = self._monitors(current)
        if missing:
            return _Plan(Change(old, "missing_monitor", fresh["id"], monitors=len(monitors)))
        if self._busy(current, monitors):
            return _Plan(Change(old, "busy", fresh["id"]))
        if fresh["id"] == old:
            writes = [current.update({**current.data, "spec": fresh})]
            return self._planned(Change(old, "rewritten", old), old, old, writes)
        return self._move(current, fresh, monitors)

    def _block(self, current: Document, check: str) -> _Plan:
        """A stored link the rules now refuse stops its checks, as an unreadable flight
        does, until someone chooses Retry collection."""
        old = current.data["spec"]["id"]
        if current.partition == BLOCKED and current.data.get("last_error") == UNREADABLE:
            return _Plan(Change(old, "blocked", check=check))
        if current.data.get("lease_until", 0) > self.now:
            return _Plan(Change(old, "busy", check=check))
        data = {
            **current.data,
            "last_error": UNREADABLE,
            "failures": current.data.get("failures", 0) + 1,
            "lease_token": None,
            "lease_until": 0,
        }
        writes = [current.update(data, partition=BLOCKED)]
        return self._planned(Change(old, "blocked", old, check=check), old, old, writes)

    def _move(self, current: Document, spec: dict, monitors: list[Document]) -> _Plan:
        old, new = current.data["spec"]["id"], spec["id"]
        existing = self.read("target:" + new)
        joined: list[Document] = []
        if existing is not None:
            joined, missing = self._monitors(existing)
            if missing:
                return _Plan(Change(old, "missing_monitor", new))
            if self._busy(existing, joined):
                return _Plan(Change(old, "busy", new))
        target = _merged(self.store, current, existing, spec, [*monitors, *joined])
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
        capacity = self.store.get(CAPACITY)
        reserve = capacity is not None and old in capacity.data["targets"]
        plan = self._planned(change, old, new, writes, reserve)
        if plan.change.outcome != "too_large":
            plan.history = history
            self.monitors[new] += [monitor.key for monitor in monitors]
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
    store: Store,
    current: Document,
    existing: Document | None,
    spec: dict,
    monitors: list[Document],
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
        data["failures"] = blocked.data.get("failures", 0)
        data["last_error"] = blocked.data.get("last_error")
    # Where the merged target lives follows from both: departed, unreadable, watched or not.
    if any(doc.partition == EXPIRED for doc in both):
        partition = EXPIRED
    elif blocked:
        partition = BLOCKED
    elif any(receives_alerts(store, monitor) for monitor in monitors):
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


def _swap(store: Store, old: str, new: str) -> list[Document]:
    """The capacity record with ``old``'s reservation moved to ``new``, as it is now."""
    capacity = store.get(CAPACITY)
    if capacity is None or old not in capacity.data["targets"]:
        return []
    reserved = [identifier for identifier in capacity.data["targets"] if identifier != old]
    if new not in reserved:
        reserved.append(new)
    return [capacity.update({**capacity.data, "targets": reserved})]


def _private_file(path: Path) -> int:
    """A new file only its owner can read, in a directory only its owner can open."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise NotReady(f"Keep the file in a directory only you can open (chmod 700 {path.parent})")
    try:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise NotReady(f"{path} exists: each run keeps its own file") from None


def apply(
    store: Store, plans: list[_Plan], before: Path, emit: Callable[[Change], None]
) -> list[Change]:
    """Save what each plan will change, then carry the plans out one target at a time."""
    _require_paused(store)
    with os.fdopen(_private_file(before), "w") as saved:

        def note(line: dict) -> None:
            saved.write(json.dumps(line) + "\n")
            saved.flush()

        for plan in plans:
            for doc in plan.writes:
                after = doc.revision + 1
                note(
                    {
                        "target": plan.old,
                        "key": doc.key,
                        "before": _snapshot(plan.before[doc.key]),
                        "after": after,
                    }
                )
            for doc in plan.history:
                note(
                    {
                        "target": plan.old,
                        "key": doc.key,
                        "before": _snapshot(doc),
                        "after": doc.revision + 1,
                    }
                )
            if plan.reserve:
                note({"target": plan.old, "capacity": {"from": plan.old, "to": plan.new}})
        changes = []
        for plan in plans:
            change = plan.change
            if plan.writes or plan.history:
                note({"target": plan.old, "attempted": True})
                try:
                    if plan.writes:
                        reservation = _swap(store, plan.old, plan.new) if plan.reserve else []
                        store.commit([*plan.writes, *reservation])
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
                except Exception as error:  # noqa: BLE001 - one target's failure is reported, the run goes on
                    change = Change(plan.old, "failed", plan.new, error=describe_failure(error))
            changes.append(change)
            emit(change)
    return changes


class _Removable(Store, Protocol):
    def remove(self, documents: list[Document]) -> None: ...


def _read_saved(path: Path) -> list[dict]:
    """A run's saved file, if it is the operator's own and holds only what runs write."""
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise NotReady(f"{path} must be your own file with mode 0600")
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for line in lines:
        if "key" in line and not line["key"].startswith(_WRITTEN):
            raise NotReady(f"{path} names a document a run never writes")
    return lines


def restore(store: _Removable, before: Path) -> tuple[int, list[str]]:
    """Undo each attempted target whose documents are still as the run left them.

    Returns how many targets were undone and the ones left alone because something
    changed them after the run.
    """
    _require_paused(store)
    lines = _read_saved(before)
    attempted = [line["target"] for line in lines if line.get("attempted")]
    restored, skipped = 0, []
    # A document this restore already put back (a merge undone before the move it
    # joined) is as the earlier target left it, at the revision the put gave it.
    settled: dict[str, int] = {}
    for target in reversed(list(dict.fromkeys(attempted))):
        documents = [line for line in lines if line.get("target") == target and "key" in line]
        capacity = next(
            (
                line["capacity"]
                for line in lines
                if line.get("target") == target and "capacity" in line
            ),
            None,
        )
        puts, removals, changed = [], [], []
        for line in documents:
            current, prior = store.get(line["key"]), line["before"]
            left = {line["after"], settled.get(line["key"])}
            if prior is None:
                if current is None:
                    continue  # Already removed.
                if current.revision in left:
                    removals.append(current)
                else:
                    changed.append(line["key"])
            elif current is not None and current.revision in left:
                puts.append(
                    current.update(
                        prior["data"],
                        **{name: prior[name] for name in ("partition", "due", "expires_at")},
                    )
                )
            elif current is None or (current.partition, current.data) != (
                prior["partition"],
                prior["data"],
            ):
                changed.append(line["key"])
        if changed:
            skipped.append(target)
            continue
        for start in range(0, len(puts), 100):
            store.commit(puts[start : start + 100])
        settled.update({doc.key: doc.revision + 1 for doc in puts})
        for start in range(0, len(removals), 100):
            store.remove(removals[start : start + 100])
        if capacity:
            # The reservation moves back on the record as it is now, keeping later ones.
            created = any(line["before"] is None for line in documents)
            reserved = store.get(CAPACITY)
            if reserved is not None and capacity["to"] in reserved.data["targets"]:
                targets = list(reserved.data["targets"])
                if capacity["from"] not in targets:
                    if created:  # A move: the old reservation takes the new one's place.
                        targets[targets.index(capacity["to"])] = capacity["from"]
                    else:  # A merge: the reservation it joined stays.
                        targets.append(capacity["from"])
                elif created:
                    targets.remove(capacity["to"])
                store.commit([reserved.update({**reserved.data, "targets": targets})])
        restored += 1
    return restored, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--table", help="DynamoDB table")
    where.add_argument("--database", help="SQLite database file")
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--apply",
        metavar="FILE",
        type=Path,
        help="Write the changes, saving what they replace to this new file",
    )
    action.add_argument(
        "--restore", metavar="FILE", type=Path, help="Undo the run that saved this file"
    )
    args = parser.parse_args(argv)
    if args.database and not Path(args.database).is_file():
        parser.error(f"no database at {args.database}")
    store = DynamoStore(args.table) if args.table else SQLiteStore(args.database)

    def emit(change: Change) -> None:
        print(json.dumps(asdict(change)), flush=True)

    try:
        if args.restore:
            restored, skipped = restore(store, args.restore)
            print(json.dumps({"restored": restored, "skipped": skipped}), flush=True)
            return 1 if skipped else 0
        plans = plan_changes(store)
        if args.apply:
            changes = apply(store, plans, args.apply, emit)
        else:
            changes = [plan.change for plan in plans]
            for change in changes:
                emit(change)
    except NotReady as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.outcome] = counts.get(change.outcome, 0) + 1
    print(json.dumps({"applied": bool(args.apply), "outcomes": counts}), file=sys.stderr)
    return 1 if PROBLEMS & counts.keys() else 0


if __name__ == "__main__":
    raise SystemExit(main())
