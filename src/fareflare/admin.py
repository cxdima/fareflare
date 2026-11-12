"""The admin panel's view of the whole service, and the actions it may take.

Read access covers every account and watched flight, collection health and the
email budgets. Actions are the ones support and abuse handling need. Every action
is written to an audit log that admins can read and nobody can edit from the
panel. Nothing here grants or removes the admin role: only the command line
(``fareflare.admin_cli``), run with the database's own credentials, can do that.

The panel opens only for an admin who has two-step sign-in or a passkey, in a
session that began with one of them less than twelve hours ago.
"""

from __future__ import annotations

import contextlib
import secrets
import time
from collections import Counter
from collections.abc import Callable

from fareflare.accounts import Accounts
from fareflare.health import status_report
from fareflare.service import MonitoringService, NotFound
from fareflare.store import Conflict, Document, Store

ADMIN_SESSION_SECONDS = 12 * 3600
SCAN_LIMIT = 10_000
WATCHERS_SHOWN = 100
AUDIT_DAYS = 400
DAY = 86400
SWITCHES = ("registration_paused", "collection_paused")
ACTIONS = ("suspend", "reactivate", "sign-out", "reset-two-factor", "temporary-password")
FLIGHT_ACTIONS = {"paused": "pause-flight", "active": "resume-flight", "cancelled": "stop-flight"}

GATE_MESSAGES = {
    "not_admin": "Not found",
    "password": "Choose a new password first.",
    "mfa": "Turn on two-step sign-in or add a passkey to use the admin panel.",
    "reauth": "Sign in again with a passkey or your authenticator code to use the admin panel.",
}


class AdminDenied(PermissionError):
    def __init__(self, reason: str):
        super().__init__(GATE_MESSAGES[reason])
        self.reason = reason


def _name(data: dict) -> str:
    return data.get("email") or data.get("username") or data.get("id", "")


