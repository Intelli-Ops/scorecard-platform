"""Collection High-Level — steps doc Phase 7 (Payment Detailed Report).

Verified against week 2026-W35:
    grid   196/196 cells matched (9 groups x 4 weeks x 5 columns, plus the Total row)
    pace    45/45 cells matched
    footer   4/4  matched (BILLING / RE BILLING / APPEAL / SETTLEMENT)

Two things the steps doc leaves implicit and that were confirmed from the data:

  * "in payment type make 'board reps' & 'in house rep', 'settlement'" means BOARD REPS
    and IN HOUSE REPS are folded INTO the SETTLEMENT bucket, not renamed alongside it.
  * The sheet's "Week 01..05" columns are Excel WEEKNUM buckets, not week-of-month.
    For August 2026 that is weeks 32..36, and the fifth holds no payments.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl

from ...common import excel_weeknum, i64 as _i64

PAYMENT_TYPES = ["BILLING", "REBILLING", "APPEAL", "SETTLEMENT"]


@dataclass
class CollectionReport:
    stages: list[tuple[str, int]] = field(default_factory=list)
    weeks: list[int] = field(default_factory=list)
    unknown_groups: list[str] = field(default_factory=list)

    def add(self, label: str, n: int) -> None:
        self.stages.append((label, n))

    def show(self) -> str:
        w = max(len(s) for s, _ in self.stages) + 2
        return "\n".join(f"  {s:<{w}} {n:>9,}" for s, n in self.stages)


def build_collections(payments: pl.DataFrame,
                      gfs_cases: pl.DataFrame,
                      provider_list: pl.DataFrame,
                      rules: dict,
                      year: int = 2026,
                      month: int | None = None,
                      week_expr: pl.Expr | None = None,
                      after: dt.date | None = None) -> tuple[pl.DataFrame, CollectionReport]:
    """Payment Detailed Report -> Group x week x payment-type totals.

    `month` keeps only that month's payments: the sheet's week blocks belong to one
    month, and a report pulled across a month end must not spill into them.
    `week_expr` numbers the weeks (over the `paid_on` column); by default Excel WEEKNUM.
    `after` keeps only payments dated later than that day."""
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

    # drop PI case types
    drop = [x.upper() for x in r["drop_case_types"]]
    d = d.filter(~pl.col("case_type").cast(pl.Utf8).str.to_uppercase().is_in(drop)
                 | pl.col("case_type").is_null())
    rep.add(f"after dropping {'/'.join(r['drop_case_types'])}", d.height)

    # Group from the Provider List
    prov = (provider_list
            .select(_i64("BUSINESSREGID").alias("regid"),
                    pl.col("Provider Group").alias("Group"))
            .unique(subset=["regid"], keep="first"))
    d = d.join(prov, on="regid", how="left")

    # Type: gfs when the case is in Supporting File 'GFS Cases', else other client
    g = (gfs_cases.select(_i64("CASEID").alias("cid")).unique()
                  .with_columns(pl.lit(True).alias("_g")))
    d = (d.join(g, on="cid", how="left")
           .with_columns(pl.when(pl.col("_g").fill_null(False))
                           .then(pl.lit(r["gfs_type_value"]))
                           .otherwise(pl.lit(r["other_type_value"])).alias("Type"))
           .drop("_g"))
    d = d.filter(pl.col("Type") == r["gfs_type_value"])
    rep.add("after Type = gfs", d.height)

    # collapse payment types
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
