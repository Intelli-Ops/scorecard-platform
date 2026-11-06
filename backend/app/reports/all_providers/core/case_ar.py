"""All Providers: Raw Data and Case AR (steps doc phases 1-3)."""
from __future__ import annotations

import polars as pl

from ...common import case_ar_rows


def build_raw_data(owner_ar: pl.DataFrame, providers: pl.DataFrame,
                   custom_ar: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """Combined Owner Case AR -> the Raw Data sheet (13 columns)."""
    ca = rules["case_ar"]
    df = case_ar_rows(owner_ar.filter(pl.col("CASETYPE").is_in(ca["case_types"])),
                      providers, custom_ar, ca)
    keys, measures = ca["raw_data_group_by"], ca["raw_data_measures"]
    raw = (df.group_by(keys)
             .agg([pl.col(m).sum() for m in measures])
             .select(keys + measures)
             .sort(keys[0]))
    raw.columns = list(ca["raw_data_headers"])
    return raw


def build_case_ar(raw: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """Raw Data -> the Case AR sheet: one row per File Status, the case count and
    five measures under the sheet's headings, highest Outstanding first."""
    ca = rules["case_ar"]
    h = ca["raw_data_headers"]
    status, measures = h[7], h[8:]
    names = ca.get("case_ar_headers") or [m.strip() for m in measures]
    by = ca.get("case_ar_sort")
    out = (raw.group_by(status)
              .agg(pl.len().alias("Count of Cases"),
                   *[pl.col(m).sum().alias(n) for m, n in zip(measures, names, strict=True)]))
    out = out.sort([by, status], descending=[True, False]) if by else out.sort(status)
    total = out.select([pl.lit("Grand Total").alias(status),
                        *[pl.col(c).sum() for c in out.columns[1:]]])
    return pl.concat([out, total], how="vertical_relaxed")
