"""Helpers shared by both reports' calculations."""
from __future__ import annotations
import datetime as dt
import re
from dataclasses import dataclass, field

import polars as pl


def i64(col: str) -> pl.Expr:
    """Excel hands integers back as floats (3120398.0)."""
    return pl.col(col).cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


def excel_weeknum(col: str, year: int) -> pl.Expr:
    """Excel's WEEKNUM: weeks start on Sunday and Jan 1 is always in week 1."""
    offset = (dt.date(year, 1, 1).weekday() + 1) % 7
    return (pl.col(col).dt.ordinal_day() + offset - 1) // 7 + 1


def norm(s: object) -> str:
    """Match sheet labels to source groups ignoring case and punctuation."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def find_row(rows: list[list], marker: str) -> int | None:
    """The first row whose first cell reads `marker`, ignoring case and punctuation."""
    want = norm(marker)
    for i, r in enumerate(rows):
        if r and norm(r[0]) == want:
            return i
    return None


@dataclass
class StageLog:
    """Row counts after each stage of a calculation, for the review screen."""
    stages: list[tuple[str, int]] = field(default_factory=list)

    def add(self, label: str, n: int) -> None:
        self.stages.append((label, n))


def number(v) -> float:
    """A spreadsheet cell as a number: commas dropped, 0.0 if it is not one."""
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
