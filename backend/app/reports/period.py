"""The month and weeks a report covers, worked out from the week being built.

A Mon-Fri week belongs to the month holding most of its weekdays, which is always the
month of its Wednesday. So 2026-W36 (Mon 31 Aug - Fri 4 Sep) is September's week 1,
shown as 1-4 Sep, with 31 August counted in August's month total; and 2026-W40
(Mon 28 Sep - Fri 2 Oct) is September's week 5, 28-30 Sep, with 1-2 October added to
October's week 1, which then runs 1-9 Oct.

Pacing counts working days: weekdays that are not in the `holidays` list of
the report's rules.yml.

Both reports use this one calendar. The .bat pipelines keep a copy each
(gfs-automation scripts/run_week.py and ap/period.py); this is that code, shared.
"""
from __future__ import annotations
import calendar
import datetime as dt
from dataclasses import dataclass

import polars as pl


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def working_days(first: dt.date, last: dt.date, holidays=frozenset()) -> int:
    return sum(1 for i in range((last - first).days + 1)
               if (d := first + dt.timedelta(days=i)).weekday() < 5 and d not in holidays)


def month_weeks(year: int, month: int) -> list[tuple[dt.date, dt.date]]:
    """Every week of the month as (first day, last day).

    A week is in the month when its Wednesday is. The first week starts on the 1st, so
    leading days that belong to the previous month's week join it."""
    first = dt.date(year, month, 1)
    last = dt.date(year, month, calendar.monthrange(year, month)[1])
    spans = []
    m = first - dt.timedelta(days=first.weekday())
    while m <= last:
        if (m + dt.timedelta(days=2)).month == month:
            spans.append([max(m, first), min(m + dt.timedelta(days=4), last)])
        m += dt.timedelta(days=7)
    spans[0][0] = first
    return [tuple(s) for s in spans]


@dataclass
class Period:
    year: int
    month: int
    month_weeks: list[tuple[dt.date, dt.date]]
    weeks_so_far: int
    last_day: dt.date                    # the Sunday closing the reporting week
    holidays: frozenset
    # The month's working days as entered by a person on the upload screen,
    # when the calendar's count is wrong. None: use the calendar.
    entered_days: int | None = None

    @property
    def weeks(self) -> list[tuple[dt.date, dt.date]]:
        return self.month_weeks[:self.weeks_so_far]

    @property
    def label(self) -> str:
        return month_label(self.year, self.month)

    @property
    def prev(self) -> tuple[int, int]:
        return (self.year, self.month - 1) if self.month > 1 else (self.year - 1, 12)

    @property
    def week_mondays(self) -> list[dt.date]:
        return [s - dt.timedelta(days=s.weekday()) for s, _ in self.month_weeks]

    @property
    def calendar_days(self) -> int:
        """Weekdays in the month, less the holidays in the rules."""
        last = calendar.monthrange(self.year, self.month)[1]
        return working_days(dt.date(self.year, self.month, 1),
                            dt.date(self.year, self.month, last), self.holidays)

    @property
    def business_days(self) -> int:
        """The month's working days the pace is built on: what was entered for
        the month if anything was, the calendar's count if not."""
        return self.entered_days or self.calendar_days

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def elapsed(self, week_index: int) -> int:
        """Working days from the 1st to the end of week `week_index` (1-based)."""
        return working_days(dt.date(self.year, self.month, 1),
                            self.month_weeks[week_index - 1][1], self.holidays)

    def pace_divisor(self, week_index: int) -> int:
        return max(1, min(self.elapsed(week_index), self.business_days))

    def pace_formula(self, cells: list[str], week_index: int) -> str:
        """e.g. =SUM(J9,K9)/8*21 - month-to-date over the working days elapsed, times
        the month's working days. At month end the two are equal: pace = actual."""
        return (f"=SUM({','.join(cells)})/{self.pace_divisor(week_index)}"
                f"*{self.business_days}")


def reporting_period(week: str, holidays: list | None,
                     entered: dict | None = None) -> Period:
    """The period `week` reports on. `entered` maps "2026-09" to the working
    days a person entered for that month, when they did."""
    y, w = map(int, week.split("-W"))
    monday = dt.date.fromisocalendar(y, w, 1)
    wednesday = monday + dt.timedelta(days=2)
    year, month = wednesday.year, wednesday.month
    spans = month_weeks(year, month)
    so_far = sum(1 for s, _ in spans if s - dt.timedelta(days=s.weekday()) <= monday)
    off = frozenset(h for h in (holidays or []) if isinstance(h, dt.date))
    days = (entered or {}).get(f"{year:04d}-{month:02d}")
    return Period(year, month, spans, so_far, monday + dt.timedelta(days=6), off,
                  int(days) if days else None)


def week_index_expr(col: str, period: Period) -> pl.Expr:
    """1-based week of the month for a date column: the last week whose Monday is on or
    before the date. Weekend days join the week they close; the 1st joins week 1."""
    later = period.week_mondays[1:]
    if not later:
        return pl.lit(1)
    return pl.sum_horizontal([(pl.col(col) >= pl.lit(m)).cast(pl.Int32)
                              for m in later]) + 1
