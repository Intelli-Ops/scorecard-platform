"""Small helpers both reports' calculations use, written once.

The two reports' maths is kept apart on purpose (see __init__.py), but these
are not maths - they are how a spreadsheet value is read - and each had been
copied into every core module that needed it.
"""
from __future__ import annotations
import datetime as dt
import re

import polars as pl


def i64(col: str) -> pl.Expr:
    """Excel hands integers back as floats (3120398.0). Normalise before joining -
    a float/int mismatch on a join key silently produces zero matches."""
    return pl.col(col).cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


def excel_weeknum(col: str, year: int) -> pl.Expr:
    """Excel WEEKNUM with the default return type: weeks start on Sunday and
    Jan 1 always falls in week 1. polars' dt.week() is ISO and does not match.

    `offset` is how many days of week 1 fall before Jan 1. Python numbers the
    days Mon=0 .. Sun=6; a Sunday-start week needs Sun=0 .. Sat=6, hence +1.
    """
    offset = (dt.date(year, 1, 1).weekday() + 1) % 7
    return (pl.col(col).dt.ordinal_day() + offset - 1) // 7 + 1


def norm(s: object) -> str:
    """Match sheet labels to source groups ignoring case and punctuation.
    The sheet says 'BayCo', the Supporting File says 'Bayco'."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def find_row(rows: list[list], marker: str) -> int | None:
    """The first row whose first cell reads `marker`, ignoring case and
    punctuation."""
    want = norm(marker)
    for i, r in enumerate(rows):
        if r and norm(r[0]) == want:
            return i
    return None
