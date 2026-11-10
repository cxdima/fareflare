"""Fail when a pinned requirement and its hash-locked file disagree.

Dependency bots edit ``requirements*.txt`` but cannot regenerate the uv lock
files that are actually installed, so a bump could otherwise look tested while
changing nothing. Run ``make lock`` after editing a pin.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("requirements.txt", "requirements.lock"),
    ("requirements-dev.txt", "requirements-dev.lock"),
)
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)")


def _name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def pins(path: Path) -> dict[str, str]:
    """Exact pins declared in a requirements file, following ``-r`` includes."""
    found: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("-r "):
            found.update(pins(path.parent / line[3:].strip()))
        elif match := _PIN.match(line):
            found[_name(match[1])] = match[2]
    return found


def problems(root: Path = ROOT) -> list[str]:
    issues = []
    for source, lock in PAIRS:
        declared, locked = pins(root / source), pins(root / lock)
        for name, version in sorted(declared.items()):
            if locked.get(name) != version:
                issues.append(
                    f"{source} pins {name}=={version}, but {lock} has "
                    + (f"{name}=={locked[name]}" if name in locked else "no such package")
                )
    return issues


def main() -> int:
    issues = problems()
    for issue in issues:
        print(issue, file=sys.stderr)
    if issues:
        print("Run `make lock` to regenerate the lock files.", file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
