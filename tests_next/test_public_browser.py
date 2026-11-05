import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import TimeoutException, WebDriverException

from gfpt_next import public_browser
from gfpt_next.links import import_link
from gfpt_next.public_browser import PublicGoogleFlightsProvider
from gfpt_next.public_quotes import QuoteUnavailable


@pytest.fixture
def browser(monkeypatch):
    page = json.loads((Path(__file__).parent / "fixtures/public_booking_usd.json").read_text())["page"]
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
    profile = next(arg.split("=", 1)[1] for arg in options.arguments if arg.startswith("--user-data-dir="))
    assert "gfpt-next-public-" in profile
    assert not Path(profile).exists()
    assert "--no-sandbox" not in options.arguments
    driver.get_cookies.assert_not_called()
    driver.add_cookie.assert_not_called()


@pytest.mark.parametrize("url,code", [
    ("https://accounts.google.com/login", "login_required"),
    ("https://consent.google.com/", "consent_required"),
    ("https://www.google.com/sorry/index", "challenge"),
    ("https://example.com/", "unexpected_page"),
])
def test_redirect_gates_stop_without_interaction_and_close_browser(browser, url, code):
    driver, _, target = browser
    driver.current_url = url
    with pytest.raises(QuoteUnavailable, match=code):
        PublicGoogleFlightsProvider().collect(target)
    driver.quit.assert_called_once()
    driver.find_elements.assert_not_called()


@pytest.mark.parametrize("failure,code", [(TimeoutException("secret"), "timeout"),
                                          (WebDriverException("secret"), "browser_failed")])
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


@pytest.mark.parametrize("scenario,code", [("challenge", "challenge"), ("loading", "timeout"),
                                           ("no_details", "incomplete_trip_context"),
                                           ("no_numbers", "timeout")])
def test_partial_pages_are_not_prices(browser, scenario, code):
    driver, _, target = browser
    if scenario == "challenge":
        driver.find_element.return_value.text = "Our systems detected unusual traffic"
    elif scenario == "loading":
        driver.find_element.return_value.text = "Getting prices"
    elif scenario == "no_details":
        driver.find_elements.return_value = []
    else:
        driver.execute_script.return_value = {**driver.execute_script.return_value, "flight_numbers": []}
    with pytest.raises(QuoteUnavailable, match=code):
        PublicGoogleFlightsProvider().collect(target)


def test_quit_failure_does_not_mask_valid_quote(browser):
    driver, _, target = browser
    driver.quit.side_effect = WebDriverException("cleanup")
    assert PublicGoogleFlightsProvider("/test/chrome", "/test/driver").collect(target).amount_minor == 30900


def test_lambda_browser_uses_container_process_settings_without_affecting_local_runs(browser, monkeypatch):
    driver, launch, target = browser
    monkeypatch.setenv('AWS_LAMBDA_FUNCTION_NAME', 'gfpt-next-test')
    assert PublicGoogleFlightsProvider().collect(target).amount_minor == 30900
    options = launch.call_args.kwargs['options']
    assert {'--single-process', '--no-sandbox', '--disable-dev-shm-usage'} <= set(options.arguments)
    driver.quit.assert_called_once()
    monkeypatch.delenv('AWS_LAMBDA_FUNCTION_NAME')
    PublicGoogleFlightsProvider().collect(target)
    assert '--single-process' not in launch.call_args.kwargs['options'].arguments


def test_startup_failure_is_distinguishable_and_removes_its_profile(browser):
    _, launch, target = browser
    launch.side_effect = WebDriverException('sensitive driver diagnostics')
    with pytest.raises(QuoteUnavailable, match='browser_start_failed') as failure:
        PublicGoogleFlightsProvider().collect(target)
    assert 'sensitive' not in str(failure.value)
    profile = next(arg.split('=', 1)[1] for arg in launch.call_args.kwargs['options'].arguments
                   if arg.startswith('--user-data-dir='))
    assert not Path(profile).exists()


def test_browser_diagnostics_retain_phase_but_never_exception_details(browser, caplog):
    driver, _, target = browser
    driver.get.side_effect = WebDriverException('net::ERR_CONNECTION_CLOSED url=private cookie=secret')
    with pytest.raises(QuoteUnavailable, match='browser_failed'):
        PublicGoogleFlightsProvider().collect(target)
    assert 'phase=navigation' in caplog.text and 'ERR_CONNECTION_CLOSED' in caplog.text
    assert 'cookie' not in caplog.text and 'private' not in caplog.text and 'secret' not in caplog.text


def test_unrelated_loading_text_does_not_block_verified_booking_price(browser):
    driver, _, target = browser
    driver.find_element.return_value.text += '\nPrice insights\nGetting prices'
    assert PublicGoogleFlightsProvider().collect(target).amount_minor == 30900


def test_timeout_diagnostic_identifies_phase_without_page_data(browser, caplog):
    driver, _, target = browser
    driver.find_element.return_value.text = 'Getting prices private customer details'
    with pytest.raises(QuoteUnavailable, match='timeout'):
        PublicGoogleFlightsProvider().collect(target)
    assert 'phase=summary' in caplog.text
    assert 'private' not in caplog.text


def test_batch_is_lazy_and_closes_before_reuse_outside_scope(browser):
    _, launch, target = browser
    provider = PublicGoogleFlightsProvider()
    with provider.batch() as batch:
        launch.assert_not_called()
    with pytest.raises(ValueError, match='closed'):
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
    assert [call.args[0] for call in driver.get.call_args_list] == [target['url'], 'about:blank', target['url']]
    driver.delete_all_cookies.assert_called_once()
    assert any('localStorage.clear' in call.args[0] and 'sessionStorage.clear' in call.args[0]
               for call in driver.execute_script.call_args_list)
    driver.quit.assert_called_once()


@pytest.mark.parametrize('failure', [TimeoutException('private'), WebDriverException('private'),
                                   QuoteUnavailable('itinerary_changed')])
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
        with pytest.raises(ValueError, match='exhausted'):
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
