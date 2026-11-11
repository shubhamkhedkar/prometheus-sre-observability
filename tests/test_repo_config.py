"""Cross-file consistency: config, rules, dashboards, runbooks and promtool tests agree."""

import json
import re

import pytest
import yaml

RECORD_RE = re.compile(r"\b([a-z_]+:[a-z_0-9]+:[a-z_0-9]+)\b")
APP_METRICS = {
    "http_requests_total",
    "http_request_duration_seconds_bucket",
    "http_request_duration_seconds_count",
    "http_requests_in_flight",
    "checkout_orders_total",
    "checkout_inventory_stock_items",
    "checkout_build_info",
    "process_cpu_seconds_total",
    "process_resident_memory_bytes",
    "up",
    "ALERTS",
}


def load_rules(root):
    groups = []
    for path in sorted((root / "prometheus" / "rules").glob("*.yml")):
        groups += yaml.safe_load(path.read_text())["groups"]
    return groups


def test_prometheus_config_references_existing_rule_files(root):
    cfg = yaml.safe_load((root / "prometheus" / "prometheus.yml").read_text())
    files = cfg["rule_files"]
    assert files and all((root / "prometheus" / f).is_file() for f in files)
    jobs = {j["job_name"] for j in cfg["scrape_configs"]}
    assert "checkout-api" in jobs


def test_every_alert_has_severity_runbook_and_test(root):
    tests_text = "".join(p.read_text() for p in (root / "tests" / "promtool").glob("*.yml"))
    runbooks = (root / "docs" / "runbooks.md").read_text().lower()
    alerts = [r for g in load_rules(root) for r in g["rules"] if "alert" in r]
    assert alerts
    for rule in alerts:
        assert rule["labels"]["severity"] in {"page", "ticket", "info"}
        anchor = rule["annotations"]["runbook_url"].split("#", 1)[1]
        assert f"## {anchor}" in runbooks, f"docs/runbooks.md lacks section for {anchor}"
        assert f"alertname: {rule['alert']}" in tests_text, f"no promtool test for {rule['alert']}"


def recorded_names(root):
    return {r["record"] for g in load_rules(root) for r in g["rules"] if "record" in r}


@pytest.mark.parametrize("name", ["checkout-api-overview.json", "checkout-api-slo.json"])
def test_dashboard_structure(root, name):
    dash = json.loads((root / "grafana" / "dashboards" / name).read_text())
    assert dash["uid"] and dash["title"]
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids))
    assert any(v["type"] == "datasource" for v in dash["templating"]["list"])
    for panel in dash["panels"]:
        if panel["type"] == "row":
            continue
        assert panel["datasource"]["uid"] == "${datasource}"
        assert panel["targets"], panel["title"]
        g = panel["gridPos"]
        assert 0 <= g["x"] and g["x"] + g["w"] <= 24


@pytest.mark.parametrize("name", ["checkout-api-overview.json", "checkout-api-slo.json"])
def test_dashboard_queries_use_known_metrics(root, name):
    dash = json.loads((root / "grafana" / "dashboards" / name).read_text())
    known = recorded_names(root) | APP_METRICS
    for panel in dash["panels"]:
        for target in panel.get("targets", []):
            expr = target["expr"]
            for metric in RECORD_RE.findall(expr):
                assert metric in known, f"{panel['title']}: unknown recorded series {metric}"
            raw = RECORD_RE.sub("", expr)
            for metric in re.findall(r"\b(http_[a-z_]+|checkout_[a-z_]+|process_[a-z_]+)\b", raw):
                assert metric in APP_METRICS, f"{panel['title']}: unknown metric {metric}"


def test_compose_pins_images_and_binds_localhost(root):
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    for name, svc in compose["services"].items():
        image = svc.get("image", "")
        assert ":" in image and not image.endswith(":latest"), name
        for port in svc.get("ports", []):
            assert port.startswith("127.0.0.1:"), f"{name} exposes {port} beyond localhost"
    env = compose["services"]["grafana"]["environment"]
    assert env["GF_SECURITY_ADMIN_PASSWORD"].startswith("${GRAFANA_ADMIN_PASSWORD:?")


def test_compose_prometheus_version_matches_fetch_script(root):
    compose = (root / "docker-compose.yml").read_text()
    script = (root / "scripts" / "fetch-tools.sh").read_text()
    version = re.search(r"PROMETHEUS_VERSION:-([0-9.]+)", script).group(1)
    assert f"prom/prometheus:v{version}" in compose
