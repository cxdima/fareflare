"""Bring stored targets in line with how links are read now.

A target's identity is derived from its link (``links.import_link``). When those
rules change, a stored target can hold an identity, or an address, that its link no
longer imports to, and the collector would then refuse it as a changed itinerary.
This rewrites each such target as its link imports today. A target whose identity
changes moves to its new key with everything that names it: its watchers' monitors,
its price history and its place in the collection capacity. When another stored
target already has that identity, the two become one, as they would had both links
been added today.

It is safe to run again: a finished target is left alone, and a run that stopped
part way through moving a price history finishes it. A target that a check holds,
or that has an alert waiting, is reported as busy and moved by a later run.
Nothing is written unless asked: ``python -m fareflare.reidentify --table NAME``
shows the plan and ``--apply`` carries it out.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from fareflare.links import import_link
from fareflare.refusals import LinkRefused
from fareflare.service import COLLECTING, TARGET_PARTITIONS
from fareflare.store import Document, DynamoStore, SQLiteStore, Store

# A moved target's old key keeps only where it went, until it expires.
MOVED = "targets_moved"
_MOVED_KEPT = 30 * 86400
# One transaction holds at most 100 documents: the target, its old key, the
# capacity record and its watchers' monitors.
_MOST_WATCHERS = 97


@dataclass(frozen=True)
class Change:
    target: str
    outcome: str  # unchanged, rewritten, moved, merged, busy, too_large or unreadable
    to: str | None = None
    watchers: int = 0
    history: int = 0  # Price observations moved to the new key.


def _documents(store: Store, partition: str) -> list[Document]:
    documents, cursor = [], None
    while True:
        page = store.page(partition, limit=1000, cursor=cursor)
        documents += page.items
        cursor = page.cursor
        if cursor is None:
            return documents


def _move_history(store: Store, old: str, new: str, apply: bool) -> int:
    """Move a price history to the new key, or without ``apply`` count it."""
    listed = _documents(store, "history:" + old)
    if not apply:
        return len(listed)
    moved = 0
    for start in range(0, len(listed), 100):
        # Read each again: the partition index can lag behind the documents.
        current = [store.get(document.key) for document in listed[start : start + 100]]
        writes = [
            document.update({**document.data, "target_id": new}, partition="history:" + new)
            for document in current
            if document is not None and document.partition == "history:" + old
        ]
        if writes:
            store.commit(writes)
            moved += len(writes)
    return moved


def _alerting(store: Store) -> set[str]:
    """Targets with an alert that has not been delivered yet."""
    return {event.data["observation"]["target_id"] for event in _documents(store, "events_pending")}


def _merged(current: Document, existing: Document | None, spec: dict) -> Document:
    """The new key's document: this target's state, or the two targets as one."""
    if existing is None:
        data = {**current.data, "spec": spec}
        if current.data.get("latest"):
            data["latest"] = {**current.data["latest"], "target_id": spec["id"]}
        return Document("target:" + spec["id"], current.partition, data, due=current.due)
    subscribers = existing.data.get("subscribers", [])
    collecting = COLLECTING in (current.partition, existing.partition)
    return existing.update(
        {
            **existing.data,
            "subscribers": subscribers
            + [s for s in current.data.get("subscribers", []) if s not in subscribers],
            "interval_seconds": min(
                current.data["interval_seconds"], existing.data["interval_seconds"]
            ),
        },
        partition=COLLECTING if collecting else existing.partition,
        due=min(current.due, existing.due) if collecting else existing.due,
    )


def _move(store: Store, current: Document, spec: dict, now: int, apply: bool) -> Change:
    old, new = current.data["spec"]["id"], spec["id"]
    existing = store.get("target:" + new)
    monitors = [
        monitor
        for monitor in (store.get("monitor:" + mid) for mid in current.data.get("subscribers", []))
        if monitor is not None
    ]
    if len(monitors) > _MOST_WATCHERS:
        return Change(old, "too_large", new, watchers=len(monitors))
    target = _merged(current, existing, spec)
    if apply:
        writes = [
            target,
            current.update({"moved_to": new}, partition=MOVED, due=0, expires_at=now + _MOVED_KEPT),
        ]
        for monitor in monitors:
            data = {**monitor.data, "target_id": new}
            if existing:
                # Alerts continue from the merged target's sequence, never replaying its past.
                data["last_sequence"] = target.data["sequence"]
            writes.append(monitor.update(data))
        capacity = store.get("capacity:collection")
        if capacity and old in capacity.data["targets"]:
            reserved = [identifier for identifier in capacity.data["targets"] if identifier != old]
            if new not in reserved:
                reserved.append(new)
            writes.append(capacity.update({"targets": reserved}))
        store.commit(writes)
    return Change(
        old,
        "merged" if existing else "moved",
        new,
        watchers=len(monitors),
        history=_move_history(store, old, new, apply),
    )


def _update(
    store: Store, listed: Document, now: int, apply: bool, alerting: set[str]
) -> Change | None:
    # Read it again: the partition index can lag behind the document.
    current = store.get(listed.key)
    if current is None or current.partition != listed.partition:
        return None
    spec = current.data["spec"]
    try:
        fresh = import_link(spec["url"], allow_search=spec.get("kind") == "search")
    except LinkRefused:
        return Change(spec["id"], "unreadable")
    if fresh == spec:
        return Change(spec["id"], "unchanged")
    # A check holds it, or an alert from it is still waiting to be sent.
    if current.data.get("lease_until", 0) > now or spec["id"] in alerting:
        return Change(spec["id"], "busy", fresh["id"])
    if fresh["id"] != spec["id"]:
        return _move(store, current, fresh, now, apply)
    if apply:
        store.commit([current.update({**current.data, "spec": fresh})])
    return Change(spec["id"], "rewritten", fresh["id"])


def reidentify(store: Store, *, apply: bool = False, now: int | None = None) -> list[Change]:
    """Plan, or carry out, the changes that bring every stored target up to date."""
    now = int(time.time()) if now is None else now
    changes = []
    # A run that stopped after moving a target finishes moving its history.
    for moved in _documents(store, MOVED):
        old, new = moved.key.removeprefix("target:"), moved.data["moved_to"]
        if store.page("history:" + old, limit=1).items:
            changes.append(Change(old, "moved", new, history=_move_history(store, old, new, apply)))
    alerting = _alerting(store)
    for partition in TARGET_PARTITIONS:
        for listed in _documents(store, partition):
            change = _update(store, listed, now, apply, alerting)
            if change is not None:
                changes.append(change)
    return changes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--table", help="DynamoDB table")
    where.add_argument("--database", help="SQLite database file")
    parser.add_argument("--apply", action="store_true", help="Write the changes")
    args = parser.parse_args(argv)
    if args.database and not Path(args.database).is_file():
        parser.error(f"no database at {args.database}")
    store = DynamoStore(args.table) if args.table else SQLiteStore(args.database)
    changes = reidentify(store, apply=args.apply)
    for change in changes:
        print(json.dumps(asdict(change)))
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.outcome] = counts.get(change.outcome, 0) + 1
    print(json.dumps({"applied": args.apply, "outcomes": counts}), file=sys.stderr)


if __name__ == "__main__":
    main()
