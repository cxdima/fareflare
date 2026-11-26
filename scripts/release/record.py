"""Write the release record, .fareflare/release-<short sha>/release.json, after the checks.

    .venv/bin/python scripts/release/record.py --change "what the release changes" \\
        --verified "what was checked before it went out"

Everything else is read from the release folder: the time it was applied, the tag,
the images production now runs and the ones it ran before, the plan, the website
upload, and the last lines of the smoke and watch logs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from production import ROOT, TFVARS, release_dir


def last(path: Path, prefix: str = "") -> str | None:
    """The last line of a release log that starts with ``prefix``, if the log exists."""
    if not path.exists():
        return None
    lines = [line for line in path.read_text().splitlines() if line.startswith(prefix)]
    return lines[-1].strip() if lines else None


parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
parser.add_argument("--change", required=True, help="what the release changes, in a sentence")
parser.add_argument("--verified", required=True, help="what was checked before the release")
args = parser.parse_args()
sha = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
release = release_dir(sha)
before = json.loads((release / "production.auto.tfvars.before.json").read_text())
after = json.loads(TFVARS.read_text())
rollback = (
    "copy production.auto.tfvars.before.json from this folder to "
    "infra/production.auto.tfvars.json, then terraform plan and apply"
)
# Rolling back images does not undo a data migration: a release that moved flights
# undoes that first (docs/OPERATIONS.md, "The saved file").
migration = sorted(path.name for path in (release / "reidentify").glob("apply-*.jsonl"))
if migration:
    rollback = (
        "with checks paused, reidentify --restore each file in reidentify/, newest first ("
        + ", ".join(reversed(migration))
        + "); then "
        + rollback
    )
record = {
    "released_at": last(release / "applied-at.txt"),
    "source": sha,
    "tag": last(release / "tag.txt"),
    "api_image": after["api_image_uri"],
    "worker_image": after["image_uri"],
    "previous_api_image": before["api_image_uri"],
    "previous_worker_image": before["image_uri"],
    "change": args.change,
    "verified_before": args.verified,
    "web": last(release / "publish-web.log"),
    "plan": last(release / "plan.log", "Plan:"),
    "smoke": last(release / "smoke.log", "FAILURES:"),
    "watch": last(release / "watch.log", "FRESH"),
    "migration": migration or None,
    "rollback": rollback,
}
(release / "release.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
