"""GFS: Settlement High-Level grids and CP Settled Cases (steps doc phase 5)."""
from __future__ import annotations

import polars as pl

from ...period import Period, week_index_expr
from ...common import i64

MONEY = r"[,$%\s]"


LOCATIONS = {"In House": "in house", "Board": "board"}


def settled_rows(comb: pl.DataFrame, gfs_cases: pl.DataFrame, prov: pl.DataFrame,
                 period: Period) -> pl.DataFrame:
    """The GFS Delta rows of the reporting year, up to the reporting week, with a group."""
    d = comb.with_columns(
        i64("Case_ID").alias("Case_ID"), i64("Provider_ID").alias("Provider_ID"),
        pl.col("Date").cast(pl.Date, strict=False).alias("D"),
        pl.col("Location").cast(pl.Utf8).str.strip_chars().str.to_lowercase().alias("loc"))
    g = (gfs_cases.select(i64("CASEID").alias("Case_ID")).unique()
                  .with_columns(pl.lit(True).alias("_g")))
    d = (d.join(g, on="Case_ID", how="left")
           .with_columns(pl.when(pl.col("_g").fill_null(False)).then(pl.lit("GFS"))
                           .otherwise(pl.lit("Other")).alias("Type")).drop("_g"))
    p = (prov.select(i64("BUSINESSREGID").alias("Provider_ID"),
                     pl.col("Provider Group").alias("Group"))
             .unique(subset=["Provider_ID"], keep="first"))
    return (d.join(p, on="Provider_ID", how="left")
             .filter(pl.col("D").dt.year() == period.year)
             .filter(pl.col("D") <= period.last_day)
             .filter(pl.col("Group").is_not_null())
             .filter(pl.col("Type") == "GFS"))


def settlement_grids(comb: pl.DataFrame, gfs_cases: pl.DataFrame, prov: pl.DataFrame,
                     period: Period, d: pl.DataFrame | None = None) -> dict:
    """Phase 5: settlement amount and % by group, per past month and per week
    of this month. `d` is settled_rows(), when the caller already has it."""
    if d is None:
        d = settled_rows(comb, gfs_cases, prov, period)
    d = d.with_columns(
        pl.when(pl.col("D").dt.month() == period.month)
          .then(pl.lit("W") + week_index_expr("D", period).cast(pl.Utf8))
          .otherwise(pl.lit("M") + pl.col("D").dt.month().cast(pl.Utf8)).alias("Bucket"))
    out = {}
    for label, key in LOCATIONS.items():
        x = d.filter(pl.col("loc") == key)
        a = (x.group_by(["Group", "Bucket"])
               .agg(pl.col("Settlement_Amount").sum().alias("amt"),
                    (pl.col("Settlement_Amount").sum() + pl.col("Paid").sum()).alias("num"),
                    pl.col("Billed").sum().alias("den")))
        t = (x.group_by("Bucket")
               .agg((pl.col("Settlement_Amount").sum() + pl.col("Paid").sum()).alias("num"),
                    pl.col("Billed").sum().alias("den")))
        out[label] = ({(r[0], r[1]): r[2] for r in a.rows()},
                      {(r[0], r[1]): (r[3] / r[4] if r[4] else 0.0) for r in a.rows()},
                      {r[0]: (r[1] / r[2] if r[2] else 0.0) for r in t.rows()})
    return out


def cp_settled(noi: pl.DataFrame, year: int, cur_month: int) -> dict:
    def num(c):
        return (pl.col(c).cast(pl.Utf8).str.replace_all(MONEY, "")
                  .cast(pl.Float64, strict=False))
    x = noi.select(pl.col("Hearing Date").cast(pl.Date, strict=False).alias("HD"),
                   num("Outstanding").alias("O"), num("Settlement Amount").alias("SA"))
    out = {}
    for m in range(1, cur_month + 1):
        s = x.filter((pl.col("HD").dt.year() == year) & (pl.col("HD").dt.month() == m))
        out[m] = (s.height, s["O"].sum() or 0.0, s["SA"].sum() or 0.0)
    return out
