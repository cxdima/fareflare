"""Account-owned Telegram views and confirmed, transaction-fenced commands.

The webhook adapter authenticates private chat updates. This application adapter
also rechecks that binding at each write, including menu token creation.
"""

from __future__ import annotations

import copy
import hashlib
import re
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from fareflare.accounts import Accounts, AuthenticationFailed
from fareflare.domain import AlertPolicy
from fareflare.message_templates import Run, plain_text, telegram_html
from fareflare.preferences import (
    ListOrder,
    Preferences,
    merge_preferences,
    observed_time,
    quiet_hours_label,
    short_price,
)
from fareflare.refusals import LinkRefused
from fareflare.service import CapacityReached, MonitoringService, NotFound, QuotaReached
from fareflare.store import Conflict, Document, Store
from fareflare.telegram_messages import (
    STATUS_LABELS,
    TelegramMessage,
    cabin_name,
    flight_list,
    flight_numbers,
    flight_row_values,
    local_date,
    monitor_segments,
    monitor_times,
    ordered_flights,
    party,
    preview_message,
    safe_flight_url,
    schedule_lines,
    single_line,
    trip_route,
    trip_values,
    utf16_length,
)
from fareflare.telegram_rules import parse_amount, price_example
from fareflare.telegram_templates import PRESETS, STYLES, SWITCHES, style_switches

_TOKEN = re.compile(r"ff:([A-Za-z0-9_-]{24})\Z")
_MENU_SECONDS = 15 * 60
_STATUS = STATUS_LABELS
_LIVE = ("pending", "active", "degraded")
# Telegram allows 4096 characters. A view keeps to 4000, and its flight list to
# less, which leaves room for the title, a notice and the line under the list.
_VIEW_LIMIT = 4000
_LIST_BUDGET = 3300
# Flights offered at a time when choosing one to open, and readings per history page.
_CHOICES = 8
_READINGS = 10
# Offered with one tap; any other window is set in Account settings.
_DEFAULT_QUIET_HOURS = "22:00-07:00"
# The flight list's orders: what each is called on the button that switches to it.
_LIST_ORDERS: dict[ListOrder, str] = {"departure": "Sort by departure", "price": "Sort by price"}
# A line of a view: plain words, or runs that carry their own emphasis.
Line = str | tuple[Run, ...]


class _Unavailable(Exception):
    """The authenticated connection or a previously displayed action changed."""


