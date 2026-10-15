"""All Providers: the full calculation, from source tables to finished tables."""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt
import time

import polars as pl

from ..notes import Note, sort_notes
from ..pacing import pace_grid
from ..period import reporting_period, week_index_expr
from ..review_notes import add_new_providers, review_notes, week_label
from .core.case_ar import build_raw_data, build_case_ar
from .core.collections import build_collections
from .core.delta import (combine_delta, prepare, settlement_grids,
                         delta_comparison, cp_settled)
from .core.kpi import build_kpi_sql, build_kpi_scorecard, read_kpi_layout
from .readers import ApSources


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

    raw, rep = build_raw_data(src.owner_ar, src.providers, src.custom_ar, rules)
    case_ar = build_case_ar(raw, rules)

    comb, drep = combine_delta(src.delta_sheets, rules)
    dd, drep = prepare(comb, src.providers, rules, year, drep)

    grids = settlement_grids(dd, rules, period, drep)
    delta = delta_comparison(dd, rules, drep)
    cp = cp_settled(src.hearing_noi, year, month)
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

    kpi_blocks = read_kpi_layout(src.template, rules)
    kpi, krep = build_kpi_sql(src.sql_doc, src.providers, kpi_blocks, rules,
                              year, month)
    kpi.update(build_kpi_scorecard(src.scorecard, src.providers, kpi_blocks,
                                   rules, krep))
    added = add_new_providers(kpi, krep)

    notes: list[Note] = [n for n in src.notes if n.code == "kpi_numbers_not_supplied"]
    notes += review_notes(drep, krep, added, delta, grids, coll, kpi, period,
                          None, has_scorecard=src.scorecard is not None)

    return RunResult(
        raw_data=raw, case_ar=case_ar, delta_comparison=delta, collections=coll,
        settlement_grids=grids, cp_settled=cp, kpi=kpi, current_month=month,
        settlement_pace=paced, collections_pace=collections_paced, year=year,
        notes=sort_notes(notes),
        seconds=time.perf_counter() - t0,
    )
