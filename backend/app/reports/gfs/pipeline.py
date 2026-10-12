"""The GFS calculation run: source tables in, finished tables out.

This is the middle third of the .bat pipeline's main() - the part between
reading the files and writing the workbook. The reading now lives in
readers.py; the writing is gone entirely, because this project produces no
workbook.

Nothing here calculates anything itself. It calls the audited functions in
core/ in the same order, with the same arguments, as scripts/run_week.py.

The checks a person must see before the report goes out - new providers, no
data for the week, duplicate case ids - are collected in RunResult.notes (see
review_notes.py) and become the review screen.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl

from .core.case_ar import build_raw_data, build_case_ar
from .core.collections import build_collections
from .core.delta import attach_comments, combine_delta, build_delta
from .core.kpi import build_kpi_sql, build_kpi_scorecard
from .core.settlement import settlement_grids, cp_settled
from ..notes import Note, info, sort_notes, warning
from ..pacing import pace_grid
from ..period import reporting_period, week_index_expr
from ..review_notes import add_new_providers, review_notes, week_label
from .readers import GfsSources

# The groups the report's sheets are laid out for. A group outside this list is
# a new one - its figures are still shown, and the review says so.
GROUPS = ["A Miles", "Artheon", "Bayco", "Med-Legal", "Medvantage", "MH Express",
          "POS", "United", "Southern California"]


@dataclass
class RunResult:
    """Everything one GFS run produced."""
    # The four tables the .bat pipeline also wrote to marts/<week>/.
    raw_data: pl.DataFrame
    case_ar: pl.DataFrame
    delta_comparison: pl.DataFrame
    collections: pl.DataFrame

    # Sheet-shaped results that were written straight into Excel before and
    # had nowhere else to live.
    settlement_grids: dict
    cp_settled: dict
    kpi: dict
    current_month: int

    # Settlements (In House - Pace) and (Board - Pace): the current month's
    # weeks projected to a full month at the rate seen so far. Empty for a
    # month with no weekly buckets yet.
    settlement_pace: dict = field(default_factory=dict)

    # Collections Pace, the block under the Collection High-Level grid. Built
    # from the week TOTALS - the sheet paces a group's whole week, not each
    # payment type separately.
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
    """What the review says about Tuesday's Ongoing DOR lookups: how many of
    each sheet's rows found their case in the comments copy, or that a
    comments file was not uploaded and its rows are blank."""
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
    """`week` is the label being reported, e.g. 2026-W37. It decides the month
    and its weeks: a Mon-Fri week belongs to the month of its Wednesday (see
    period.py), and nothing dated after that week is counted."""
    import time
    t0 = time.perf_counter()
    as_of = as_of or dt.date.today()
    period = reporting_period(week_label(week, as_of), rules.get("holidays"),
                              rules.get("working_days"))

    raw, rep = build_raw_data(src.owner_ar, src.providers, src.custom_ar, rules)
    case_ar = build_case_ar(raw, rules)

    comb, drep = combine_delta(src.delta_sheets, rules)
    delta, drep = build_delta(comb, src.gfs_cases, src.providers, src.custom_ar,
                              rules, as_of=as_of, rep=drep)
    # Tuesday's Ongoing DOR Status / Details, by Case ID - blank without them.
    delta = attach_comments(delta, src.delta_comments, rules, drep)

    # The sheet's week blocks belong to one month; a payment report pulled
    # across a month end must not spill into them.
    coll, crep = build_collections(src.payments, src.gfs_cases, src.providers, rules,
                                   year=period.year, month=period.month,
                                   week_expr=week_index_expr("paid_on", period))

    grids = settlement_grids(comb, src.gfs_cases, src.providers, period)
    cp = cp_settled(src.hearing_noi, period.year, period.month)

    # The sheet's two Pace blocks. Built from the same grids rather than from a
    # second pass over the data, so a pace can never disagree with the amount
    # it is projected from.
    weeks = [f"W{i}" for i in range(1, period.weeks_so_far + 1)]
    paced = {block: pace_grid(amounts, weeks, period)
             for block, (amounts, _pcts, _totals) in grids.items()}

    # The same projection over Collections, from each group's week TOTALS - the
    # sheet paces a group's whole week, not each payment type separately.
    coll_amounts = {(g, f"W{w}"): amt for g, w, amt in
                    coll.group_by(["Group", "Week"])
                        .agg(pl.col("Payment").sum().alias("amt"))
                        .select("Group", "Week", "amt").rows()}
    collections_paced = pace_grid(coll_amounts, weeks, period)

    kpi, krep = build_kpi_sql(src.sql_doc, src.providers, rules,
                              period.year, period.month)
    kpi.update(build_kpi_scorecard(src.scorecard, src.providers, rules, krep))
    added = add_new_providers(kpi, krep)

    notes: list[Note] = [n for n in src.notes if n.code == "kpi_numbers_not_supplied"]
    notes += review_notes(drep, krep, added, delta, grids, coll, kpi, period,
                          GROUPS, has_scorecard=src.scorecard is not None)
    notes += comment_notes(drep, rules)

    return RunResult(
        raw_data=raw, case_ar=case_ar, delta_comparison=delta, collections=coll,
        settlement_grids=grids, cp_settled=cp, kpi=kpi, current_month=period.month,
        settlement_pace=paced, collections_pace=collections_paced,
        year=period.year,
        notes=sort_notes(notes),
        seconds=time.perf_counter() - t0,
    )
