"""Prometheus metric definitions for the checkout API.

Metric names follow the Prometheus naming guidance: base units (seconds), `_total` for
counters, and low-cardinality labels (route templates, never raw paths or IDs).
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# Bucket boundaries include the 0.3 s latency SLO threshold so the latency SLI is exact.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0)
LATENCY_SLO_THRESHOLD_SECONDS = 0.3


@dataclass(frozen=True)
class Metrics:
    registry: CollectorRegistry
    requests: Counter
    latency: Histogram
    in_flight: Gauge
    orders: Counter
    stock: Gauge
    build_info: Gauge


def build_metrics(version: str, registry: CollectorRegistry | None = None) -> Metrics:
    """Create all metrics on a dedicated registry (one per app instance, test friendly)."""
    reg = registry or CollectorRegistry()
    requests = Counter(
        "http_requests",
        "HTTP requests handled, by method, route template and status code.",
        ["method", "route", "code"],
        registry=reg,
    )
    latency = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds, by method and route template.",
        ["method", "route"],
        buckets=LATENCY_BUCKETS,
        registry=reg,
    )
    in_flight = Gauge(
        "http_requests_in_flight",
        "HTTP requests currently being served.",
        registry=reg,
    )
    orders = Counter(
        "checkout_orders",
        "Orders processed, by outcome (created, rejected, failed).",
        ["outcome"],
        registry=reg,
    )
    stock = Gauge(
        "checkout_inventory_stock_items",
        "Units in stock per product SKU.",
        ["sku"],
        registry=reg,
    )
    build_info = Gauge(
        "checkout_build_info",
        "Build information; value is always 1.",
        ["version"],
        registry=reg,
    )
    build_info.labels(version=version).set(1)
    for outcome in ("created", "rejected", "failed"):
        orders.labels(outcome=outcome)  # initialise so rate() sees a zero series
    return Metrics(reg, requests, latency, in_flight, orders, stock, build_info)
