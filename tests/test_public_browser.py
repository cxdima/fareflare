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
from fareflare.public_quotes import QuoteUnavailable


@pytest.fixture
def browser(monkeypatch):
    page = json.loads((Path(__file__).parent / "fixtures/public_booking_usd.json").read_text())[
        "page"
    ]
    driver = Mock()
    driver.current_url = page["url"]
    driver.find_element.return_value.text = page["body"]
    driver.execute_script.return_value = page
    driver.find_elements.return_value = [Mock()]
    launch = Mock(return_value=driver)
    monkeypatch.setattr(public_browser.webdriver, "Chrome", launch)

    class ImmediateWait:
        def __init__(self, driver, timeout):
            self.driver = driver

        def until(self, condition):
            result = condition(self.driver)
            if not result:
                raise TimeoutException()
            return result

    monkeypatch.setattr(public_browser, "WebDriverWait", ImmediateWait)
    return driver, launch, import_link(page["url"])


def test_browser_uses_disposable_profile_and_only_expands_details(browser):
    driver, launch, target = browser
    reading = PublicGoogleFlightsProvider(clock=lambda: 42).collect(target)
    assert reading.amount_minor == 30900 and reading.observed_at == 42
    driver.get.assert_called_once_with(target["url"])
    driver.find_elements.return_value[0].click.assert_called_once()
    driver.quit.assert_called_once()
    options = launch.call_args.kwargs["options"]
    profile = next(
        arg.split("=", 1)[1] for arg in options.arguments if arg.startswith("--user-data-dir=")
    )
    assert "fareflare-public-" in profile
    assert not Path(profile).exists()
    assert "--no-sandbox" not in options.arguments
    driver.get_cookies.assert_not_called()
    driver.add_cookie.assert_not_called()


@pytest.mark.parametrize(
    "url,code",
    [
        ("https://accounts.google.com/login", "login_required"),
        ("https://consent.google.com/", "consent_required"),
        ("https://www.google.com/sorry/index", "challenge"),
        ("https://example.com/", "unexpected_page"),
    ],
)
def test_redirect_gates_stop_without_interaction_and_close_browser(browser, url, code):
    driver, _, target = browser
    driver.current_url = url
    with pytest.raises(QuoteUnavailable, match=code):
        PublicGoogleFlightsProvider().collect(target)
    driver.quit.assert_called_once()
    driver.find_elements.assert_not_called()


@pytest.mark.parametrize(
    "failure,code",
    [(TimeoutException("secret"), "timeout"), (WebDriverException("secret"), "browser_failed")],
)
def test_browser_errors_are_sanitized_and_closed(browser, failure, code):
    driver, _, target = browser
    driver.get.side_effect = failure
    with pytest.raises(QuoteUnavailable) as caught:
        PublicGoogleFlightsProvider().collect(target)
    assert caught.value.code == code
    assert "secret" not in str(caught.value)
    driver.quit.assert_called_once()


def test_unsupported_or_tampered_targets_never_start_browser(browser):
    _, launch, target = browser
    with pytest.raises(QuoteUnavailable, match="unsupported_itinerary"):
        PublicGoogleFlightsProvider().collect({**target, "adults": 3})
    with pytest.raises(QuoteUnavailable, match="itinerary_changed"):
        PublicGoogleFlightsProvider().collect({**target, "id": "changed"})
    launch.assert_not_called()


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("challenge", "challenge"),
        ("loading", "timeout"),
        ("no_details", "incomplete_trip_context"),
        ("no_numbers", "timeout"),
    ],
)
def test_partial_pages_are_not_prices(browser, scenario, code):
    driver, _, target = browser
    if scenario == "challenge":
        driver.find_element.return_value.text = "Our systems detected unusual traffic"
    elif scenario == "loading":
        driver.find_element.return_value.text = "Getting prices"
    elif scenario == "no_details":
        driver.find_elements.return_value = []
    else:
        driver.execute_script.return_value = {
            **driver.execute_script.return_value,
            "flight_numbers": [],
        }
    with pytest.raises(QuoteUnavailable, match=code):
        PublicGoogleFlightsProvider().collect(target)


