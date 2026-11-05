"""Anonymous local browser adapter; never opens a personal Chrome profile."""
from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from urllib.parse import urlsplit

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from gfpt_next.public_quotes import (
    PageEvidence,
    QuoteUnavailable,
    supported_target,
    verified_reading,
)
from gfpt_next.service import Reading

log = logging.getLogger(__name__)


def _browser_failure_reason(error: Exception) -> str:
    """Extract only a known diagnostic label, never URLs or driver exception text."""
    message = str(error)
    for code in ("ERR_CONNECTION_CLOSED", "ERR_CONNECTION_RESET", "ERR_PROXY_CONNECTION_FAILED",
                 "ERR_NAME_NOT_RESOLVED", "ERR_CERT_AUTHORITY_INVALID", "ERR_HTTP_RESPONSE_CODE_FAILURE"):
        if "net::" + code in message:
            return code
    for phrase, label in (("tab crashed", "tab_crashed"), ("invalid session id", "session_lost"),
                          ("disconnected", "disconnected")):
        if phrase in message.lower():
            return label
    return "unclassified"

# Scope prices to the summary and the explicit eligibility marker. In particular,
# never select the cheapest dollar amount from the page or click a booking button.
_SNAPSHOT = r"""
const norm = s => s.replace(/\s+/g, ' ').trim();
const leaves = [...document.querySelectorAll('body *')].filter(e => !e.children.length);
const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
const totals = leaves.filter(e => norm(e.textContent) === 'Lowest total price' && visible(e));
const prices = totals.flatMap(e => [...(e.closest('[role="text"]')?.querySelectorAll('[aria-label]') || [])]
    .filter(visible).map(n => n.getAttribute('aria-label')));
const markers = leaves.filter(e => norm(e.textContent) === 'Cheapest option matching your search' && visible(e));
const matching = markers.flatMap(marker => {
    for (let node = marker.parentElement; node && node !== document.body; node = node.parentElement) {
        const buttons = [...node.querySelectorAll('button[aria-label^="Continue to book with "]')].filter(visible);
        if (buttons.length > 1) return [];
        if (buttons.length === 1) return [buttons[0].getAttribute('aria-label')];
    }
    return [];
});
const headings = [...document.querySelectorAll('h2')].filter(e => norm(e.textContent) === 'Selected flights');
// Observed selected-itinerary container; missing/changed structure fails closed.
const section = headings.length === 1 ? headings[0].closest('[jsname="QKujQ"]') : null;
return {
    url: location.href,
    body: document.body.innerText,
    summary_prices: prices,
    matching_options: matching,
    selected_text: (section?.innerText || '').split('\nBooking options\n')[0],
    flight_numbers: section ? [...section.querySelectorAll('[jsname="lVbzR"] span')]
        .filter(e => visible(e) && /^[A-Z0-9]{2,3} \d{1,5}[A-Z]?$/.test(norm(e.textContent)))
        .map(e => norm(e.textContent)) : [],
    departure_dates: section ? [...section.querySelectorAll('[data-outbound-date]')]
        .map(e => e.getAttribute('data-outbound-date')) : []
};
"""

_SEARCH_SNAPSHOT = r"""
const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
const buttons = [...document.querySelectorAll('button[aria-label]')].filter(visible);
const details = buttons.filter(e => e.getAttribute('aria-label').startsWith('Flight details.'));
const label = prefix => buttons.find(e => e.getAttribute('aria-label').startsWith(prefix))?.getAttribute('aria-label') || '';
return {
    url: location.href, body: document.body.innerText,
    sort_label: label('Sorted by'), stops_label: label('Nonstop, Stops'),
    passenger_label: label('1 passenger'),
    more_results: buttons.some(e => e.getAttribute('aria-label') === 'View more flights'),
    rows: details.map(e => {
        const row = e.closest('li');
        return {text: row?.innerText || '',
            label: row?.querySelector('[role="link"][aria-label^="From "]')?.getAttribute('aria-label') || '',
            prices: [...(row?.querySelectorAll('[role="text"][aria-label$=" US dollars"]') || [])]
                .filter(visible).map(n => n.getAttribute('aria-label'))};
    })
};
"""


