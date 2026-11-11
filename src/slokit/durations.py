"""Prometheus-style duration parsing and formatting (subset: s, m, h, d, w)."""

from __future__ import annotations

import re

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_RE = re.compile(r"^(\d+)([smhdw])$")


def parse(value: str) -> int:
    """Return seconds for a single-unit duration like '5m', '6h', '30d'."""
    if not isinstance(value, str):
        raise ValueError(f"duration must be a string like '30d', got {value!r}")
    match = _RE.match(value.strip())
    if not match:
        raise ValueError(f"invalid duration {value!r}; use <int><s|m|h|d|w>, e.g. 30d")
    seconds = int(match.group(1)) * _UNITS[match.group(2)]
    if seconds <= 0:
        raise ValueError(f"duration must be positive, got {value!r}")
    return seconds


def format_seconds(seconds: int) -> str:
    """Format seconds using the largest unit that divides exactly (Prometheus style)."""
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    for unit in ("w", "d", "h", "m", "s"):
        size = _UNITS[unit]
        if seconds % size == 0:
            if unit == "w":
                # Prefer days for windows such as 28d/30d; weeks only when the user wrote w.
                return f"{seconds // _UNITS['d']}d"
            return f"{seconds // size}{unit}"
    raise AssertionError("unreachable")  # pragma: no cover


def humanize(seconds: float) -> str:
    """Human readable duration, e.g. 43m12s, 7h12m, 2d3h."""
    seconds = int(round(seconds))
    if seconds <= 0:
        return "0s"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and not days:
        parts.append(f"{minutes}m")
    if secs and not days and not hours:
        parts.append(f"{secs}s")
    return "".join(parts) or "0s"
