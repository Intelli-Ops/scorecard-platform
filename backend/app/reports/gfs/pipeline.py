"""GFS: the full calculation, from source tables to finished tables."""
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

    raw, rep = build_raw_data(src.owner_ar, src.providers, src.custom_ar, rules)
    case_ar = build_case_ar(raw, rules)

    comb, drep = combine_delta(src.delta_sheets, rules)
    delta, drep = build_delta(comb, src.gfs_cases, src.providers, src.custom_ar,
                              rules, as_of=as_of, rep=drep)
    delta = attach_comments(delta, src.delta_comments, rules, drep)

    coll, crep = build_collections(src.payments, src.gfs_cases, src.providers, rules,
                                   year=period.year, month=period.month,
                                   week_expr=week_index_expr("paid_on", period))

    grids = settlement_grids(comb, src.gfs_cases, src.providers, period)
    cp = cp_settled(src.hearing_noi, period.year, period.month)

    weeks = [f"W{i}" for i in range(1, period.weeks_so_far + 1)]
    paced = {block: pace_grid(amounts, weeks, period)
             for block, (amounts, _pcts, _totals) in grids.items()}

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
