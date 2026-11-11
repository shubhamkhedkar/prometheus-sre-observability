"""SLO specification model and loader (slos/*.yaml)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import durations
from .budget import error_budget

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
WINDOW_PLACEHOLDER = "$window"


@dataclass(frozen=True)
class AlertTier:
    """One multi-window burn-rate alert: fire when both windows exceed the burn threshold."""

    severity: str
    long_window: str
    short_window: str
    budget_consumed: float  # fraction of budget spent over long_window at threshold
    for_: str


# SRE Workbook recommendation for a 30d window (2%/1h, 5%/6h page; 10%/1d, 10%/3d ticket).
DEFAULT_TIERS: tuple[AlertTier, ...] = (
    AlertTier("page", "1h", "5m", 0.02, "2m"),
    AlertTier("page", "6h", "30m", 0.05, "15m"),
    AlertTier("ticket", "1d", "2h", 0.10, "1h"),
    AlertTier("ticket", "3d", "6h", 0.10, "1h"),
)


@dataclass(frozen=True)
class SLO:
    name: str
    objective: float  # ratio, e.g. 0.999
    description: str
    errors_expr: str  # PromQL with $window placeholder
    total_expr: str

    @property
    def budget(self) -> float:
        return error_budget(self.objective)

    def errors(self, window: str) -> str:
        return self.errors_expr.replace(WINDOW_PLACEHOLDER, window)

    def total(self, window: str) -> str:
        return self.total_expr.replace(WINDOW_PLACEHOLDER, window)


@dataclass(frozen=True)
class ServiceSLOs:
    service: str
    window: str
    slos: tuple[SLO, ...]
    tiers: tuple[AlertTier, ...] = DEFAULT_TIERS
    runbook_base: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def window_seconds(self) -> int:
        return durations.parse(self.window)


class SpecError(ValueError):
    pass


def _objective(raw: object, where: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise SpecError(f"{where}: objective must be a number (percent, e.g. 99.9)")
    value = float(raw)
    if not 50.0 <= value < 100.0:
        raise SpecError(f"{where}: objective {value} must be a percent in [50, 100)")
    return round(value / 100.0, 10)


def _latency_exprs(raw: dict, where: str) -> tuple[str, str]:
    metric = raw.get("metric")
    selector = raw.get("selector", "")
    threshold = raw.get("threshold")
    if not isinstance(metric, str) or not re.match(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$", metric):
        raise SpecError(f"{where}: latency.metric must be a histogram metric name")
    if isinstance(threshold, bool) or not isinstance(threshold, int | float) or threshold <= 0:
        raise SpecError(f"{where}: latency.threshold must be a positive number of seconds")
    if not isinstance(selector, str):
        raise SpecError(f"{where}: latency.selector must be a string")
    sel = selector.strip().strip("{}")
    le_sel = f'{sel},le="{threshold:g}"' if sel else f'le="{threshold:g}"'
    total = f"sum(rate({metric}_count{{{sel}}}[{WINDOW_PLACEHOLDER}]))"
    good = f"sum(rate({metric}_bucket{{{le_sel}}}[{WINDOW_PLACEHOLDER}]))"
    return f"({total} - {good})", total


def load(path: str | Path) -> ServiceSLOs:
    data = yaml.safe_load(Path(path).read_text())
    return parse(data)


def parse(data: object) -> ServiceSLOs:
    if not isinstance(data, dict):
        raise SpecError("spec must be a mapping")
    service = data.get("service")
    if not isinstance(service, str) or not _NAME_RE.match(service):
        raise SpecError("service must be a lowercase name ([a-z][a-z0-9_-]*)")
    window = data.get("window", "30d")
    try:
        window_seconds = durations.parse(window)
    except ValueError as exc:
        raise SpecError(f"window: {exc}") from exc
    if not 86400 <= window_seconds <= 90 * 86400:
        raise SpecError("window must be between 1d and 90d")
    raw_slos = data.get("slos")
    if not isinstance(raw_slos, list) or not raw_slos:
        raise SpecError("slos must be a non-empty list")

    slos: list[SLO] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_slos):
        where = f"slos[{i}]"
        if not isinstance(raw, dict):
            raise SpecError(f"{where}: must be a mapping")
        name = raw.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise SpecError(f"{where}: name must match [a-z][a-z0-9_-]*")
        if name in seen:
            raise SpecError(f"{where}: duplicate SLO name {name!r}")
        seen.add(name)
        objective = _objective(raw.get("objective"), where)
        sli = raw.get("sli")
        if not isinstance(sli, dict):
            raise SpecError(f"{where}: sli must be a mapping")
        if "latency" in sli:
            if not isinstance(sli["latency"], dict):
                raise SpecError(f"{where}: sli.latency must be a mapping")
            errors, total = _latency_exprs(sli["latency"], where)
        else:
            errors, total = sli.get("errors"), sli.get("total")
            for key, expr in (("errors", errors), ("total", total)):
                if not isinstance(expr, str) or WINDOW_PLACEHOLDER not in expr:
                    raise SpecError(
                        f"{where}: sli.{key} must be PromQL containing {WINDOW_PLACEHOLDER}"
                    )
            errors, total = " ".join(errors.split()), " ".join(total.split())
        slos.append(
            SLO(
                name=name,
                objective=objective,
                description=str(raw.get("description", "")).strip(),
                errors_expr=errors,
                total_expr=total,
            )
        )

    tiers = DEFAULT_TIERS
    if "alerting" in data:
        tiers = _parse_tiers(data["alerting"], window_seconds)
    runbook = data.get("runbook_base", "")
    if not isinstance(runbook, str):
        raise SpecError("runbook_base must be a string")
    return ServiceSLOs(
        service, durations.format_seconds(window_seconds), tuple(slos), tiers, runbook
    )


def _parse_tiers(raw: object, window_seconds: int) -> tuple[AlertTier, ...]:
    if not isinstance(raw, list) or not raw:
        raise SpecError("alerting must be a non-empty list of tiers")
    tiers = []
    for i, t in enumerate(raw):
        where = f"alerting[{i}]"
        if not isinstance(t, dict):
            raise SpecError(f"{where}: must be a mapping")
        try:
            long_s = durations.parse(t["long_window"])
            short_s = durations.parse(t["short_window"])
            for_ = t.get("for", "0s")
            if for_ != "0s":
                durations.parse(for_)
        except (KeyError, ValueError) as exc:
            raise SpecError(f"{where}: {exc}") from exc
        if short_s >= long_s:
            raise SpecError(f"{where}: short_window must be shorter than long_window")
        if long_s > window_seconds:
            raise SpecError(f"{where}: long_window exceeds the SLO window")
        consumed = t.get("budget_consumed")
        if isinstance(consumed, bool) or not isinstance(consumed, int | float):
            raise SpecError(f"{where}: budget_consumed must be a fraction, e.g. 0.02")
        if not 0 < consumed <= 1:
            raise SpecError(f"{where}: budget_consumed must be in (0, 1]")
        severity = t.get("severity")
        if severity not in ("page", "ticket"):
            raise SpecError(f"{where}: severity must be page or ticket")
        tiers.append(
            AlertTier(
                severity,
                durations.format_seconds(long_s),
                durations.format_seconds(short_s),
                float(consumed),
                for_,
            )
        )
    return tuple(tiers)
