"""All Providers: the full calculation, from source tables to finished tables."""
from __future__ import annotations
import datetime as dt
import time

import polars as pl

from ..closed_weeks import settlement_month_weeks
from ..common import KpiReport, stack_delta
from ..notes import sort_notes
from ..partial import empty, missing_books, waiting
from ..period import reporting_period
from ..result import (COLLECTIONS, RunResult, case_ar_tables, collections_table, cp_table,
                      kpi_notes, paced, rules_layout)
from ..review_notes import add_new_providers, review_notes, week_label
from .core.case_ar import build_case_ar, build_raw_data
from .core.delta import delta_comparison, prepare, settlement_grids
from .core.kpi import KpiBlock, build_kpi_scorecard, build_kpi_sql, kpi_layout
from ..reading import Sources


# The four tables' columns, for a section whose files are not in yet.
EMPTY = {
    "raw_data": {"CASEID": pl.Int64, "PROVIDER": pl.Utf8, "BUSINESSREGID": pl.Int64,
                 "Group": pl.Utf8, "CASETYPE": pl.Utf8, "Closing Order": pl.Utf8,
                 "Validity": pl.Utf8, "File Status": pl.Utf8, " BILLED": pl.Float64,
                 " PAID": pl.Float64, "WRITEOFF": pl.Float64, "ADVANCE": pl.Float64,
                 "OUTSTANDING": pl.Float64},
    "case_ar": {"File Status": pl.Utf8, "Count of Cases": pl.UInt32, "BILLED": pl.Float64,
                "Paid": pl.Float64, "Write Off": pl.Float64, "Advance": pl.Float64,
                "Outstanding": pl.Float64},
    "delta_comparison": {"Group": pl.Utf8, "Month": pl.Int8, "Total Settlement": pl.Float64,
                         "Pay Received - YES": pl.Float64, "Pay Received - NO": pl.Float64},
    "collections": COLLECTIONS,
}


def sheet_layout(rules: dict, kpi_blocks: dict[str, KpiBlock]) -> dict[str, list[str]]:
    """Each block's rows in the workbook's order, for the screens: rules.yml `layout`,
    then the KPI blocks (`kpi`) and each one's rows (`kpi/SBR` and so on)."""
    out = rules_layout(rules)
    out["kpi"] = list(kpi_blocks)
    out.update({f"kpi/{name}": list(b.rows) for name, b in kpi_blocks.items()})
    return out


def run(src: Sources, rules: dict, as_of: dt.date | None = None,
        week: str | None = None) -> RunResult:
    """`week` is the label being reported, e.g. 2026-W37."""
    t0 = time.perf_counter()
    as_of = as_of or dt.date.today()
    period = reporting_period(week_label(week, as_of), rules.get("holidays"),
                              rules.get("working_days"))
    notes = kpi_notes(src)

    raw, case_ar = case_ar_tables(src, rules, EMPTY, notes, build_raw_data, build_case_ar)

    books = missing_books(rules, src.delta_sheets)
    if not src.delta_sheets:
        delta, grids, month_weeks = empty(EMPTY["delta_comparison"]), {}, []
        notes.append(waiting("Delta Comparison or Settlement", books))
    else:
        if books:
            notes.append(waiting("part of Delta Comparison and Settlement", books))
        d = prepare(stack_delta(src.delta_sheets, rules), src.providers, rules, period.year)
        grids = settlement_grids(d, rules, period)
        month_weeks = settlement_month_weeks(d, rules["delta"]["locations"], period)
        delta = delta_comparison(d, rules)

    cp = cp_table(src, period, notes)
    coll = collections_table(src, rules, period, notes)
    settlement_pace, collections_pace = paced(grids, coll, period)

    blocks = kpi_layout(rules)
    krep = KpiReport()
    if src.sql_doc is None:
        kpi = {}
        notes.append(waiting("KPI SBR or DDE", ["document_log"]))
    else:
        kpi = build_kpi_sql(src.sql_doc, src.providers, blocks, rules,
                            period.year, period.month, krep)
    kpi.update(build_kpi_scorecard(src.scorecard, src.providers, blocks, rules, krep))
    added = add_new_providers(kpi, krep)

    notes += review_notes(None, krep, added, delta, grids, coll, kpi, period,
                          None, has_scorecard=src.scorecard is not None,
                          has_payments=src.payments is not None)

    return RunResult(
        raw_data=raw, case_ar=case_ar, delta_comparison=delta, collections=coll,
        settlement_grids=grids, cp_settled=cp, kpi=kpi, current_month=period.month,
        settlement_pace=settlement_pace, collections_pace=collections_pace,
        year=period.year, settlement_month_weeks=month_weeks, period=period,
        layout=sheet_layout(rules, blocks), notes=sort_notes(notes),
        seconds=time.perf_counter() - t0)
