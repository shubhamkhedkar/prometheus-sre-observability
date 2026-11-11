# Runbooks

Each alert in `prometheus/rules/` links to a section below through `runbook_url`.
A unit test fails if an alert is added without a section here.

## ErrorBudgetBurn

Generated from `slos/checkout-api.yaml`. Labels tell you which SLO and which tier fired:

| severity | long / short window | burn rate | budget spent at threshold |
|---|---|---|---|
| page | 1h / 5m | 14.4x | 2% in 1h |
| page | 6h / 30m | 6x | 5% in 6h |
| ticket | 1d / 2h | 3x | 10% in 1d |
| ticket | 3d / 6h | 1x | 10% in 3d |

1. Open the **checkout-api / SLOs and error budget** dashboard and select the `slo` label.
2. Compare the burn-rate windows. A high 5m value with a lower 1h value means the incident has
   just started; a low 5m with a high 1h means it is recovering (the short window resets the
   alert quickly once the problem stops).
3. For `slo=availability`, open the service overview dashboard and check **Responses by status
   code** for which route returns 5xx. For `slo=latency`, check **Latency percentiles** and the
   heatmap.
4. Correlate with recent deploys, config changes and dependency health. Roll back first if a
   change lines up with the start of the burn.
5. Once mitigated, note the remaining budget (`slo:error_budget_remaining:ratio`). If it drops
   below 25%, apply the error-budget policy: freeze risky releases until it recovers.

## CheckoutAPITargetDown

Prometheus cannot scrape the instance named in the `instance` label.

1. `curl -s http://<instance>/healthz` from a host on the same network as Prometheus.
2. Check the process / container status and recent restarts.
3. Check Prometheus **Status > Targets** for the scrape error (timeout, DNS, TLS, 404).

## CheckoutAPIMetricsAbsent

No `up{job="checkout-api"}` series exists, so service discovery returned nothing or the job was
removed from the config. Every other checkout-api alert is blind while this fires.

1. `promtool check config prometheus.yml` on the deployed config.
2. Confirm the job name is still `checkout-api` and that discovery finds targets.

## CheckoutAPIHighErrorRate

Cause-oriented signal: more than 5% of requests return 5xx for 5 minutes with at least
0.1 rps of traffic. Usually accompanied by `ErrorBudgetBurn`; use it to find the route.

1. `topk(5, job_route_code:http_requests:rate5m{job="checkout-api",code=~"5.."})` in Prometheus.
2. Check application logs for the failing route and any dependency timeouts.

## CheckoutAPIHighLatencyP99

p99 latency on a route has been above 500 ms for 10 minutes.

1. Check the heatmap for a bimodal distribution (slow dependency) versus a uniform shift (CPU).
2. Check **Requests in flight** and process CPU; scale out if saturated.

## CheckoutAPISaturation

More than 50 concurrent requests. The API uses a thread per request, so sustained concurrency
points to slow downstream calls or a traffic spike.

1. Compare **Request rate** with **Latency percentiles**: rising latency with flat traffic points
   at a dependency; rising traffic points at capacity.

## CheckoutInventoryLow

Business alert, routed to the merchandising receiver rather than on-call. A SKU has fewer than
5 units left. No engineering action required.

## PrometheusRuleEvaluationFailures

Prometheus failed to evaluate a rule group, which can silently disable SLO alerts.

1. Prometheus **Status > Rules** shows the failing rule and error.
2. Re-run `promtool check rules` and `promtool test rules tests/promtool/*.yml` on the change
   that introduced it.
