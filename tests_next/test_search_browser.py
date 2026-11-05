"""Search navigation boundaries, evidence freshness, and cumulative worker budget."""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import TimeoutException

from gfpt_next import public_browser
from gfpt_next.links import import_link
from gfpt_next.public_browser import PublicGoogleFlightsProvider
from gfpt_next.public_quotes import QuoteUnavailable


@pytest.fixture
def search_browser(monkeypatch):
    data = json.loads((Path(__file__).parent / "fixtures/search_nonstop_oneway_usd.json").read_text())
    target = import_link(data["search"]["url"], allow_search=True)
    driver = Mock()
    driver.current_url = target["url"]
    driver.find_element.return_value.text = data["search"]["body"] + data["booking"]["body"]
    sort, detail, select, booked = Mock(), Mock(), Mock(), Mock()
    sort.get_attribute.return_value = data["search"]["sort_label"]
    detail.find_element.return_value.find_element.return_value.get_attribute.return_value = data["search"]["rows"][0]["label"]

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
    assert reading.amount_minor == 19100 and reading.observed_offer.segments[0].legs[0].number == "2550"
    driver.get.assert_called_once_with(target["url"])
    detail.click.assert_called_once()
    select.click.assert_called_once()
    driver.quit.assert_called_once()
    assert "gfpt-next-public-" in str(launch.call_args.kwargs["options"].arguments)
    assert all("Continue to book" not in str(call) for call in driver.find_elements.call_args_list)


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
