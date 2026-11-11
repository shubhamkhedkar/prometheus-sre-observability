"""slokit command line: error budget maths and SLO rule generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import budget, durations, model, rules


def _ratio(objective: float) -> float:
    return round(objective / 100.0, 10) if objective >= 1 else objective


def cmd_budget(args: argparse.Namespace) -> int:
    objective = _ratio(args.objective)
    window = durations.parse(args.window)
    eb = budget.error_budget(objective)
    out = {
        "objective": objective,
        "window": args.window,
        "error_budget_ratio": eb,
        "allowed_downtime": durations.humanize(budget.allowed_bad_seconds(objective, window)),
        "allowed_downtime_seconds": round(budget.allowed_bad_seconds(objective, window), 3),
    }
    if args.requests is not None:
        out["allowed_failed_requests"] = round(
            budget.allowed_bad_events(objective, args.requests), 3
        )
    tiers = []
    for tier in model.DEFAULT_TIERS:
        burn = budget.burn_rate_for_consumption(
            tier.budget_consumed, durations.parse(tier.long_window), window
        )
        tiers.append(
            {
                "severity": tier.severity,
                "windows": f"{tier.long_window}/{tier.short_window}",
                "burn_rate": round(burn, 4),
                "error_ratio_threshold": round(burn * eb, 8),
                "budget_consumed_pct": round(tier.budget_consumed * 100, 4),
                "exhausts_full_budget_in": durations.humanize(
                    budget.time_to_exhaustion(burn, window)
                ),
            }
        )
    out["burn_rate_alerts"] = tiers
    _emit(out, args.json)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    objective = _ratio(args.objective)
    st = budget.budget_status(objective, args.good, args.total)
    out = {
        "objective": objective,
        "good": st.good,
        "total": st.total,
        "error_ratio": round(st.error_ratio, 8),
        "allowed_bad": round(st.allowed_bad, 3),
        "actual_bad": st.actual_bad,
        "budget_remaining_pct": round(st.remaining_fraction * 100, 4),
        "slo_met": st.met,
    }
    _emit(out, args.json)
    return 0 if st.met else 1


def cmd_burn(args: argparse.Namespace) -> int:
    objective = _ratio(args.objective)
    window = durations.parse(args.window)
    burn = budget.burn_rate(args.error_ratio, objective)
    out = {
        "objective": objective,
        "error_ratio": args.error_ratio,
        "burn_rate": round(burn, 4),
        "exhausts_full_budget_in": durations.humanize(budget.time_to_exhaustion(burn, window)),
        "budget_consumed_in_1h_pct": round(budget.budget_consumed(burn, 3600, window) * 100, 4),
    }
    _emit(out, args.json)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    for path in args.specs:
        spec = model.load(path)
        print(f"{path}: ok ({spec.service}, {len(spec.slos)} SLOs, window {spec.window})")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    spec = model.load(args.spec)
    text = rules.render(spec, Path(args.spec).as_posix())
    if args.check:
        current = Path(args.out).read_text() if Path(args.out).exists() else ""
        if current != text:
            print(f"{args.out} is out of date; run slokit generate", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date")
        return 0
    if args.out == "-":
        sys.stdout.write(text)
    else:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    return 0


def _emit(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2))
        return
    for key, value in data.items():
        if isinstance(value, list):
            print(f"{key}:")
            for row in value:
                print("  - " + ", ".join(f"{k}={v}" for k, v in row.items()))
        else:
            print(f"{key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="slokit", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("budget", help="error budget and burn-rate alert thresholds")
    b.add_argument("--objective", type=float, required=True, help="99.9 or 0.999")
    b.add_argument("--window", default="30d")
    b.add_argument("--requests", type=int, help="expected requests in the window")
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_budget)

    s = sub.add_parser("status", help="budget status from good/total event counts")
    s.add_argument("--objective", type=float, required=True)
    s.add_argument("--good", type=int, required=True)
    s.add_argument("--total", type=int, required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    r = sub.add_parser("burn", help="burn rate for an observed error ratio")
    r.add_argument("--objective", type=float, required=True)
    r.add_argument("--error-ratio", type=float, required=True)
    r.add_argument("--window", default="30d")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_burn)

    v = sub.add_parser("validate", help="validate SLO spec files")
    v.add_argument("specs", nargs="+")
    v.set_defaults(func=cmd_validate)

    g = sub.add_parser("generate", help="render Prometheus rules from an SLO spec")
    g.add_argument("spec")
    g.add_argument("--out", default="-")
    g.add_argument("--check", action="store_true", help="exit 1 if --out differs")
    g.set_defaults(func=cmd_generate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
