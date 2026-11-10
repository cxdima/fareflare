"""Collection problems stay quiet by default; details and notices are an explicit opt-in."""

import json
from unittest.mock import Mock

import httpx
import pytest

from fareflare.accounts import Accounts
from fareflare.contracts import CollectionFailure, Reading
from fareflare.product_config import ProductConfig
from fareflare.service import FAILURE_NOTICE_THRESHOLD
from fareflare.telegram_accounts import TelegramConnections
from fareflare.webhooks import RoutedSink
from fareflare.worker import Worker
from tests.test_telegram_accounts import BOT_TOKEN, PASSWORD, bind
from tests.test_telegram_bot import _call, _press, native_bot  # noqa: F401


class Recorder:
    """A notice channel that records what it was asked to send."""

    def __init__(self, outcome=True):
        self.outcome, self.notices = outcome, []

    def send(self, delivery):
        return True

    def notify(self, notice):
        self.notices.append(notice)
        return self.outcome


def fail(service, clock, code="timeout", times=1):
    """Run failing checks, moving the clock past each retry delay."""
    provider = Mock()
    provider.collect.side_effect = CollectionFailure(code)
    failed = 0
    for _ in range(times):
        failed += service.collect_due(provider)["failed"]
        clock[0] += 3700
    return failed


def succeed(service, monitor, clock, amount=30000):
    provider = Mock()
    provider.collect.side_effect = lambda target: Reading(
        monitor["target_id"], amount, "USD", clock[0], "test-fixture"
    )
    return service.collect_due(provider)


def pending(service):
    return [doc.data for doc in service.store.query("notices_pending")]


def test_nothing_is_queued_for_accounts_that_did_not_opt_in(service, flight_url, clock):
    service.create_monitor("alice", flight_url, "quiet-default")
    assert fail(service, clock, times=FAILURE_NOTICE_THRESHOLD + 2) == FAILURE_NOTICE_THRESHOLD + 2
    assert pending(service) == []
    sink = Recorder()
    assert service.deliver_notices(sink) == 0 and sink.notices == []


def test_a_sustained_run_of_failures_queues_one_notice_then_one_recovery(
    service, flight_url, clock
):
    service.set_preferences("alice", diagnostics=True)
    monitor = service.create_monitor("alice", flight_url, "opted-in")
    service.create_monitor("bob", flight_url, "shares-the-check")  # did not opt in
    fail(service, clock, times=FAILURE_NOTICE_THRESHOLD - 1)
    assert pending(service) == []  # A few early retries are normal.
    fail(service, clock)
    notices = pending(service)
    assert [(n["tenant"], n["kind"], n["code"], n["failures"]) for n in notices] == [
        ("alice", "collection_failing", "timeout", FAILURE_NOTICE_THRESHOLD)
    ]
    fail(service, clock, times=3)
    assert len(pending(service)) == 1  # Not repeated on every later failure.
    view = service.get_monitor("alice", monitor["id"])
    assert view["last_error"] == "timeout"
    assert view["collection_failures"] == FAILURE_NOTICE_THRESHOLD + 3

    sink = Recorder()
    assert service.deliver_notices(sink) == 1
    assert sink.notices[0]["monitor"]["id"] == monitor["id"]
    assert service.deliver_notices(sink) == 0 and len(sink.notices) == 1

    assert succeed(service, monitor, clock)["collected"] == 1
    recovered = pending(service)
    assert [(n["tenant"], n["kind"]) for n in recovered] == [("alice", "collection_recovered")]
    assert service.get_monitor("alice", monitor["id"])["collection_failures"] == 0
    # A later ordinary success has nothing to announce.
    clock[0] += 3700
    succeed(service, monitor, clock, amount=29000)
    assert len(pending(service)) == 1


def test_a_blocked_check_is_reported_immediately(service, flight_url, clock):
    service.set_preferences("alice", diagnostics=True)
    service.create_monitor("alice", flight_url, "blocked-check")
    fail(service, clock, code="challenge")
    assert [(n["kind"], n["code"], n["failures"]) for n in pending(service)] == [
        ("collection_blocked", "challenge", 1)
    ]


