"""`checkout-api serve` and `checkout-api loadgen`."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

from .app import CATALOG, CheckoutApp, FaultConfig, build_server


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def cmd_serve(args: argparse.Namespace) -> int:
    faults = FaultConfig(
        error_rate=args.error_rate, slow_rate=args.slow_rate, slow_seconds=args.slow_seconds
    )
    app = CheckoutApp(faults=faults)
    server = build_server(app, args.host, args.port)
    print(f"checkout-api listening on http://{args.host}:{args.port} (metrics at /metrics)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_loadgen(args: argparse.Namespace) -> int:
    """Send a steady mix of reads and orders so dashboards and rules have data."""
    base = args.target.rstrip("/")
    if not base.startswith(("http://", "https://")):
        print("target must be an http(s) URL", file=sys.stderr)
        return 2
    rng = random.Random(args.seed)  # noqa: S311 - traffic mix, not crypto
    skus = list(CATALOG)
    deadline = time.monotonic() + args.duration
    sent = 0
    codes: dict[int, int] = {}
    while time.monotonic() < deadline and (args.requests == 0 or sent < args.requests):
        roll = rng.random()
        data = None
        if roll < 0.6:
            path = "/api/v1/products"
        elif roll < 0.85:
            path = f"/api/v1/products/{rng.choice(skus)}"
        else:
            path = "/api/v1/orders"
            data = json.dumps({"sku": rng.choice(skus), "quantity": 1}).encode()
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(f"{base}{path}", data=data, headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - scheme checked
                code = resp.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        except OSError:
            code = 0
        codes[code] = codes.get(code, 0) + 1
        sent += 1
        if args.rate > 0:
            time.sleep(1.0 / args.rate)
    print(json.dumps({"sent": sent, "status_codes": codes}, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="checkout-api", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the instrumented API")
    s.add_argument("--host", default=os.environ.get("CHECKOUT_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.environ.get("CHECKOUT_PORT", "8080")))
    s.add_argument("--error-rate", type=float, default=_env_float("CHECKOUT_ERROR_RATE", 0.0))
    s.add_argument("--slow-rate", type=float, default=_env_float("CHECKOUT_SLOW_RATE", 0.0))
    s.add_argument("--slow-seconds", type=float, default=_env_float("CHECKOUT_SLOW_SECONDS", 0.5))
    s.set_defaults(func=cmd_serve)

    lg = sub.add_parser("loadgen", help="generate traffic against a running instance")
    lg.add_argument("--target", default="http://127.0.0.1:8080")
    lg.add_argument("--duration", type=float, default=60.0, help="seconds")
    lg.add_argument("--requests", type=int, default=0, help="stop after N requests (0 = no cap)")
    lg.add_argument("--rate", type=float, default=20.0, help="requests per second (0 = max)")
    lg.add_argument("--seed", type=int, default=None)
    lg.set_defaults(func=cmd_loadgen)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
