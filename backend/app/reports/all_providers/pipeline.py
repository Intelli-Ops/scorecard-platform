"""The All-Providers calculation run: source tables in, finished tables out.

The middle third of the All-Providers .bat pipeline's main(). It calls the
audited functions in ap/marts in the same order with the same arguments; the
workbook-writing that followed them is gone.

It is a different sequence from the GFS pipeline, not a variation on it -
prepare() before settlement_grids(), the current month taken from the delta
report rather than from the data's own maximum, the week columns worked out
from the week being reported rather than from the weeks present, and the KPI
blocks read out of last week's sheet. That is why the two reports keep separate
pipelines instead of one parameterised engine.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt
import time

import polars as pl

from ..notes import Note, info, warning, action, sort_notes
from .core.case_ar import build_raw_data, build_case_ar
from .core.collections import build_collections
from .core.delta import (combine_delta, prepare, settlement_grids,
                         delta_comparison, cp_settled)
from .core.kpi import build_kpi_sql, build_kpi_scorecard, read_kpi_layout
from .core.period import month_week_columns
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

    notes: list[Note] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def tables(self) -> dict[str, pl.DataFrame]:
        return {"raw_data": self.raw_data, "case_ar": self.case_ar,
                "delta_comparison": self.delta_comparison,
                "collections": self.collections}


def run(src: ApSources, rules: dict, as_of: dt.date | None = None,
        week: str | None = None) -> RunResult:
    """`week` is the label being reported, e.g. 2026-W35.

    It is not cosmetic. The sheet shows one column per Monday in the month UP TO
    the week being reported, not one per week that happens to appear in the
    data: August 2026 settlements run into week 35, but a Week-34 report stops
    at week 34. Without the week label the grid would gain columns the delivered
    workbook does not have.
    """
    t0 = time.perf_counter()
    year = rules["delta"]["year"]

    raw, rep = build_raw_data(src.owner_ar, src.providers, src.custom_ar, rules)
    case_ar = build_case_ar(raw, rules)

    comb, drep = combine_delta(src.delta_sheets, rules)
    dd, drep = prepare(comb, src.providers, rules, drep)
    month = drep.current_month

    report_week = int(week.split("W")[1]) if week else dt.date.today().isocalendar()[1]
    weeks_present = month_week_columns(year, month, report_week)

    grids = settlement_grids(dd, rules, month, weeks_present, drep)
    delta = delta_comparison(dd, rules, drep)
    cp = cp_settled(src.hearing_noi, year, month)
    coll, crep = build_collections(src.payments, src.providers, rules, year)

    kpi_blocks = read_kpi_layout(src.template, rules)
    kpi, krep = build_kpi_sql(src.sql_doc, src.providers, kpi_blocks, rules,
                              year, month)
    kpi.update(build_kpi_scorecard(src.scorecard, src.providers, kpi_blocks,
                                   rules, krep))

    return RunResult(
        raw_data=raw, case_ar=case_ar, delta_comparison=delta, collections=coll,
        settlement_grids=grids, cp_settled=cp, kpi=kpi, current_month=month,
        notes=_notes(rep, drep, krep, src),
        seconds=time.perf_counter() - t0,
    )


def _notes(rep, drep, krep, src: ApSources) -> list[Note]:
    """STEP 4, as data. Same wording as the .bat pipeline; same codes as the GFS
    pipeline wherever the two report the same thing, so a warning means the same
    on both dashboards."""
    notes: list[Note] = list(src.notes)

    if getattr(rep, "dropped_no_group", 0):
        notes.append(warning(
            "ar_rows_dropped_no_group",
            f"{rep.dropped_no_group:,} AR rows dropped - provider not in the "
            f"Provider List (regids {rep.unknown_regids[:6]})",
            rows=rep.dropped_no_group, regids=list(rep.unknown_regids[:6])))
    if getattr(rep, "dropped_no_status", 0):
        notes.append(warning(
            "ar_rows_dropped_no_status",
            f"{rep.dropped_no_status:,} AR rows dropped - no match in "
            f"Custom Case AR", rows=rep.dropped_no_status))
    for k, v in (getattr(rep, "validity_fixed", None) or {}).items():
        if v:
            notes.append(info("case_validity_corrected",
                              f"{v:,} rows had Case_Validity '{k}' corrected to Valid",
                              rows=v, value=k))

    if getattr(drep, "duplicate_case_ids", 0):
        notes.append(warning("delta_duplicate_case_ids",
                             f"{drep.duplicate_case_ids} duplicate case id(s) in "
                             f"Delta Comparison", count=drep.duplicate_case_ids))
    if getattr(drep, "partial_paid_rewritten", 0):
        notes.append(info("delta_partial_paid_rewritten",
                          f"{drep.partial_paid_rewritten} Partial Paid row(s): "
                          f"settlement amount replaced with remaining payment",
                          count=drep.partial_paid_rewritten))

    if getattr(krep, "skipped_blocks", None):
        why = ("no column for them in the KPI-numbers file"
               if src.scorecard is not None else "no KPI-numbers file was supplied")
        notes.append(action("kpi_block_without_source",
                            f"KPI blocks left without a figure - {why}: "
                            f"{', '.join(krep.skipped_blocks)}",
                            blocks=list(krep.skipped_blocks), reason=why))
    if getattr(krep, "scorecard_missing", None):
        notes.append(warning("kpi_columns_not_found",
                             f"KPI-numbers columns named in rules.yml but not found "
                             f"in the file: {', '.join(krep.scorecard_missing)}",
                             columns=list(krep.scorecard_missing)))
    if getattr(krep, "unknown_providers", None):
        notes.append(warning("sqldoc_rows_dropped_unknown_provider",
                             f"SQL-Doc rows dropped - ProviderID not in the "
                             f"Provider List: {krep.unknown_providers}",
                             providers=list(krep.unknown_providers)))
    for entry in (getattr(krep, "unmapped_groups", None) or []):
        block, group, v = entry
        notes.append(action("kpi_group_not_in_layout",
                            f"KPI {block}: '{group}' has {v:,.0f} but the sheet has "
                            f"no row for it - NOT counted in the {block} total",
                            block=block, group=group, value=float(v)))

    return sort_notes(notes)
