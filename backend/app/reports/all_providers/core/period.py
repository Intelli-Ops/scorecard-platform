"""Which week columns the sheet shows for a month.

Copied VERBATIM from scripts/run_week.py in the All-Providers .bat pipeline,
where it sat among the Excel-writing code. It is a calculation, not rendering:
settlement_grids needs it to know which weeks the report covers.
"""
from __future__ import annotations
import datetime as dt


def month_week_columns(year: int, month: int, report_week: int,
                       excel_style: bool = False) -> list[int]:
    """The week columns the sheet shows for `month`.

    One column per Monday that falls in the month, up to and including the week the
    report is for - NOT one per week that happens to appear in the data. That
    distinction is the whole rule, and the delivered Week-34 workbook proves it:
    August 2026 settlements run into week 35, but its sheet stops at week 34 with
    period starts 3, 10 and 17 August, because that is the week it reports.

    `excel_style` picks Excel's WEEKNUM (weeks start Sunday, 1 January is week 1)
    for the Collections grid; the Settlement grids use ISO weeks, which is what
    their Monday-to-Friday Period Start / Period End rows describe. For 2026 the
    two agree on every Monday, but they do not in every year.
    """
    d = dt.date(year, month, 1)
    while d.weekday() != 0:                       # first Monday of the month
        d += dt.timedelta(days=1)
    offset = dt.date(year, 1, 1).weekday() % 7
    out = []
    while d.month == month:
        w = ((d.timetuple().tm_yday + offset - 1) // 7 + 1) if excel_style             else d.isocalendar()[1]
        if w <= report_week:
            out.append(w)
        d += dt.timedelta(days=7)
    return out or [report_week]
