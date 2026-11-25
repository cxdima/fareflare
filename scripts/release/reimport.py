"""Read-only: does every stored itinerary import to the identical target with this source?

Run it before releasing any change to how links are read (``links.py``,
``search_links.py``). A target that imports differently gets another id, and its
checks fail with ``itinerary_changed`` until it is migrated. Exits 1 if any differs.

    PYTHONPATH=src .venv/bin/python scripts/release/reimport.py
"""

from __future__ import annotations

import sys

from production import targets

from fareflare.links import import_link

same, changed = 0, []
for document in targets():
    spec = document.data["spec"]
    try:
        identical = import_link(spec["url"], allow_search=spec.get("kind") == "search") == spec
    except ValueError as exc:  # InvalidLink: this source refuses a stored link outright.
        identical = False
        print(f"{document.key[7:15]} {document.partition} refused: {type(exc).__name__}: {exc}")
    if identical:
        same += 1
    else:
        changed.append(document.key[7:15])
print(f"identical={same} changed={len(changed)} {' '.join(changed)}".rstrip())
sys.exit(1 if changed else 0)
