"""What a build hands back, and the sections both pipelines build the same way."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

import polars as pl

from .collection_sheet import build_collections
from .common import cp_settled
from .notes import Note
from .pacing import pace_grid
from .partial import absent, empty, waiting
from .period import Period, week_index_expr

COLLECTIONS = {"Group": pl.Utf8, "Week": pl.Int32, "PT": pl.Utf8, "Payment": pl.Float64}


@dataclass
class RunResult:
    """Everything one build produced."""
    raw_data: pl.DataFrame
    case_ar: pl.DataFrame
    delta_comparison: pl.DataFrame
    collections: pl.DataFrame

    settlement_grids: dict
    cp_settled: dict
    kpi: dict
    current_month: int

    settlement_pace: dict = field(default_factory=dict)
    collections_pace: dict = field(default_factory=dict)
    year: int = 0
    settlement_month_weeks: list = field(default_factory=list)
    period: Period | None = None
    layout: dict = field(default_factory=dict)      # {block: its rows, in the sheet's order}

    notes: list[Note] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def tables(self) -> dict[str, pl.DataFrame]:
        return {"raw_data": self.raw_data, "case_ar": self.case_ar,
                "delta_comparison": self.delta_comparison,
                "collections": self.collections}


def case_ar_tables(src, rules: dict, empty_tables: dict, notes: list[Note],
                   build_raw: Callable, build_case: Callable
                   ) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Raw Data and Case AR, or both empty while a Case AR file is missing."""
    gone = absent(owner_case_ar=src.owner_ar, custom_case_ar=src.custom_ar)
    if gone:
        notes.append(waiting("Raw Data or Case AR", gone))
        return empty(empty_tables["raw_data"]), empty(empty_tables["case_ar"])
    raw = build_raw(src.owner_ar, src.providers, src.custom_ar, rules)
    return raw, build_case(raw, rules)


def cp_table(src, period: Period, notes: list[Note]) -> dict:
    """CP Settled Cases, or nothing while the Hearing Calendar is missing."""
    if src.hearing_noi is None:
        notes.append(waiting("CP Settled Cases", ["hearing_calendar"]))
        return {}
    return cp_settled(src.hearing_noi, period.year, period.month)


def collections_table(src, rules: dict, period: Period, notes: list[Note],
                      gfs_cases: pl.DataFrame | None = None, **needed) -> pl.DataFrame:
    """Collections for the month, or empty while a file it reads is missing:
    the Payment Detail Report and any `needed`."""
    gone = absent(payment_detail=src.payments, **needed)
    if gone:
        notes.append(waiting("Collections", gone))
        return empty(COLLECTIONS)
    return build_collections(src.payments, src.providers, rules, period.year, period.month,
                             week_index_expr("paid_on", period), gfs_cases)


def paced(amounts_by_block: dict, coll: pl.DataFrame, period: Period) -> tuple[dict, dict]:
    """Each settlement block's pace, and Collections' pace, week by week this month."""
    weeks = [f"W{i}" for i in range(1, period.weeks_so_far + 1)]
    coll_amounts = {(g, f"W{w}"): amt for g, w, amt in
                    coll.group_by(["Group", "Week"]).agg(pl.col("Payment").sum()).rows()}
    return ({block: pace_grid(amounts, weeks, period)
             for block, amounts in amounts_by_block.items()},
            pace_grid(coll_amounts, weeks, period))


def kpi_notes(src) -> list[Note]:
    """The reader's note that no KPI-numbers file came, if it did not."""
    return [n for n in src.notes if n.code == "kpi_numbers_not_supplied"]


def rules_layout(rules: dict) -> dict[str, list[str]]:
    """rules.yml `layout`: each block's rows in the order the client's workbook lists them."""
    return {k: [str(r) for r in rows or []] for k, rows in (rules.get("layout") or {}).items()}
