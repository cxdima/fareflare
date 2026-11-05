"""Retry only a fast Chrome startup failure, before navigation or quote capture."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import WebDriverException

from gfpt_next import public_browser
from gfpt_next.public_browser import PublicGoogleFlightsProvider
from gfpt_next.public_quotes import QuoteUnavailable

TARGET = {"market": "US", "currency": "USD", "adults": 1, "cabin": 1, "provider_query": {}}


def profile_from(options):
    return Path(next(arg.split("=", 1)[1] for arg in options.arguments if arg.startswith("--user-data-dir=")))


def test_fast_failed_first_launch_retries_with_fresh_profile_and_counts_both(monkeypatch, caplog):
    profiles, clock = [], [0.0]
    driver = Mock()

    def launch(**kwargs):
        profile = profile_from(kwargs["options"])
        assert profile.is_dir()
        if profiles:
            assert not profiles[0].exists()
            assert profile != profiles[0]
        profiles.append(profile)
        if len(profiles) == 1:
            clock[0] = 3.4
            raise WebDriverException("private driver diagnostics; cookie=secret")
        return driver

    monkeypatch.setattr(public_browser.webdriver, "Chrome", launch)
    monkeypatch.setattr(public_browser.time, "monotonic", lambda: clock[0])
    with PublicGoogleFlightsProvider().batch() as batch:
        assert batch.browser_for(TARGET) is driver
        assert batch.browser_launches == 2 and batch.browser_reuses == 0
        driver.get.assert_not_called()
    driver.quit.assert_called_once()
    assert len(profiles) == 2 and all(not profile.exists() for profile in profiles)
    assert "startup retry attempt=2 reason=browser_start_failed elapsed_ms=3400" in caplog.text
    assert "private" not in caplog.text and "secret" not in caplog.text


def test_two_startup_failures_stop_and_remove_both_profiles(monkeypatch, caplog):
    profiles = []

    def launch(**kwargs):
        profiles.append(profile_from(kwargs["options"]))
        raise WebDriverException("private startup diagnostics")

    monkeypatch.setattr(public_browser.webdriver, "Chrome", launch)
    monkeypatch.setattr(public_browser.time, "monotonic", lambda: 0.0)
    with PublicGoogleFlightsProvider().batch() as batch:
        with pytest.raises(QuoteUnavailable, match="browser_start_failed"):
            batch.browser_for(TARGET)
        assert batch.browser_launches == 2 and batch.browser_reuses == 0
    assert len(profiles) == 2 and all(not profile.exists() for profile in profiles)
    assert caplog.text.count("startup retry") == 1
    assert "private" not in caplog.text


@pytest.mark.parametrize("elapsed,expected_attempts", [(10.0, 2), (10.001, 1), (35.0, 1)])
def test_slow_initial_startup_does_not_spend_time_on_retry(monkeypatch, caplog, elapsed, expected_attempts):
    clock, profiles = [0.0], []

    def launch(**kwargs):
        profiles.append(profile_from(kwargs["options"]))
        clock[0] = elapsed
        raise WebDriverException("startup failed")

    monkeypatch.setattr(public_browser.webdriver, "Chrome", launch)
    monkeypatch.setattr(public_browser.time, "monotonic", lambda: clock[0])
    with PublicGoogleFlightsProvider().batch() as batch:
        with pytest.raises(QuoteUnavailable, match="browser_start_failed"):
            batch.browser_for(TARGET)
        assert batch.browser_launches == expected_attempts
    assert len(profiles) == expected_attempts
    assert all(not profile.exists() for profile in profiles)
    assert ("startup retry" in caplog.text) is (expected_attempts == 2)


@pytest.mark.parametrize("failure", [QuoteUnavailable("challenge"), QuoteUnavailable("browser_failed"),
                                   QuoteUnavailable("timeout"), RuntimeError("local failure")])
def test_non_startup_failures_never_retry(monkeypatch, caplog, failure):
    factory = Mock(side_effect=failure)
    monkeypatch.setattr(public_browser, "anonymous_browser", factory)
    with PublicGoogleFlightsProvider().batch() as batch:
        with pytest.raises(type(failure)) as caught:
            batch.browser_for(TARGET)
        assert caught.value is failure
        assert batch.browser_launches == 1
    factory.assert_called_once()
    assert "startup retry" not in caplog.text
