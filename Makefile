.PHONY: install lock test lint format audit slo-rules slo-check tools promtool-check promtool-test validate serve loadgen clean

PROMTOOL ?= bin/promtool
AMTOOL ?= bin/amtool

install:
	uv sync --frozen

lock:
	uv lock
	uv export --frozen --no-dev --no-emit-project --format requirements-txt > requirements.lock

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run yamllint -s .
	shellcheck scripts/*.sh
	hadolint Dockerfile

format:
	uv run ruff format .

audit:
	uv export --frozen --format requirements-txt --no-hashes --no-emit-project > /tmp/pso-reqs.txt
	uvx pip-audit -r /tmp/pso-reqs.txt

slo-rules:
	uv run slokit generate slos/checkout-api.yaml --out prometheus/rules/slo-checkout-api.yml

slo-check:
	uv run slokit generate slos/checkout-api.yaml --out prometheus/rules/slo-checkout-api.yml --check

tools:
	./scripts/fetch-tools.sh

promtool-check:
	$(PROMTOOL) check config prometheus/prometheus.yml
	$(PROMTOOL) check rules prometheus/rules/*.yml
	$(AMTOOL) check-config alertmanager/alertmanager.yml

promtool-test:
	$(PROMTOOL) test rules tests/promtool/*.yml

validate:
	./scripts/validate-all.sh

serve:
	uv run checkout-api serve --port 8080

loadgen:
	uv run checkout-api loadgen --target http://127.0.0.1:8080 --duration 300

clean:
	rm -rf .venv .pytest_cache .ruff_cache bin dist
