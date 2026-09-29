"""The run-rate projection, checked against the delivered workbook.

These four numbers are read straight out of the Week-35 GFS workbook's
"Settlements (In House - Pace)" block for A Miles. They are the reason the
formula is shared rather than written twice: both sheets ask the same question
and must answer it the same way.
"""
from __future__ import annotations
import pytest

import datetime as dt

from app.reports.pacing import pace, pace_grid
from app.reports.period import reporting_period, month_weeks

HOLIDAYS = [dt.date(2026, 9, 7)]                    # Labour Day


def test_august_2026_has_twenty_one_working_days():
    assert reporting_period("2026-W35", HOLIDAYS).business_days == 21


def test_pace_reproduces_the_workbook_for_a_miles():
    weekly = [17200.0, 9900.0, 35543.07, 39800.0]
    expected = [72240.0, 56910.0, 87700.298, 107565.2235]
    running = 0.0
    for i, (amount, want) in enumerate(zip(weekly, expected), start=1):
        running += amount
        assert pace(running, 5 * i, 21) == pytest.approx(want, abs=1e-4)


def test_pace_grid_accumulates_across_the_month():
    aug = reporting_period("2026-W35", HOLIDAYS)
    amounts = {("A Miles", "W1"): 17200.0, ("A Miles", "W2"): 9900.0,
               ("A Miles", "W3"): 35543.07, ("A Miles", "W4"): 39800.0}
    grid = pace_grid(amounts, ["W1", "W2", "W3", "W4"], aug)
    assert grid[("A Miles", "W4")] == pytest.approx(107565.2235, abs=1e-4)
    # Week 2 is built from weeks 1 AND 2, not from week 2 alone.
    assert grid[("A Miles", "W2")] == pytest.approx(56910.0, abs=1e-4)


def test_a_week_belongs_to_the_month_of_its_wednesday():
    # Mon 31 Aug - Fri 4 Sep is September's week 1, shown as 1-4 Sep.
    sep = reporting_period("2026-W36", HOLIDAYS)
    assert (sep.month, sep.weeks_so_far) == (9, 1)
    assert sep.weeks == [(dt.date(2026, 9, 1), dt.date(2026, 9, 4))]
    # 1-2 Oct join October's week 1, which runs 1-9 Oct.
    assert month_weeks(2026, 10)[0] == (dt.date(2026, 10, 1), dt.date(2026, 10, 9))


def test_holidays_are_not_working_days():
    """September 2026: 22 weekdays less Labour Day. Week 2 has elapsed 4 + 4 days,
    the sheet's own =SUM(J9,K9)/8*21."""
    sep = reporting_period("2026-W37", HOLIDAYS)
    assert sep.business_days == 21
    assert sep.pace_divisor(1) == 4
    assert sep.pace_divisor(2) == 8
    grid = pace_grid({("G", "W1"): 400.0, ("G", "W2"): 400.0}, ["W1", "W2"], sep)
    assert grid[("G", "W2")] == pytest.approx(800.0 / 8 * 21)


def test_the_last_week_paces_over_the_days_it_covers():
    """August's weeks end on Fri 28 Aug; Mon 31 Aug is in September's week 1."""
    aug = reporting_period("2026-W35", HOLIDAYS)
    weeks = [f"W{n}" for n in range(1, 5)]
    amounts = {("G", w): 100.0 for w in weeks}
    grid = pace_grid(amounts, weeks, aug)
    assert grid[("G", "W4")] == pytest.approx(400.0 / 20 * 21)


def test_a_group_that_settled_nothing_paces_to_nothing():
    grid = pace_grid({("G", "W1"): 0.0}, ["W1"], reporting_period("2026-W35", HOLIDAYS))
    assert grid[("G", "W1")] == 0.0


def test_pace_of_nothing_elapsed_is_nothing_rather_than_a_crash():
    assert pace(1000.0, 0, 21) == 0.0


def test_excel_weeknum_starts_weeks_on_sunday():
    """Excel's WEEKNUM(date, 1): Jan 1 is in week 1, and each Sunday starts a
    new week. The old copy treated Monday as the first day."""
    import datetime as dt
    import polars as pl
    from app.reports.common import excel_weeknum
    days = [dt.date(2026, 1, 3), dt.date(2026, 1, 4),    # Sat, Sun
            dt.date(2023, 1, 1), dt.date(2023, 1, 7), dt.date(2023, 1, 8)]
    got = lambda year: (pl.DataFrame({"d": days})
                        .select(excel_weeknum("d", year))["d"].to_list())
    assert got(2026)[:2] == [1, 2]
    assert got(2023)[2:] == [1, 1, 2]
