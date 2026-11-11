import math

import pytest

from slokit import budget

MONTH = 30 * 86400


def test_error_budget_is_rounded():
    assert budget.error_budget(0.999) == 0.001
    assert budget.error_budget(0.99) == 0.01


@pytest.mark.parametrize("bad", [0, 1, 1.5, -0.1])
def test_objective_bounds(bad):
    with pytest.raises(ValueError):
        budget.error_budget(bad)


def test_allowed_downtime_99_9_over_30d_is_43m12s():
    assert budget.allowed_bad_seconds(0.999, MONTH) == pytest.approx(2592.0)


def test_allowed_bad_events():
    assert budget.allowed_bad_events(0.999, 1_000_000) == pytest.approx(1000)
    with pytest.raises(ValueError):
        budget.allowed_bad_events(0.999, -1)


def test_burn_rate():
    assert budget.burn_rate(0.0144, 0.999) == pytest.approx(14.4)
    assert budget.burn_rate(0.0, 0.999) == 0
    with pytest.raises(ValueError):
        budget.burn_rate(1.2, 0.999)


@pytest.mark.parametrize(
    ("consumed", "window_h", "expected_burn"),
    [(0.02, 1, 14.4), (0.05, 6, 6.0), (0.10, 24, 3.0), (0.10, 72, 1.0)],
)
def test_workbook_burn_rate_thresholds(consumed, window_h, expected_burn):
    burn = budget.burn_rate_for_consumption(consumed, window_h * 3600, MONTH)
    assert burn == pytest.approx(expected_burn)
    # And the inverse: sustaining that burn for the window spends exactly `consumed`.
    assert budget.budget_consumed(burn, window_h * 3600, MONTH) == pytest.approx(consumed)


def test_time_to_exhaustion():
    assert budget.time_to_exhaustion(14.4, MONTH) == pytest.approx(MONTH / 14.4)  # ~2 days
    assert budget.time_to_exhaustion(2, MONTH, remaining=0.5) == pytest.approx(MONTH / 4)
    assert math.isinf(budget.time_to_exhaustion(0, MONTH))


def test_budget_status_met_and_breached():
    ok = budget.budget_status(0.999, good=999_500, total=1_000_000)
    assert ok.met and ok.actual_bad == 500
    assert ok.remaining_fraction == pytest.approx(0.5)

    breached = budget.budget_status(0.999, good=997_000, total=1_000_000)
    assert not breached.met
    assert breached.remaining_fraction == pytest.approx(-2.0)


def test_budget_status_no_traffic_and_invalid():
    empty = budget.budget_status(0.99, good=0, total=0)
    assert empty.met and empty.remaining_fraction == 1.0
    with pytest.raises(ValueError):
        budget.budget_status(0.99, good=11, total=10)
