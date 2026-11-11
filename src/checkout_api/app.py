"""Checkout API request handling with Prometheus instrumentation and fault injection.

`CheckoutApp.handle` is transport independent so it can be unit tested without sockets;
`serve` wraps it in a stdlib ThreadingHTTPServer.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__
from .metrics import Metrics, build_metrics

MAX_BODY_BYTES = 16 * 1024
MAX_QUANTITY = 50

CATALOG: dict[str, dict] = {
    "SKU-1001": {"name": "Mechanical keyboard", "price_inr": 4499, "stock": 40},
    "SKU-1002": {"name": "USB-C dock", "price_inr": 7999, "stock": 15},
    "SKU-1003": {"name": "27in monitor", "price_inr": 18999, "stock": 8},
    "SKU-1004": {"name": "Noise cancelling headset", "price_inr": 9999, "stock": 25},
}

_PRODUCT_RE = re.compile(r"^/api/v1/products/([A-Za-z0-9-]{1,32})$")


@dataclass
class FaultConfig:
    """Synthetic faults so alerts and dashboards can be exercised locally.

    error_rate:   probability (0..1) that an /api request returns 503.
    slow_rate:    probability (0..1) that an /api request gets `slow_seconds` extra latency.
    """

    error_rate: float = 0.0
    slow_rate: float = 0.0
    slow_seconds: float = 0.5

    def __post_init__(self) -> None:
        for name in ("error_rate", "slow_rate"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {value}")
        if not 0.0 <= self.slow_seconds <= 10.0:
            raise ValueError("slow_seconds must be between 0 and 10")


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"


@dataclass
class CheckoutApp:
    faults: FaultConfig = field(default_factory=FaultConfig)
    seed: int | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.perf_counter

    def __post_init__(self) -> None:
        self.metrics: Metrics = build_metrics(__version__)
        self._rng = random.Random(self.seed)  # noqa: S311 - fault injection, not crypto
        self._lock = threading.Lock()
        self._stock = {sku: item["stock"] for sku, item in CATALOG.items()}
        self._order_seq = 0
        for sku, qty in self._stock.items():
            self.metrics.stock.labels(sku=sku).set(qty)

    # ------------------------------------------------------------------ routing
    @staticmethod
    def route_for(method: str, path: str) -> str:
        """Map a raw path to a bounded route template (keeps label cardinality low)."""
        path = path.split("?", 1)[0]
        if path in ("/healthz", "/readyz", "/metrics", "/api/v1/products", "/api/v1/orders"):
            return path
        if _PRODUCT_RE.match(path):
            return "/api/v1/products/:sku"
        return "unmatched"

    def handle(self, method: str, path: str, body: bytes = b"") -> Response:
        route = self.route_for(method, path)
        start = self.clock()
        self.metrics.in_flight.inc()
        try:
            response = self._dispatch(method, path.split("?", 1)[0], route, body)
        except Exception:  # noqa: BLE001 - always answer and count a 500
            response = _json(500, {"error": "internal error"})
        finally:
            self.metrics.in_flight.dec()
        if route != "/metrics":
            elapsed = max(self.clock() - start, 0.0)
            self.metrics.latency.labels(method=method, route=route).observe(elapsed)
            self.metrics.requests.labels(
                method=method, route=route, code=str(response.status)
            ).inc()
        return response

    def _dispatch(self, method: str, path: str, route: str, body: bytes) -> Response:
        if route == "/metrics":
            if method != "GET":
                return _json(405, {"error": "method not allowed"})
            return Response(200, generate_latest(self.metrics.registry), CONTENT_TYPE_LATEST)
        if route in ("/healthz", "/readyz"):
            return _json(200, {"status": "ok", "version": __version__})
        if route == "unmatched":
            return _json(404, {"error": "not found"})

        # Business routes: apply synthetic faults first.
        if self.faults.slow_rate and self._rng.random() < self.faults.slow_rate:
            self.sleep(self.faults.slow_seconds)
        if self.faults.error_rate and self._rng.random() < self.faults.error_rate:
            return _json(503, {"error": "injected fault"})

        if route == "/api/v1/products":
            if method != "GET":
                return _json(405, {"error": "method not allowed"})
            with self._lock:
                items = [
                    {
                        "sku": sku,
                        **{k: v for k, v in item.items() if k != "stock"},
                        "stock": self._stock[sku],
                    }
                    for sku, item in CATALOG.items()
                ]
            return _json(200, {"items": items})
        if route == "/api/v1/products/:sku":
            if method != "GET":
                return _json(405, {"error": "method not allowed"})
            sku = _PRODUCT_RE.match(path).group(1)  # type: ignore[union-attr]
            if sku not in CATALOG:
                return _json(404, {"error": "unknown sku"})
            with self._lock:
                stock = self._stock[sku]
            return _json(200, {"sku": sku, **CATALOG[sku], "stock": stock})
        if route == "/api/v1/orders":
            if method != "POST":
                return _json(405, {"error": "method not allowed"})
            return self._create_order(body)
        return _json(404, {"error": "not found"})  # pragma: no cover

    def _create_order(self, body: bytes) -> Response:
        if len(body) > MAX_BODY_BYTES:
            self.metrics.orders.labels(outcome="rejected").inc()
            return _json(413, {"error": "payload too large"})
        try:
            payload = json.loads(body or b"{}")
            sku = payload["sku"]
            qty = payload.get("quantity", 1)
            if not isinstance(sku, str) or not isinstance(qty, int) or isinstance(qty, bool):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            self.metrics.orders.labels(outcome="rejected").inc()
            return _json(400, {"error": "body must be JSON {sku: str, quantity: int}"})
        if sku not in CATALOG:
            self.metrics.orders.labels(outcome="rejected").inc()
            return _json(404, {"error": "unknown sku"})
        if not 1 <= qty <= MAX_QUANTITY:
            self.metrics.orders.labels(outcome="rejected").inc()
            return _json(400, {"error": f"quantity must be 1..{MAX_QUANTITY}"})
        with self._lock:
            if self._stock[sku] < qty:
                self.metrics.orders.labels(outcome="rejected").inc()
                return _json(409, {"error": "insufficient stock", "available": self._stock[sku]})
            self._stock[sku] -= qty
            self._order_seq += 1
            order_id = f"ORD-{self._order_seq:06d}"
            self.metrics.stock.labels(sku=sku).set(self._stock[sku])
        self.metrics.orders.labels(outcome="created").inc()
        total = CATALOG[sku]["price_inr"] * qty
        return _json(201, {"order_id": order_id, "sku": sku, "quantity": qty, "total_inr": total})


def _json(status: int, payload: dict) -> Response:
    return Response(status, json.dumps(payload).encode())


def make_handler(app: CheckoutApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "checkout-api"
        sys_version = ""

        def _serve(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                body = b"x" * (MAX_BODY_BYTES + 1)  # do not read oversized bodies
            else:
                body = self.rfile.read(length) if length > 0 else b""
            resp = app.handle(method, self.path, body)
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Content-Length", str(len(resp.body)))
            self.end_headers()
            self.wfile.write(resp.body)

        def do_GET(self) -> None:  # noqa: N802
            self._serve("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._serve("POST")

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass  # access logs would duplicate metrics; keep stdout quiet

    return Handler


def build_server(
    app: CheckoutApp, host: str = "127.0.0.1", port: int = 8080
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(app))
