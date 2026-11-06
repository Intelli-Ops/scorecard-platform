"""GFS: Settlement High-Level grids (steps doc phase 5)."""
from __future__ import annotations

import polars as pl

from ...common import i64, mark_gfs, provider_groups
from ...period import Period, week_index_expr

LOCATIONS = {"In House": "in house", "Board": "board"}


def settled_rows(comb: pl.DataFrame, gfs_cases: pl.DataFrame, providers: pl.DataFrame,
                 period: Period) -> pl.DataFrame:
    """The GFS Delta rows of the reporting year, up to the reporting week, with a group."""
    d = comb.with_columns(
        i64("Case_ID").alias("Case_ID"), i64("Provider_ID").alias("Provider_ID"),
        pl.col("Date").cast(pl.Date, strict=False).alias("D"),
        pl.col("Location").cast(pl.Utf8).str.strip_chars().str.to_lowercase().alias("loc"))
    return (mark_gfs(d, gfs_cases, "Case_ID", "GFS", "Other")
            .join(provider_groups(providers, "Provider_ID"), on="Provider_ID", how="left")
            .filter((pl.col("D").dt.year() == period.year) & (pl.col("D") <= period.last_day)
                    & pl.col("Group").is_not_null() & (pl.col("Type") == "GFS")))


def settlement_grids(d: pl.DataFrame, period: Period) -> dict:
    """Settlement amount and % by group, per past month and per week of this month,
    from settled_rows(): {location: (amounts, percentages, total row percentages)}."""
    d = d.with_columns(
        pl.when(pl.col("D").dt.month() == period.month)
          .then(pl.lit("W") + week_index_expr("D", period).cast(pl.Utf8))
          .otherwise(pl.lit("M") + pl.col("D").dt.month().cast(pl.Utf8)).alias("Bucket"))
    ratio = [(pl.col("Settlement_Amount").sum() + pl.col("Paid").sum()).alias("num"),
             pl.col("Billed").sum().alias("den")]
    out = {}
    for label, key in LOCATIONS.items():
        x = d.filter(pl.col("loc") == key)
        a = x.group_by(["Group", "Bucket"]).agg(pl.col("Settlement_Amount").sum().alias("amt"),
                                                *ratio).rows()
        t = x.group_by("Bucket").agg(*ratio).rows()
        out[label] = ({(g, b): amt for g, b, amt, _, _ in a},
                      {(g, b): (num / den if den else 0.0) for g, b, _, num, den in a},
                      {b: (num / den if den else 0.0) for b, num, den in t})
    return out
