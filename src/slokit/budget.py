"""Error budget and burn-rate arithmetic.

Definitions (Google SRE Workbook, "Alerting on SLOs"):
  error budget      = 1 - objective
  burn rate         = observed error ratio / error budget
  budget consumed   = burn rate * alert window / SLO window
  time to exhaust   = SLO window / burn rate   (from a full budget)
"""

from __future__ import annotations

from dataclasses import dataclass


def _check_objective(objective: float) -> None:
    if not 0.0 < objective < 1.0:
        raise ValueError(f"objective must be a ratio strictly between 0 and 1, got {objective}")


def error_budget(objective: float) -> float:
    _check_objective(objective)
    return round(1.0 - objective, 12)


def allowed_bad_seconds(objective: float, window_seconds: int) -> float:
    """Seconds of full outage the budget allows over the window (time-based view)."""
    return error_budget(objective) * window_seconds


def allowed_bad_events(objective: float, total_events: int) -> float:
    if total_events < 0:
        raise ValueError("total_events must be >= 0")
    return error_budget(objective) * total_events


def burn_rate(error_ratio: float, objective: float) -> float:
    if not 0.0 <= error_ratio <= 1.0:
        raise ValueError(f"error_ratio must be between 0 and 1, got {error_ratio}")
    return error_ratio / error_budget(objective)


def budget_consumed(burn: float, alert_window_seconds: int, slo_window_seconds: int) -> float:
    """Fraction of the whole budget spent if `burn` is sustained for the alert window."""
    if burn < 0:
        raise ValueError("burn rate must be >= 0")
    return burn * alert_window_seconds / slo_window_seconds


def burn_rate_for_consumption(
    consumed_fraction: float, alert_window_seconds: int, slo_window_seconds: int
) -> float:
    """Burn rate threshold that spends `consumed_fraction` of the budget in the alert window."""
    if not 0.0 < consumed_fraction <= 1.0:
        raise ValueError("consumed_fraction must be in (0, 1]")
    return consumed_fraction * slo_window_seconds / alert_window_seconds


def time_to_exhaustion(burn: float, slo_window_seconds: int, remaining: float = 1.0) -> float:
    """Seconds until the remaining budget fraction is gone at the given burn rate."""
    if burn <= 0:
        return float("inf")
    if not 0.0 <= remaining <= 1.0:
        raise ValueError("remaining must be between 0 and 1")
    return remaining * slo_window_seconds / burn


@dataclass(frozen=True)
class BudgetStatus:
    objective: float
    good: int
    total: int
    error_ratio: float
    allowed_bad: float
    actual_bad: int
    remaining_fraction: float  # may go negative when the SLO is breached
    met: bool


def budget_status(objective: float, good: int, total: int) -> BudgetStatus:
    """Event-based budget status for a window (e.g. from `increase()` over 30d)."""
    if good < 0 or total < 0 or good > total:
        raise ValueError("require 0 <= good <= total")
    budget = error_budget(objective)
    bad = total - good
    allowed = budget * total
    ratio = bad / total if total else 0.0
    remaining = 1.0 - (ratio / budget) if total else 1.0
    return BudgetStatus(
        objective=objective,
        good=good,
        total=total,
        error_ratio=ratio,
        allowed_bad=allowed,
        actual_bad=bad,
        remaining_fraction=remaining,
        met=ratio <= budget,
    )
