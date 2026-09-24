"""Run-rate projection, shared by both reports.

The sheet's own =SUM(J9,K9)/8*21: take what has landed so far this month,
divide by the working days elapsed, and multiply by the working days in the
month. It answers "if the rest of the month goes like the part we have seen,
where does it end up".

Working days come from the reporting Period (see period.py): weekdays that are
not in the rules' `holidays` list, counted from the 1st to the end of the week.
At month end the two counts are equal and the pace is the actual.
"""
from __future__ import annotations

from .period import Period


def pace(cumulative: float, elapsed: int, business_days: int) -> float:
    """cumulative / min(elapsed, business_days) * business_days"""
    elapsed = min(elapsed, business_days)
    return cumulative / elapsed * business_days if elapsed > 0 else 0.0


def pace_grid(amounts: dict, weeks: list[str], period: Period) -> dict:
    """{(group, bucket): amount} -> {(group, week): paced amount}.

    `weeks` is the current month's buckets in calendar order ("W1".."W5", the
    week of the month); a week's pace is built from the CUMULATIVE amount up to
    and including it, which is what makes the last week of a finished month
    pace to the month's actual total.
    """
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
