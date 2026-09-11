"""Run-rate projection, shared by both reports.

The template's own =SUM(J9)/5*21: take what has landed so far this month,
divide by the working days elapsed, and multiply by the working days in the
month. It answers "if the rest of the month goes like the part we have seen,
where does it end up".

This lived in the All Providers collections module, because that is the sheet
that needed it first. The GFS settlement sheet asks the same question of its
own numbers - Settlements (In House - Pace) and Settlements (Board - Pace) -
so the formula moved here rather than being written a second time. One copy
means one thing to be right, and the golden master covers both callers.
"""
from __future__ import annotations
import datetime as dt


def pace(cumulative: float, week_index: int, business_days: int,
         week_days: int = 5) -> float:
    """cumulative / min(week_days * week_index, business_days) * business_days

    At month end the divisor reaches the multiplier and the pace becomes the
    actual - a finished month paces to exactly what it did.
    """
    elapsed = min(week_days * week_index, business_days)
    return cumulative / elapsed * business_days if elapsed else 0.0


def business_days(year: int, month: int) -> int:
    d = dt.date(year, month, 1)
    n = 0
    while d.month == month:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n


def pace_grid(amounts: dict, weeks: list[str], year: int, month: int) -> dict:
    """{(group, bucket): amount} -> {(group, week): paced amount}.

    `weeks` is the current month's buckets in calendar order; a week's pace is
    built from the CUMULATIVE amount up to and including it, which is what
    makes week 4 of a finished month pace to the month's actual total.
    """
    days = business_days(year, month)
    groups = {g for g, _ in amounts}
    out = {}
    for group in groups:
        running = 0.0
        for i, week in enumerate(weeks, start=1):
            running += float(amounts.get((group, week), 0.0))
            out[(group, week)] = pace(running, i, days)
    return out
