"""Exercise real collection, validation, persistence and delivery with fake Chrome."""

import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import (
    InvalidSessionIdException,
    TimeoutException,
    WebDriverException,
)

from fareflare import public_browser
from fareflare.links import import_link
from fareflare.public_browser import PublicGoogleFlightsProvider
from fareflare.store import Page
from fareflare.worker import Worker
from tests.test_links import change_token


@pytest.fixture
def pages():
    first = json.loads((Path(__file__).parent / "fixtures/public_booking_usd.json").read_text())[
        "page"
    ]
    second = copy.deepcopy(first)
    second["url"] = import_link(
        change_token(
            first["url"], lambda message: setattr(message.segments[0].legs[0], "number", "415")
        )
    )["url"]
    for key in ("body", "selected_text"):
        second[key] = second[key].replace("414", "415").replace("309", "279")
    second["flight_numbers"] = ["UA 415"]
    second["summary_prices"] = ["279 US dollars"]
    second["matching_options"] = ["Continue to book with United, Economy for 279 US dollars"]
    return first, second


@pytest.fixture
def browsers(monkeypatch, pages):
    drivers = []
    by_url = {import_link(page["url"])["url"]: page for page in pages}

    def launch(**kwargs):
        driver = Mock()
        driver.current_url = "about:blank"
        driver.page = None

        def navigate(url):
            driver.current_url = url
            driver.page = copy.deepcopy(by_url[url]) if url != "about:blank" else None

        def execute(script):
            return copy.deepcopy(driver.page) if script == public_browser._SNAPSHOT else None

        driver.get.side_effect = navigate
        driver.execute_script.side_effect = execute
        driver.find_element.side_effect = lambda *args: Mock(text=driver.page["body"])
        driver.find_elements.return_value = [Mock()]
        drivers.append(driver)
        return driver

    factory = Mock(side_effect=launch)
    monkeypatch.setattr(public_browser.webdriver, "Chrome", factory)

    class ImmediateWait:
        def __init__(self, driver, timeout):
            self.driver = driver

        def until(self, condition):
            result = condition(self.driver)
            if not result:
                raise TimeoutException()
            return result

    monkeypatch.setattr(public_browser, "WebDriverWait", ImmediateWait)
    return factory, drivers, by_url


def create_pair(service, pages):
    monitors = [
        service.create_monitor("alice", page["url"], f"watch-pair-{index}")
        for index, page in enumerate(pages)
    ]
    # Explicit order makes stale-page and failure-recovery regressions reproducible
    # with both SQLite and DynamoDB discovery indexes.
    for index, monitor in enumerate(monitors):
        doc = service.store.get("target:" + monitor["target_id"])
        service.store.commit([doc.update(doc.data, due=service._now() - 2 + index)])
    return monitors


def test_two_targets_share_one_browser_without_sharing_prices(
    service, clock, pages, browsers, monkeypatch
):
    monitors = create_pair(service, pages)
    factory, drivers, _ = browsers
    process = service.process_event_batch

    def after_browser_close(*args, **kwargs):
        assert drivers and all(driver.quit.call_count == 1 for driver in drivers)
        return process(*args, **kwargs)

    monkeypatch.setattr(service, "process_event_batch", after_browser_close)
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert result["collected"] == result["events_processed"] == result["alerts_suppressed"] == 2
    assert result["browser_launches"] == result["browser_reuses"] == 1
    factory.assert_called_once()
    drivers[0].quit.assert_called_once()
    assert [service.history("alice", monitor["id"])[0]["amount_minor"] for monitor in monitors] == [
        30900,
        27900,
    ]


def test_stale_first_page_cannot_be_recorded_for_second_target(service, clock, pages, browsers):
    monitors = create_pair(service, pages)
    factory, drivers, by_url = browsers
    first, second = pages
    # Simulate a source response retaining the old flight despite the new URL.
    by_url[import_link(second["url"])["url"]] = {**first, "url": second["url"]}
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert result["collected"] == 1 and result["failed"] == 1
    assert service.history("alice", monitors[1]["id"]) == []
    assert (
        service.store.get("target:" + monitors[1]["target_id"]).data["last_error"]
        == "flight_identity_mismatch"
    )
    factory.assert_called_once()
    drivers[0].quit.assert_called_once()


