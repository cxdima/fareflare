"""Explicit development product flags and collection-cost limits."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ProductConfig:
    product_name: str = "Fareflare"
    public_url: str = ""
    registration_mode: str = "invite"
    billing_enabled: bool = False
    monitor_limit: int = 3
    min_interval_seconds: int = 900
    global_target_limit: int = 20
    search_enabled: bool = False

    def __post_init__(self) -> None:
        if (not isinstance(self.product_name, str) or not 1 <= len(self.product_name) <= 64
                or any(ord(c) < 32 for c in self.product_name)):
            raise ValueError("Product name must contain 1–64 printable characters")
        if self.registration_mode not in ("invite", "open"):
            raise ValueError("Registration mode must be invite or open")
        if type(self.billing_enabled) is not bool or self.billing_enabled:
            raise ValueError("Billing is unavailable; keep GFPT_NEXT_BILLING_ENABLED=false")
        if type(self.search_enabled) is not bool:
            raise ValueError("search_enabled must be a boolean")
        for name, value, low, high in (
            ("monitor_limit", self.monitor_limit, 1, 100),
            ("min_interval_seconds", self.min_interval_seconds, 300, 86400),
            ("global_target_limit", self.global_target_limit, 1, 1000),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Invalid {name}")
        if self.public_url:
            parsed = urlsplit(self.public_url)
            if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path not in ("", "/") or parsed.scheme not in ("http", "https")
                    or parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1")):
                raise ValueError("Public URL must be an HTTPS origin, or local HTTP origin")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ProductConfig:
        values = os.environ if environ is None else environ
        billing = values.get("GFPT_NEXT_BILLING_ENABLED", "false").lower()
        search = values.get("GFPT_NEXT_SEARCH_ENABLED", "false").lower()
        if billing not in ("true", "false"):
            raise ValueError("GFPT_NEXT_BILLING_ENABLED must be true or false")
        if search not in ("true", "false"):
            raise ValueError("GFPT_NEXT_SEARCH_ENABLED must be true or false")
        try:
            return cls(
                product_name=values.get("GFPT_NEXT_PRODUCT_NAME", "Fareflare"),
                public_url=values.get("GFPT_NEXT_PUBLIC_URL", "").rstrip("/"),
                registration_mode=values.get("GFPT_NEXT_REGISTRATION_MODE", "invite"),
                billing_enabled=billing == "true",
                monitor_limit=int(values.get("GFPT_NEXT_MONITOR_LIMIT", "3")),
                min_interval_seconds=int(values.get("GFPT_NEXT_MIN_INTERVAL", "900")),
                global_target_limit=int(values.get("GFPT_NEXT_GLOBAL_TARGET_LIMIT", "20")),
                search_enabled=search == "true",
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid development product configuration") from exc

    def public(self) -> dict:
        return {"product_name": self.product_name, "billing_enabled": self.billing_enabled,
                "registration_mode": self.registration_mode,
                "capabilities": {"route_searches": self.search_enabled},
                "limits": {"monitors": self.monitor_limit, "min_interval_seconds": self.min_interval_seconds,
                           "global_targets": self.global_target_limit}}