class _Applied(Exception):
    """Another delivery of this action already committed its mutation."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _connection(binding: Document) -> str:
    # Existing connections predate the explicit connection generation.
    return str(binding.data.get("connection_id", binding.data.get("connected_at", "")))


@dataclass
class _Context:
    tenant: str
    chat_id: str
    epoch: int
    connection: str
    pending: list[Document] = field(default_factory=list)


class _BoundStore:
    """Fence normal service transactions against disconnects and stale buttons."""

    def __init__(
        self,
        store: Store,
        context: _Context,
        now: Callable[[], int],
        action: Document | None = None,
    ):
        self.store, self.context, self.now, self.action = store, context, now, action
        self.completed = False

    def get(self, key: str) -> Document | None:
        return self.store.get(key)

    def page(self, *args, **kwargs):
        return self.store.page(*args, **kwargs)

    def query(self, *args, **kwargs):
        return self.store.query(*args, **kwargs)

    def guards(self) -> list[Document]:
        ctx = self.context
        account = self.get("account:" + ctx.tenant)
        binding = self.get("telegram-account:" + ctx.tenant)
        chat = self.get("telegram-chat:" + ctx.chat_id)
        if (
            not account
            or account.data.get("status") != "active"
            or account.data.get("auth_epoch") != ctx.epoch
            or not binding
            or not binding.data.get("connected")
            or binding.data.get("auth_epoch") != ctx.epoch
            or binding.data.get("chat_id") != ctx.chat_id
            or _connection(binding) != ctx.connection
            or not chat
            or not chat.data.get("connected")
            or chat.data.get("tenant") != ctx.tenant
            or chat.data.get("auth_epoch") != ctx.epoch
            or binding.data.get("connection_id") != chat.data.get("connection_id")
        ):
            raise _Unavailable
        guards = [account, binding, chat]
        if self.action is not None:
            action = self.get(self.action.key)
            if not action or action.data.get("expires_at", 0) <= self.now():
                raise _Unavailable
            if action.data.get("used"):
                raise _Applied
            params = action.data["params"]
            if "monitor_id" in params:
                monitor = self.get("monitor:" + params["monitor_id"])
                if (
                    not monitor
                    or monitor.data.get("tenant") != ctx.tenant
                    or monitor.data.get("notification_epoch", 0) != params["monitor_epoch"]
                    or (
                        "expected_policy" in params
                        and monitor.data["policy"] != params["expected_policy"]
                    )
                ):
                    raise _Unavailable
                guards.append(monitor)
            if action.data.get("confirmation"):
                draft = self.get("telegram-draft:" + ctx.tenant)
                if not draft or draft.data.get("action") != action.key:
                    raise _Unavailable
                guards.append(draft.update({"action": None}))
            elif "draft_generation" in params:
                draft = self.get("telegram-draft:" + ctx.tenant)
                if not draft or draft.data.get("generation") != params["draft_generation"]:
                    raise _Unavailable
                guards.append(draft)
            guards.append(action.update({**action.data, "used": True}))
        return guards

    def commit(self, documents: list[Document]) -> None:
        guards = self.guards()
        writes = {doc.key: doc for doc in documents}
        for guard in guards:
            if guard.key in writes:
                # Service writes already fence their read revision. A newer guard
                # must never replace that revision or the mutation's new data.
                if writes[guard.key].revision != guard.revision:
                    raise Conflict("The flight changed; open its current controls")
            else:
                writes[guard.key] = guard.update(guard.data)
        self.store.commit(list(writes.values()))
        if self.action is not None:
            self.completed = True

    def complete(self) -> None:
        if not self.completed:
            self.commit([])  # A service no-op still consumes its explicit action.


class TelegramBot:
    def __init__(
        self,
        service: MonitoringService,
        accounts: Accounts,
        public_url: str,
        *,
        clock: Callable[[], float] = time.time,
    ):
        self.service, self.accounts, self.store, self.clock = (
            service,
            accounts,
            service.store,
            clock,
        )
        self.public_url = public_url.rstrip("/")
        parts = urlsplit(self.public_url)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Configure a valid public application URL")

    def _now(self) -> int:
        return int(self.clock())

    def _context(self, tenant: str, chat_id: str, epoch: int) -> _Context:
        if (
            not isinstance(tenant, str)
            or not isinstance(chat_id, str)
            or not chat_id.isdigit()
            or type(epoch) is not int
        ):
            raise _Unavailable
        binding = self.store.get("telegram-account:" + tenant)
        if not binding:
            raise _Unavailable
        ctx = _Context(tenant, chat_id, epoch, _connection(binding))
        _BoundStore(self.store, ctx, self._now).guards()
        return ctx

    def handle(
        self,
        tenant: str,
        chat_id: str,
        auth_epoch: int,
        text: str | None = None,
        callback_data: str | None = None,
        update_id: int = 0,
    ) -> TelegramMessage:
        del update_id  # Update delivery deduplication belongs to the webhook adapter.
        try:
            ctx = self._context(tenant, chat_id, auth_epoch)
            if callback_data is not None:
                return self._callback(ctx, callback_data)
            text = text.strip() if isinstance(text, str) else ""
            command, _, argument = text.partition(" ")
            command = command.split("@", 1)[0].lower()
            if command == "/flights":
                return self._flights(ctx)
            if command == "/settings":
                return self._settings(ctx)
            if command == "/cancel":
                draft = self.store.get("telegram-draft:" + tenant)
                if draft:
                    _BoundStore(self.store, ctx, self._now).commit([draft.update({"action": None})])
                return self._home(ctx, "Pending confirmation cancelled.")
            if command == "/add" and not argument:
                return self._add_help(ctx)
            if command == "/add" or text.startswith("https://"):
                return self._preview(ctx, argument.strip() if command == "/add" else text)
            if command == "/help":
                return self._help(ctx)
            if command in ("/start", "/status", "/menu"):
                return self._home(ctx)
            draft = self.store.get("telegram-draft:" + tenant)
            if draft and draft.data.get("input") == "price":
                return self._price_confirmation(
                    ctx, draft, argument.strip() if command == "/target" else text
                )
            return self._help(ctx, "Send a Google Flights link or choose a command below.")
        except (_Unavailable, AuthenticationFailed):
            return self._plain(
                "This control is no longer current. Use /start for a fresh menu. If disconnected, reconnect from Fareflare Account settings."
            )
        except _Applied:
            return self._plain(
                "This action was already applied. Use /flights or /settings to see the current state."
            )
        except NotFound:
            return self._plain(
                "That flight is no longer available. Use /flights for your current list."
            )
        except Conflict:
            return self._plain(
                "Your account changed while this request was running. Open /flights or /settings and try again."
            )
        except QuotaReached:
            unit = "flight" if self.service.monitor_limit == 1 else "flights"
            return self._plain(
                f"Your account can watch {self.service.monitor_limit} {unit}. Use /flights to stop one before adding another."
            )
        except CapacityReached:
            return self._plain(
                "Fareflare is at its current collection capacity. Try adding this flight later."
            )
        except LinkRefused as refusal:
            # Confirmed after its preview, the link was refused: say why.
            return self._plain(str(refusal))
        except ValueError:
            # Provider and storage diagnostics must not become bot messages.
            return self._plain(
                "This request could not be completed. Check your flight link or use Fareflare for more details."
            )

    def _plain(self, text: str) -> TelegramMessage:
        return TelegramMessage(
            text=text,
            reply_markup={
                "inline_keyboard": [[{"text": "Open Fareflare", "url": self.public_url + "/app"}]]
            },
        )

    def _button(
        self,
        ctx: _Context,
        label: str,
        action: str,
        params: dict | None = None,
        *,
        style: str | None = None,
        confirmation: bool = False,
        draft: Document | None = None,
    ) -> dict:
        token = secrets.token_urlsafe(18)
        expires = self._now() + _MENU_SECONDS
        doc = Document(
            "telegram-action:" + _hash(token),
            "telegram-actions:" + ctx.tenant,
            {
                "tenant": ctx.tenant,
                "chat_id": ctx.chat_id,
                "auth_epoch": ctx.epoch,
                "connection": ctx.connection,
                "action": action,
                "params": params or {},
                "used": False,
                "confirmation": confirmation,
                "expires_at": expires,
            },
            expires_at=expires,
        )
        ctx.pending.append(doc)
        if confirmation:
            draft = (
                draft
                or self.store.get("telegram-draft:" + ctx.tenant)
                or Document("telegram-draft:" + ctx.tenant, "telegram-drafts", {})
            )
            ctx.pending.append(
                draft.update({"action": doc.key, "generation": doc.key}, expires_at=expires)
            )
        button = {"text": label, "callback_data": "ff:" + token}
        if style:
            button["style"] = style
        return button

    def _cancel_button(self, ctx: _Context, label: str = "Cancel") -> dict:
        draft = next(
            (doc for doc in reversed(ctx.pending) if doc.key == "telegram-draft:" + ctx.tenant),
            None,
        )
        if draft is None:
            raise ValueError("Inline cancellation requires its originating draft")
        return self._button(ctx, label, "cancel", {"draft_generation": draft.data["generation"]})

    def _message(
        self,
        ctx: _Context,
        title: str,
        lines: Sequence[Line],
        rows: list[list[dict]],
        notice: str | None = None,
    ) -> TelegramMessage:
        """Build a view: an optional notice, a bold title, then the lines beneath it."""
        view: list[tuple[Run, ...]] = [(Run(notice),), ()] if notice else []
        view.append((Run(title, bold=True),))
        if lines:
            view.append(())
        view += [
            ((Run(line),) if line else ()) if isinstance(line, str) else line for line in lines
        ]
        plain = plain_text(tuple(view))
        if utf16_length(plain) > _VIEW_LIMIT:
            raise ValueError("Telegram view exceeds the message limit")
        if ctx.pending:
            _BoundStore(self.store, ctx, self._now).commit(ctx.pending)
            ctx.pending.clear()
        return TelegramMessage(
            text=plain, html=telegram_html(tuple(view)), reply_markup={"inline_keyboard": rows}
        )

    def _nav(self, ctx: _Context) -> list[dict]:
        return [
            self._button(ctx, "Flights", "flights"),
            self._button(ctx, "Alert settings", "settings"),
        ]

    def _preferences(self, tenant: str) -> Preferences:
        return merge_preferences(self.service.preferences(tenant))

    def _home(self, ctx: _Context, notice: str | None = None) -> TelegramMessage:
        page = self.service.monitors_page(ctx.tenant, limit=1)
        prefs = self._preferences(ctx.tenant)
        return self._message(
            ctx,
            "Your flight dashboard",
            [
                f"Watching {page['active_count']} of {self.service.monitor_limit} available flights",
                "Alerts are muted. Price checks continue."
                if prefs.muted
                else "Price alerts are on.",
                "",
                "Add a Google Flights link, review recorded prices, or manage your alerts.",
            ],
            [
                [
                    self._button(ctx, "My flights", "flights"),
                    self._button(ctx, "Watch a flight", "add", style="primary"),
                ],
                [
                    self._button(ctx, "Alert settings", "settings"),
                    {"text": "Open Fareflare", "url": self.public_url + "/app"},
                ],
            ],
            notice,
        )

    def _help(self, ctx: _Context, notice: str | None = None) -> TelegramMessage:
        return self._message(
            ctx,
            "Fareflare commands",
            [
                "/flights — prices, history and flight controls",
                "/add — watch a Google Flights link",
                "/settings — message style, sound and muting",
                "/cancel — cancel a pending confirmation",
                "/stop — disconnect Telegram",
                "",
                "You can also paste a Google Flights link directly.",
                "Prices are checked periodically and can change before booking.",
            ],
            [self._nav(ctx)],
            notice,
        )

    def _add_help(self, ctx: _Context) -> TelegramMessage:
        return self._message(
            ctx,
            "Watch a flight",
            [
                "Paste a full Google Flights link here. I’ll show the itinerary before you confirm.",
                "",
                "Select your flights on Google Flights, then copy the address from your browser.",
                "Short share links must be opened first. Supported route-search links also work.",
                "",
                "Use /cancel to discard a pending confirmation.",
            ],
            [self._nav(ctx)],
        )

    @staticmethod
    def _travellers(target: dict) -> str:
        """Who travels and in which cabin: ``1 adult · Economy``."""
        return f"{party(target['adults'])} · {cabin_name(target['cabin']) or 'Cabin not specified'}"

    @staticmethod
    def _flights_of(segments: list[dict], target: dict) -> str:
        """Flight numbers, or what a route search is still looking for."""
        return ", ".join(flight_numbers(segments)) or (
            "Route search" if target.get("kind") == "search" else ""
        )

    def _current(self, tenant: str, prefs: Preferences) -> list[dict]:
        """The flights being watched or paused, in the order this account lists them."""
        return ordered_flights(self.service.current_monitors(tenant), prefs)

    def _prefer(self, ctx: _Context, label: str, changes: dict, view: str) -> dict:
        """A button that saves settings and returns to the view it was pressed in."""
        return self._button(ctx, label, "prefer", {"changes": changes, "view": view})

    def _flights(self, ctx: _Context, start: int = 0, notice: str | None = None) -> TelegramMessage:
        prefs = self._preferences(ctx.tenant)
        monitors = self._current(ctx.tenant, prefs)
        if not 0 < start < len(monitors):
            start = 0
        lines, shown = flight_list(
            monitors[start:], prefs, local_date(self._now(), prefs), budget=_LIST_BUDGET
        )
        body: list[Line] = list(lines)
        page = monitors[start : start + shown]
        notes = []
        if shown < len(monitors):
            notes.append(f"Flights {start + 1}–{start + shown} of {len(monitors)}")
        checks = [flight["latest"]["observed_at"] for flight in page if flight.get("latest")]
        if checks:
            notes.append("Latest check " + observed_time(max(checks), prefs, zone_label=False))
        if notes:
            body += ["", (Run(" · ".join(notes), italic=True),)]
        if not monitors:
            body = ["No flights yet. Paste a Google Flights link to start watching."]
        rows = []
        if start + shown < len(monitors):
            rows.append([self._button(ctx, "Next flights", "flights", {"start": start + shown})])
        if start:
            rows.append([self._button(ctx, "First page", "flights")])
        actions = [self._button(ctx, "Watch a flight", "add", style="primary")]
        if len(monitors) == 1:
            actions.insert(
                0, self._button(ctx, "Manage this flight", "detail", {"id": monitors[0]["id"]})
            )
        elif monitors:
            actions.insert(0, self._button(ctx, "Manage a flight", "choose"))
        settings = [self._button(ctx, "Alert settings", "settings")]
        if len(monitors) > 1:
            # Offer the order the list is not in.
            other: ListOrder = "price" if prefs.telegram_list_order == "departure" else "departure"
            settings.insert(
                0, self._prefer(ctx, _LIST_ORDERS[other], {"telegram_list_order": other}, "flights")
            )
        rows += [actions, settings]
        title = "Your flights" + (f" ({len(monitors)})" if monitors else "")
        return self._message(ctx, title, body, rows, notice)

    def _choose(self, ctx: _Context, start: int = 0) -> TelegramMessage:
        """Pick one flight to open. The list itself stays free of a button per flight."""
        prefs = self._preferences(ctx.tenant)
        monitors = self._current(ctx.tenant, prefs)
        if not monitors:
            return self._flights(ctx)
        if not 0 < start < len(monitors):
            start = 0
        today = local_date(self._now(), prefs)
        rows = []
        for monitor in monitors[start : start + _CHOICES]:
            values = flight_row_values(monitor, prefs, today)
            label = " · ".join(
                str(values[name])
                for name in ("route", "dates_short", "flights")
                if values.get(name)
            )
            rows.append(
                [self._button(ctx, single_line(label, 60), "detail", {"id": monitor["id"]})]
            )
        end = min(start + _CHOICES, len(monitors))
        if end < len(monitors):
            rows.append([self._button(ctx, "More flights", "choose", {"start": end})])
        if start:
            rows.append([self._button(ctx, "First flights", "choose")])
        rows.append([self._button(ctx, "Back to my flights", "flights")])
        lines = (
            [f"Flights {start + 1}–{end} of {len(monitors)}"] if len(monitors) > _CHOICES else []
        )
        return self._message(ctx, "Choose a flight", lines, rows)

    def _detail(self, ctx: _Context, identifier: str, notice: str | None = None) -> TelegramMessage:
        monitor = self.service.get_monitor(ctx.tenant, identifier)
        prefs, target, latest = (
            self._preferences(ctx.tenant),
            monitor["target"],
            monitor.get("latest"),
        )
        values = flight_row_values(monitor, prefs, local_date(self._now(), prefs))
        segments = monitor_segments(monitor)
        times = schedule_lines(monitor_times(monitor), prefs)
        lines: list[Line] = []
        for index, segment in enumerate(segments):
            parts = (self._flights_of([segment], target), times[index] if times else "")
            if direction := " · ".join(part for part in parts if part):
                lines.append(("↩ " if index else "") + direction)
        lines += [self._travellers(target), ""]
        if latest:
            price: list[Run] = [Run(str(values["price_short"]), bold=True)]
            if values.get("low_note"):
                price.append(Run(f" {values['low_note']}"))
            lines += [
                tuple(price),
                "Checked " + observed_time(latest["observed_at"], prefs, zone_label=False),
            ]
            if latest.get("fare_name"):
                lines.append("Fare: " + single_line(latest["fare_name"]))
        else:
            lines.append("Waiting for the first price check.")
        status = _STATUS.get(monitor["status"], "Unknown")
        if monitor["status"] in _LIVE:
            status += f" · checked every {monitor['interval_seconds'] // 60} min"
        lines += ["", status]
        if monitor.get("stale") and latest and monitor["status"] in _LIVE:
            lines.append("This price needs a fresh check.")
        if monitor.get("last_error") and monitor["status"] in _LIVE:
            # Plain language for everyone; codes only for accounts that asked for them.
            if monitor.get("collection_status") == "blocked":
                lines.append("Price checks have stopped. Choose Retry collection to try again.")
            else:
                lines.append("The last check could not finish. Fareflare will try again.")
            if prefs.diagnostics:
                failures = monitor.get("collection_failures", 0)
                lines.append(
                    f"Diagnostic code: {single_line(str(monitor['last_error']), 40)}"
                    f" · failed checks in a row: {failures}"
                )
        rows = [[self._button(ctx, "Recent prices", "history", {"id": identifier})]]
        params = {"monitor_id": identifier, "monitor_epoch": monitor.get("notification_epoch", 0)}
        if monitor["status"] == "paused":
            rows.append(
                [
                    self._button(
                        ctx,
                        "Resume watching",
                        "status",
                        {**params, "status": "active"},
                        style="success",
                    )
                ]
            )
        elif monitor["status"] in _LIVE:
            rows.append(
                [self._button(ctx, "Pause watching", "status", {**params, "status": "paused"})]
            )
            if monitor.get("collection_status") == "blocked":
                rows.append([self._button(ctx, "Retry collection", "retry", params)])
        if monitor["status"] not in ("cancelled", "expired"):
            rows.append([self._button(ctx, "Alert rules", "rules", {"id": identifier})])
            rows.append([self._button(ctx, "Stop watching…", "stop-confirm", {"id": identifier})])
        offer = (latest or {}).get("observed_offer") or {}
        url = safe_flight_url(offer.get("url") or target.get("url"))
        if url:
            rows.append([{"text": "View on Google Flights", "url": url}])
        rows.append(self._nav(ctx))
        title = f"{values['route']} · {values['dates_short']}"
        return self._message(ctx, title, lines, rows, notice)

    def _history(
        self, ctx: _Context, identifier: str, cursor: str | None = None
    ) -> TelegramMessage:
        monitor = self.service.get_monitor(ctx.tenant, identifier)
        prefs = self._preferences(ctx.tenant)
        page = self.service.history_page(ctx.tenant, identifier, limit=_READINGS, cursor=cursor)
        items = page["items"]
        lines: list[Line] = [
            (
                Run(short_price(item["amount_minor"], item["currency"], prefs.locale), bold=True),
                Run(" · " + observed_time(item["observed_at"], prefs, zone_label=False)),
            )
            for item in items
        ]
        if len(items) > 1:
            lowest = min(items, key=lambda item: item["amount_minor"])
            lines += [
                "",
                "Lowest of these: "
                + short_price(lowest["amount_minor"], lowest["currency"], prefs.locale),
            ]
        if not items:
            lines = ["No prices recorded yet. The first check comes soon after a flight is added."]
        rows = []
        if page["next_cursor"]:
            rows.append(
                [
                    self._button(
                        ctx,
                        "Earlier prices",
                        "history",
                        {"id": identifier, "cursor": page["next_cursor"]},
                    )
                ]
            )
        if cursor:
            rows.append([self._button(ctx, "Latest prices", "history", {"id": identifier})])
        rows.append([self._button(ctx, "Back to flight", "detail", {"id": identifier})])
        title = "Recorded prices: " + trip_route(monitor["target"]["segments"])
        return self._message(ctx, title, lines, rows)

    def _settings(self, ctx: _Context, notice: str | None = None) -> TelegramMessage:
        prefs = self._preferences(ctx.tenant)
        lines = [
            "Notifications: " + ("muted" if prefs.muted else "on"),
            "Telegram sound: " + ("silent" if prefs.telegram_silent else "standard"),
            "Quiet hours: "
            + (
                quiet_hours_label(prefs.quiet_hours, prefs) + ", no sound"
                if prefs.quiet_hours
                else "off"
            ),
            "Message style: " + STYLES[prefs.telegram_style][0],
            "Time zone: " + (prefs.time_zone or "UTC (choose your local zone in Fareflare)"),
            "Regional format: " + prefs.locale,
        ]
        rows = [
            [
                self._prefer(
                    ctx,
                    "Turn alerts on" if prefs.muted else "Mute alerts",
                    {"muted": not prefs.muted},
                    "settings",
                )
            ],
            [
                self._prefer(
                    ctx,
                    "Enable notification sound" if prefs.telegram_silent else "Send silently",
                    {"telegram_silent": not prefs.telegram_silent},
                    "settings",
                )
            ],
            [
                self._prefer(
                    ctx,
                    "Turn off quiet hours"
                    if prefs.quiet_hours
                    else "Go quiet " + quiet_hours_label(_DEFAULT_QUIET_HOURS, prefs),
                    {"quiet_hours": None if prefs.quiet_hours else _DEFAULT_QUIET_HOURS},
                    "settings",
                )
            ],
            [self._button(ctx, "Message style", "styles")],
        ]
        if prefs.diagnostics:
            # Opting in happens in Account settings; opting out is one tap where notices arrive.
            lines.append("Diagnostic notices: on")
            rows.append(
                [
                    self._prefer(
                        ctx, "Turn off diagnostic notices", {"diagnostics": False}, "settings"
                    )
                ]
            )
        lines += ["", "Muting stops delivery; price checks and history continue."]
        rows += [
            [{"text": "Time zone and more settings", "url": self.public_url + "/app#settings"}],
            [self._button(ctx, "My flights", "flights")],
        ]
        return self._message(ctx, "Your alert settings", lines, rows, notice)

    def _styles(self, ctx: _Context, notice: str | None = None) -> TelegramMessage:
        """Choose a style and what its alerts include, beside an example of the result."""
        prefs = self._preferences(ctx.tenant)
        sample = preview_message("new_low", prefs, None, self._now())
        styles = list(PRESETS)
        if prefs.telegram_templates or prefs.telegram_style == "custom":
            styles.append("custom")

        def choice(chosen: bool, label: str, changes: dict) -> dict:
            return self._prefer(ctx, ("✓ " if chosen else "") + label, changes, "styles")

        rows = [
            [
                choice(style == prefs.telegram_style, STYLES[style][0], {"telegram_style": style})
                for style in styles
            ],
            # The details this style's alerts can leave out; own wording has none.
            *(
                [choice(shown, SWITCHES[name].label, {name: not shown})]
                for name in style_switches(prefs.telegram_style)
                for shown in [getattr(prefs, name)]
            ),
            [
                choice(
                    prefs.telegram_show_buttons,
                    "Buttons under alerts",
                    {"telegram_show_buttons": not prefs.telegram_show_buttons},
                )
            ],
            [{"text": "Write your own messages", "url": self.public_url + "/app#settings"}],
            [self._button(ctx, "Back to alert settings", "settings")],
        ]
        lines: list[Line] = [
            f"{STYLES[prefs.telegram_style][0]}: an example with sample data.",
            "",
            *sample.lines,
        ]
        return self._message(ctx, "Message style", lines, rows, notice)

    def _saved(self, ctx: _Context, view: str) -> TelegramMessage:
        """The view a setting was changed in, saying that it was saved."""
        if view == "styles":
            return self._styles(ctx, "Message settings saved.")
        if view == "flights":
            return self._flights(ctx, notice="Flight list order saved.")
        return self._settings(ctx, "Alert settings saved.")

    def _preview(self, ctx: _Context, url: str) -> TelegramMessage:
        try:
            target = self.service.accept_link(url)
        except LinkRefused as refusal:
            lines: list[Line] = [str(refusal), "Nothing has been added."]
            if self._preferences(ctx.tenant).diagnostics:
                lines.append(f"Diagnostic code: {refusal.check}")
            return self._message(
                ctx,
                "Fareflare can't watch this link",
                lines,
                [
                    [
                        {
                            "text": "Supported flight links",
                            "url": self.public_url + "/guides/choosing-a-flight-link",
                        }
                    ],
                    self._nav(ctx),
                ],
            )
        prefs = self._preferences(ctx.tenant)
        interval = self.service.default_interval_seconds
        return self._message(
            ctx,
            "Watch " + trip_route(target["segments"]) + "?",
            [
                str(trip_values(target["segments"], prefs, None)["dates"]),
                self._flights_of(target["segments"], target),
                self._travellers(target),
                "Currency: " + target["currency"],
                "",
                "Alert on a new observed low.",
                f"Checks requested every {interval // 60} min. A price is not available until the first check.",
                "",
                "Confirm to add this flight to your account.",
            ],
            [
                [
                    self._button(
                        ctx,
                        "Start watching",
                        "create",
                        {"url": url, "interval": interval},
                        style="primary",
                        confirmation=True,
                    )
                ],
                [self._cancel_button(ctx)],
            ],
        )

    def _stop_confirm(self, ctx: _Context, identifier: str) -> TelegramMessage:
        monitor = self.service.get_monitor(ctx.tenant, identifier)
        return self._message(
            ctx,
            "Stop watching " + trip_route(monitor["target"]["segments"]) + "?",
            [
                "This flight will stop checking prices and sending alerts. Recorded history remains available.",
                "A stopped flight cannot be resumed; you can add its link again.",
            ],
            [
                [
                    self._button(
                        ctx,
                        "Stop watching",
                        "status",
                        {
                            "monitor_id": identifier,
                            "monitor_epoch": monitor.get("notification_epoch", 0),
                            "status": "cancelled",
                        },
                        style="danger",
                        confirmation=True,
                    )
                ],
                [self._cancel_button(ctx, "Keep watching")],
            ],
        )

    def _rules(self, ctx: _Context, identifier: str, notice: str | None = None) -> TelegramMessage:
        monitor = self.service.get_monitor(ctx.tenant, identifier)
        prefs, policy = self._preferences(ctx.tenant), monitor["policy"]
        currency = monitor["target"]["currency"]
        lines = [
            "Notify on: "
            + (
                "a new observed low"
                if policy["kind"] == "new_low"
                else "a price at or below "
                + short_price(policy["threshold_minor"], currency, prefs.locale)
            )
        ]
        if policy["kind"] == "new_low":
            drop = policy["min_drop_minor"]
            lines.append(
                "Minimum drop: " + (short_price(drop, currency, prefs.locale) if drop else "none")
            )
        lines += [
            "Price rebounds: " + ("on" if policy["notify_rebounds"] else "off"),
            "",
            "Rules apply to future observations. A target price is not a prediction.",
        ]
        params = {
            "monitor_id": identifier,
            "monitor_epoch": monitor.get("notification_epoch", 0),
            "expected_policy": policy,
        }
        new_low = {**policy, "kind": "new_low", "threshold_minor": None}
        rebound = {**policy, "notify_rebounds": not policy["notify_rebounds"]}
        rows = [
            [
                self._button(ctx, "New observed lows", "policy", {**params, "policy": new_low}),
                self._button(
                    ctx, "Set target price", "price-prompt", {"id": identifier, "field": "target"}
                ),
            ]
        ]
        if policy["kind"] == "new_low":
            rows.append(
                [
                    self._button(
                        ctx, "Set minimum drop", "price-prompt", {"id": identifier, "field": "drop"}
                    )
                ]
            )
        rows += [
            [
                self._button(
                    ctx,
                    "Disable rebound alerts"
                    if policy["notify_rebounds"]
                    else "Enable rebound alerts",
                    "policy",
                    {**params, "policy": rebound},
                )
            ],
            [self._button(ctx, "Back to flight", "detail", {"id": identifier})],
        ]
        title = "Alert rules: " + trip_route(monitor["target"]["segments"])
        return self._message(ctx, title, lines, rows, notice)

    def _price_prompt(self, ctx: _Context, identifier: str, field_name: str) -> TelegramMessage:
        monitor = self.service.get_monitor(ctx.tenant, identifier)
        if monitor["status"] in ("cancelled", "expired"):
            raise _Unavailable
        currency, prefs = monitor["target"]["currency"], self._preferences(ctx.tenant)
        expires = self._now() + _MENU_SECONDS
        draft = self.store.get("telegram-draft:" + ctx.tenant) or Document(
            "telegram-draft:" + ctx.tenant, "telegram-drafts", {}
        )
        ctx.pending.append(
            draft.update(
                {
                    "input": "price",
                    "field": field_name,
                    "monitor_id": identifier,
                    "monitor_epoch": monitor.get("notification_epoch", 0),
                    "tenant": ctx.tenant,
                    "chat_id": ctx.chat_id,
                    "auth_epoch": ctx.epoch,
                    "connection": ctx.connection,
                    "generation": secrets.token_urlsafe(18),
                    "expires_at": expires,
                },
                expires_at=expires,
            )
        )
        return self._message(
            ctx,
            "Set a " + ("minimum drop" if field_name == "drop" else "target price"),
            [
                trip_route(monitor["target"]["segments"]),
                "Currency: " + currency,
                "Send the amount, for example " + price_example(currency, prefs.locale) + ".",
                "Do not include currency symbols or thousands separators.",
                "Use whole yen."
                if currency == "JPY"
                else "Use the decimal separator from your regional settings.",
                "Zero disables the minimum drop."
                if field_name == "drop"
                else "The target must be greater than zero.",
                "",
                "You’ll review the rule before saving. Use /cancel to leave this prompt.",
            ],
            [[self._cancel_button(ctx)]],
        )

    def _price_confirmation(self, ctx: _Context, draft: Document, value: str) -> TelegramMessage:
        data = draft.data
        if (
            data.get("tenant") != ctx.tenant
            or data.get("chat_id") != ctx.chat_id
            or data.get("auth_epoch") != ctx.epoch
            or data.get("connection") != ctx.connection
            or data.get("expires_at", 0) <= self._now()
        ):
            return self._plain(
                "That price prompt expired. Use /flights, open a flight and choose Alert rules again."
            )
        monitor = self.service.get_monitor(ctx.tenant, data["monitor_id"])
        if monitor.get("notification_epoch", 0) != data["monitor_epoch"]:
            raise _Unavailable
        prefs, currency, policy = (
            self._preferences(ctx.tenant),
            monitor["target"]["currency"],
            monitor["policy"],
        )
        try:
            amount = parse_amount(value, currency, prefs.locale, allow_zero=data["field"] == "drop")
        except ValueError:
            return self._plain(
                "Enter a valid "
                + currency
                + " amount, such as "
                + price_example(currency, prefs.locale)
                + ", without currency symbols or thousands separators. Use /cancel to leave this prompt."
            )
        if data["field"] == "drop":
            updated = {
                **policy,
                "kind": "new_low",
                "threshold_minor": None,
                "min_drop_minor": amount,
            }
            description = (
                "Alert on a new observed low after a drop of at least "
                + short_price(amount, currency, prefs.locale)
                + "."
                if amount
                else "Alert on every new observed low."
            )
        else:
            updated = {
                **policy,
                "kind": "below_price",
                "threshold_minor": amount,
                "min_drop_minor": 0,
            }
            description = (
                "Alert when an observed price reaches or crosses below "
                + short_price(amount, currency, prefs.locale)
                + "."
            )
        params = {
            "monitor_id": monitor["id"],
            "monitor_epoch": monitor.get("notification_epoch", 0),
            "expected_policy": policy,
            "policy": updated,
        }
        return self._message(
            ctx,
            "Save this alert rule?",
            [
                trip_route(monitor["target"]["segments"]),
                description,
                "",
                "This changes future alerts. It does not change the flight or its currency.",
            ],
            [
                [
                    self._button(
                        ctx,
                        "Save alert rule",
                        "policy",
                        params,
                        style="primary",
                        confirmation=True,
                        draft=draft,
                    )
                ],
                [self._cancel_button(ctx)],
            ],
        )

    def _callback(self, ctx: _Context, data: str) -> TelegramMessage:
        match = _TOKEN.fullmatch(data) if isinstance(data, str) else None
        action = self.store.get("telegram-action:" + _hash(match[1])) if match else None
        if (
            not action
            or action.data.get("tenant") != ctx.tenant
            or action.data.get("chat_id") != ctx.chat_id
            or action.data.get("auth_epoch") != ctx.epoch
            or action.data.get("connection") != ctx.connection
            or action.data.get("expires_at", 0) <= self._now()
        ):
            return self._home(
                ctx,
                "This button expired or belongs to another session. Choose a fresh control below.",
            )
        if action.data.get("used"):
            raise _Applied
        kind, params = action.data["action"], action.data["params"]
        if kind in ("flights", "choose"):
            start = params.get("start")
            view = self._flights if kind == "flights" else self._choose
            return view(ctx, start if type(start) is int else 0)
        if kind == "detail":
            return self._detail(ctx, params["id"])
        if kind == "history":
            return self._history(ctx, params["id"], params.get("cursor"))
        if kind == "settings":
            return self._settings(ctx)
        if kind == "styles":
            return self._styles(ctx)
        if kind == "add":
            return self._add_help(ctx)
        if kind == "stop-confirm":
            return self._stop_confirm(ctx, params["id"])
        if kind == "rules":
            return self._rules(ctx, params["id"])
        if kind == "price-prompt":
            return self._price_prompt(ctx, params["id"], params["field"])
        if kind == "cancel":
            draft = self.store.get("telegram-draft:" + ctx.tenant)
            if (
                not draft
                or not params.get("draft_generation")
                or draft.data.get("generation") != params["draft_generation"]
            ):
                return self._home(
                    ctx, "This confirmation is no longer current. Your newer request is unchanged."
                )
            _BoundStore(self.store, ctx, self._now, action).commit([draft.update({"action": None})])
            return self._home(ctx, "Pending confirmation cancelled.")
        guarded = _BoundStore(self.store, ctx, self._now, action)
        guarded.guards()  # Check expiry and revision before invoking a use case.
        service = copy.copy(self.service)
        service.store = guarded
        if kind == "create":
            monitor = service.create_monitor(
                ctx.tenant,
                params["url"],
                "telegram:" + action.key.split(":", 1)[1],
                interval_seconds=params["interval"],
            )
            guarded.complete()
            return self._detail(ctx, monitor["id"], "Flight added. The first check is scheduled.")
        if kind == "status":
            service.set_status(ctx.tenant, params["monitor_id"], params["status"])
            guarded.complete()
            return self._detail(ctx, params["monitor_id"], "Flight updated.")
        if kind == "retry":
            service.retry_collection(ctx.tenant, params["monitor_id"])
            guarded.complete()
            return self._detail(ctx, params["monitor_id"], "A new collection attempt is scheduled.")
        if kind == "prefer":
            service.set_preferences(ctx.tenant, **params["changes"])
            guarded.complete()
            return self._saved(ctx, params["view"])
        if kind == "policy":
            service.set_policy(ctx.tenant, params["monitor_id"], AlertPolicy(**params["policy"]))
            guarded.complete()
            return self._rules(ctx, params["monitor_id"], "Alert rule saved.")
        return self._home(ctx)
