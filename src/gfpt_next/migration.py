"""Reviewable, idempotent migration from an explicitly verified legacy export.

No implicit dollars-to-cents assumption, no account cookies, no legacy writes.
Imported baselines are alert state, never presented as fresh observations.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict

from gfpt_next.contracts import Money
from gfpt_next.domain import AlertPolicy
from gfpt_next.links import import_link
from gfpt_next.service import MonitoringService


def plan_migration(export: dict) -> dict:
    if export.get("schema_version") != 1 or export.get("currency_units_verified") is not True:
        raise ValueError("Verify the legacy currency and units before migration")
    currency, unit = export.get("currency"), export.get("unit")
    if not isinstance(currency, str):
        raise ValueError("Specify the verified currency")
    if unit not in ("major", "minor"):
        raise ValueError("Specify major or minor legacy units")
    multiplier = 10 ** Money(1, currency).exponent if unit == "major" else 1
    owners = export.get("owners", {})  # Explicit legacy-chat-ID -> tenant map.
    if not owners or not isinstance(owners, dict) or len(set(owners.values())) != len(owners):
        raise ValueError("Provide a unique tenant for each family member")
    monitors, preferences = [], {}
    for chat_id, tenant in owners.items():
        MonitoringService._tenant(tenant)
        prefs = export.get("preferences", {}).get(chat_id, {})
        threshold = prefs.get("threshold", 0)
        if type(threshold) is not int or threshold < 0:
            raise ValueError("Invalid legacy drop threshold")
        policy = AlertPolicy(min_drop_minor=threshold * multiplier,
                             notify_rebounds=prefs.get("rise_alerts", False))
        routes = prefs.get("muted_routes", [])
        if (type(prefs.get("muted", False)) is not bool or not isinstance(routes, list)
                or len(routes) > 100 or any(not isinstance(route, str) or
                    not re.fullmatch(r"[A-Z]{3}-[A-Z]{3}", route) for route in routes)):
            raise ValueError("Invalid legacy mute preferences")
        preferences[tenant] = {"muted": bool(prefs.get("muted", False)),
                               "muted_routes": prefs.get("muted_routes", [])}
        for legacy_id, entry in export.get("manifest", {}).items():
            if legacy_id.startswith("__"):
                continue
            target = import_link(entry["search_url"])
            if target["currency"] != currency:
                raise ValueError("Legacy currency does not match the selected itinerary")
            price, low = entry.get("price"), entry.get("low_price")
            if (type(price) is not int or type(low) is not int or not 0 < low <= price
                    or price * multiplier > 100_000_000):
                raise ValueError("Each migrated flight needs a verified current price and low watermark")
            identifier = hashlib.sha256(f"{tenant}:{legacy_id}".encode()).hexdigest()
            monitors.append({"tenant": tenant, "legacy_id": legacy_id, "url": target["url"],
                             "target_id": target["id"], "request_key": "migration:" + identifier,
                             "policy": asdict(policy), "baseline": {
                                 "price_minor": price * multiplier, "low_minor": low * multiplier,
                                 "last_alert_minor": low * multiplier}})
    if not monitors:
        raise ValueError("The export contains no selected flights")
    return {"schema_version": 1, "monitors": monitors, "preferences": preferences,
            "initial_status": "paused", "legacy_modified": False}


def apply_migration(service: MonitoringService, export: dict) -> list[dict]:
    plan = plan_migration(export)  # Validate the entire input before any writes.
    for item in plan["monitors"]:
        target = import_link(item["url"])
        if service._departure_day_elapsed(target):
            raise ValueError("A migrated itinerary has already departed")
        if service.capability_check:
            service.capability_check(target)
    results = []
    for item in plan["monitors"]:
        results.append(service.create_monitor(item["tenant"], item["url"], item["request_key"],
            AlertPolicy(**item["policy"]), baseline=item["baseline"], initially_paused=True))
    for tenant, preferences in plan["preferences"].items():
        if service.preferences(tenant) != preferences:
            service.set_preferences(tenant, **preferences)
    return results
