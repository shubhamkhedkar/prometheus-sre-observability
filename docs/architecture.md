# Architecture

## Components

| Component | Role |
|---|---|
| `checkout-api` | Python HTTP service instrumented with the official `prometheus_client`; exposes `/metrics`, optional fault injection |
| `loadgen` | Same image, sends a read-heavy mix of product and order requests |
| Prometheus | Scrapes the API every 10s, evaluates recording rules, SLO rules and alerts |
| Alertmanager | Routes `page`, `ticket`, `info` severities; inhibits ticket burn alerts while a page burn alert fires |
| Grafana | Provisioned data source plus two dashboards (service overview, SLO/error budget) |
| `slokit` | Generates SLO recording and burn-rate alert rules from `slos/*.yaml`; budget maths CLI |

## Rule layers

```mermaid
flowchart TB
    raw["Raw series<br/>http_requests_total<br/>http_request_duration_seconds_bucket"]
    rec["recording.yml<br/>job_route:http_requests:rate5m<br/>job_route:...:p99_5m"]
    sli["slo-checkout-api.yml (generated)<br/>slo:sli_error:ratio_rate{5m..30d}"]
    budget["slo:error_budget:ratio<br/>slo:error_budget_remaining:ratio"]
    alerts["alerts.yml<br/>target down, 5xx, p99, saturation"]
    burn["ErrorBudgetBurn<br/>4 tiers x 2 SLOs"]
    raw --> rec --> alerts
    raw --> sli --> burn
    sli --> budget
    rec --> dash1["Service overview dashboard"]
    sli --> dash2["SLO dashboard"]
    budget --> dash2
```

## Change workflow

1. Edit `slos/checkout-api.yaml` (objective, SLI query, tiers).
2. `make slo-rules` regenerates `prometheus/rules/slo-checkout-api.yml`.
3. `make test promtool-check promtool-test` proves the rules parse and that the expected alerts
   fire (and stay silent) for synthetic series.
4. Review the diff of the generated file in the pull request, then reload Prometheus
   (`curl -X POST localhost:9090/-/reload` with `--web.enable-lifecycle`).
