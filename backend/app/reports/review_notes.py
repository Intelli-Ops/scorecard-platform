"""The checks a person must see before a report goes out."""
from __future__ import annotations
import datetime as dt

import polars as pl

from .notes import Note, action, warning
from .period import Period


def week_label(week: str | None, as_of: dt.date) -> str:
    """The iso week being reported; the run date's own week when none is given."""
    if week:
        return week
    y, w, _ = as_of.isocalendar()
    return f"{y}-W{w:02d}"


def add_new_providers(kpi: dict, krep) -> list[tuple[str, str, float]]:
    """Give every provider with a KPI figure and no row a row of its own."""
    added = []
    for block, name, v in krep.unmapped_groups:
        if v and block in kpi:
            kpi[block][name] = kpi[block].get(name, 0.0) + v
            added.append((block, name, v))
    krep.unmapped_groups = [x for x in krep.unmapped_groups
                            if not (x[2] and x[0] in kpi)]
    return added


def _groups_in(delta: pl.DataFrame, grids: dict, coll: pl.DataFrame) -> set[str]:
    seen: set[str] = set()
    if "Group" in delta.columns:
        seen |= set(delta["Group"].drop_nulls().to_list())
    for value in grids.values():
        amounts = value[0] if isinstance(value, tuple) else value
        seen |= {g for g, _b in amounts if g}
    if "Group" in coll.columns:
        seen |= set(coll["Group"].drop_nulls().to_list())
    return seen


def review_notes(drep, krep, added, delta: pl.DataFrame, grids: dict,
                 coll: pl.DataFrame, kpi: dict, period: Period,
                 layout_groups: list[str] | None, has_scorecard: bool) -> list[Note]:
    """`layout_groups` is None when the report has no fixed group list (All
    Providers reads its layout from last week's sheet)."""
    notes: list[Note] = []

    for block, name, v in added:
        notes.append(action(
            "kpi_new_provider",
            f"New provider in KPI {block}: '{name}' has {v:,.0f} and had no row - "
            f"added as its own row and counted in the {block} total",
            block=block, provider=name, value=float(v)))
    for block, group, v in krep.unmapped_groups:
        notes.append(action(
            "kpi_group_not_in_layout",
            f"KPI {block}: '{group}' has {v:,.0f} but the report has no row for "
            f"it - NOT counted in the {block} total",
            block=block, provider=group, value=float(v)))
    if layout_groups is not None:
        for g in sorted(_groups_in(delta, grids, coll) - set(layout_groups)):
            notes.append(action(
                "new_group",
                f"New group '{g}' in this week's data - not one of the report's "
                f"groups; check its figures land where they should",
                provider=g))
    unknown = list(getattr(krep, "unknown_providers_named", None) or [])
    if unknown:
        notes.append(warning(
            "kpi_rows_dropped_unknown_provider",
            f"Provider(s) in the KPI-numbers file but not in the Supporting File - "
            f"their figures are not counted: {', '.join(map(str, unknown))}",
            providers=[str(u) for u in unknown]))
    if getattr(krep, "unknown_providers", None):
        notes.append(warning(
            "sqldoc_rows_dropped_unknown_provider",
            f"ProviderID(s) in the SQL-Doc but not in the Provider List - their "
            f"figures are not counted: {', '.join(map(str, krep.unknown_providers))}",
            providers=[str(u) for u in krep.unknown_providers]))

    if krep.skipped_blocks:
        why = ("no column for it in the KPI-numbers file" if has_scorecard
               else "no KPI-numbers file was supplied")
        for block in dict.fromkeys(krep.skipped_blocks):
            notes.append(action(
                "kpi_block_without_source",
                f"No data for KPI {block} this week - {why}",
                block=block, reason=why))
    for block, vals in kpi.items():
        if isinstance(vals, dict) and vals and not any(vals.values()):
            notes.append(warning(
                "kpi_block_empty",
                f"No data for KPI {block} in {period.label} - every provider is 0",
                block=block))
    if krep.scorecard_missing:
        notes.append(warning(
            "kpi_columns_not_found",
            f"Expected column(s) not found in the KPI-numbers file, so those "
            f"figures are missing: {', '.join(krep.scorecard_missing)}",
            columns=list(krep.scorecard_missing)))
    if coll.height == 0:
        notes.append(warning(
            "collections_empty",
            f"No payments for {period.label} up to this week in the Payment "
            f"Detail Report", month=period.month))

    if getattr(drep, "duplicate_case_ids", 0) and "Case_ID" in delta.columns:
        dup = (delta.group_by("Case_ID").len().filter(pl.col("len") > 1)
                    .sort("Case_ID")["Case_ID"].to_list())
        if dup:
            shown = ", ".join(map(str, dup[:20])) + (" …" if len(dup) > 20 else "")
            notes.append(warning(
                "delta_duplicate_case_ids",
                f"{len(dup)} duplicate case id(s) in Delta Comparison: {shown}",
                count=len(dup), case_ids=[int(x) for x in dup[:200]]))
    return notes