class Admin:
    def __init__(
        self,
        store: Store,
        accounts: Accounts,
        service: MonitoringService,
        clock: Callable[[], float] = time.time,
        *,
        oauth=None,
    ):
        self.store, self.accounts, self.service, self.clock = store, accounts, service, clock
        self.oauth = oauth
        self._sequence = 0

    def _now(self) -> int:
        return int(self.clock())

    # Who may open the panel.

    def gate(self, identity: dict) -> dict:
        """Whether this signed-in person may use the admin panel now, and if not, why."""
        account = self.accounts.account_document(identity["account"]["id"])
        data = account.data if account else {}
        signed_in_at = identity.get("signed_in_at") or 0
        if data.get("role") != "admin" or data.get("status") != "active":
            reason = "not_admin"
        elif data.get("must_change_password"):
            reason = "password"
        elif not ((data.get("totp") or {}).get("enabled") or data.get("passkey_ids")):
            reason = "mfa"
        elif not identity.get("strong") or self._now() - signed_in_at >= ADMIN_SESSION_SECONDS:
            reason = "reauth"
        else:
            reason = None
        return {
            "ready": reason is None,
            "reason": reason,
            "message": GATE_MESSAGES[reason] if reason else None,
            "expires_at": signed_in_at + ADMIN_SESSION_SECONDS if reason is None else None,
        }

    def require(self, identity: dict) -> dict:
        """The admin's account data, or AdminDenied with the reason."""
        gate = self.gate(identity)
        if not gate["ready"]:
            raise AdminDenied(gate["reason"])
        account = self.accounts.account_document(identity["account"]["id"])
        assert account is not None
        return account.data

    # Reading.

    def _scan(self, partition: str, limit: int = SCAN_LIMIT) -> tuple[list[Document], bool]:
        """Up to ``limit`` documents of a partition, and whether more were left."""
        items: list[Document] = []
        cursor = None
        while True:
            page = self.store.page(partition, limit=min(1000, limit - len(items)), cursor=cursor)
            items.extend(page.items)
            cursor = page.cursor
            if not cursor:
                return items, False
            if len(items) >= limit:
                return items, True

    def _tenants(self) -> dict[str, dict]:
        documents, _ = self._scan("tenants")
        return {document.key.removeprefix("tenant:"): document.data for document in documents}

    def _telegram(self, accounts: list[Document]) -> set[str]:
        """Accounts with a live Telegram link (one made in their current sign-in epoch)."""
        epochs = {account.data["id"]: account.data.get("auth_epoch") for account in accounts}
        links, _ = self._scan("telegram-accounts")
        return {
            link.data["tenant"]
            for link in links
            if link.data.get("connected")
            and "tenant" in link.data
            and epochs.get(link.data["tenant"]) == link.data.get("auth_epoch")
        }

    @staticmethod
    def _row(account: Document, tenants: dict[str, dict], telegram: set[str]) -> dict:
        data = account.data
        tenant = data["id"]
        status = data.get("status", "active")
        return {
            "id": tenant,
            "email": (data.get("email") or data.get("username") or None)
            if status != "deleted"
            else None,
            "status": status,
            "admin": data.get("role") == "admin",
            "created_at": data.get("created_at"),
            "last_sign_in_at": data.get("last_login_at"),
            "email_verified": bool(data.get("email_verified")),
            "two_factor": bool((data.get("totp") or {}).get("enabled")),
            "passkeys": len(data.get("passkey_ids", [])),
            "api_keys": len(data.get("key_ids", [])),
            "flights": int((tenants.get(tenant) or {}).get("monitors", 0)),
            "telegram": tenant in telegram,
            "must_change_password": bool(data.get("must_change_password")),
            "suspended_at": data.get("suspended_at"),
        }

    def _rows(self) -> tuple[list[dict], bool]:
        accounts, truncated = self._scan("accounts")
        tenants = self._tenants()
        telegram = self._telegram(accounts)
        return [self._row(account, tenants, telegram) for account in accounts], truncated

    def users(
        self,
        query: str = "",
        status: str = "all",
        sort: str = "newest",
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        if status not in ("all", "active", "suspended", "deleted", "admins"):
            raise ValueError("Unknown status filter")
        if sort not in ("newest", "oldest", "last_sign_in", "flights"):
            raise ValueError("Unknown sort order")
        rows, truncated = self._rows()
        if status == "all":
            rows = [row for row in rows if row["status"] != "deleted"]
        elif status == "admins":
            rows = [row for row in rows if row["admin"] and row["status"] != "deleted"]
        else:
            rows = [row for row in rows if row["status"] == status]
        needle = query.strip().lower()
        if needle:
            rows = [row for row in rows if needle in (row["email"] or "") or needle in row["id"]]
        keys: dict[str, Callable[[dict], tuple]] = {
            "newest": lambda row: (-(row["created_at"] or 0), row["id"]),
            "oldest": lambda row: (row["created_at"] or 0, row["id"]),
            "last_sign_in": lambda row: (-(row["last_sign_in_at"] or 0), row["id"]),
            "flights": lambda row: (-row["flights"], -(row["created_at"] or 0), row["id"]),
        }
        rows.sort(key=keys[sort])
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "truncated": truncated,
        }

    def overview(self) -> dict:
        now = self._now()
        rows, truncated = self._rows()
        live = [row for row in rows if row["status"] != "deleted"]

        def since(field: str, seconds: int) -> int:
            return sum(1 for row in live if (row[field] or 0) >= now - seconds)

        today = now - now % DAY
        signups = {today - index * DAY: 0 for index in range(29, -1, -1)}
        for row in rows:
            created = row["created_at"] or 0
            day = created - created % DAY
            if day in signups:
                signups[day] += 1
        return {
            "generated_at": now,
            "users": {
                "total": len(live),
                "active": sum(1 for row in live if row["status"] == "active"),
                "suspended": sum(1 for row in live if row["status"] == "suspended"),
                "deleted": len(rows) - len(live),
                "admins": sum(1 for row in live if row["admin"]),
                "new_day": since("created_at", DAY),
                "new_week": since("created_at", 7 * DAY),
                "new_month": since("created_at", 30 * DAY),
                "signed_in_week": since("last_sign_in_at", 7 * DAY),
                "signed_in_month": since("last_sign_in_at", 30 * DAY),
                "email_verified": sum(1 for row in live if row["email_verified"]),
                "two_factor": sum(1 for row in live if row["two_factor"]),
                "passkeys": sum(1 for row in live if row["passkeys"]),
                "telegram": sum(1 for row in live if row["telegram"]),
                "api_keys": sum(1 for row in live if row["api_keys"]),
                "truncated": truncated,
            },
            "signups": [{"day": day, "count": count} for day, count in signups.items()],
            "flights": self._flight_summary(),
            "collection": status_report(self.store, now),
            "email": self.accounts.email_usage(),
            "switches": self.accounts.switches(),
            "config": self._config(),
        }

    def _config(self) -> dict:
        config = self.accounts.config
        return {
            "registration_mode": config.registration_mode,
            "email_enabled": self.accounts.email_enabled,
            "breach_check": self.accounts.breached is not None,
            "monitor_limit": self.service.monitor_limit,
            "global_target_limit": self.service.global_target_limit,
            "min_interval_seconds": self.service.min_interval_seconds,
        }

    def _capacity(self) -> dict:
        capacity = self.store.get("capacity:collection")
        return {
            "used": len(capacity.data["targets"]) if capacity else 0,
            "limit": self.service.global_target_limit,
        }

    _STATES = (("targets", "collecting"), ("targets_blocked", "blocked"), ("targets_idle", "idle"))

    def _flight_summary(self) -> dict:
        targets: dict[str, int] = {}
        statuses: Counter[str] = Counter()
        fetched = 0
        for partition, state in self._STATES:
            documents, _ = self._scan(partition, 2000)
            targets[state] = len(documents)
            for document in documents:
                for identifier in document.data.get("subscribers", []):
                    if fetched >= 2000:
                        break
                    fetched += 1
                    monitor = self.store.get("monitor:" + identifier)
                    if monitor:
                        statuses[monitor.data["status"]] += 1
        return {
            "watched": sum(statuses.values()),
            "by_status": dict(statuses),
            "targets": targets,
            "capacity": self._capacity(),
        }

    def flights(self) -> dict:
        """Every flight being collected, with who watches it."""
        accounts, _ = self._scan("accounts")
        names = {account.data["id"]: _name(account.data) for account in accounts}
        items = []
        for partition, state in self._STATES:
            documents, _ = self._scan(partition, 2000)
            for document in documents:
                data = document.data
                subscribers = data.get("subscribers", [])
                watchers = []
                for identifier in subscribers[:WATCHERS_SHOWN]:
                    monitor = self.store.get("monitor:" + identifier)
                    if not monitor:
                        continue
                    watchers.append(
                        {
                            "monitor_id": identifier,
                            "account_id": monitor.data["tenant"],
                            "email": names.get(monitor.data["tenant"]),
                            "status": monitor.data["status"],
                            "interval_seconds": monitor.data["interval_seconds"],
                            "created_at": monitor.data.get("created_at"),
                        }
                    )
                items.append(
                    {
                        "id": data["spec"]["id"],
                        "state": state,
                        "target": data["spec"],
                        "latest": data.get("latest"),
                        "failures": data.get("failures", 0),
                        "last_error": data.get("last_error"),
                        "next_check_at": document.due if state == "collecting" else None,
                        "interval_seconds": data.get("interval_seconds"),
                        "watcher_count": len(subscribers),
                        "watchers": watchers,
                    }
                )
        order = {"collecting": 0, "blocked": 1, "idle": 2}
        items.sort(key=lambda item: (order[item["state"]], item["next_check_at"] or 0))
        expired, _ = self._scan("targets_expired")
        return {"items": items, "capacity": self._capacity(), "expired": len(expired)}

    def user(self, tenant: str) -> dict:
        account = self.accounts.account_document(tenant)
        if account is None:
            raise NotFound("Account not found")
        data = account.data
        customer = self.store.get("tenant:" + tenant)
        link = self.store.get("telegram-account:" + tenant)
        telegram = bool(
            link
            and link.data.get("connected")
            and link.data.get("auth_epoch") == data.get("auth_epoch")
        )
        row = self._row(
            account, {tenant: customer.data if customer else {}}, {tenant} if telegram else set()
        )
        flights = []
        for index in self.store.page("monitors:" + tenant, limit=1000).items:
            with contextlib.suppress(NotFound, AssertionError, KeyError):
                flights.append(self.service.get_monitor(tenant, index.data["id"]))
        flights.sort(key=lambda flight: -(flight.get("created_at") or 0))
        alerts = [
            {
                "id": alert["id"],
                "monitor_id": alert["monitor_id"],
                "reason": alert.get("reason"),
                "status": alert.get("status"),
                "attempts": alert.get("attempts", 0),
                "observed_at": (alert.get("observation") or {}).get("observed_at"),
                "amount_minor": (alert.get("observation") or {}).get("amount_minor"),
                "currency": (alert.get("observation") or {}).get("currency"),
            }
            for alert in self.service.alerts_page(tenant, limit=20)["items"]
        ]
        keys = []
        for identifier in data.get("key_ids", []):
            key = self.store.get("credential:" + identifier)
            if key and key.data.get("tenant") == tenant:
                keys.append(
                    {
                        "name": key.data.get("name", "API key"),
                        "created_at": key.data.get("created_at"),
                        "expires_at": key.data.get("expires_at"),
                        "revoked": bool(key.data.get("revoked")),
                    }
                )
        passkeys = [
            {key: passkey[key] for key in ("name", "provider", "created_at", "last_used_at")}
            for passkey in self.accounts.passkeys.list(account)
        ]
        applications: list[dict] = []
        if self.oauth is not None and data.get("status") == "active":
            with contextlib.suppress(Exception):
                applications = [
                    {key: grant[key] for key in ("client_name", "created_at", "revoked")}
                    for grant in self.oauth.list_grants(tenant, limit=50)["items"]
                ]
        webhooks: list[dict] = []
        with contextlib.suppress(Exception):
            # The host is enough to recognise an endpoint; a path can carry a secret.
            webhooks = [
                {
                    "host": hook["url"].split("/")[2] if "://" in hook["url"] else "",
                    "status": hook["status"],
                    "created_at": hook.get("created_at"),
                }
                for hook in self.service.webhooks.list(tenant, limit=50)["items"]
            ]
        preferences = (customer.data if customer else {}).get("preferences") or {}
        return {
            "account": {
                **row,
                "sessions": len(data.get("session_ids", [])),
                "suspended_reason": data.get("suspended_reason"),
                "temporary_password_expires_at": (data.get("temporary_password") or {}).get(
                    "expires_at"
                ),
                "alerts_muted": bool(preferences.get("muted")),
            },
            "flights": flights,
            "alerts": alerts,
            "api_keys": keys,
            "passkeys": passkeys,
            "applications": applications,
            "webhooks": webhooks,
            "audit": self.audit(target=tenant, limit=25)["items"],
        }

    def audit(self, target: str | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        partition = "admin_audit" + (":" + target if target else "")
        page = self.store.page(partition, limit=limit, cursor=cursor, reverse=True)
        return {"items": [document.data for document in page.items], "next_cursor": page.cursor}

    # Acting. Every action is recorded with who did it, to whom, and why.

    def _record(self, admin: dict, action: str, target: dict | None, detail: dict) -> None:
        now = self._now()
        # The index orders by ``due`` alone, so entries in the same second need their
        # own place: a per-process sequence keeps a run of actions in the order made.
        self._sequence = (self._sequence + 1) % 10_000
        position = now * 10_000 + self._sequence
        suffix = f"{position:016d}:{secrets.token_hex(6)}"
        entry = {
            "at": now,
            "action": action,
            "admin_id": admin["id"],
            "admin": _name(admin),
            "target_id": target["id"] if target else None,
            "target": _name(target) if target else None,
            "detail": detail,
        }
        expires = now + AUDIT_DAYS * DAY
        documents = [
            Document(
                "admin-audit:" + suffix, "admin_audit", entry, due=position, expires_at=expires
            )
        ]
        if target:
            documents.append(
                Document(
                    "admin-audit:" + target["id"] + ":" + suffix,
                    "admin_audit:" + target["id"],
                    entry,
                    due=position,
                    expires_at=expires,
                )
            )
        self.store.commit(documents)

    def _target(self, admin: dict, tenant: str) -> dict:
        account = self.accounts.account_document(tenant)
        if account is None or account.data.get("status") == "deleted":
            raise NotFound("Account not found")
        if account.data["id"] == admin["id"]:
            raise ValueError("Change your own account from your security settings.")
        if account.data.get("role") == "admin":
            raise ValueError("Admins are managed from the command line, not from the panel.")
        return account.data

    def act(self, admin: dict, tenant: str, action: str, reason: str = "") -> dict:
        target = self._target(admin, tenant)
        result: dict = {}
        if action == "suspend":
            if not reason.strip():
                raise ValueError("Give a reason for the suspension.")
            self.accounts.suspend(tenant, reason.strip())
        elif action == "reactivate":
            self.accounts.reactivate(tenant)
        elif action == "sign-out":
            self.accounts.revoke_access(tenant)
        elif action == "reset-two-factor":
            self.accounts.reset_two_factor(tenant)
        elif action == "temporary-password":
            result = self.accounts.set_temporary_password(tenant)
        else:
            raise ValueError("Unknown action")
        # The temporary password itself is never recorded.
        self._record(admin, action, target, {"reason": reason.strip()} if reason.strip() else {})
        return {"done": True, **result}

    def delete(self, admin: dict, tenant: str, confirm: str, reason: str) -> dict:
        target = self._target(admin, tenant)
        if confirm.strip().lower() not in {(_name(target) or "").lower(), target["id"]}:
            raise ValueError("Type the account's email address to confirm.")
        if not reason.strip():
            raise ValueError("Give a reason for deleting the account.")
        self.accounts.remove_account(tenant)
        self._record(admin, "delete", target, {"reason": reason.strip()})
        return {"deleted": True}

    def set_flight(
        self, admin: dict, tenant: str, monitor_id: str, status: str, reason: str = ""
    ) -> dict:
        account = self.accounts.account_document(tenant)
        if account is None or account.data.get("status") == "deleted":
            raise NotFound("Account not found")
        if status not in FLIGHT_ACTIONS:
            raise ValueError("Unsupported flight status")
        result = self.service.set_status(tenant, monitor_id, status)
        segments = result["target"].get("segments") or []
        legs = segments[0].get("legs", []) if segments else []
        route = f"{legs[0]['origin']} → {legs[-1]['destination']}" if legs else monitor_id
        detail = {"monitor_id": monitor_id, "route": route}
        if reason.strip():
            detail["reason"] = reason.strip()
        self._record(admin, FLIGHT_ACTIONS[status], account.data, detail)
        return result

    def set_switches(self, admin: dict, changes: dict) -> dict:
        changes = {key: bool(value) for key, value in changes.items() if key in SWITCHES}
        if not changes:
            raise ValueError("Nothing to change")
        for _ in range(5):
            current = self.store.get("configuration:admin") or Document(
                "configuration:admin", "configuration", {}
            )
            data = {**current.data, **changes, "updated_at": self._now(), "updated_by": admin["id"]}
            try:
                self.store.commit([current.update(data)])
                break
            except Conflict:
                continue
        else:
            raise Conflict("The switches changed in another window; try again")
        self._record(admin, "switches", None, changes)
        return self.accounts.switches()
