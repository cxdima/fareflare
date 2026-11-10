"""Deterministic alert rules. Monetary amounts are integer minor units."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AlertPolicy:
    kind: Literal["new_low", "below_price"] = "new_low"
    min_drop_minor: int = 0
    threshold_minor: int | None = None
    notify_rebounds: bool = False

    def __post_init__(self):
        if type(self.notify_rebounds) is not bool:
            raise ValueError("Rebound preference must be a boolean")
        if self.kind not in ("new_low", "below_price"):
            raise ValueError("Unsupported alert policy")
        if type(self.min_drop_minor) is not int or self.min_drop_minor < 0:
            raise ValueError("Minimum drop must be a nonnegative integer")
        if self.kind == "below_price" and (
            type(self.threshold_minor) is not int or self.threshold_minor <= 0
        ):
            raise ValueError("A positive threshold is required")


def evaluate(policy: AlertPolicy, state: dict, amount: int) -> tuple[dict, str | None]:
    """Advance observed state; an alert baseline advances only on a queued event.

    Small successive new lows accumulate against the last queued alert. A durable
    outbox is responsible for delivery; a provider failure never calls this rule.
    """
    if type(amount) is not int or amount <= 0:
        raise ValueError("Price must be a positive integer in minor units")
    low = state.get("low_minor")
    previous = state.get("price_minor")
    baseline = state.get("last_alert_minor", low)
    reason = None
    if policy.kind == "new_low":
        if low is None:
            reason = "tracking_started"
        elif amount < low and baseline is not None and baseline - amount >= policy.min_drop_minor:
            reason = "new_low"
    elif (
        policy.threshold_minor is not None
        and amount <= policy.threshold_minor
        and (previous is None or previous > policy.threshold_minor)
    ):
        reason = "below_price"
    updated = {
        **state,
        "price_minor": amount,
        "low_minor": min(low, amount) if low is not None else amount,
    }
    if low is None or amount < low:
        updated["rebounded"] = False
    if reason:
        updated["last_alert_minor"] = amount
    elif (
        policy.notify_rebounds
        and low is not None
        and previous == low
        and amount > low
        and not state.get("rebounded", False)
    ):
        reason = "rebound"
        updated["rebounded"] = True
    return updated, reason
