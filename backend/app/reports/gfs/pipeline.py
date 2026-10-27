"""GFS: the full calculation, from source tables to finished tables."""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl

from .core.case_ar import build_raw_data, build_case_ar
from .core.collections import build_collections
from .core.delta import DeltaReport, attach_comments, combine_delta, build_delta
from .core.kpi import KpiReport, build_kpi_sql, build_kpi_scorecard
from .core.settlement import settlement_grids, cp_settled
from ..notes import Note, info, sort_notes, warning
from ..pacing import pace_grid
from ..partial import absent, empty, missing_books, waiting
from ..period import reporting_period, week_index_expr
from ..review_notes import add_new_providers, review_notes, week_label
from .readers import GfsSources

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
    "collections": {"Group": pl.Utf8, "Week": pl.Int32, "PT": pl.Utf8, "Payment": pl.Float64},
}

GROUPS = ["A Miles", "Artheon", "Bayco", "Med-Legal", "Medvantage", "MH Express",
          "POS", "United", "Southern California"]


@dataclass
class RunResult:
    """Everything one GFS run produced."""
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

    notes: list[Note] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def tables(self) -> dict[str, pl.DataFrame]:
        return {"raw_data": self.raw_data, "case_ar": self.case_ar,
                "delta_comparison": self.delta_comparison,
                "collections": self.collections}


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


def run(src: GfsSources, rules: dict, as_of: dt.date | None = None,
        week: str | None = None) -> RunResult:
    """`week` is the label being reported, e.g. 2026-W37."""
    import time
    t0 = time.perf_counter()
    as_of = as_of or dt.date.today()
    period = reporting_period(week_label(week, as_of), rules.get("holidays"),
                              rules.get("working_days"))

    notes: list[Note] = [n for n in src.notes if n.code == "kpi_numbers_not_supplied"]

    gone = absent(owner_case_ar=src.owner_ar, custom_case_ar=src.custom_ar)
    if gone:
        raw, case_ar = empty(EMPTY["raw_data"]), empty(EMPTY["case_ar"])
        notes.append(waiting("Raw Data or Case AR", gone))
    else:
        raw, rep = build_raw_data(src.owner_ar, src.providers, src.custom_ar, rules)
        case_ar = build_case_ar(raw, rules)

    books = missing_books(rules, src.delta_sheets)
    drep = DeltaReport()
    comb = None
    gone = absent(owner_case_ar=src.owner_ar, delta=src.delta_sheets)
    if gone:
        delta, grids = empty(EMPTY["delta_comparison"]), {}
        notes.append(waiting("Delta Comparison or Settlement",
                             [k for k in gone if k != "delta"] + books))
    else:
        if books:
            notes.append(waiting("part of Delta Comparison and Settlement", books))
        comb, drep = combine_delta(src.delta_sheets, rules)
        grids = settlement_grids(comb, src.gfs_cases, src.providers, period)
        if src.custom_ar is None:
            delta = empty(EMPTY["delta_comparison"])
            notes.append(waiting("Delta Comparison", ["custom_case_ar"]))
        else:
            delta, drep = build_delta(comb, src.gfs_cases, src.providers, src.custom_ar,
                                      rules, as_of=as_of, rep=drep)
            delta = attach_comments(delta, src.delta_comments, rules, drep)

    gone = absent(payment_detail=src.payments, owner_case_ar=src.owner_ar)
    if gone:
        coll = empty(EMPTY["collections"])
        notes.append(waiting("Collections", gone))
    else:
        coll, crep = build_collections(src.payments, src.gfs_cases, src.providers, rules,
                                       year=period.year, month=period.month,
                                       week_expr=week_index_expr("paid_on", period))

    if src.hearing_noi is None:
        cp = {}
        notes.append(waiting("CP Settled Cases", ["hearing_calendar"]))
    else:
        cp = cp_settled(src.hearing_noi, period.year, period.month)

    weeks = [f"W{i}" for i in range(1, period.weeks_so_far + 1)]
    paced = {block: pace_grid(amounts, weeks, period)
             for block, (amounts, _pcts, _totals) in grids.items()}

    coll_amounts = {(g, f"W{w}"): amt for g, w, amt in
                    coll.group_by(["Group", "Week"])
                        .agg(pl.col("Payment").sum().alias("amt"))
                        .select("Group", "Week", "amt").rows()}
    collections_paced = pace_grid(coll_amounts, weeks, period)

    if src.sql_doc is None:
        kpi, krep = {}, KpiReport()
        notes.append(waiting("KPI SBR or DDE", ["document_log"]))
    else:
        kpi, krep = build_kpi_sql(src.sql_doc, src.providers, rules,
                                  period.year, period.month)
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
        settlement_pace=paced, collections_pace=collections_paced,
        year=period.year,
        notes=sort_notes(notes),
        seconds=time.perf_counter() - t0,
    )