def test_notices_respect_later_opt_out_muting_and_paused_flights(service, flight_url, clock):
    tenants = ("opted-out", "muted", "paused")
    for tenant in tenants:
        service.set_preferences(tenant, diagnostics=True)
    monitors = {
        tenant: service.create_monitor(tenant, flight_url, "notice-" + tenant) for tenant in tenants
    }
    fail(service, clock, code="challenge")
    assert len(pending(service)) == 3
    service.set_preferences("opted-out", diagnostics=False)
    service.set_preferences("muted", muted=True)
    service.set_status("paused", monitors["paused"]["id"], "paused")
    sink = Recorder()
    assert service.deliver_notices(sink) == 0 and sink.notices == []
    assert pending(service) == []  # Dropped, never held back for later.


def test_failed_sends_retry_a_bounded_number_of_times(service, flight_url, clock):
    service.set_preferences("alice", diagnostics=True)
    monitor = service.create_monitor("alice", flight_url, "retrying")
    fail(service, clock, code="challenge")
    sink = Recorder(outcome=False)
    for attempt in range(1, 4):
        assert service.deliver_notices(sink) == 0
        assert len(sink.notices) == attempt
        clock[0] += 301
    assert pending(service) == []
    assert service.deliver_notices(sink) == 0 and len(sink.notices) == 3

    # A channel that raises is treated as a failed attempt, never as a crash.
    service.retry_collection("alice", monitor["id"])
    fail(service, clock, code="challenge")
    broken = Mock()
    broken.notify.side_effect = RuntimeError("transport detail that must not escape")
    assert service.deliver_notices(broken) == 0
    broken.notify.assert_called_once()


def test_no_channel_means_nothing_is_sent_and_nothing_is_retried(service, flight_url, clock):
    service.set_preferences("alice", diagnostics=True)
    service.create_monitor("alice", flight_url, "no-channel")
    fail(service, clock, code="challenge")
    assert RoutedSink(service.webhooks).notify({}) is None
    assert service.deliver_notices(RoutedSink(service.webhooks)) == 0
    assert pending(service) == []
    assert service.deliver_notices(None) == 0  # Shadow mode has no channel either.


def test_worker_sends_notices_after_price_alerts(service, flight_url, clock):
    service.set_preferences("alice", diagnostics=True)
    service.create_monitor("alice", flight_url, "worker-notice")
    provider = Mock()
    provider.collect.side_effect = CollectionFailure("challenge")
    sink = Recorder()
    result = Worker(service, provider, sink).tick()
    assert result["failed"] == 1 and result["notices_sent"] == 1
    assert sink.notices[0]["kind"] == "collection_blocked"
    shadow = Worker(service, provider).tick()
    assert shadow["notices_sent"] == 0 and shadow["shadow"] is True


@pytest.fixture
def connected(service, store, clock):
    accounts = Accounts(store, ProductConfig(registration_mode="open"), lambda: clock[0])
    tenant = accounts.register("diagnostic-reader", PASSWORD)["account"]["id"]
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    connections = TelegramConnections(
        store,
        accounts,
        BOT_TOKEN,
        "fareflare_bot",
        "https://fareflare.test",
        transport=httpx.MockTransport(transport),
        clock=lambda: clock[0],
        service=service,
    )
    return connections, tenant, sent


def test_telegram_delivers_an_opted_in_notice_with_the_readers_settings(
    connected, service, flight_url, clock
):
    connections, tenant, sent = connected
    assert connections.notify({"tenant": tenant}) is None  # No chat connected yet.
    bind(connections, tenant)
    sent.clear()
    service.set_preferences(tenant, diagnostics=True, telegram_silent=True, locale="de-DE")
    service.create_monitor(tenant, flight_url, "telegram-notice")
    fail(service, clock, code="challenge")
    assert service.deliver_notices(RoutedSink(service.webhooks, connections)) == 1
    payload = sent[-1]
    assert payload["chat_id"] == "123" and payload["disable_notification"] is True
    assert payload["parse_mode"] == "HTML"
    assert "<b>⚠️ Price checks have stopped</b>" in payload["text"]
    assert "14.03.2027" in payload["text"] and "Diagnostic code: challenge" in payload["text"]
    assert connections.notify({"tenant": "not-an-account"}) is None
    assert connections.notify({"tenant": "acct_" + "0" * 32}) is None


