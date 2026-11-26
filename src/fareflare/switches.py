"""The service-wide switches an admin can flip: one record, read one way everywhere."""

from __future__ import annotations

from fareflare.store import Store

KEY = "configuration:admin"
NAMES = ("registration_paused", "collection_paused")


def switches(store: Store) -> dict[str, bool]:
    """Every switch, off unless an admin turned it on."""
    document = store.get(KEY)
    data = document.data if document else {}
    return {name: bool(data.get(name)) for name in NAMES}
