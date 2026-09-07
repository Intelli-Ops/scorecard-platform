"""The GFS calculation run: source tables in, finished tables out.

This is the middle third of the .bat pipeline's main() - the part between
reading the files and writing the workbook. The reading now lives in
readers.py; the writing is gone entirely, because this project produces no
workbook.

Nothing here calculates anything itself. It calls the audited functions in
core/ in the same order, with the same arguments, as scripts/run_week.py.
The golden-master test exists to keep that true.

Every diagnostic the .bat pipeline printed under "STEP 4 THINGS WORTH YOUR
EYES" is collected as data instead, in RunResult.notes. Those become the
review screen: the same warnings, but recorded against the run rather than
scrolling past in a console window.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl

from .core.case_ar import build_raw_data, build_case_ar
from .core.collections import build_collections
from .core.delta import combine_delta, build_delta
from .core.kpi import build_kpi_sql, build_kpi_scorecard
from .core.settlement import settlement_grids, cp_settled
from ..notes import Note, info, warning, action, sort_notes
from .readers import GfsSources

YEAR = 2026


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

    notes: list[Note] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def tables(self) -> dict[str, pl.DataFrame]:
        return {"raw_data": self.raw_data, "case_ar": self.case_ar,
                "delta_comparison": self.delta_comparison,
                "collections": self.collections}


def run(src: GfsSources, rules: dict,
        as_of: dt.date | None = None) -> RunResult:
    import time
    t0 = time.perf_counter()
    as_of = as_of or dt.date.today()

    raw, rep = build_raw_data(src.owner_ar, src.providers, src.custom_ar, rules)
    case_ar = build_case_ar(raw, rules)

    comb, drep = combine_delta(src.delta_sheets, rules)
    delta, drep = build_delta(comb, src.gfs_cases, src.providers, src.custom_ar,
                              rules, as_of=as_of, rep=drep)

    coll, crep = build_collections(src.payments, src.gfs_cases, src.providers, rules)

    grids, cur_month = settlement_grids(comb, src.gfs_cases, src.providers)
    cp = cp_settled(src.hearing_noi, cur_month)

    kpi, krep = build_kpi_sql(src.sql_doc, src.providers, rules, YEAR, cur_month)
    kpi.update(build_kpi_scorecard(src.scorecard, src.providers, rules, krep))

    return RunResult(
        raw_data=raw, case_ar=case_ar, delta_comparison=delta, collections=coll,
        settlement_grids=grids, cp_settled=cp, kpi=kpi, current_month=cur_month,
        notes=_notes(rep, drep, krep, src, rules),
        seconds=time.perf_counter() - t0,
    )


def _notes(rep, drep, krep, src: GfsSources, rules: dict) -> list[Note]:
    """The STEP 4 warnings, as data rather than console output.

    Same wording as the .bat pipeline so nothing a reader already recognises
    changes meaning. What is added is the code (so a warning can be compared
    with last week's), the severity (so the serious ones sort to the top) and
    the numbers behind the sentence (so the screen can show a trend rather
    than a string).

    Severity is assigned by what it costs the reader, not by how alarming it
    sounds. Dropped rows are routine and expected every week - the COUNT is
    what matters, and a jump is visible because the count is now a number.
    A KPI block with no source is ACTION: a figure the client will look at is
    not there, and someone has to decide whether to send it anyway.
    """
    notes: list[Note] = list(src.notes)

    if rep.dropped_no_group:
        notes.append(warning(
            "ar_rows_dropped_no_group",
            f"{rep.dropped_no_group:,} AR rows dropped - provider not in the "
            f"Provider List (regids {rep.unknown_regids[:6]})",
            rows=rep.dropped_no_group, regids=list(rep.unknown_regids[:6])))
    if rep.dropped_no_status:
        notes.append(warning(
            "ar_rows_dropped_no_status",
            f"{rep.dropped_no_status:,} AR rows dropped - no match in "
            f"Custom Case AR", rows=rep.dropped_no_status))
    for k, v in (rep.validity_fixed or {}).items():
        if v:
            notes.append(info(
                "case_validity_corrected",
                f"{v:,} rows had Case_Validity '{k}' corrected to Valid",
                rows=v, value=k))

    if drep.duplicate_case_ids:
        notes.append(warning(
            "delta_duplicate_case_ids",
            f"{drep.duplicate_case_ids} duplicate case id(s) in "
            f"Delta Comparison", count=drep.duplicate_case_ids))
    if drep.partial_paid_rewritten:
        notes.append(info(
            "delta_partial_paid_rewritten",
            f"{drep.partial_paid_rewritten} Partial Paid row(s): settlement "
            f"amount replaced with remaining payment",
            count=drep.partial_paid_rewritten))

    if krep.skipped_blocks:
        why = ("no column for them in the KPI-numbers file"
               if src.scorecard is not None else
               "no KPI-numbers file was supplied")
        notes.append(action(
            "kpi_block_without_source",
            f"KPI blocks left without a figure - {why}: "
            f"{', '.join(krep.skipped_blocks)}",
            blocks=list(krep.skipped_blocks), reason=why))
    if krep.scorecard_missing:
        notes.append(warning(
            "kpi_columns_not_found",
            f"KPI-numbers columns named in rules.yml but not found in the "
            f"file: {', '.join(krep.scorecard_missing)}",
            columns=list(krep.scorecard_missing)))
    if krep.unknown_providers_named:
        notes.append(warning(
            "kpi_rows_dropped_unknown_provider",
            f"KPI-numbers rows dropped - provider not in the Supporting "
            f"File: {krep.unknown_providers_named}",
            providers=list(krep.unknown_providers_named)))
    if krep.unknown_providers:
        notes.append(warning(
            "sqldoc_rows_dropped_unknown_provider",
            f"SQL-Doc rows dropped - ProviderID not in the Provider List: "
            f"{krep.unknown_providers}",
            providers=list(krep.unknown_providers)))
    for block, group, v in krep.unmapped_groups:
        notes.append(action(
            "kpi_group_not_in_layout",
            f"KPI {block}: '{group}' has {v:,.0f} but the sheet has no row "
            f"for it - NOT counted in the {block} total",
            block=block, group=group, value=float(v)))

    return sort_notes(notes)
