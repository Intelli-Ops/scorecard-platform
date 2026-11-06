"""GFS: Case AR and Raw Data (steps doc phases 1-3)."""
from __future__ import annotations

import polars as pl

from ...common import case_ar_rows, i64


def _gfs_rows(owner_ar: pl.DataFrame, ca: dict) -> pl.DataFrame:
    """The Owner Case AR rows of the GFS owners and case types."""
    return owner_ar.filter(pl.col("OWNER NAME").is_in(ca["owner_names"])
                           & pl.col("CASETYPE").is_in(ca["case_types"]))


def gfs_case_ids(owner_ar: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """PHASE 1 output: the GFS case list the manual process pastes into the
    Supporting File's 'GFS Cases' sheet."""
    return _gfs_rows(owner_ar, rules["case_ar"]).select(i64("CASEID").alias("CASEID")).unique()


def build_raw_data(owner_ar: pl.DataFrame, providers: pl.DataFrame,
                   custom_ar: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """Combined Owner Case AR -> the Raw Data sheet, by case."""
    ca = rules["case_ar"]
    closed = ca["file_status_closed_value"]
    df = (case_ar_rows(_gfs_rows(owner_ar, ca), providers, custom_ar, ca)
          .with_columns(pl.when(pl.col("FileStatus") == closed).then(pl.lit(closed))
                          .otherwise(pl.lit(ca["file_status_open_value"])).alias("FileStatus2")))
    keys, measures = ca["raw_data_group_by"], ca["raw_data_measures"]
    return (df.group_by(keys)
              .agg([pl.col(m).sum() for m in measures])
              .select(keys[:2] + ["Group"] + keys[3:] + measures)
              .sort(keys))


def build_case_ar(raw: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """Raw Data to the Case AR sheet: a pivot by validity and closing order."""
    ca = rules["case_ar"]
    rows, measures = ca["case_ar_rows"], ca["raw_data_measures"]
    v_order = {v: i for i, v in enumerate(ca["case_ar_row_order"])}
    c_order = {c: i for i, c in enumerate(ca["case_ar_closing_order_order"])}
    return (raw.group_by(rows)
               .agg(pl.len().alias("# Of Cases"), *[pl.col(m).sum() for m in measures])
               .with_columns(pl.col(rows[0]).replace_strict(v_order, default=99).alias("_v"),
                             pl.col(rows[1]).replace_strict(c_order, default=99).alias("_c"))
               .sort(["_v", "_c", *rows]).drop(["_v", "_c"]))
