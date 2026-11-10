"""Search navigation boundaries, evidence freshness, and cumulative worker budget."""

import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import TimeoutException

from fareflare import public_browser
from fareflare.links import import_link
from fareflare.public_browser import PublicGoogleFlightsProvider
from fareflare.public_quotes import QuoteUnavailable


@pytest.fixture
def search_browser(monkeypatch):
    data = json.loads(
        (Path(__file__).parent / "fixtures/search_nonstop_oneway_usd.json").read_text()
    )
    target = import_link(data["search"]["url"], allow_search=True)
    driver = Mock()
    driver.current_url = target["url"]
    driver.find_element.return_value.text = data["search"]["body"] + data["booking"]["body"]
    sort, detail, select, booked = Mock(), Mock(), Mock(), Mock()
    sort.get_attribute.return_value = data["search"]["sort_label"]
    detail.find_element.return_value.find_element.return_value.get_attribute.return_value = data[
        "search"
    ]["rows"][0]["label"]

    def select_flight():
        driver.current_url = data["booking"]["url"]

    select.click.side_effect = select_flight
    elements = {
        'button[aria-label^="Sorted by"]': [sort],
        'li button[aria-label^="Flight details."]': [detail],
        'button[aria-label="Select flight"]': [select],
        'button[aria-label^="Flight details."]': [booked],
    }
    driver.find_elements.side_effect = lambda by, selector: elements.get(selector, [])
    driver.execute_script.side_effect = [data["search"], data["search"], data["booking"]]
    launch = Mock(return_value=driver)
    monkeypatch.setattr(public_browser.webdriver, "Chrome", launch)
    clock, waits = [0.0], []
    monkeypatch.setattr(public_browser.time, "monotonic", lambda: clock[0])

    class ImmediateWait:
        def __init__(self, browser, timeout):
            self.browser = browser
            waits.append(timeout)

        def until(self, condition):
            value = condition(self.browser)
            if not value:
                raise TimeoutException()
            return value

    monkeypatch.setattr(public_browser, "WebDriverWait", ImmediateWait)
    return data, target, driver, launch, detail, select, clock, waits


def test_search_browser_selects_only_verified_result_then_booking(search_browser):
    _, target, driver, launch, detail, select, _, _ = search_browser
    reading = PublicGoogleFlightsProvider(clock=lambda: 42).collect(target)
    assert (
        reading.amount_minor == 19100
        and reading.observed_offer.segments[0].legs[0].number == "2550"
    )
    driver.get.assert_called_once_with(target["url"])
    detail.click.assert_called_once()
    select.click.assert_called_once()
    driver.quit.assert_called_once()
    assert "fareflare-public-" in str(launch.call_args.kwargs["options"].arguments)
    assert all("Continue to book" not in str(call) for call in driver.find_elements.call_args_list)


@pytest.mark.parametrize("recovers", [True, False])
def test_search_loads_the_link_again_when_google_shows_its_error_page(
    search_browser, monkeypatch, caplog, recovers
):
    _, target, driver, _, detail, select, _, _ = search_browser
    pauses = []
    monkeypatch.setattr(public_browser.time, "sleep", pauses.append)
    body, controls = driver.find_element.return_value.text, driver.find_elements.side_effect
    # The error page has none of the controls a search page has.
    driver.find_element.return_value.text = "Sign in\nOops, something went wrong.\nReload"
    driver.find_elements.side_effect = lambda by, selector: []

    def load(_url):
        if recovers and driver.get.call_count == 2:
            driver.find_element.return_value.text = body
            driver.find_elements.side_effect = controls

    driver.get.side_effect = load
    provider = PublicGoogleFlightsProvider(clock=lambda: 42)
    if recovers:
        assert provider.collect(target).amount_minor == 19100
        detail.click.assert_called_once()
        select.click.assert_called_once()
        assert caplog.text == ""
    else:
        with pytest.raises(QuoteUnavailable) as caught:
            provider.collect(target)
        assert caught.value.code == "provider_error"
        assert "Public browser provider error page reloads=2" in caplog.text
        assert "Oops" not in caplog.text
        detail.click.assert_not_called()
        select.click.assert_not_called()
    loads = 2 if recovers else 3
    assert [call.args for call in driver.get.call_args_list] == [(target["url"],)] * loads
    assert pauses == [1] * (loads - 1)
    driver.quit.assert_called_once()


