"""The month and weeks a report covers, and its working days."""
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
    """Every week of the month as (first day, last day)."""
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


def reporting_period(week: str, holidays: list | None,
                     entered: dict | None = None) -> Period:
    """The period `week` reports on."""
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


def month_period(year: int, month: int, holidays=frozenset()) -> Period:
    """A whole month, every week of it passed - a closed month opened into its weeks."""
    spans = month_weeks(year, month)
    return Period(year, month, spans, len(spans), spans[-1][1], frozenset(holidays))


def week_index_expr(col: str, period: Period) -> pl.Expr:
    """1-based week of the month for a date column: the last week whose Monday
    is on or before the date."""
    later = period.week_mondays[1:]
    if not later:
        return pl.lit(1)
    return pl.sum_horizontal([(pl.col(col) >= pl.lit(m)).cast(pl.Int32)
                              for m in later]) + 1