def test_quit_failure_does_not_mask_valid_quote(browser):
    driver, _, target = browser
    driver.quit.side_effect = WebDriverException("cleanup")
    assert (
        PublicGoogleFlightsProvider("/test/chrome", "/test/driver").collect(target).amount_minor
        == 30900
    )


def test_lambda_browser_uses_container_process_settings_without_affecting_local_runs(
    browser, monkeypatch
):
    driver, launch, target = browser
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fareflare-test")
    assert PublicGoogleFlightsProvider().collect(target).amount_minor == 30900
    options = launch.call_args.kwargs["options"]
    assert {"--single-process", "--no-sandbox", "--disable-dev-shm-usage"} <= set(options.arguments)
    driver.quit.assert_called_once()
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME")
    PublicGoogleFlightsProvider().collect(target)
    assert "--single-process" not in launch.call_args.kwargs["options"].arguments


def test_startup_failure_is_distinguishable_and_removes_its_profile(browser):
    _, launch, target = browser
    launch.side_effect = WebDriverException("sensitive driver diagnostics")
    with pytest.raises(QuoteUnavailable, match="browser_start_failed") as failure:
        PublicGoogleFlightsProvider().collect(target)
    assert "sensitive" not in str(failure.value)
    profile = next(
        arg.split("=", 1)[1]
        for arg in launch.call_args.kwargs["options"].arguments
        if arg.startswith("--user-data-dir=")
    )
    assert not Path(profile).exists()


def test_browser_diagnostics_retain_phase_but_never_exception_details(browser, caplog):
    driver, _, target = browser
    driver.get.side_effect = WebDriverException(
        "net::ERR_CONNECTION_CLOSED url=private cookie=secret"
    )
    with pytest.raises(QuoteUnavailable, match="browser_failed"):
        PublicGoogleFlightsProvider().collect(target)
    assert "phase=navigation" in caplog.text and "ERR_CONNECTION_CLOSED" in caplog.text
    assert (
        "cookie" not in caplog.text and "private" not in caplog.text and "secret" not in caplog.text
    )


def test_unrelated_loading_text_does_not_block_verified_booking_price(browser):
    driver, _, target = browser
    driver.find_element.return_value.text += "\nPrice insights\nGetting prices"
    assert PublicGoogleFlightsProvider().collect(target).amount_minor == 30900


def test_timeout_diagnostic_identifies_phase_without_page_data(browser, caplog):
    driver, _, target = browser
    driver.find_element.return_value.text = "Getting prices private customer details"
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert "phase=summary" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    "body,signs,chars",
    [
        # The booking page rendered the trip but Google returned no booking options.
        (
            "Selected flights\nDenver to Dallas\nUA 414\nBooking options\n" + "x" * 280,
            "selected_flights,booking_options",
            300,
        ),
        # One of the two phrases the collector waits for, without the other.
        (
            "Selected flights\nBooking options\nLowest total price\n$309",
            "selected_flights,booking_options,lowest_total",
            0,
        ),
        ("We could not load prices. Try again later", "try_again", 0),
        ("Prices are currently unavailable", "unavailable", 0),
        ("Getting prices private customer details", "getting_prices", 0),
        ("", "none", 0),
        ("private customer details " * 20, "none", 500),
    ],
)
def test_a_summary_timeout_names_what_the_page_held_without_quoting_it(
    browser, caplog, body, signs, chars
):
    driver, _, target = browser
    driver.find_element.return_value.text = body
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert f"Public browser timeout phase=summary page={signs} chars={chars}" in caplog.text
    for private in ("Denver", "UA 414", "$309", "private", "customer", "Oops", "Prices are"):
        assert private not in caplog.text


def test_a_timeout_after_the_summary_keeps_its_own_phase(browser, polling_wait, caplog):
    driver, _, target = browser
    driver.execute_script.return_value = {
        **driver.execute_script.return_value,
        "flight_numbers": [],
    }
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert "Public browser timeout phase=evidence" in caplog.text
    assert "page=" not in caplog.text


