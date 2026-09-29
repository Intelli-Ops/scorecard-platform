"""The Case AR tab, filtered.

The Case AR sheet is a pivot of Raw Data, and in Excel it carries page filters
- Group, File Status, Validity - that re-pivot it on the spot. Raw Data is
hundreds of thousands of rows, so the browser cannot do that; this does it
here, with each report's own Case AR builder, so a filtered table is built the
same way as the unfiltered one the run produced.
"""
from __future__ import annotations

import polars as pl

from ..reports.all_providers.core import case_ar as ap_case_ar
from ..reports.gfs.core import case_ar as gfs_case_ar
from .runner import column_kinds

GRAND_TOTAL = "Grand Total"

# (query key, label, the column it filters in either report's Raw Data)
FILTERS = (
    ("group", "Group", ("Group",)),
    # GFS only: FileStatus2 (Open / Closed), as its sheet does. All Providers
    # has no FileStatus2, so its Case AR filters on Group and Validity alone.
    ("file_status", "File status", ("FileStatus2",)),
    ("validity", "Validity", ("Case_Validity", "Validity")),
)

_BUILD = {"gfs": gfs_case_ar.build_case_ar,
          "all_providers": ap_case_ar.build_case_ar}


def _column(raw: pl.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((c for c in names if c in raw.columns), None)


def case_ar(raw: pl.DataFrame, rules: dict, report_key: str,
            chosen: dict[str, str | None]) -> dict:
    """The Case AR pivot of the Raw Data rows matching `chosen`, with its
    Grand Total row, and what each filter can be set to."""
    filters, narrowed = [], raw
    for key, label, names in FILTERS:
        col = _column(raw, names)
        if col is None:
            continue
        values = sorted(str(v) for v in raw[col].drop_nulls().unique().to_list())
        filters.append({"key": key, "label": label, "values": values})
        if chosen.get(key):
            narrowed = narrowed.filter(pl.col(col).cast(pl.Utf8) == chosen[key])

    rows: list[dict] = []
    columns: list[str] = []
    kinds: dict[str, str] = {}
    if narrowed.height:
        pivot = _BUILD[report_key](narrowed, rules)
        first = pivot.columns[0]
        # All Providers' builder adds its own Grand Total; GFS's does not.
        # Drop it and add one here, so both tabs total the same way.
        pivot = pivot.filter(pl.col(first).cast(pl.Utf8) != GRAND_TOTAL)
        columns = pivot.columns
        kinds = column_kinds(pivot.schema)
        total = {c: (GRAND_TOTAL if c == first else "") if kinds[c] == "text"
                 else pivot[c].sum() for c in columns}
        rows = pivot.to_dicts() + [total]

    return {"columns": columns, "kinds": kinds, "rows": rows, "filters": filters,
            "matched": narrowed.height, "of": raw.height}
