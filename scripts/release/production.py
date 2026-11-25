"""What the release scripts share: the deployment's names, read from Terraform, and the
release folder. Nothing here writes to AWS.

Run the scripts from the repository root with ``PYTHONPATH=src .venv/bin/python``.
"""

from __future__ import annotations

import functools
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TFVARS = ROOT / "infra/production.auto.tfvars.json"
# Every partition a checked itinerary can be in: collecting, idle, blocked, expired.
TARGET_PARTITIONS = ("targets", "targets_idle", "targets_blocked", "targets_expired")


def release_dir(sha: str) -> Path:
    """Where one release keeps its logs, plan and record (git-ignored)."""
    return ROOT / ".fareflare" / f"release-{sha}"


@functools.cache
def output(name: str) -> str:
    """One Terraform output of the deployed stack, such as ``table_name``."""
    return subprocess.run(
        ["terraform", f"-chdir={ROOT / 'infra'}", "output", "-raw", name],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@functools.cache
def store() -> Any:
    """Production's table: ``FAREFLARE_TABLE`` (as the application reads it) or Terraform's."""
    from fareflare.store import DynamoStore

    return DynamoStore(os.environ.get("FAREFLARE_TABLE") or output("table_name"))


def targets(partitions: tuple[str, ...] = TARGET_PARTITIONS) -> Iterator[Any]:
    """Every stored itinerary document in the given partitions."""
    production = store()
    for partition in partitions:
        cursor = None
        while True:
            page = production.page(partition, limit=1000, cursor=cursor)
            for item in page.items:
                document = production.get(item.key)
                if document is not None:
                    yield document
            cursor = page.cursor
            if cursor is None:
                break


def prices_since(target_key: str, since: int) -> list[int]:
    """When each price of an itinerary was observed after ``since``, oldest first."""
    page = store().page("history:" + target_key.removeprefix("target:"), limit=200, reverse=True)
    return sorted(item.due for item in page.items if item.due and item.due > since)
