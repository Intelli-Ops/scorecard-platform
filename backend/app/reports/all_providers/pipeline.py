"""All Providers: the full calculation, from source tables to finished tables."""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt
import time

import polars as pl

from ..notes import Note, sort_notes
from ..pacing import pace_grid
from ..partial import absent, empty, missing_books, waiting
from ..closed_weeks import settlement_month_weeks
from ..period import Period, reporting_period, week_index_expr
from ..review_notes import add_new_providers, review_notes, week_label
from .core.case_ar import build_raw_data, build_case_ar
from .core.collections import build_collections
from .core.delta import (DeltaReport, combine_delta, prepare, settlement_grids,
                         delta_comparison, cp_settled)
from .core.kpi import KpiReport, build_kpi_sql, build_kpi_scorecard, kpi_layout
from .readers import ApSources


# The four tables' columns, for a section whose files are not in yet.
EMPTY = {
    "raw_data": {"CASEID": pl.Int64, "PROVIDER": pl.Utf8, "BUSINESSREGID": pl.Int64,
                 "Group": pl.Utf8, "CASETYPE": pl.Utf8, "Closing Order": pl.Utf8,
                 "Validity": pl.Utf8, "File Status": pl.Utf8, " BILLED": pl.Float64,
                 " PAID": pl.Float64, "WRITEOFF": pl.Float64, "ADVANCE": pl.Float64,
                 "OUTSTANDING": pl.Float64},
    "case_ar": {"File Status": pl.Utf8, "Count of Cases": pl.UInt32, "BILLED": pl.Float64,
                "PAID": pl.Float64, "WRITEOFF": pl.Float64, "ADVANCE": pl.Float64,
                "OUTSTANDING": pl.Float64},
    "delta_comparison": {"Group": pl.Utf8, "Month": pl.Int8, "Total Settlement": pl.Float64,
                         "Pay Received - YES": pl.Float64, "Pay Received - NO": pl.Float64},
    "collections": {"Group": pl.Utf8, "Week": pl.Int32, "PT": pl.Utf8, "Payment": pl.Float64},
}


@dataclass
class RunResult:
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

    notes: list[Note] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def tables(self) -> dict[str, pl.DataFrame]:
        return {"raw_data": self.raw_data, "case_ar": self.case_ar,
                "delta_comparison": self.delta_comparison,
                "collections": self.collections}


def run(src: ApSources, rules: dict, as_of: dt.date | None = None,
        week: str | None = None) -> RunResult:
    """`week` is the label being reported, e.g. 2026-W37."""
    t0 = time.perf_counter()
    as_of = as_of or dt.date.today()
    period = reporting_period(week_label(week, as_of), rules.get("holidays"),
                              rules.get("working_days"))
    year, month = period.year, period.month

    notes: list[Note] = [n for n in src.notes if n.code == "kpi_numbers_not_supplied"]

    gone = absent(owner_case_ar=src.owner_ar, custom_case_ar=src.custom_ar)
    if gone:
        raw, case_ar = empty(EMPTY["raw_data"]), empty(EMPTY["case_ar"])
        notes.append(waiting("Raw Data or Case AR", gone))
    else:
        raw, rep = build_raw_data(src.owner_ar, src.providers, src.custom_ar, rules)
        case_ar = build_case_ar(raw, rules)

    books = missing_books(rules, src.delta_sheets)
    if not src.delta_sheets:
        delta, grids, drep = empty(EMPTY["delta_comparison"]), {}, DeltaReport()
        month_weeks = []
        notes.append(waiting("Delta Comparison or Settlement", books))
    else:
        if books:
            notes.append(waiting("part of Delta Comparison and Settlement", books))
        comb, drep = combine_delta(src.delta_sheets, rules)
        dd, drep = prepare(comb, src.providers, rules, year, drep)
        grids = settlement_grids(dd, rules, period, drep)
        month_weeks = settlement_month_weeks(dd, rules["delta"]["locations"], period)
        delta = delta_comparison(dd, rules, drep)

    if src.hearing_noi is None:
        cp = {}
        notes.append(waiting("CP Settled Cases", ["hearing_calendar"]))
    else:
        cp = cp_settled(src.hearing_noi, year, month)

    if src.payments is None:
        coll = empty(EMPTY["collections"])
        notes.append(waiting("Collections", ["payment_detail"]))
    else:
        coll, crep = build_collections(src.payments, src.providers, rules, year,
                                       month=month,
                                       week_expr=week_index_expr("paid_on", period))

    weeks = [f"W{i}" for i in range(1, period.weeks_so_far + 1)]
    paced = {block: pace_grid(amounts, weeks, period)
             for block, amounts in grids.items()}
    coll_amounts = {(g, f"W{w}"): amt for g, w, amt in
                    coll.group_by(["Group", "Week"])
                        .agg(pl.col("Payment").sum().alias("amt"))
                        .select("Group", "Week", "amt").rows()}
    collections_paced = pace_grid(coll_amounts, weeks, period)

    kpi_blocks = kpi_layout(rules)
    if src.sql_doc is None:
        kpi, krep = {}, KpiReport()
        notes.append(waiting("KPI SBR or DDE", ["document_log"]))
    else:
        kpi, krep = build_kpi_sql(src.sql_doc, src.providers, kpi_blocks, rules,
                                  year, month)
    kpi.update(build_kpi_scorecard(src.scorecard, src.providers, kpi_blocks,
                                   rules, krep))
    added = add_new_providers(kpi, krep)

    notes += review_notes(drep, krep, added, delta, grids, coll, kpi, period,
                          None, has_scorecard=src.scorecard is not None,
                          has_payments=src.payments is not None)

    return RunResult(
        raw_data=raw, case_ar=case_ar, delta_comparison=delta, collections=coll,
        settlement_grids=grids, cp_settled=cp, kpi=kpi, current_month=month,
        settlement_pace=paced, collections_pace=collections_paced, year=year,
        settlement_month_weeks=month_weeks, period=period,
        notes=sort_notes(notes),
        seconds=time.perf_counter() - t0,
    )
