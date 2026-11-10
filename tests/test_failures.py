"""Unexpected errors are logged by type and code location, never by their message."""

import logging
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from fareflare import failures
from fareflare.contracts import CollectionFailure
from fareflare.failures import describe_failure
from fareflare.links import InvalidLink, import_link
from fareflare.service import MonitoringService
from fareflare.worker import Worker
from tests.test_service import observe

SECRET = "cookie=DO-NOT-LOG"


def _records(caplog, logger):
    return [record.getMessage() for record in caplog.records if record.name == logger]


def test_an_error_raised_outside_the_package_is_named_by_type_only():
    try:
        raise RuntimeError(SECRET)
    except RuntimeError as error:
        assert describe_failure(error) == "RuntimeError"
    assert describe_failure(RuntimeError(SECRET)) == "RuntimeError"  # Never raised at all.


def test_an_error_raised_inside_the_package_names_the_code_that_raised_it():
    with pytest.raises(InvalidLink) as caught:
        import_link("https://example.com/" + SECRET)
    described = describe_failure(caught.value)
    assert re.fullmatch(r"InvalidLink at links\.py:\d+ import_link", described)
    assert SECRET not in described


def test_the_trail_is_bounded_and_starts_where_the_error_was_raised(monkeypatch):
    # Treat this test module as package code so its own frames are reported.
    monkeypatch.setattr(failures, "_PACKAGE", Path(__file__).resolve().parent)

    def descend(depth):
        if not depth:
            raise KeyError(SECRET)
        descend(depth - 1)

    try:
        descend(9)
    except KeyError as error:
        described = describe_failure(error)
    name, trail = described.split(" at ")
    steps = trail.split(" < ")
    assert name == "KeyError" and len(steps) == failures._MAX_FRAMES
    assert all(re.fullmatch(r"test_failures\.py:\d+ descend", step) for step in steps)
    assert SECRET not in described


def test_an_unexpected_collector_error_is_logged_without_its_message(service, flight_url, caplog):
    service.create_monitor("alice", flight_url, "unexpected-error")
    provider = Mock()
    provider.collect.side_effect = KeyError(SECRET)
    with caplog.at_level(logging.WARNING, logger="fareflare"):
        result = Worker(service, provider).tick()
    assert result["failed"] == 1 and result["failure_codes"] == {"collection_failed": 1}
    [message] = _records(caplog, "fareflare.service")
    assert re.fullmatch(
        r"Unexpected collection error: KeyError at service\.py:\d+ collect_batch", message
    )
    assert SECRET not in caplog.text


def test_an_expected_failure_is_counted_by_code_and_not_logged(service, flight_url, caplog):
    service.create_monitor("alice", flight_url, "expected-failure")
    provider = Mock()
    provider.collect.side_effect = CollectionFailure("unrecognized_price")
    with caplog.at_level(logging.WARNING, logger="fareflare"):
        result = Worker(service, provider).tick()
    assert result["failed"] == 1 and result["failure_codes"] == {"unrecognized_price": 1}
    assert caplog.records == []
    # A clean run reports an empty mapping, so the field is always present.
    assert Worker(service, provider).tick()["failure_codes"] == {}


def test_a_raising_alert_channel_is_logged_without_its_message(service, flight_url, clock, caplog):
    monitor = service.create_monitor("alice", flight_url, "raising-sink")
    observe(service, monitor, clock)
    service.process_events()
    sink = Mock()
    sink.send.side_effect = RuntimeError(SECRET)
    with caplog.at_level(logging.WARNING, logger="fareflare"):
        assert service.deliver_due(sink) == 0
    [message] = _records(caplog, "fareflare.outbox")
    assert re.fullmatch(r"Alert delivery raised: RuntimeError at outbox\.py:\d+ \w+", message)
    assert SECRET not in caplog.text


def test_a_raising_notice_channel_is_logged_without_its_message(service, flight_url, caplog):
    service.set_preferences("alice", diagnostics=True)
    service.create_monitor("alice", flight_url, "raising-notice")
    provider = Mock()
    provider.collect.side_effect = CollectionFailure("challenge")
    assert service.collect_due(provider)["failed"] == 1
    channel = Mock()
    channel.notify.side_effect = RuntimeError(SECRET)
    with caplog.at_level(logging.WARNING, logger="fareflare"):
        assert service.deliver_notices(channel) == 0
    [message] = _records(caplog, "fareflare.service")
    assert re.fullmatch(r"Notice delivery raised: RuntimeError at service\.py:\d+ \w+", message)
    assert SECRET not in caplog.text


def test_a_raising_webhook_challenge_is_logged_without_its_message(store, clock, caplog):
    transport = Mock()
    transport.send.side_effect = OSError(SECRET)
    service = MonitoringService(store, lambda: clock[0], webhook_transport=transport)
    endpoint = service.webhooks.register(
        "alice", "https://hooks.example.com/flight", "raising-hook"
    )
    with caplog.at_level(logging.WARNING, logger="fareflare"):
        assert service.webhooks.challenge("alice", endpoint["id"])["delivered"] is False
    [message] = _records(caplog, "fareflare.webhooks")
    assert re.fullmatch(r"Webhook challenge raised: OSError at webhooks\.py:\d+ challenge", message)
    assert SECRET not in caplog.text
