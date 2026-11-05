"""Closed months opened back into their weeks."""
from __future__ import annotations
import datetime as dt

import polars as pl

from app.reports.closed_weeks import closed_months, settlement_month_weeks, week_spans
from app.reports.period import reporting_period


def rows(*cells):
    return pl.DataFrame(
        [{"D": d, "loc": loc, "Group": g, "Settlement_Amount": amt, "Paid": paid,
          "Billed": billed} for d, loc, g, amt, paid, billed in cells],
        schema={"D": pl.Date, "loc": pl.Utf8, "Group": pl.Utf8,
                "Settlement_Amount": pl.Float64, "Paid": pl.Float64, "Billed": pl.Float64})


def test_only_months_from_october_2026_are_kept_by_week():
    assert closed_months(reporting_period("2026-W43", [])) == []          # October itself
    assert closed_months(reporting_period("2026-W49", [])) == [10, 11]    # December
    assert closed_months(reporting_period("2027-W06", [])) == [1]         # February 2027
    assert closed_months(reporting_period("2026-W38", [])) == []          # September


def test_a_closed_month_splits_into_its_weeks_and_its_total_row():
    period = reporting_period("2026-W45", [])          # November: October is closed
    d = rows((dt.date(2026, 10, 1), "in house", "POS", 100.0, 0.0, 200.0),
             (dt.date(2026, 10, 11), "in house", "POS", 50.0, 0.0, 100.0),   # Sunday: week 1
             (dt.date(2026, 10, 12), "in house", "POS", 30.0, 10.0, 100.0),
             (dt.date(2026, 10, 12), "board", "POS", 7.0, 0.0, 7.0),
             (dt.date(2026, 11, 2), "in house", "POS", 999.0, 0.0, 1.0))      # this month
    out = settlement_month_weeks(d, {"In House": "in house"}, period, with_pct=True)
    pos = {r["bucket"]: r for r in out if r["group"] == "POS"}
    assert pos["W1"]["amount"] == 150.0 and pos["W1"]["settlement_pct"] == 0.5
    assert pos["W2"]["amount"] == 30.0 and pos["W2"]["settlement_pct"] == 0.4
    assert {r["month"] for r in out} == {10}
    assert [r["bucket"] for r in out if r["group"] is None] == ["W1", "W2"]


def test_week_spans_name_the_days_of_this_month_and_each_kept_month():
    spans = week_spans(reporting_period("2026-W45", []))
    assert spans["10"][0] == {"week": 1, "first": "2026-10-01", "last": "2026-10-09"}
    assert spans["11"][0]["week"] == 1 and "9" not in spans
