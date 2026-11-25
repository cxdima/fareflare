"""Read-only picture of production's price checks: one line per itinerary."""

from __future__ import annotations

import time

from production import targets

now = int(time.time())
for document in targets():
    data = document.data
    lease = data.get("lease_until", 0) - now
    print(
        f"{document.partition:15} {document.key[7:15]} due_in={(document.due or 0) - now:>6}s "
        f"interval={data.get('interval_seconds')} failures={data.get('failures', 0)} "
        f"error={data.get('last_error')} subscribers={len(data.get('subscribers', []))} "
        f"lease={'held ' + str(lease) + 's' if lease > 0 else 'free'}"
    )
