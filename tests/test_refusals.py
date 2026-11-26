import pytest

from fareflare.refusals import (
    CHECKS,
    DAY,
    REASONS,
    LinkRefused,
    record_refusal,
    refusal_report,
)
from fareflare.store import Document


def test_every_check_belongs_to_a_reason_and_every_reason_is_used():
    assert set(CHECKS.values()) == set(REASONS)


@pytest.mark.parametrize("reason", sorted(REASONS))
def test_each_reason_is_one_plain_sentence_saying_what_to_do(reason):
    sentence = REASONS[reason]
    assert sentence.endswith(".") and "\n" not in sentence and len(sentence) <= 180
    # People never see the link's internals or a code.
    for word in ("tfs", "tfu", "URL", "token", "parameter", "protobuf", "_"):
        assert word not in sentence
    assert any(verb in sentence for verb in ("send", "Send", "Open", "Choose"))


def test_a_refusal_shows_its_sentence_and_keeps_the_codes_apart():
    refusal = LinkRefused("searched_places")
    assert str(refusal) == REASONS["incomplete"]
    assert (refusal.reason, refusal.check) == ("incomplete", "searched_places")
    assert isinstance(refusal, ValueError)
    with pytest.raises(KeyError):
        LinkRefused("anything else")


def test_refusals_are_counted_per_day_and_reported_for_thirty_days(store, clock):
    now = clock[0]
    for check in ("connections", "connections", "too_many_legs", "codes"):
        record_refusal(store, now, check)
    record_refusal(store, now - 29 * DAY, "cabin")
    record_refusal(store, now - 30 * DAY, "cabin")  # A day outside the window.
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


def test_a_check_renamed_by_a_later_release_is_left_out_of_the_report(store, clock):
    now = clock[0]
    key = f"refusals:{now - now % DAY}"
    store.commit([Document(key, "refusals", {"day": now - now % DAY, "checks": {"gone": 4}})])
    record_refusal(store, now, "cabin")
    assert refusal_report(store, now)["total"] == 1


def test_a_lost_race_is_retried_and_a_lost_count_never_fails_the_request(store, clock):
    class Racing:
        def __init__(self, store, losses):
            self.store, self.losses = store, losses

        def get(self, key):
            return self.store.get(key)

        def commit(self, documents):
            if self.losses:
                self.losses -= 1
                # Another request counted first; this commit then conflicts.
                record_refusal(self.store, clock[0], "cabin")
            self.store.commit(documents)

    record_refusal(Racing(store, 1), clock[0], "cabin")
    assert refusal_report(store, clock[0])["total"] == 2
    record_refusal(Racing(store, 5), clock[0], "cabin")  # Gives up quietly after three.
    assert refusal_report(store, clock[0])["total"] == 5
