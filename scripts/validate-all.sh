#!/usr/bin/env bash
# Local quality gate: unit tests, lint, SLO rule drift check, promtool/amtool validation and
# promtool rule unit tests. Runs nothing long-lived and contacts no Prometheus server.
set -euo pipefail

cd "$(dirname "$0")/.."
PROMTOOL="${PROMTOOL:-bin/promtool}"
AMTOOL="${AMTOOL:-bin/amtool}"

echo "==> python unit tests"
uv run pytest

echo "==> lint"
uv run ruff check .
uv run ruff format --check .
uv run yamllint -s .
shellcheck scripts/*.sh
if command -v hadolint >/dev/null; then hadolint Dockerfile; else echo "hadolint not installed, skipped"; fi

echo "==> generated SLO rules are up to date"
uv run slokit generate slos/checkout-api.yaml --out prometheus/rules/slo-checkout-api.yml --check

if [[ ! -x "$PROMTOOL" || ! -x "$AMTOOL" ]]; then
  echo "promtool/amtool missing; run ./scripts/fetch-tools.sh first" >&2
  exit 1
fi

echo "==> promtool check config / rules, amtool check-config"
"$PROMTOOL" check config prometheus/prometheus.yml
"$PROMTOOL" check rules prometheus/rules/*.yml
"$AMTOOL" check-config alertmanager/alertmanager.yml

echo "==> promtool rule unit tests"
"$PROMTOOL" test rules tests/promtool/*.yml

echo "All local checks passed."