def test_a_blocked_bot_is_final_and_other_telegram_errors_are_retried(
    service, store, clock, flight_url
):
    accounts = Accounts(store, ProductConfig(registration_mode="open"), lambda: clock[0])
    tenant = accounts.register("blocked-reader", PASSWORD)["account"]["id"]
    replies = [(200, {"ok": True})]

    def transport(request):
        status, body = replies[-1]
        return httpx.Response(status, json=body)

    connections = TelegramConnections(
        store,
        accounts,
        BOT_TOKEN,
        "fareflare_bot",
        "https://fareflare.test",
        transport=httpx.MockTransport(transport),
        clock=lambda: clock[0],
        service=service,
    )
    bind(connections, tenant)
    monitor = service.create_monitor(tenant, flight_url, "blocked-bot")
    notice = {
        "tenant": tenant,
        "kind": "collection_failing",
        "code": "timeout",
        "failures": 5,
        "monitor": service.get_monitor(tenant, monitor["id"]),
    }
    replies.append((403, {"ok": False, "error_code": 403}))
    assert connections.notify(notice) is True
    replies.append((500, {"ok": False, "error_code": 500}))
    assert connections.notify(notice) is False


def test_the_bot_explains_failures_plainly_and_shows_codes_only_on_request(
    native_bot,  # noqa: F811
    service,
    flight_url,
    clock,
):
    _, tenant, _ = native_bot
    monitor = service.create_monitor(tenant, flight_url, "bot-diagnostics")
    fail(service, clock, times=2)
    detail = _press(native_bot, _call(native_bot, "/flights"), "DEN → DFW · Mar 14, 2027 · UA 414")
    assert "The last check could not finish. Fareflare will try again." in detail.text
    assert "timeout" not in detail.text and "Diagnostic" not in detail.text
    assert "Diagnostic notices" not in _call(native_bot, "/settings").text

    service.set_preferences(tenant, diagnostics=True)
    detail = _press(native_bot, _call(native_bot, "/flights"), "DEN → DFW · Mar 14, 2027 · UA 414")
    assert "Diagnostic code: timeout · failed checks in a row: 2" in detail.text

    settings = _call(native_bot, "/settings")
    assert "Diagnostic notices: on" in settings.text
    off = _press(native_bot, settings, "Turn off diagnostic notices")
    assert "Diagnostic notices" not in off.text
    assert service.preferences(tenant)["diagnostics"] is False
    assert service.get_monitor(tenant, monitor["id"])["collection_status"] == "backoff"


def test_a_blocked_flight_tells_the_reader_what_to_do(native_bot, service, flight_url, clock):  # noqa: F811
    _, tenant, _ = native_bot
    service.create_monitor(tenant, flight_url, "bot-blocked")
    fail(service, clock, code="challenge")
    detail = _press(native_bot, _call(native_bot, "/flights"), "DEN → DFW · Mar 14, 2027 · UA 414")
    assert "Price checks have stopped. Choose Retry collection to try again." in detail.text
    assert "challenge" not in detail.text


def test_notice_delivery_stops_when_its_time_budget_is_spent(service, flight_url, clock):
    for tenant in ("first", "second", "third"):
        service.set_preferences(tenant, diagnostics=True)
        service.create_monitor(tenant, flight_url, "budget-" + tenant)
    fail(service, clock, code="challenge")
    sink = Recorder()
    allowed = iter([True, False])
    assert service.deliver_notices(sink, should_continue=lambda: next(allowed)) == 1
    assert len(sink.notices) == 1 and len(pending(service)) == 2
    assert service.deliver_notices(sink) == 2