@pytest.mark.parametrize("failure", [TimeoutException("private"), WebDriverException("private")])
def test_worker_recovers_with_fresh_browser_after_collection_failure(
    service, clock, pages, browsers, failure
):
    monitors = create_pair(service, pages)
    factory, drivers, _ = browsers
    launch = factory.side_effect

    def fail_first(**kwargs):
        driver = launch(**kwargs)
        if len(drivers) == 1:
            driver.get.side_effect = failure
        return driver

    factory.side_effect = fail_first
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert result["collected"] == result["failed"] == 1
    assert result["browser_launches"] == 2 and result["browser_reuses"] == 0
    assert service.history("alice", monitors[0]["id"]) == []
    assert service.history("alice", monitors[1]["id"])[0]["amount_minor"] == 27900
    assert all(driver.quit.call_count == 1 for driver in drivers)


def test_browser_closes_when_worker_budget_stops_batch(service, clock, pages, browsers):
    create_pair(service, pages)
    _, drivers, _ = browsers
    calls = iter([0, 0, 31, 31, 31])
    result = Worker(
        service,
        PublicGoogleFlightsProvider(clock=lambda: clock[0]),
        monotonic=lambda: next(calls, 31),
    ).tick(max_targets=2)
    assert result["collected"] == 1 and result["browser_launches"] == 1
    assert len(drivers) == 1
    drivers[0].quit.assert_called_once()


def test_browser_closes_on_service_error(service, clock, pages, browsers, monkeypatch):
    monitors = create_pair(service, pages)
    _, drivers, _ = browsers
    original = service.store.get

    def fail_second(key):
        if key == "target:" + monitors[1]["target_id"] and drivers:
            raise RuntimeError("store unavailable")
        return original(key)

    monkeypatch.setattr(service.store, "get", fail_second)
    with pytest.raises(RuntimeError, match="store unavailable"):
        Worker(
            service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
        ).tick(max_targets=2)
    drivers[0].quit.assert_called_once()


def test_one_discovery_page_progresses_despite_gsi_head_lag(
    service, clock, pages, browsers, monkeypatch
):
    monitors = create_pair(service, pages)
    stale = [service.store.get("target:" + monitor["target_id"]) for monitor in monitors]
    original = service.store.page
    discovery_limits = []

    def lagging_page(partition, *args, **kwargs):
        if partition == "targets":
            limit = kwargs["limit"]
            discovery_limits.append(limit)
            # Keep returning the pre-collection head even after it is rescheduled.
            return Page(stale[:limit], None)
        return original(partition, *args, **kwargs)

    monkeypatch.setattr(service.store, "page", lagging_page)
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert discovery_limits == [2]
    assert result["collected"] == 2 and result["skipped"] == 0
    assert result["browser_launches"] == result["browser_reuses"] == 1
    assert [len(service.history("alice", monitor["id"])) for monitor in monitors] == [1, 1]


@pytest.mark.parametrize("stale_state", ["rescheduled", "moved", "deleted"])
def test_stale_candidate_does_not_block_distinct_due_target(
    service, clock, pages, browsers, monkeypatch, stale_state
):
    monitors = create_pair(service, pages)
    stale = [service.store.get("target:" + monitor["target_id"]) for monitor in monitors]
    original_page, original_get = service.store.page, service.store.get
    first = stale[0]
    if stale_state == "rescheduled":
        service.store.commit([first.update(first.data, due=clock[0] + 900)])
    elif stale_state == "moved":
        service.store.commit([first.update(first.data, partition="targets_blocked")])
    else:
        monkeypatch.setattr(
            service.store, "get", lambda key: None if key == first.key else original_get(key)
        )

    def lagging_page(partition, *args, **kwargs):
        return (
            Page(stale, None)
            if partition == "targets"
            else original_page(partition, *args, **kwargs)
        )

    monkeypatch.setattr(service.store, "page", lagging_page)
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert result["collected"] == result["skipped"] == 1
    assert result["browser_launches"] == 1 and result["browser_reuses"] == 0
    assert service.history("alice", monitors[0]["id"]) == []
    assert service.history("alice", monitors[1]["id"])[0]["amount_minor"] == 27900


