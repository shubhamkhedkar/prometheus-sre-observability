import json
import threading
import urllib.error
import urllib.request

import pytest
from prometheus_client.parser import text_string_to_metric_families

from checkout_api.app import MAX_BODY_BYTES, CheckoutApp, FaultConfig, build_server


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def sample(app, name, **labels):
    value = app.metrics.registry.get_sample_value(name, labels)
    return 0.0 if value is None else value


def test_route_templates_bound_cardinality():
    route = CheckoutApp.route_for
    assert route("GET", "/api/v1/products/SKU-1001") == "/api/v1/products/:sku"
    assert route("GET", "/api/v1/products?page=2") == "/api/v1/products"
    assert route("GET", "/wp-admin/../etc/passwd") == "unmatched"
    assert route("GET", "/api/v1/products/" + "x" * 64) == "unmatched"


def test_products_and_request_metrics():
    app = CheckoutApp()
    resp = app.handle("GET", "/api/v1/products")
    assert resp.status == 200
    assert len(json.loads(resp.body)["items"]) == 4
    app.handle("GET", "/api/v1/products/SKU-404")
    labels = {"method": "GET", "route": "/api/v1/products", "code": "200"}
    assert sample(app, "http_requests_total", **labels) == 1
    assert (
        sample(app, "http_requests_total", method="GET", route="/api/v1/products/:sku", code="404")
        == 1
    )
    assert sample(app, "http_requests_in_flight") == 0


def test_latency_histogram_buckets_include_slo_threshold():
    clock = FakeClock()
    app = CheckoutApp(
        clock=clock,
        sleep=lambda s: setattr(clock, "now", clock.now + s),
        faults=FaultConfig(slow_rate=1.0, slow_seconds=0.4),
        seed=1,
    )
    app.handle("GET", "/api/v1/products")
    base = {"method": "GET", "route": "/api/v1/products"}
    assert sample(app, "http_request_duration_seconds_bucket", le="0.3", **base) == 0
    assert sample(app, "http_request_duration_seconds_bucket", le="0.5", **base) == 1
    assert sample(app, "http_request_duration_seconds_count", **base) == 1


def test_error_injection_is_counted_as_5xx():
    app = CheckoutApp(faults=FaultConfig(error_rate=1.0), seed=7)
    assert app.handle("GET", "/api/v1/products").status == 503
    # Health and metrics endpoints are never faulted.
    assert app.handle("GET", "/healthz").status == 200
    assert app.handle("GET", "/metrics").status == 200
    assert (
        sample(app, "http_requests_total", method="GET", route="/api/v1/products", code="503") == 1
    )


def test_error_rate_is_statistically_close():
    app = CheckoutApp(faults=FaultConfig(error_rate=0.2), seed=42)
    codes = [app.handle("GET", "/api/v1/products").status for _ in range(2000)]
    assert 0.17 < codes.count(503) / len(codes) < 0.23


@pytest.mark.parametrize("bad", [{"error_rate": 1.5}, {"slow_rate": -0.1}, {"slow_seconds": 60}])
def test_fault_config_validation(bad):
    with pytest.raises(ValueError):
        FaultConfig(**bad)


def test_order_flow_updates_stock_and_business_metrics():
    app = CheckoutApp()
    resp = app.handle(
        "POST", "/api/v1/orders", json.dumps({"sku": "SKU-1003", "quantity": 5}).encode()
    )
    assert resp.status == 201
    body = json.loads(resp.body)
    assert body["order_id"] == "ORD-000001" and body["total_inr"] == 5 * 18999
    assert sample(app, "checkout_inventory_stock_items", sku="SKU-1003") == 3
    conflict = app.handle("POST", "/api/v1/orders", b'{"sku": "SKU-1003", "quantity": 4}')
    assert conflict.status == 409
    assert sample(app, "checkout_orders_total", outcome="created") == 1
    assert sample(app, "checkout_orders_total", outcome="rejected") == 1
    assert sample(app, "checkout_orders_total", outcome="failed") == 0


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (b"not json", 400),
        (b'{"quantity": 1}', 400),
        (b'{"sku": "SKU-1001", "quantity": 0}', 400),
        (b'{"sku": "SKU-1001", "quantity": true}', 400),
        (b'{"sku": "NOPE"}', 404),
        (b"x" * (MAX_BODY_BYTES + 1), 413),
    ],
)
def test_order_validation(body, status):
    assert CheckoutApp().handle("POST", "/api/v1/orders", body).status == status


def test_method_not_allowed():
    app = CheckoutApp()
    assert app.handle("GET", "/api/v1/orders").status == 405
    assert app.handle("POST", "/api/v1/products").status == 405


def test_unhandled_exception_becomes_counted_500(monkeypatch):
    app = CheckoutApp()

    def boom(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(app, "_dispatch", boom)
    assert app.handle("GET", "/api/v1/products").status == 500
    assert (
        sample(app, "http_requests_total", method="GET", route="/api/v1/products", code="500") == 1
    )
    assert sample(app, "http_requests_in_flight") == 0


def test_metrics_exposition_parses_and_excludes_self():
    app = CheckoutApp()
    app.handle("GET", "/api/v1/products")
    app.handle("GET", "/metrics")
    text = app.handle("GET", "/metrics").body.decode()
    families = {f.name: f for f in text_string_to_metric_families(text)}
    assert families["http_requests"].type == "counter"
    assert families["http_request_duration_seconds"].type == "histogram"
    assert families["http_requests_in_flight"].type == "gauge"
    assert families["checkout_build_info"].samples[0].labels == {"version": "1.0.0"}
    routes = {s.labels.get("route") for s in families["http_requests"].samples}
    assert "/metrics" not in routes


def test_http_server_end_to_end():
    app = CheckoutApp()
    server = build_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=5) as r:
            assert json.loads(r.read())["status"] == "ok"
        req = urllib.request.Request(f"{base}/api/v1/orders", data=b'{"sku":"SKU-1001"}')
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 201
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"{base}/nope", timeout=5)
        assert err.value.code == 404
        with urllib.request.urlopen(f"{base}/metrics", timeout=5) as r:
            assert r.headers["Content-Type"].startswith("text/plain")
            assert 'http_requests_total{code="201",method="POST",route="/api/v1/orders"} 1.0' in (
                r.read().decode()
            )
    finally:
        server.shutdown()
        server.server_close()