@contextmanager
def anonymous_browser(chrome_binary: str | None = None, chromedriver: str | None = None):
    with tempfile.TemporaryDirectory(prefix="gfpt-next-public-") as profile:
        options = Options()
        for argument in ("--headless=new", "--disable-sync", "--disable-extensions",
                         "--no-first-run", "--lang=en-US", "--window-size=1280,1000",
                         f"--user-data-dir={profile}"):
            options.add_argument(argument)
        if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            # Match the stable Lambda runtime's process constraints. Keep each
            # invocation's profile private; never kill other browser processes.
            for argument in ("--no-sandbox", "--disable-dev-shm-usage", "--single-process",
                             "--disable-gpu", "--disable-software-rasterizer",
                             "--disable-crash-reporter"):
                options.add_argument(argument)
        if chrome_binary:
            options.binary_location = chrome_binary
        options.page_load_strategy = "eager"
        driver = None
        try:
            service = Service(executable_path=chromedriver) if chromedriver else Service()
            try:
                driver = webdriver.Chrome(service=service, options=options)
            except WebDriverException:
                raise QuoteUnavailable("browser_start_failed") from None
            driver.set_page_load_timeout(35)
            driver.set_script_timeout(10)
            yield driver
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except WebDriverException:
                    pass


def _check_page(driver) -> None:
    parts = urlsplit(driver.current_url)
    if parts.hostname == "consent.google.com":
        raise QuoteUnavailable("consent_required")
    if parts.hostname == "accounts.google.com":
        raise QuoteUnavailable("login_required")
    if parts.path.startswith("/sorry"):
        raise QuoteUnavailable("challenge")
    if (parts.scheme != "https" or parts.hostname not in ("google.com", "www.google.com")
            or parts.path not in ("/travel/flights", "/travel/flights/booking", "/travel/flights/search")):
        raise QuoteUnavailable("unexpected_page")