# What Google Flights shows in place of a booking page when its own request fails.
ERROR_PAGE = (
    "Sign in\nOops, something went wrong.\nReload\nLanguage\u200bEnglish (United States)\n"
    "Location\u200bUnited States\nCurrency\u200bUSD\nPrivacy\nTerms"
)


@pytest.fixture
def pauses(monkeypatch):
    """Record the pause before each reload instead of sleeping."""
    taken = []
    monkeypatch.setattr(public_browser.time, "sleep", taken.append)
    return taken


def show_in_turn(driver, *bodies):
    """Each load of the link shows the next body, then the complete booking page."""
    complete = driver.find_element.return_value.text
    shown = iter(bodies)

    def load(_url):
        driver.find_element.return_value.text = next(shown, complete)

    driver.get.side_effect = load


@pytest.mark.parametrize("errors", [1, 2])
def test_googles_error_page_is_answered_by_loading_the_link_again(browser, pauses, caplog, errors):
    driver, _, target = browser
    show_in_turn(driver, *[ERROR_PAGE] * errors)
    with PublicGoogleFlightsProvider(clock=lambda: 42).batch() as batch:
        reading = batch.collect(target)
        assert batch.page_reloads == errors
    assert reading.amount_minor == 30900 and reading.evidence.identity_verified
    # Only ever the validated link, and nothing on the error page is pressed.
    assert [call.args for call in driver.get.call_args_list] == [(target["url"],)] * (errors + 1)
    driver.find_elements.return_value[0].click.assert_called_once()
    assert pauses == [1] * errors
    assert caplog.text == ""
    driver.quit.assert_called_once()


def test_an_error_page_that_stays_is_reported_at_once_as_googles_error(browser, pauses, caplog):
    driver, _, target = browser
    driver.find_element.return_value.text = ERROR_PAGE
    with PublicGoogleFlightsProvider().batch() as batch:
        with pytest.raises(QuoteUnavailable) as caught:
            batch.collect(target)
        assert batch.page_reloads == 2
    # A passing condition at Google, so the check is tried again later.
    assert caught.value.code == "provider_error" and caught.value.retryable
    assert driver.get.call_count == 3 and pauses == [1, 1]
    assert "Public browser provider error page reloads=2" in caplog.text
    assert "timeout" not in caplog.text
    for private in ("Oops", "Sign in", "United States", "google.com"):
        assert private not in caplog.text
    driver.find_elements.assert_not_called()
    driver.quit.assert_called_once()


def test_a_reloaded_page_that_never_shows_a_price_is_still_a_timeout(browser, pauses, caplog):
    driver, _, target = browser
    show_in_turn(driver, ERROR_PAGE, "Getting prices")
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert driver.get.call_count == 2
    assert "Public browser timeout phase=summary page=getting_prices chars=0" in caplog.text


def test_a_complete_page_is_never_reloaded_for_mentioning_an_error(browser, pauses):
    driver, _, target = browser
    driver.find_element.return_value.text += "\nSomething went wrong loading price insights"
    with PublicGoogleFlightsProvider(clock=lambda: 42).batch() as batch:
        assert batch.collect(target).amount_minor == 30900
        assert batch.page_reloads == 0
    driver.get.assert_called_once_with(target["url"])
    assert pauses == []


def test_reloading_stays_within_the_collection_deadline(browser, pauses, monkeypatch):
    driver, _, target = browser
    clock = [0.0]
    monkeypatch.setattr(public_browser.time, "monotonic", lambda: clock[0])
    driver.find_element.return_value.text = ERROR_PAGE
    # Every load is slow: the second reload gets what is left, and there is no third.
    driver.get.side_effect = lambda _: clock.__setitem__(0, clock[0] + 49.75)
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert driver.get.call_count == 3
    assert pauses == [1, 0.5]
    budgets = [call.args[0] for call in driver.set_page_load_timeout.call_args_list]
    assert budgets[-2:] == [35, 0.5]
    driver.quit.assert_called_once()


