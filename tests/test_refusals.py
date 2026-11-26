import ast
import logging
from pathlib import Path

import pytest

from fareflare.limits import FLIGHTS, ROUTE_SEARCHES, adults, currencies
from fareflare.refusals import (
    CHECKS,
    DAY,
    REASONS,
    RETIRED,
    LinkRefused,
    RefusalLog,
    refusal_report,
)
from fareflare.service import MonitoringService
from fareflare.store import Document


def test_every_check_belongs_to_a_reason_and_every_reason_is_used():
    assert set(CHECKS.values()) == set(REASONS)


@pytest.mark.parametrize("reason", sorted(REASONS))
def test_each_reason_is_one_plain_sentence_saying_what_to_do(reason):
    sentence = REASONS[reason]
    assert sentence.endswith(".") and "\n" not in sentence and len(sentence) <= 160
    # People never see the link's internals or a code.
    for word in ("tfs", "tfu", "gsas", "URL", "token", "parameter", "protobuf", "_"):
        assert word not in sentence
    assert any(verb in sentence for verb in ("send", "Send", "Open", "Choose"))


def test_a_limit_sentence_names_the_value_the_table_needs():
    assert adults(FLIGHTS) in REASONS["passengers"]
    assert currencies(FLIGHTS) in REASONS["currency"]
    assert adults(ROUTE_SEARCHES) in REASONS["search_passengers"]
    assert "Economy (exclude Basic)" in REASONS["search_cabin"]
    # Each states its value once, in about a hundred characters.
    for reason in ("currency", "country_unstated", "search_cabin"):
        assert len(REASONS[reason]) <= 105
    # Another country's Google with no location needs a different instruction.
    assert REASONS["country"] != REASONS["country_unstated"]
    assert "Search a one-way" not in REASONS["open_jaw"]


def test_a_refusal_shows_its_sentence_and_keeps_the_codes_apart():
    refusal = LinkRefused("searched_places")
    assert str(refusal) == REASONS["incomplete"]
    assert (refusal.reason, refusal.check) == ("incomplete", "searched_places")
    assert isinstance(refusal, ValueError)
    # An unknown check is a programming error that no surface mistakes for a refusal.
    with pytest.raises(KeyError):
        LinkRefused("anything else")


def test_refusals_are_counted_per_day_and_reported_for_thirty_days(store, clock):
    log = RefusalLog(store, lambda: clock[0])
    now = clock[0]
    for check in ("connections", "connections", "too_many_legs", "codes"):
        log.record(check)
    clock[0] = now - 29 * DAY
    log.record("cabin")
    clock[0] = now - 30 * DAY  # A day outside the window.
    log.record("cabin")
    report = refusal_report(store, now)
    assert report["total"] == 5
    assert report["reasons"][0] == {
        "reason": "connections",
        "sentence": REASONS["connections"],
        "count": 3,
        "checks": {"connections": 2, "too_many_legs": 1},
    }
    assert {entry["reason"]: entry["count"] for entry in report["reasons"]} == {
        "connections": 3,
        "incomplete": 1,
        "cabin": 1,
    }
    day = store.get(f"refusals:{now - now % DAY}")
    assert day.expires_at == now - now % DAY + 40 * DAY
    assert set(day.data) == {"day", "checks"}  # Codes and counts, never a link.


def test_a_lost_race_is_retried_and_running_out_of_retries_is_logged(store, clock, caplog):
    class Racing:
        def __init__(self, store, losses):
            self.store, self.losses = store, losses

        def get(self, key):
            return self.store.get(key)

        def commit(self, documents):
            if self.losses:
                self.losses -= 1
                # Another request counted first; this commit then conflicts.
                RefusalLog(self.store, lambda: clock[0]).record("cabin")
            self.store.commit(documents)

    RefusalLog(Racing(store, 1), lambda: clock[0]).record("cabin")
    assert refusal_report(store, clock[0])["total"] == 2
    with caplog.at_level(logging.WARNING, logger="fareflare.refusals"):
        RefusalLog(Racing(store, 5), lambda: clock[0]).record("cabin")
    assert refusal_report(store, clock[0])["total"] == 5
    assert "Refusal not counted check=cabin" in caplog.text


def test_counting_a_refusal_never_changes_the_answer(store, clock, caplog):
    class Broken:
        def record(self, check):
            raise RuntimeError("the table is unavailable")

    service = MonitoringService(store, lambda: clock[0], refusals=Broken())  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="fareflare.service"), pytest.raises(LinkRefused):
        service.accept_link("https://example.com/")
    assert "Refusal not counted check=not_google failure=RuntimeError" in caplog.text
    assert "unavailable" not in caplog.text  # The error's text is never logged.


def test_only_a_service_given_a_counter_counts(store, clock):
    with pytest.raises(LinkRefused):
        MonitoringService(store, lambda: clock[0]).accept_link("https://example.com/")
    assert refusal_report(store, clock[0])["total"] == 0
    counted = MonitoringService(
        store, lambda: clock[0], refusals=RefusalLog(store, lambda: clock[0])
    )
    with pytest.raises(LinkRefused):
        counted.accept_link("https://example.com/")
    assert refusal_report(store, clock[0])["reasons"][0]["checks"] == {"not_google": 1}


def _literal_checks() -> set[str]:
    """Every check written as a literal in the package: passed to LinkRefused, in an
    ``(unsupported, check)`` table, or assigned to a ``check`` variable."""
    found: set[str] = set()

    def strings(node):
        return {
            item.value
            for item in ast.walk(node)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }

    for path in (Path(__file__).parents[1] / "src" / "fareflare").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "LinkRefused":
                for argument in node.args:
                    found |= strings(argument)
            elif isinstance(node, ast.For) and "check" in {
                getattr(element, "id", None) for element in getattr(node.target, "elts", [])
            }:
                for pair in ast.walk(node.iter):
                    if isinstance(pair, ast.Tuple) and len(pair.elts) == 2:
                        found |= strings(pair.elts[1])
            elif isinstance(node, ast.Assign) and any(
                getattr(target, "id", None) == "check" for target in node.targets
            ):
                found |= strings(node.value)
    return found


def test_every_check_the_code_names_is_in_the_vocabulary():
    checks = _literal_checks()
    assert len(checks) > 40  # The scan finds the importer's, the collector's and others.
    assert checks <= set(CHECKS), checks - set(CHECKS)


def test_counts_outlive_a_check_a_later_release_retires(store, clock):
    day = clock[0] - clock[0] % DAY
    store.commit([Document(f"refusals:{day}", "refusals", {"day": day, "checks": {"gone": 4}})])
    RefusalLog(store, lambda: clock[0]).record("cabin")
    report = refusal_report(store, clock[0])
    assert report["total"] == 5
    retired = next(entry for entry in report["reasons"] if entry["reason"] == RETIRED)
    assert retired["checks"] == {"gone": 4} and retired["count"] == 4
