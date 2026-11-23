"""A failed check is run again after one fixed wait; a refusal by Google never stops a flight."""

import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from fareflare.contracts import RETRY_SECONDS, CollectionFailure, Reading
from fareflare.public_browser import PublicGoogleFlightsProvider
from fareflare.public_quotes import QuoteUnavailable
from fareflare.service import FAILURE_NOTICE_THRESHOLD, LEASE_SECONDS
from tests.test_public_browser import browser  # noqa: F401

SECOND_FLIGHT = json.loads(
    (Path(__file__).parent / "fixtures/selected_two_adults.json").read_text()
)["page"]["url"]


def refusing(code="challenge"):
    provider = Mock()
    provider.collect.side_effect = CollectionFailure(code)
    return provider


def pending(service):
    return [doc.data for doc in service.store.query("notices_pending")]


def target_of(service, monitor):
    return service.store.get("target:" + monitor["target_id"])


@pytest.mark.parametrize("code", sorted(CollectionFailure.REFUSED))
def test_a_refusal_is_retried_after_the_wait_and_never_stops_the_flight(
    service, flight_url, clock, code
):
    assert CollectionFailure(code).retryable
    service.set_preferences("alice", diagnostics=True)
    monitor = service.create_monitor("alice", flight_url, "refused-" + code)
    assert service.collect_due(refusing(code))["failed"] == 1
    target = target_of(service, monitor)
    assert target.partition == "targets"
    assert target.due == clock[0] + RETRY_SECONDS == clock[0] + 15 * 60
    view = service.get_monitor("alice", monitor["id"])
    assert view["collection_status"] == "retrying" and view["last_error"] == code
    assert view["next_check_at"] == target.due
    assert pending(service) == []  # One refusal is not worth a notice.
    with pytest.raises(ValueError, match="Only blocked"):
        service.retry_collection("alice", monitor["id"])  # Nothing to retry: it is queued.


def test_a_run_of_refusals_keeps_the_same_wait_reports_once_and_recovers(
    service, flight_url, clock
):
    service.set_preferences("alice", diagnostics=True)
    monitor = service.create_monitor("alice", flight_url, "refused-run")
    waits = []
    for _ in range(FAILURE_NOTICE_THRESHOLD + 1):
        assert service.collect_due(refusing())["failed"] == 1
        target = target_of(service, monitor)
        assert target.partition == "targets"
        waits.append(target.due - clock[0])
        clock[0] = target.due
    # The wait does not grow, however many checks fail in a row.
    assert waits == [RETRY_SECONDS] * (FAILURE_NOTICE_THRESHOLD + 1)
    assert [(n["kind"], n["code"], n["failures"]) for n in pending(service)] == [
        ("collection_failing", "challenge", FAILURE_NOTICE_THRESHOLD)
    ]

    provider = Mock()
    provider.collect.side_effect = lambda target: Reading(
        monitor["target_id"], 30000, "USD", clock[0], "test-fixture"
    )
    assert service.collect_due(provider)["collected"] == 1
    assert {n["kind"] for n in pending(service)} == {"collection_failing", "collection_recovered"}
    view = service.get_monitor("alice", monitor["id"])
    assert view["collection_status"] == "ready" and view["collection_failures"] == 0


@pytest.mark.parametrize("code", sorted(CollectionFailure.REFUSED))
def test_a_refusal_ends_the_run_but_other_failures_do_not(service, flight_url, clock, code):
    service.create_monitor("alice", flight_url, "first-flight")
    service.create_monitor("alice", SECOND_FLIGHT, "second-flight")
    timing_out = refusing("timeout")
    assert service.collect_due(timing_out)["failed"] == 2
    assert timing_out.collect.call_count == 2
    clock[0] += 3700

    refused = refusing(code)
    assert service.collect_due(refused) == {"collected": 0, "failed": 1, "skipped": 0}
    assert refused.collect.call_count == 1
    # The flight left waiting is checked by the next run.
    assert service.collect_due(refused)["failed"] == 1
    assert refused.collect.call_count == 2
    assert service.collect_due(refused) == {"collected": 0, "failed": 0, "skipped": 0}


@pytest.mark.parametrize("code", sorted(CollectionFailure.CODES - CollectionFailure.BLOCKING))
def test_every_failure_that_can_pass_waits_the_same_time(service, flight_url, clock, code):
    monitor = service.create_monitor("alice", flight_url, "same-wait-" + code)
    for _ in range(8):
        assert service.collect_due(refusing(code))["failed"] == 1
        target = target_of(service, monitor)
        assert target.partition == "targets" and target.due == clock[0] + RETRY_SECONDS
        # Not a second earlier: the flight is left alone until its retry is due.
        clock[0] = target.due - 1
        assert service.collect_due(refusing(code)) == {"collected": 0, "failed": 0, "skipped": 0}
        clock[0] = target.due


def test_a_check_whose_worker_stopped_is_run_again_after_the_same_wait(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "worker-stopped")
    started = clock[0]
    dying = Mock()
    # Not an error a check can report: the process running it is gone.
    dying.collect.side_effect = SystemExit
    with pytest.raises(SystemExit):
        service.collect_due(dying)
    target = target_of(service, monitor)
    assert target.partition == "targets" and target.due == started + RETRY_SECONDS
    # Nothing was settled, so the flight shows no failure of its own.
    assert target.data["lease_token"] and target.data.get("failures", 0) == 0

    provider = Mock()
    provider.collect.side_effect = lambda target: Reading(
        monitor["target_id"], 30000, "USD", clock[0], "test-fixture"
    )
    # Once the lease has run out the flight is still not asked for before its retry.
    clock[0] = started + LEASE_SECONDS + 1
    assert service.collect_due(provider) == {"collected": 0, "failed": 0, "skipped": 0}
    clock[0] = started + RETRY_SECONDS
    assert service.collect_due(provider)["collected"] == 1
    view = service.get_monitor("alice", monitor["id"])
    assert view["collection_status"] == "ready" and view["latest"]["amount_minor"] == 30000
    # From here the flight is back on its own interval.
    assert target_of(service, monitor).due == clock[0] + view["interval_seconds"]


@pytest.mark.parametrize(
    "url,body,code,signal",
    [
        ("https://www.google.com/sorry/index?continue=secret", None, "challenge", "sorry_page"),
        (None, "Our systems detected unusual traffic. secret", "challenge", "unusual_traffic"),
        ("https://consent.google.com/ml?continue=secret", None, "consent_required", "consent_page"),
        (
            "https://accounts.google.com/signin?continue=secret",
            None,
            "login_required",
            "sign_in_page",
        ),
    ],
)
def test_a_refusal_is_logged_with_fixed_labels_only(
    browser,  # noqa: F811
    caplog,
    url,
    body,
    code,
    signal,
):
    driver, _, target = browser
    if url:
        driver.current_url = url
    if body:
        driver.find_element.return_value.text = body
    with (
        caplog.at_level(logging.WARNING, logger="fareflare"),
        pytest.raises(QuoteUnavailable) as caught,
    ):
        PublicGoogleFlightsProvider().collect(target)
    assert caught.value.code == code and caught.value.retryable
    assert f"Public browser refused code={code} signal={signal} phase=summary elapsed_ms=" in (
        caplog.text
    )
    assert "secret" not in caplog.text and "google.com" not in caplog.text
    driver.quit.assert_called_once()
