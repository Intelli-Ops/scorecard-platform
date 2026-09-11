"""The run-rate projection, checked against the delivered workbook.

These four numbers are read straight out of the Week-35 GFS workbook's
"Settlements (In House - Pace)" block for A Miles. They are the reason the
formula is shared rather than written twice: both sheets ask the same question
and must answer it the same way.
"""
from __future__ import annotations
import pytest

from app.reports.pacing import business_days, pace, pace_grid


def test_august_2026_has_twenty_one_working_days():
    assert business_days(2026, 8) == 21


def test_pace_reproduces_the_workbook_for_a_miles():
    weekly = [17200.0, 9900.0, 35543.07, 39800.0]
    expected = [72240.0, 56910.0, 87700.298, 107565.2235]
    running = 0.0
    for i, (amount, want) in enumerate(zip(weekly, expected), start=1):
        running += amount
        assert pace(running, i, 21) == pytest.approx(want, abs=1e-4)


def test_pace_grid_accumulates_across_the_month():
    amounts = {("A Miles", "W32"): 17200.0, ("A Miles", "W33"): 9900.0,
               ("A Miles", "W34"): 35543.07, ("A Miles", "W35"): 39800.0}
    grid = pace_grid(amounts, ["W32", "W33", "W34", "W35"], 2026, 8)
    assert grid[("A Miles", "W35")] == pytest.approx(107565.2235, abs=1e-4)
    # Week 2 is built from weeks 1 AND 2, not from week 2 alone.
    assert grid[("A Miles", "W33")] == pytest.approx(56910.0, abs=1e-4)


def test_a_finished_month_paces_to_its_actual():
    """Once the elapsed days reach the month's, the projection stops being one."""
    weeks = [f"W{n}" for n in range(1, 6)]           # 5 weeks = 25 > 21 days
    amounts = {("G", w): 100.0 for w in weeks}
    grid = pace_grid(amounts, weeks, 2026, 8)
    assert grid[("G", "W5")] == pytest.approx(500.0)


def test_a_group_that_settled_nothing_paces_to_nothing():
    grid = pace_grid({("G", "W32"): 0.0}, ["W32"], 2026, 8)
    assert grid[("G", "W32")] == 0.0


def test_pace_of_nothing_elapsed_is_nothing_rather_than_a_crash():
    assert pace(1000.0, 1, 0) == 0.0
