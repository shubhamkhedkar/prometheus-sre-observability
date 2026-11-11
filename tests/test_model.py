import copy

import pytest

from slokit import model

BASE = {
    "service": "checkout-api",
    "window": "30d",
    "slos": [
        {
            "name": "availability",
            "objective": 99.9,
            "sli": {
                "errors": 'sum(rate(x_total{code=~"5.."}[$window]))',
                "total": "sum(rate(x_total[$window]))",
            },
        },
        {
            "name": "latency",
            "objective": 99,
            "sli": {"latency": {"metric": "h_seconds", "selector": 'job="a"', "threshold": 0.3}},
        },
    ],
}


def spec(**changes):
    data = copy.deepcopy(BASE)
    data.update(changes)
    return data


def test_parse_defaults_and_objective_ratio(root):
    s = model.parse(spec())
    assert s.service == "checkout-api" and s.window == "30d"
    assert [x.objective for x in s.slos] == [0.999, 0.99]
    assert s.slos[0].budget == 0.001
    assert s.tiers == model.DEFAULT_TIERS


def test_window_substitution():
    s = model.parse(spec())
    assert s.slos[0].errors("1h") == 'sum(rate(x_total{code=~"5.."}[1h]))'


def test_latency_sli_uses_count_minus_bucket():
    lat = model.parse(spec()).slos[1]
    assert lat.total("5m") == 'sum(rate(h_seconds_count{job="a"}[5m]))'
    assert lat.errors("5m") == (
        '(sum(rate(h_seconds_count{job="a"}[5m]))'
        ' - sum(rate(h_seconds_bucket{job="a",le="0.3"}[5m])))'
    )


def test_latency_without_selector():
    data = spec()
    data["slos"][1]["sli"]["latency"]["selector"] = ""
    assert 'h_seconds_bucket{le="0.3"}' in model.parse(data).slos[1].errors("5m")


def test_checked_in_spec_loads(root):
    s = model.load(root / "slos" / "checkout-api.yaml")
    assert {x.name for x in s.slos} == {"availability", "latency"}
    assert [t.long_window for t in s.tiers] == ["1h", "6h", "1d", "3d"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(service="Checkout API"), "service"),
        (lambda d: d.update(window="2h"), "between 1d and 90d"),
        (lambda d: d.update(window="thirty"), "window"),
        (lambda d: d.update(slos=[]), "non-empty"),
        (lambda d: d["slos"][0].update(objective=100), "percent"),
        (lambda d: d["slos"][0].update(objective="99.9"), "number"),
        (lambda d: d["slos"][0].update(objective=True), "number"),
        (lambda d: d["slos"][1].update(name="availability"), "duplicate"),
        (lambda d: d["slos"][0]["sli"].update(total="sum(rate(x_total[5m]))"), "$window"),
        (lambda d: d["slos"][1]["sli"]["latency"].update(threshold=0), "threshold"),
        (lambda d: d["slos"][1]["sli"]["latency"].update(metric="bad metric"), "metric"),
    ],
)
def test_invalid_specs(mutate, message):
    data = spec()
    mutate(data)
    with pytest.raises(model.SpecError, match=message.replace("$", r"\$")):
        model.parse(data)


def test_custom_tiers_validated():
    good = spec(
        alerting=[
            {
                "severity": "page",
                "long_window": "1h",
                "short_window": "5m",
                "budget_consumed": 0.02,
                "for": "2m",
            }
        ]
    )
    assert model.parse(good).tiers[0].for_ == "2m"
    for tier, msg in [
        (
            {
                "severity": "page",
                "long_window": "5m",
                "short_window": "1h",
                "budget_consumed": 0.02,
            },
            "shorter",
        ),
        (
            {
                "severity": "page",
                "long_window": "60d",
                "short_window": "1h",
                "budget_consumed": 0.02,
            },
            "exceeds",
        ),
        (
            {"severity": "sms", "long_window": "1h", "short_window": "5m", "budget_consumed": 0.02},
            "severity",
        ),
        (
            {"severity": "page", "long_window": "1h", "short_window": "5m", "budget_consumed": 2},
            "budget_consumed",
        ),
    ]:
        with pytest.raises(model.SpecError, match=msg):
            model.parse(spec(alerting=[tier]))
