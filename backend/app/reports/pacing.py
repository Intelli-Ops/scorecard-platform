"""Run-rate projection for the current month, used by both reports."""
from __future__ import annotations

from .period import Period


def pace(cumulative: float, elapsed: int, business_days: int) -> float:
    """Project a month-to-date figure over the whole month's business days."""
    elapsed = min(elapsed, business_days)
    return cumulative / elapsed * business_days if elapsed > 0 else 0.0


def pace_grid(amounts: dict, weeks: list[str], period: Period) -> dict:
    """{(group, bucket): amount} -> {(group, week): paced amount}."""
    days = period.business_days
    groups = {g for g, _ in amounts}
    out = {}
    for group in groups:
        running = 0.0
        for week in weeks:
            i = int(week[1:])
            running += float(amounts.get((group, week), 0.0))
            out[(group, week)] = pace(running, period.pace_divisor(i), days)
    return out
