"""Collection High-Level for both reports (steps doc phase 7)."""
from __future__ import annotations

import polars as pl

from .common import i64, mark_gfs, provider_groups


def build_collections(payments: pl.DataFrame, providers: pl.DataFrame, rules: dict,
                      year: int, month: int, week_expr: pl.Expr,
                      gfs_cases: pl.DataFrame | None = None) -> pl.DataFrame:
    """Payment Detail Report -> Group x week x payment-type totals for the month.
    With `gfs_cases` (GFS) only those cases count; without (All Providers) only
    providers on the list do."""
    r = rules["collections"]
    d = payments.select(
        i64("BUSINESSREGID").alias("regid"),
        *([i64("CASEID").alias("cid")] if gfs_cases is not None else []),
        pl.col("CASETYPE").cast(pl.Utf8).alias("case_type"),
        pl.col("PAYMENT_TYPE").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("ptype"),
        pl.col("PAYMENT").cast(pl.Float64, strict=False).alias("payment"),
        pl.col("PAYMENTDATE").cast(pl.Date, strict=False).alias("paid_on"))

    drop = [x.upper() for x in r["drop_case_types"]]
    d = (d.filter((pl.col("paid_on").dt.year() == year)
                  & (pl.col("paid_on").dt.month() == month))
          .filter(~pl.col("case_type").str.to_uppercase().is_in(drop)
                  | pl.col("case_type").is_null())
          .join(provider_groups(providers, "regid"), on="regid", how="left"))
    if gfs_cases is None:
        d = d.filter(pl.col("Group").is_not_null())
    else:
        gfs = r["gfs_type_value"]
        d = mark_gfs(d, gfs_cases, "cid", gfs, r["other_type_value"]).filter(pl.col("Type") == gfs)

    fold = [x.upper() for x in r["fold_into_settlement"]]
    return (d.with_columns(pl.when(pl.col("ptype").is_in(fold)).then(pl.lit("SETTLEMENT"))
                             .when(pl.col("ptype") == "RE BILLING").then(pl.lit("REBILLING"))
                             .otherwise(pl.col("ptype")).alias("PT"),
                           week_expr.alias("Week"))
             .group_by(["Group", "Week", "PT"])
             .agg(pl.col("payment").sum().alias("Payment"))
             .sort(["Group", "Week", "PT"]))