# What chromedriver reports when Chromium has exited under it.
BROWSER_GONE = InvalidSessionIdException(
    "invalid session id: session deleted as the browser has closed the connection\n"
    "from disconnected: not connected to DevTools\n  (Session info: chrome=146.0.7680.177)\n"
    "private https://www.google.com/travel/flights?tfs=secret"
)


def dead_browser(failure=BROWSER_GONE):
    """A browser that starts and then fails as the link is loaded."""
    dead = Mock()
    dead.get.side_effect = failure
    return dead


def test_a_browser_that_dies_before_its_first_page_is_started_again_once(browser, caplog):
    driver, launch, target = browser
    dead = dead_browser()
    launch.side_effect = [dead, driver]
    with PublicGoogleFlightsProvider(clock=lambda: 42).batch() as batch:
        reading = batch.collect(target)
        assert batch.browser_launches == 2 and batch.browser_restarts == 1
    assert reading.amount_minor == 30900 and reading.evidence.identity_verified
    # The dead browser and its profile are gone before the new one is used.
    dead.quit.assert_called_once()
    dead.find_element.assert_not_called()
    driver.get.assert_called_once_with(target["url"])
    profiles = [
        next(a for a in call.kwargs["options"].arguments if a.startswith("--user-data-dir="))
        for call in launch.call_args_list
    ]
    assert len(set(profiles)) == 2
    assert "Public browser restart attempt=2 reason=session_lost launch=" in caplog.text
    for private in ("secret", "google.com", "146.0"):
        assert private not in caplog.text
    driver.quit.assert_called_once()


def test_a_second_dead_browser_is_a_failure_not_a_third_start(browser, caplog):
    _, launch, target = browser
    browsers = [dead_browser(), dead_browser()]
    launch.side_effect = browsers
    with PublicGoogleFlightsProvider().batch() as batch:
        with pytest.raises(QuoteUnavailable, match="browser_failed"):
            batch.collect(target)
        assert batch.browser_launches == 2 and batch.browser_restarts == 1
    assert launch.call_count == 2
    assert caplog.text.count("Public browser restart attempt=2") == 1
    assert (
        "Public browser failure phase=navigation kind=InvalidSessionIdException "
        "reason=session_lost" in caplog.text
    )
    assert all(dead.quit.call_count == 1 for dead in browsers)


@pytest.mark.parametrize(
    "message,reason",
    [
        ("disconnected: not connected to DevTools", "disconnected"),
        ("unknown error: session deleted because of page crash\nfrom tab crashed", "tab_crashed"),
    ],
)
def test_other_signs_that_the_browser_is_gone_also_start_a_new_one(
    browser, caplog, message, reason
):
    driver, launch, target = browser
    launch.side_effect = [dead_browser(WebDriverException(message)), driver]
    assert PublicGoogleFlightsProvider(clock=lambda: 42).collect(target).amount_minor == 30900
    assert f"Public browser restart attempt=2 reason={reason} launch=" in caplog.text


@pytest.mark.parametrize(
    "failure,code",
    [
        (WebDriverException("unknown error: net::ERR_CONNECTION_RESET"), "browser_failed"),
        (WebDriverException("unknown error: cannot determine loading status"), "browser_failed"),
        (TimeoutException("timeout: Timed out receiving message from renderer"), "timeout"),
    ],
)
def test_a_browser_that_is_still_there_is_not_restarted(browser, caplog, failure, code):
    driver, launch, target = browser
    driver.get.side_effect = failure
    with PublicGoogleFlightsProvider().batch() as batch:
        with pytest.raises(QuoteUnavailable, match=code):
            batch.collect(target)
        assert batch.browser_launches == 1 and batch.browser_restarts == 0
    launch.assert_called_once()
    assert "restart" not in caplog.text


def test_a_restart_needs_time_left_on_the_collection_deadline(browser, monkeypatch, caplog):
    driver, launch, target = browser
    clock = [0.0]
    monkeypatch.setattr(public_browser.time, "monotonic", lambda: clock[0])

    def die_late(_url):
        clock[0] = 101.0
        raise BROWSER_GONE

    dead = dead_browser(die_late)
    launch.side_effect = [dead, driver]
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    launch.assert_called_once()
    assert "restart" not in caplog.text
    dead.quit.assert_called_once()


