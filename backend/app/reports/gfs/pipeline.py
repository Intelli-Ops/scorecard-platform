"""GFS: the full calculation, from source tables to finished tables."""
from __future__ import annotations
import datetime as dt
import time

import polars as pl

from ..closed_weeks import settlement_month_weeks
from ..notes import Note, info, sort_notes, warning
from ..partial import absent, empty, missing_books, waiting
from ..period import reporting_period
from ..result import (COLLECTIONS, RunResult, case_ar_tables, collections_table, cp_table,
                      kpi_notes, paced, rules_layout)
from ..review_notes import add_new_providers, review_notes, week_label
from .core.case_ar import build_case_ar, build_raw_data
from .core.delta import DeltaReport, attach_comments, build_delta, combine_delta
from ..common import KpiReport
from .core.kpi import build_kpi_scorecard, build_kpi_sql
from .core.settlement import LOCATIONS, settled_rows, settlement_grids
from ..reading import Sources

# The four tables' columns, for a section whose files are not in yet.
EMPTY = {
    "raw_data": {"CASEID": pl.Int64, "BUSINESSREGID": pl.Int64, "Group": pl.Utf8,
                 "Closing Order": pl.Utf8, "Case_Validity": pl.Utf8, "FileStatus": pl.Utf8,
                 "FileStatus2": pl.Utf8, "BILLED": pl.Float64, "PAID": pl.Float64,
                 "WRITEOFF": pl.Float64, "ADVANCE": pl.Float64, "OUTSTANDING": pl.Float64},
    "case_ar": {"Case_Validity": pl.Utf8, "Closing Order": pl.Utf8, "# Of Cases": pl.UInt32,
                "BILLED": pl.Float64, "PAID": pl.Float64, "WRITEOFF": pl.Float64,
                "ADVANCE": pl.Float64, "OUTSTANDING": pl.Float64},
    "delta_comparison": {
        "Date": pl.Datetime("ms"), "Location": pl.Utf8, "Case_ID": pl.Int64,
        "MRN": pl.Float64, "Billed": pl.Float64, "Paid": pl.Float64,
        "Outstanding": pl.Float64, "Settlement_Amount": pl.Float64,
        "Settlement_Pct": pl.Float64, "Provider_ID": pl.Int64, "Provider": pl.Utf8,
        "Settlement_Payment": pl.Float64, "Settlement_Payment_Received": pl.Utf8,
        "Remaining_Payment": pl.Float64, "File_Status": pl.Utf8,
        "Settlement_Type": pl.Utf8, "_source_sheet": pl.Utf8, "Type": pl.Utf8,
        "Group": pl.Utf8, "Closing Order": pl.Utf8, "Case_Validity": pl.Utf8,
        "Lien Filed": pl.Utf8, "Aging": pl.Utf8, "Ongoing DOR Status": pl.Utf8,
        "Ongoing DOR Details": pl.Utf8},
    "collections": COLLECTIONS,
}

GROUPS = ["A Miles", "Artheon", "Bayco", "Med-Legal", "Medvantage", "MH Express",
          "POS", "United", "Southern California"]


def comment_notes(drep, rules: dict) -> list[Note]:
    """Review notes on the Ongoing DOR lookups from the comments files."""
    out: list[Note] = []
    sheets = (rules["delta"].get("comments") or {}).get("sheets") or {}
    for sheet in sheets:
        if sheet not in drep.comment_rows:
            out.append(warning(
                "delta_comments_missing",
                f"No '- comments' copy for {sheet} was uploaded - its Ongoing DOR "
                f"Status and Details are blank (the files arrive on Tuesday)",
                block=sheet))
            continue
        got, total = drep.comments_found.get(sheet, (0, 0))
        make = info if got == total else warning
        out.append(make(
            "delta_comments_matched",
            f"Ongoing DOR for {sheet}: {got:,} of {total:,} Delta Comparison "
            f"row(s) found their case id in the comments copy",
            block=sheet, matched=got, rows=total,
            unmatched=total - got))
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
    drep = DeltaReport()
    comb = None
    gone = absent(owner_case_ar=src.owner_ar, delta=src.delta_sheets)
    if gone:
        delta, grids, month_weeks = empty(EMPTY["delta_comparison"]), {}, []
        notes.append(waiting("Delta Comparison or Settlement",
                             [k for k in gone if k != "delta"] + books))
    else:
        if books:
            notes.append(waiting("part of Delta Comparison and Settlement", books))
        comb = combine_delta(src.delta_sheets, rules)
        settled = settled_rows(comb, src.gfs_cases, src.providers, period)
        grids = settlement_grids(settled, period)
        month_weeks = settlement_month_weeks(settled, LOCATIONS, period, with_pct=True)
        if src.custom_ar is None:
            delta = empty(EMPTY["delta_comparison"])
            notes.append(waiting("Delta Comparison", ["custom_case_ar"]))
        else:
            delta = build_delta(comb, src.gfs_cases, src.providers, src.custom_ar,
                                rules, as_of, drep)
            delta = attach_comments(delta, src.delta_comments, rules, drep)

    coll = collections_table(src, rules, period, notes, src.gfs_cases,
                             owner_case_ar=src.owner_ar)
    cp = cp_table(src, period, notes)
    settlement_pace, collections_pace = paced(
        {block: amounts for block, (amounts, _pcts, _totals) in grids.items()}, coll, period)

    krep = KpiReport()
    if src.sql_doc is None:
        kpi = {}
        notes.append(waiting("KPI SBR or DDE", ["document_log"]))
    else:
        kpi = build_kpi_sql(src.sql_doc, src.providers, rules, period.year, period.month, krep)
    kpi.update(build_kpi_scorecard(src.scorecard, src.providers, rules, krep))
    added = add_new_providers(kpi, krep)

    notes += review_notes(drep, krep, added, delta, grids, coll, kpi, period,
                          GROUPS, has_scorecard=src.scorecard is not None,
                          has_payments=src.payments is not None)
    if comb is not None:
        notes += comment_notes(drep, rules)

    return RunResult(
        raw_data=raw, case_ar=case_ar, delta_comparison=delta, collections=coll,
        settlement_grids=grids, cp_settled=cp, kpi=kpi, current_month=period.month,
        settlement_pace=settlement_pace, collections_pace=collections_pace,
        year=period.year, settlement_month_weeks=month_weeks, period=period,
        layout=rules_layout(rules), notes=sort_notes(notes),
        seconds=time.perf_counter() - t0)