class PublicGoogleFlightsProvider:
    def __init__(self, chrome_binary: str | None = None, chromedriver: str | None = None,
                 clock: Callable[[], float] = time.time):
        self.chrome_binary, self.chromedriver, self.clock = chrome_binary, chromedriver, clock

    def collect(self, target: dict) -> Reading:
        # Individual calls remain disposable. Only an explicit batch shares a
        # browser, and each batch owns its own state even if providers are shared.
        with self.batch() as batch:
            return batch.collect(target)

    @contextmanager
    def batch(self):
        """Lazily reuse Chrome for at most 20 sequential, verified collections."""
        batch = _BrowserBatch(self)
        try:
            yield batch
        finally:
            batch.close()

    def _collect(self, target: dict, batch: _BrowserBatch) -> Reading:
        if target.get("kind") == "search":
            return self._collect_search(target, batch)
        supported_target(target)  # Unsupported targets never launch Chrome.
        # Revalidate the navigation URL before a browser sees it, even if callers
        # constructed a target themselves instead of using the importer.
        from gfpt_next.links import import_link
        checked = import_link(target["url"])
        if checked != target:
            raise QuoteUnavailable("itinerary_changed")
        phase = "browser_start"
        try:
            driver = batch.browser_for(target)
            phase = "navigation"
            driver.get(target["url"])

            def ready(browser):
                _check_page(browser)
                text = browser.find_element(By.TAG_NAME, "body").text
                if "unusual traffic" in text.lower():
                    raise QuoteUnavailable("challenge")
                # Insights and unrelated offers can still be loading after
                # the selected fare is ready. Validate that fare below.
                return "Lowest total price" in text and "Cheapest option matching your search" in text

            wait = WebDriverWait(driver, 30)
            phase = "summary"
            wait.until(ready)
            phase = "details"
            details = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label^="Flight details."]')
            details = [button for button in details if button.is_displayed()]
            if len(details) != len(target["segments"]):
                raise QuoteUnavailable("incomplete_trip_context")
            for index in range(len(details)):
                # Expanding a slice can replace sibling DOM nodes: reacquire each time.
                current = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label^="Flight details."]')
                [button for button in current if button.is_displayed()][index].click()

            def expanded(browser):
                _check_page(browser)
                snapshot = PageEvidence(**browser.execute_script(_SNAPSHOT))
                return snapshot if len(snapshot.flight_numbers) >= len(target["segments"]) else False

            phase = "evidence"
            evidence = wait.until(expanded)
            return verified_reading(target, evidence, int(self.clock()))
        except QuoteUnavailable:
            raise
        except TimeoutException:
            log.warning("Public browser timeout phase=%s", phase)
            raise QuoteUnavailable("timeout") from None
        except (WebDriverException, TypeError, KeyError) as exc:
            # WebDriver diagnostics can contain page data; return only stable codes.
            log.warning("Public browser failure phase=%s kind=%s reason=%s",
                        phase, type(exc).__name__, _browser_failure_reason(exc))
            raise QuoteUnavailable("browser_failed") from None

    def _collect_search(self, target: dict, batch: _BrowserBatch) -> Reading:
        from gfpt_next.links import import_link
        from gfpt_next.search_quotes import (
            SearchPageEvidence,
            verified_search_minimum,
            verified_search_reading,
        )
        if import_link(target["url"], allow_search=True) != target:
            raise QuoteUnavailable("itinerary_changed")
        deadline = time.monotonic() + 100

        def remaining() -> float:
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutException()
            return budget

        phase = "search_navigation"
        try:
            driver = batch.browser_for(target)
            driver.set_page_load_timeout(min(35, remaining()))
            driver.get(target["url"])

            def wait_for(condition):
                return WebDriverWait(driver, min(25, remaining())).until(condition)

            def page_ready(browser):
                _check_page(browser)
                if "unusual traffic" in browser.find_element(By.TAG_NAME, "body").text.lower():
                    raise QuoteUnavailable("challenge")
                return [button for button in browser.find_elements(
                    By.CSS_SELECTOR, 'button[aria-label^="Sorted by"]') if button.is_displayed()]

            sort = wait_for(page_ready)[0]
            if sort.get_attribute("aria-label") != "Sorted by price, Change sort order.":
                driver.set_page_load_timeout(min(20, remaining()))
                sort.click()
                choice = wait_for(lambda browser: [item for item in browser.find_elements(
                    By.CSS_SELECTOR, '[role="menuitemradio"]') if item.is_displayed() and item.text == "Price"])
                driver.set_page_load_timeout(min(20, remaining()))
                choice[0].click()
            phase = "search_results"
            expansions = 0

            def complete_results(browser):
                nonlocal expansions
                page_ready(browser)
                driver.set_script_timeout(min(10, remaining()))
                evidence = SearchPageEvidence(**browser.execute_script(_SEARCH_SNAPSHOT))
                if evidence.more_results:
                    if expansions >= 3:
                        raise QuoteUnavailable("unsupported_itinerary")
                    visible = [button for button in browser.find_elements(
                        By.CSS_SELECTOR, 'button[aria-label="View more flights"]') if button.is_displayed()]
                    if visible:
                        driver.set_page_load_timeout(min(20, remaining()))
                        visible[0].click()
                        expansions += 1
                    return False
                try:
                    verified_search_minimum(target, evidence)
                    return evidence
                except QuoteUnavailable as exc:
                    if exc.code in ("unexpected_page", "itinerary_changed"):
                        raise
                    return False

            search = wait_for(complete_results)
            phase = "search_selection"
            driver.set_script_timeout(min(10, remaining()))
            fresh = SearchPageEvidence(**driver.execute_script(_SEARCH_SNAPSHOT))
            if (verified_search_minimum(target, fresh) != verified_search_minimum(target, search)
                    or fresh.rows[0]["label"] != search.rows[0]["label"]):
                raise QuoteUnavailable("price_disagreement")
            details = [button for button in driver.find_elements(
                By.CSS_SELECTOR, 'li button[aria-label^="Flight details."]') if button.is_displayed()
                and button.find_element(By.XPATH, 'ancestor::li[1]').find_element(
                    By.CSS_SELECTOR, '[role="link"][aria-label^="From "]').get_attribute("aria-label") == search.rows[0]["label"]]
            if len(details) != 1:
                raise QuoteUnavailable("ambiguous_fare")
            driver.set_page_load_timeout(min(20, remaining()))
            details[0].click()
            selections = wait_for(lambda browser: [button for button in browser.find_elements(
                By.CSS_SELECTOR, 'button[aria-label="Select flight"]') if button.is_displayed()])
            if len(selections) != 1:
                raise QuoteUnavailable("ambiguous_fare")
            # This navigates to Google's quote page, never to an airline or a purchase.
            driver.set_page_load_timeout(min(20, remaining()))
            selections[0].click()
            phase = "search_booking"

            def booking_ready(browser):
                _check_page(browser)
                body = browser.find_element(By.TAG_NAME, "body").text
                return "Lowest total price" in body and "Cheapest option matching your search" in body

            wait_for(booking_ready)
            selected = import_link(driver.current_url)
            details = [button for button in driver.find_elements(
                By.CSS_SELECTOR, 'button[aria-label^="Flight details."]') if button.is_displayed()]
            if len(details) != 1:
                raise QuoteUnavailable("incomplete_trip_context")
            driver.set_page_load_timeout(min(20, remaining()))
            details[0].click()

            def expanded(browser):
                _check_page(browser)
                driver.set_script_timeout(min(10, remaining()))
                evidence = PageEvidence(**browser.execute_script(_SNAPSHOT))
                return evidence if evidence.flight_numbers else False

            booking = wait_for(expanded)
            remaining()
            return verified_search_reading(target, search, selected, booking, int(self.clock()))
        except QuoteUnavailable:
            raise
        except TimeoutException:
            log.warning("Public search timeout phase=%s", phase)
            raise QuoteUnavailable("timeout") from None
        except (WebDriverException, TypeError, KeyError, IndexError, ValueError) as exc:
            log.warning("Public search failure phase=%s kind=%s reason=%s",
                        phase, type(exc).__name__, _browser_failure_reason(exc))
            raise QuoteUnavailable("browser_failed") from None


