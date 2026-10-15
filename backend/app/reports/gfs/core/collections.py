"""GFS: Collection High-Level (steps doc phase 7)."""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl

from ...common import StageLog, excel_weeknum, i64 as _i64

PAYMENT_TYPES = ["BILLING", "REBILLING", "APPEAL", "SETTLEMENT"]


@dataclass
class CollectionReport(StageLog):
    weeks: list[int] = field(default_factory=list)
    unknown_groups: list[str] = field(default_factory=list)


def build_collections(payments: pl.DataFrame,
                      gfs_cases: pl.DataFrame,
                      provider_list: pl.DataFrame,
                      rules: dict,
                      year: int = 2026,
                      month: int | None = None,
                      week_expr: pl.Expr | None = None,
                      after: dt.date | None = None) -> tuple[pl.DataFrame, CollectionReport]:
    """Payment Detailed Report -> Group x week x payment-type totals."""
    r = rules["collections"]
    rep = CollectionReport()

    d = payments.select(
        _i64("BUSINESSREGID").alias("regid"),
        _i64("CASEID").alias("cid"),
        pl.col("CASETYPE").cast(pl.Utf8).alias("case_type"),
        pl.col("PAYMENT_TYPE").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("ptype"),
        pl.col("PAYMENT").cast(pl.Float64, strict=False).alias("payment"),
        pl.col("PAYMENTDATE").cast(pl.Date, strict=False).alias("paid_on"))
    rep.add("payment rows", d.height)
    if month is not None:
        d = d.filter((pl.col("paid_on").dt.year() == year)
                     & (pl.col("paid_on").dt.month() == month))
        rep.add(f"in {year}-{month:02d}", d.height)
    if after is not None:
        d = d.filter(pl.col("paid_on") > after)

    drop = [x.upper() for x in r["drop_case_types"]]
    d = d.filter(~pl.col("case_type").cast(pl.Utf8).str.to_uppercase().is_in(drop)
                 | pl.col("case_type").is_null())
    rep.add(f"after dropping {'/'.join(r['drop_case_types'])}", d.height)

    prov = (provider_list
            .select(_i64("BUSINESSREGID").alias("regid"),
                    pl.col("Provider Group").alias("Group"))
            .unique(subset=["regid"], keep="first"))
    d = d.join(prov, on="regid", how="left")

    g = (gfs_cases.select(_i64("CASEID").alias("cid")).unique()
                  .with_columns(pl.lit(True).alias("_g")))
    d = (d.join(g, on="cid", how="left")
           .with_columns(pl.when(pl.col("_g").fill_null(False))
                           .then(pl.lit(r["gfs_type_value"]))
                           .otherwise(pl.lit(r["other_type_value"])).alias("Type"))
           .drop("_g"))
    d = d.filter(pl.col("Type") == r["gfs_type_value"])
    rep.add("after Type = gfs", d.height)

    to_settlement = [x.upper() for x in r["fold_into_settlement"]]
    d = d.with_columns(
        pl.when(pl.col("ptype").is_in(to_settlement)).then(pl.lit("SETTLEMENT"))
          .when(pl.col("ptype") == "RE BILLING").then(pl.lit("REBILLING"))
          .otherwise(pl.col("ptype")).alias("PT"))

    wk = week_expr if week_expr is not None else excel_weeknum("paid_on", year)
    d = d.with_columns(wk.alias("Week"))
    rep.weeks = sorted(x for x in d["Week"].unique().to_list() if x is not None)

    out = (d.group_by(["Group", "Week", "PT"])
             .agg(pl.col("payment").sum().alias("Payment"))
             .sort(["Group", "Week", "PT"]))
    return out, rep
