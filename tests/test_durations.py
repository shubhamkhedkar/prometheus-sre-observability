import pytest

from slokit import durations


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("5m", 300),
        ("30m", 1800),
        ("1h", 3600),
        ("6h", 21600),
        ("1d", 86400),
        ("30d", 2592000),
        ("2w", 1209600),
        ("45s", 45),
    ],
)
def test_parse(text, seconds):
    assert durations.parse(text) == seconds


@pytest.mark.parametrize("bad", ["", "5", "1.5h", "0m", "-1h", "1y", "1h30m", 5])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        durations.parse(bad)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(300, "5m"), (3600, "1h"), (86400, "1d"), (2592000, "30d"), (604800, "7d"), (90, "90s")],
)
def test_format_round_trip(seconds, text):
    assert durations.format_seconds(seconds) == text
    assert durations.parse(text) == seconds


def test_humanize():
    assert durations.humanize(2592) == "43m12s"
    assert durations.humanize(25920) == "7h12m"
    assert durations.humanize(2 * 86400 + 3 * 3600 + 59) == "2d3h"
    assert durations.humanize(0) == "0s"