class _BrowserBatch:
    """One worker's bounded browser lifetime, never shared across invocations."""

    def __init__(self, provider: PublicGoogleFlightsProvider):
        self.provider = provider
        self._stack = ExitStack()
        self._driver = None
        self._scope = None
        self._closed = False
        self._attempts = 0
        self.browser_launches = 0
        self.browser_reuses = 0

    def collect(self, target: dict) -> Reading:
        if self._closed or self._attempts >= 20:
            raise ValueError("Browser batch is closed or exhausted")
        self._attempts += 1
        try:
            return self.provider._collect(target, self)
        except BaseException:
            # Failed navigation/validation must not leave stale evidence or a
            # broken browser available to the next target. Also close on cancel.
            self._discard_browser()
            raise

    def browser_for(self, target: dict):
        scope = (target["market"], target["currency"], target["adults"],
                 target["cabin"], target["provider_query"].get("hl", "en-US"))
        if self._driver is not None and scope != self._scope:
            self._discard_browser()
        if self._driver is None:
            started = time.monotonic()
            for attempt in range(2):
                self.browser_launches += 1
                try:
                    self._driver = self._stack.enter_context(
                        anonymous_browser(self.provider.chrome_binary, self.provider.chromedriver))
                    break
                except QuoteUnavailable as exc:
                    elapsed = time.monotonic() - started
                    if attempt or exc.code != "browser_start_failed" or elapsed > 10:
                        raise
                    # The failed context has already removed its profile. Retry
                    # only fast startup failures, with a new isolated profile;
                    # callers retain their original cumulative deadline.
                    log.warning("Public browser startup retry attempt=2 reason=browser_start_failed elapsed_ms=%d",
                                max(0, int(elapsed * 1000)))
            assert self._driver is not None
            self._scope = scope
        else:
            # Clear the previous document and anonymous preference state before
            # loading the next explicit URL. A fresh validation still follows.
            _check_page(self._driver)
            self._driver.execute_script(
                "window.stop(); window.localStorage.clear(); window.sessionStorage.clear();")
            self._driver.delete_all_cookies()
            self._driver.set_page_load_timeout(5)
            self._driver.get("about:blank")
            self._driver.set_page_load_timeout(35)
            self.browser_reuses += 1
        return self._driver

    def _discard_browser(self) -> None:
        self._driver = None
        self._scope = None
        self._stack.close()

    def close(self) -> None:
        self._closed = True
        self._discard_browser()
