# SLO maths used by slokit

| Term | Formula | checkout-api availability (99.9%, 30d) |
|---|---|---|
| Error budget | `1 - objective` | 0.1% of requests |
| Allowed full-outage time | `budget * window` | 43m12s per 30d |
| Burn rate | `error ratio / budget` | 1.44% errors = 14.4x |
| Budget spent in window `w` | `burn * w / window` | 14.4x for 1h = 2% |
| Time to exhaust a full budget | `window / burn` | 14.4x = 2d2h |
| Budget remaining | `1 - (error ratio over window / budget)` | negative once breached |

## Multi-window, multi-burn-rate alerts

A single-window alert either pages too late (long window) or flaps and stays firing after the
problem is fixed (short window). Each tier therefore checks two windows:

- the **long window** proves that a meaningful share of the budget is being spent;
- the **short window** (1/12 of the long one) proves that it is *still* being spent, so the
  alert clears within minutes of recovery.

Default tiers, from the Google SRE Workbook chapter "Alerting on SLOs", for a 30d window:

| Severity | Long | Short | Budget spent | Burn rate |
|---|---|---|---|---|
| page | 1h | 5m | 2% | 14.4 |
| page | 6h | 30m | 5% | 6 |
| ticket | 1d | 2h | 10% | 3 |
| ticket | 3d | 6h | 10% | 1 |

For other SLO windows slokit keeps the "budget spent" column and recomputes the burn rate:
`burn = spent * slo_window / long_window` (for 28d the fast tier becomes 13.44x).

## Latency SLI

The latency SLO counts a request as bad when it takes longer than the threshold:

```
bad   = rate(http_request_duration_seconds_count[w]) - rate(http_request_duration_seconds_bucket{le="0.3"}[w])
total = rate(http_request_duration_seconds_count[w])
```

This is exact only because `0.3` is one of the histogram bucket boundaries, which is why
`checkout_api/metrics.py` defines the buckets explicitly and a unit test checks it.

## Examples

```bash
uv run slokit budget --objective 99.9 --window 30d --requests 50000000
uv run slokit burn --objective 99.9 --error-ratio 0.005
uv run slokit status --objective 99.9 --good 49962000 --total 50000000   # exit 1 = SLO missed
```