def test_a_worker_reports_reloads_and_still_records_the_price(
    service, clock, pages, browsers, monkeypatch
):
    monitors = create_pair(service, pages)
    factory, _, _ = browsers
    monkeypatch.setattr(public_browser.time, "sleep", lambda seconds: None)
    launch, served = factory.side_effect, []

    def flaky_launch(**kwargs):
        driver = launch(**kwargs)
        navigate = driver.get.side_effect

        def flaky(url):
            navigate(url)
            served.append(url)
            # Google answers the first flight's first load with its error page.
            if served == [monitors[0]["target"]["url"]]:
                driver.page["body"] = "Oops, something went wrong.\nReload"

        driver.get.side_effect = flaky
        return driver

    factory.side_effect = flaky_launch
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert result["collected"] == 2 and result["failed"] == 0 and result["page_reloads"] == 1
    assert result["failure_codes"] == {}
    assert service.history("alice", monitors[0]["id"])[0]["amount_minor"] == 30900
    assert service.history("alice", monitors[1]["id"])[0]["amount_minor"] == 27900


def test_a_worker_whose_first_browser_dies_still_records_both_prices(
    service, clock, pages, browsers
):
    monitors = create_pair(service, pages)
    factory, drivers, _ = browsers
    launch = factory.side_effect

    def first_dies(**kwargs):
        driver = launch(**kwargs)
        if len(drivers) == 1:
            # As in a new Lambda environment: the first Chromium exits as it loads.
            driver.get.side_effect = InvalidSessionIdException("invalid session id")
        return driver

    factory.side_effect = first_dies
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert result["collected"] == 2 and result["failed"] == 0
    assert result["failure_codes"] == {}
    assert result["browser_launches"] == 2 and result["browser_restarts"] == 1
    assert result["browser_reuses"] == 1
    assert service.history("alice", monitors[0]["id"])[0]["amount_minor"] == 30900
    assert service.history("alice", monitors[1]["id"])[0]["amount_minor"] == 27900
    assert all(driver.quit.call_count == 1 for driver in drivers)


def test_idle_or_short_budget_worker_never_starts_browser(service, browsers):
    factory, _, _ = browsers
    worker = Worker(service, PublicGoogleFlightsProvider(), monotonic=lambda: 0)
    assert worker.tick(max_targets=20)["browser_launches"] == 0
    assert worker.tick(max_targets=20, budget_seconds=60)["browser_launches"] == 0
    factory.assert_not_called()


@pytest.mark.parametrize(
    "fixture,currency", [("selected_jpy.json", "JPY"), ("selected_two_adults.json", "USD")]
)
def test_browser_restarts_for_changed_pricing_context(
    service, clock, pages, browsers, fixture, currency
):
    first, _ = pages
    recorded = json.loads((Path(__file__).parent / "fixtures" / fixture).read_text())
    changed_page = recorded["page"]
    monitors = create_pair(service, [first, changed_page])
    factory, drivers, by_url = browsers
    by_url[import_link(changed_page["url"])["url"]] = changed_page
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert (
        result["collected"] == 2
        and result["browser_launches"] == 2
        and result["browser_reuses"] == 0
    )
    assert factory.call_count == 2
    assert all(driver.quit.call_count == 1 for driver in drivers)
    assert service.history("alice", monitors[1]["id"])[0]["currency"] == currency


def test_failed_state_reset_discards_browser_without_recording_old_price(
    service, clock, pages, browsers
):
    monitors = create_pair(service, pages)
    factory, drivers, _ = browsers
    launch = factory.side_effect

    def fail_reset(**kwargs):
        driver = launch(**kwargs)
        driver.delete_all_cookies.side_effect = WebDriverException("private")
        return driver

    factory.side_effect = fail_reset
    result = Worker(
        service, PublicGoogleFlightsProvider(clock=lambda: clock[0]), monotonic=lambda: 0
    ).tick(max_targets=2)
    assert result["collected"] == result["failed"] == 1
    assert service.history("alice", monitors[1]["id"]) == []
    assert result["browser_launches"] == 1 and result["browser_reuses"] == 0
    drivers[0].quit.assert_called_once()