def test_a_reused_browser_that_dies_is_replaced_for_the_same_flight(browser, caplog):
    driver, launch, target = browser
    replacement = Mock()
    for name in ("current_url", "find_element", "execute_script", "find_elements"):
        setattr(replacement, name, getattr(driver, name))
    launch.side_effect = [driver, replacement]
    with PublicGoogleFlightsProvider(clock=lambda: 42).batch() as batch:
        assert batch.collect(target).amount_minor == 30900
        # The shared browser dies when the next flight's link is loaded.
        driver.get.side_effect = [None, BROWSER_GONE]
        assert batch.collect(target).amount_minor == 30900
        assert batch.browser_launches == 2 and batch.browser_restarts == 1
        assert batch.browser_reuses == 1
    replacement.get.assert_called_once_with(target["url"])
    driver.quit.assert_called_once()
    replacement.quit.assert_called_once()


def test_batch_is_lazy_and_closes_before_reuse_outside_scope(browser):
    _, launch, target = browser
    provider = PublicGoogleFlightsProvider()
    with provider.batch() as batch:
        launch.assert_not_called()
    with pytest.raises(ValueError, match="closed"):
        batch.collect(target)
    launch.assert_not_called()


def test_batch_reuses_browser_but_resets_document_and_preferences(browser):
    driver, launch, target = browser
    with PublicGoogleFlightsProvider().batch() as batch:
        batch.collect(target)
        driver.quit.assert_not_called()
        batch.collect(target)
        assert batch.browser_launches == batch.browser_reuses == 1
    launch.assert_called_once()
    assert [call.args[0] for call in driver.get.call_args_list] == [
        target["url"],
        "about:blank",
        target["url"],
    ]
    driver.delete_all_cookies.assert_called_once()
    assert any(
        "localStorage.clear" in call.args[0] and "sessionStorage.clear" in call.args[0]
        for call in driver.execute_script.call_args_list
    )
    driver.quit.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutException("private"),
        WebDriverException("private"),
        QuoteUnavailable("itinerary_changed"),
    ],
)
def test_batch_discards_failed_browser_before_next_target(browser, failure):
    driver, launch, target = browser
    driver.get.side_effect = [failure, None]
    with PublicGoogleFlightsProvider().batch() as batch:
        with pytest.raises(QuoteUnavailable):
            batch.collect(target)
        driver.quit.assert_called_once()
        assert batch.collect(target).amount_minor == 30900
        assert batch.browser_launches == 2 and batch.browser_reuses == 0
    assert launch.call_count == driver.quit.call_count == 2


def test_batch_has_hard_target_bound(browser):
    driver, launch, target = browser
    with PublicGoogleFlightsProvider().batch() as batch:
        for _ in range(20):
            assert batch.collect(target).amount_minor == 30900
        with pytest.raises(ValueError, match="exhausted"):
            batch.collect(target)
    launch.assert_called_once()
    driver.quit.assert_called_once()


def test_batches_on_one_provider_have_independent_lifetimes(browser):
    driver, launch, target = browser
    second = copy.deepcopy(driver)
    launch.side_effect = [driver, second]
    provider = PublicGoogleFlightsProvider()
    with provider.batch() as outer:
        outer.collect(target)
        with provider.batch() as inner:
            inner.collect(target)
        second.quit.assert_called_once()
        driver.quit.assert_not_called()
        assert outer.collect(target).amount_minor == 30900
        assert inner.browser_launches == outer.browser_launches == 1
        assert inner.browser_reuses == 0 and outer.browser_reuses == 1
    assert launch.call_count == 2
    driver.quit.assert_called_once()


@pytest.fixture
def polling_wait(monkeypatch):
    """Exercise changing DOM snapshots without sleeping or contacting Google."""
    timeouts = []

    class PollingWait:
        def __init__(self, driver, timeout):
            self.driver = driver
            timeouts.append(timeout)

        def until(self, condition):
            for _ in range(3):
                result = condition(self.driver)
                if result:
                    return result
            raise TimeoutException()

    monkeypatch.setattr(public_browser, "WebDriverWait", PollingWait)
    return timeouts