def test_search_cumulative_deadline_stops_before_selection(search_browser):
    data, target, driver, _, detail, select, clock, waits = search_browser

    def capture(_):
        clock[0] = 101
        return data["search"]

    driver.execute_script.side_effect = capture
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    detail.click.assert_not_called()
    select.click.assert_not_called()
    driver.quit.assert_called_once()
    assert all(0 < timeout <= 25 for timeout in waits)


def test_remaining_budget_bounds_each_wait_and_navigation(search_browser):
    data, target, driver, _, _, _, clock, waits = search_browser
    snapshots = iter([data["search"], data["search"], data["booking"]])

    def capture(_):
        clock[0] += 40
        return next(snapshots)

    driver.execute_script.side_effect = capture
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert min(waits) <= 20
    assert min(call.args[0] for call in driver.set_page_load_timeout.call_args_list) <= 20
    driver.quit.assert_called_once()


def test_reordered_rows_or_changed_first_result_are_not_selected(search_browser):
    data, target, driver, _, detail, select, _, _ = search_browser
    changed = copy.deepcopy(data["search"])
    changed["rows"][0], changed["rows"][1] = changed["rows"][1], changed["rows"][0]
    driver.execute_script.side_effect = [data["search"], changed]
    with pytest.raises(QuoteUnavailable, match="price_disagreement"):
        PublicGoogleFlightsProvider().collect(target)
    detail.click.assert_not_called()
    select.click.assert_not_called()
    driver.quit.assert_called_once()


def test_search_initial_sort_transition_waits_instead_of_selecting(search_browser):
    data, target, driver, _, detail, select, _, _ = search_browser
    changed = copy.deepcopy(data["search"])
    changed["rows"][0], changed["rows"][-1] = changed["rows"][-1], changed["rows"][0]
    driver.execute_script.side_effect = [changed]
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    detail.click.assert_not_called()
    select.click.assert_not_called()
    driver.quit.assert_called_once()


@pytest.fixture
def polling_wait(monkeypatch):
    class PollingWait:
        def __init__(self, browser, timeout):
            self.browser = browser

        def until(self, condition):
            for _ in range(3):
                value = condition(self.browser)
                if value:
                    return value
            raise TimeoutException()

    monkeypatch.setattr(public_browser, "WebDriverWait", PollingWait)


@pytest.mark.parametrize(
    "pending",
    [
        {"matching_options": []},
        {"summary_prices": ["190 US dollars"]},
        {"body": "Getting prices"},
    ],
)
def test_search_waits_for_matching_booking_evidence_without_repeating_selection(
    search_browser, polling_wait, pending
):
    data, target, driver, _, detail, select, _, _ = search_browser
    driver.execute_script.side_effect = [
        data["search"],
        data["search"],
        {**data["booking"], **pending},
        data["booking"],
    ]
    reading = PublicGoogleFlightsProvider(clock=lambda: 42).collect(target)
    assert reading.amount_minor == 19100
    assert reading.observed_offer.segments[0].legs[0].number == "2550"
    assert driver.execute_script.call_count == 4
    detail.click.assert_called_once()
    select.click.assert_called_once()
    driver.get.assert_called_once_with(target["url"])
    driver.quit.assert_called_once()


def test_search_price_change_is_not_recorded_without_agreement_with_results(
    search_browser, polling_wait
):
    data, target, driver, _, _, _, _, _ = search_browser
    repriced = {
        **data["booking"],
        "summary_prices": ["190 US dollars"],
        "matching_options": ["Continue to book with Frontier, Economy for 190 US dollars"],
    }
    driver.execute_script.side_effect = [
        data["search"],
        data["search"],
        repriced,
        repriced,
        repriced,
    ]
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert driver.execute_script.call_count == 5
    driver.quit.assert_called_once()


def test_search_challenge_after_selection_stops_before_booking_capture(search_browser):
    data, target, driver, _, _, select, _, _ = search_browser

    def challenge_after_selection():
        driver.current_url = data["booking"]["url"]
        driver.find_element.return_value.text = "Our systems detected unusual traffic"

    select.click.side_effect = challenge_after_selection
    with pytest.raises(QuoteUnavailable, match="challenge"):
        PublicGoogleFlightsProvider().collect(target)
    assert driver.execute_script.call_count == 2
    driver.quit.assert_called_once()
