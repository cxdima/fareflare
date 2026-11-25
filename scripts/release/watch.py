"""Follow production after a release until every collecting itinerary has new prices.

Read-only. Prices come from each itinerary's history, so a watch started late still
sees every price since the release. Prints each price and each failed check as it
appears, then the gaps between prices. Exits 1 if an itinerary had too few new prices
before the time limit.

    PYTHONPATH=src .venv/bin/python scripts/release/watch.py --since 2026-11-25T23:26:37Z
    # A change to check timing: wait for three prices each and compare the gaps.
    PYTHONPATH=src .venv/bin/python scripts/release/watch.py --since ... --prices 3
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from itertools import pairwise

from production import prices_since, targets

from fareflare.contracts import CHECK_INTERVAL_SECONDS, RETRY_SECONDS


def clock(seconds: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(seconds))


parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
parser.add_argument(
    "--since", required=True, help="UTC time the release was applied (applied-at.txt)"
)
parser.add_argument("--prices", type=int, default=1, help="new prices to wait for per itinerary")
parser.add_argument("--minutes", type=int, default=25, help="give up after this many minutes")
args = parser.parse_args()
since = int(datetime.fromisoformat(args.since.replace("Z", "+00:00")).timestamp())
deadline = time.time() + args.minutes * 60
prices: dict[str, list[int]] = {}
failures: dict[str, int] = {}
while True:
    collecting = list(targets(("targets",)))
    for document in collecting:
        name = document.key[7:15]
        for observed in prices_since(document.key, since):
            if observed not in prices.setdefault(name, []):
                print(f"{clock(observed)} {name} price recorded", flush=True)
                prices[name].append(observed)
        failed = document.data.get("failures", 0)
        if failed and failed != failures.get(name, 0):
            error = document.data.get("last_error")
            print(
                f"{clock(time.time())} {name} check failed ({error}), {failed} in a row", flush=True
            )
        failures[name] = failed
    enough = [len(prices.get(document.key[7:15], [])) >= args.prices for document in collecting]
    if all(enough) or time.time() > deadline:
        break
    time.sleep(30)

print(f"--- since {clock(since)}; interval {CHECK_INTERVAL_SECONDS}s, retry {RETRY_SECONDS}s")
for document in collecting:
    name = document.key[7:15]
    seen = sorted(prices.get(name, []))
    print(
        f"{name} new_prices={len(seen)} first_after={seen[0] - since if seen else None}s "
        f"gaps={[later - earlier for earlier, later in pairwise(seen)]} "
        f"failures={failures[name]} error={document.data.get('last_error')}"
    )
print(f"FRESH {sum(enough)}/{len(enough)}")
sys.exit(0 if all(enough) else 1)
