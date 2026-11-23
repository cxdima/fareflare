"""A flight keeps its interval on a worker that wakes on a schedule.

The worker runs once a period. These tests run it the way the schedule does, with
runs that start a little early or late and checks that take time, and count the
runs between one check of a flight and the next.
"""

from unittest.mock import Mock

import pytest

from fareflare.contracts import CHECK_INTERVAL_SECONDS, RETRY_SECONDS, CollectionFailure, Reading
from fareflare.worker import Worker

PERIOD = 60
# How far from its minute each run starts, repeating; a cold start is the late one.
OFFSETS = (0, 1, 0, -1, 3, 0, 0, 2, -2, 0, 1)


def scheduled_runs(service, clock, provider, runs, period=PERIOD):
    """Run the worker on its schedule and return the numbers of the runs that checked."""
    first, checked = clock[0], []
    worker = Worker(service, provider)
    for number in range(runs):
        clock[0] = first + number * period + OFFSETS[number % len(OFFSETS)]
        result = worker.tick(max_targets=5, period_seconds=period)
        if result["collected"] or result["failed"]:
            checked.append(number)
    return checked


def pricing(clock, monitor, seconds):
    """A provider whose check takes ``seconds`` before it reads a price."""
    provider = Mock()

    def collect(target):
        clock[0] += seconds
        return Reading(monitor["target_id"], 30000, "USD", clock[0], "test-fixture")

    provider.collect.side_effect = collect
    return provider


@pytest.mark.parametrize("seconds", [3, 9, 40])
def test_a_flight_is_checked_every_ten_minutes_however_long_a_check_takes(
    service, flight_url, clock, seconds
):
    monitor = service.create_monitor("alice", flight_url, "ten-minutes")
    every = CHECK_INTERVAL_SECONDS // PERIOD
    checked = scheduled_runs(service, clock, pricing(clock, monitor, seconds), 6 * every + 1)
    assert checked == [0, every, 2 * every, 3 * every, 4 * every, 5 * every, 6 * every]
    assert every == 10


def test_a_longer_interval_is_kept_the_same_way(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "half-hour", interval_seconds=1800)
    assert scheduled_runs(service, clock, pricing(clock, monitor, 9), 91) == [0, 30, 60, 90]


@pytest.mark.parametrize("seconds", [1, 9, 40])
def test_a_failed_check_is_tried_again_fifteen_minutes_later_to_the_run(
    service, flight_url, clock, seconds
):
    service.create_monitor("alice", flight_url, "fifteen-minutes")
    failing = Mock()

    def collect(target):
        clock[0] += seconds
        raise CollectionFailure("timeout")

    failing.collect.side_effect = collect
    again = RETRY_SECONDS // PERIOD
    assert scheduled_runs(service, clock, failing, 3 * again + 1) == [
        0,
        again,
        2 * again,
        3 * again,
    ]
    assert again == 15


def test_a_check_whose_worker_stopped_is_tried_again_fifteen_minutes_later_to_the_run(
    service, flight_url, clock
):
    monitor = service.create_monitor("alice", flight_url, "stopped-worker")
    first = clock[0]
    dying = Mock()
    dying.collect.side_effect = SystemExit
    with pytest.raises(SystemExit):
        Worker(service, dying).tick(max_targets=5, period_seconds=PERIOD)
    again = RETRY_SECONDS // PERIOD
    checked = scheduled_runs(service, clock, pricing(clock, monitor, 9), again + 11)
    # The run that stopped was run 0; the next one to check the flight is run 15, and
    # from there the flight is back on its ten minutes.
    assert checked == [again, again + 10]
    assert (
        first + again * PERIOD
        <= service.get_monitor("alice", monitor["id"])["latest"]["observed_at"]
    )


def test_a_run_made_by_hand_takes_only_what_is_already_due(service, flight_url, clock):
    monitor = service.create_monitor("alice", flight_url, "run-by-hand")
    provider = pricing(clock, monitor, 9)
    worker = Worker(service, provider)
    assert worker.tick(max_targets=5)["collected"] == 1
    due = service.store.get("target:" + monitor["target_id"]).due
    clock[0] = due - 20
    # Twenty seconds early: a scheduled run takes it, because it is the nearest run.
    assert worker.tick(max_targets=5)["collected"] == 0
    assert worker.tick(max_targets=5, period_seconds=PERIOD)["collected"] == 1
    # More than half a period early belongs to the run after this one.
    clock[0] = service.store.get("target:" + monitor["target_id"]).due - 31
    assert worker.tick(max_targets=5, period_seconds=PERIOD)["collected"] == 0


def test_the_worker_refuses_a_period_that_is_not_a_schedule(service):
    worker = Worker(service, Mock())
    for period in (-1, 3601):
        with pytest.raises(ValueError, match="Invalid worker budget"):
            worker.tick(period_seconds=period)
    with pytest.raises(ValueError, match="from the past"):
        service.collect_batch(Mock(), early_seconds=-1)