@pytest.mark.parametrize(
    "pending",
    [
        {"summary_prices": []},
        {"matching_options": []},
        {"summary_prices": ["310 US dollars"]},
        {"body": "Getting prices"},
    ],
)
def test_booking_updates_are_rechecked_until_the_whole_quote_is_verified(
    browser, polling_wait, pending
):
    driver, _, target = browser
    complete = driver.execute_script.return_value
    driver.execute_script.side_effect = [{**complete, **pending}, complete]
    reading = PublicGoogleFlightsProvider(clock=lambda: 42).collect(target)
    assert reading.amount_minor == 30900 and reading.evidence.identity_verified
    assert driver.execute_script.call_count == 2
    # Polling only reads the current document; it never reloads the page or books.
    driver.get.assert_called_once_with(target["url"])
    driver.find_elements.return_value[0].click.assert_called_once()
    driver.quit.assert_called_once()


@pytest.mark.parametrize(
    "pending",
    [
        {"summary_prices": []},
        {"matching_options": []},
        {"summary_prices": ["310 US dollars"]},
    ],
)
def test_a_booking_that_never_agrees_yields_no_price(browser, polling_wait, pending):
    driver, _, target = browser
    driver.execute_script.return_value = {**driver.execute_script.return_value, **pending}
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert driver.execute_script.call_count == 3
    driver.quit.assert_called_once()


@pytest.mark.parametrize(
    "changed,code",
    [
        ({"flight_numbers": ["UA 415"]}, "flight_identity_mismatch"),
        ({"summary_prices": ["309 Canadian dollars"]}, "unrecognized_price"),
        ({"matching_options": ["Continue anyway"]}, "unrecognized_fare"),
        ({"body": "Our systems detected unusual traffic"}, "challenge"),
    ],
)
def test_identity_currency_and_challenge_errors_do_not_wait_for_another_quote(
    browser, polling_wait, changed, code
):
    driver, _, target = browser
    complete = driver.execute_script.return_value
    driver.execute_script.side_effect = [{**complete, **changed}, complete]
    with pytest.raises(QuoteUnavailable, match=code):
        PublicGoogleFlightsProvider().collect(target)
    assert driver.execute_script.call_count == 1
    driver.quit.assert_called_once()


def test_selected_quote_deadline_includes_navigation_and_rejects_late_results(
    browser, polling_wait, monkeypatch
):
    driver, _, target = browser
    clock = [0.0]
    monkeypatch.setattr(public_browser.time, "monotonic", lambda: clock[0])
    driver.get.side_effect = lambda _: clock.__setitem__(0, 97.0)
    complete = driver.execute_script.return_value

    def capture(_):
        clock[0] = 101.0
        return complete

    driver.execute_script.side_effect = capture
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    assert polling_wait == [3.0, 3.0]
    assert driver.set_page_load_timeout.call_args.args == (3.0,)
    assert driver.set_script_timeout.call_args.args == (3.0,)
    driver.quit.assert_called_once()


def test_selected_quote_deadline_includes_browser_startup(browser, monkeypatch):
    driver, launch, target = browser
    clock = [0.0]
    monkeypatch.setattr(public_browser.time, "monotonic", lambda: clock[0])

    def slow_start(**kwargs):
        clock[0] = 101.0
        return driver

    launch.side_effect = slow_start
    with pytest.raises(QuoteUnavailable, match="timeout"):
        PublicGoogleFlightsProvider().collect(target)
    driver.get.assert_not_called()
    driver.execute_script.assert_not_called()
    driver.quit.assert_called_once()


def test_selected_details_disappearing_during_expansion_fail_with_a_safe_code(browser):
    driver, _, target = browser
    driver.find_elements.side_effect = [[Mock()], []]
    with pytest.raises(QuoteUnavailable, match="browser_failed"):
        PublicGoogleFlightsProvider().collect(target)
    driver.execute_script.assert_not_called()
    driver.quit.assert_called_once()
