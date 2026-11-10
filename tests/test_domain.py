import pytest

from fareflare.domain import AlertPolicy, evaluate


def test_small_drops_accumulate_against_last_queued_alert():
    policy = AlertPolicy(min_drop_minor=5000)
    state, reason = evaluate(policy, {}, 50000)
    assert reason == "tracking_started"
    state, reason = evaluate(policy, state, 48000)
    assert reason is None
    state, reason = evaluate(policy, state, 46000)
    assert reason is None
    state, reason = evaluate(policy, state, 45000)
    assert reason == "new_low"


def test_price_rise_and_return_do_not_create_false_new_lows():
    state = {}
    reasons = []
    for amount in [50000, 40000, 50000, 40000, 35000]:
        state, reason = evaluate(AlertPolicy(), state, amount)
        reasons.append(reason)
    assert reasons == ["tracking_started", "new_low", None, None, "new_low"]


def test_threshold_crossing_rearms_after_rebound():
    policy, state = AlertPolicy(kind="below_price", threshold_minor=40000), {}
    reasons = []
    for amount in [50000, 40000, 39000, 50000, 40000]:
        state, reason = evaluate(policy, state, amount)
        reasons.append(reason)
    assert reasons == [None, "below_price", None, None, "below_price"]


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, "300"])
def test_invalid_money_is_rejected(amount):
    with pytest.raises(ValueError):
        evaluate(AlertPolicy(), {}, amount)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "bad"},
        {"min_drop_minor": -1},
        {"kind": "below_price"},
        {"kind": "below_price", "threshold_minor": 0},
    ],
)
def test_invalid_rule_is_rejected(kwargs):
    with pytest.raises(ValueError):
        AlertPolicy(**kwargs)
