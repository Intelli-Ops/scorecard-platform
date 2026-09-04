"""Phase 5 - Settlement High-Level: the In House / Board grids and CP Settled Cases.

Copied VERBATIM from scripts/run_week.py in the .bat pipeline, where these two
functions were left sitting among the Excel-writing code. Nothing inside them is
changed - see the golden-master test.

They live here because they are calculations, not rendering. The All-Providers
pipeline already keeps its equivalents in ap/marts/delta.py; this brings GFS in
line with that.

The .bat pipeline still has its own copies and is not modified. It keeps running
weekly until the golden master proves this project reproduces it.
"""
from __future__ import annotations

import polars as pl

MONEY = r"[,$%\s]"


def i64(c: str) -> pl.Expr:
    return pl.col(c).cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


def settlement_grids(comb: pl.DataFrame, gfs_cases: pl.DataFrame, prov: pl.DataFrame):
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
    d = (d.join(p, on="Provider_ID", how="left")
           .filter(pl.col("D").dt.year() == 2026)
           .filter(pl.col("Group").is_not_null())
           .filter(pl.col("Type") == "GFS"))
    cur = d["D"].max().month
    d = d.with_columns(
        pl.when(pl.col("D").dt.month() == cur)
          .then(pl.lit("W") + pl.col("D").dt.week().cast(pl.Utf8))
          .otherwise(pl.lit("M") + pl.col("D").dt.month().cast(pl.Utf8)).alias("Bucket"))
    out = {}
    for key, label in [("in house", "In House"), ("board", "Board")]:
        x = d.filter(pl.col("loc") == key)
        a = (x.group_by(["Group", "Bucket"])
               .agg(pl.col("Settlement_Amount").sum().alias("amt"),
                    (pl.col("Settlement_Amount").sum() + pl.col("Paid").sum()).alias("num"),
                    pl.col("Billed").sum().alias("den")))
        # The Total row's "Settlement %" is NOT the sum of the group percentages and
        # not their average either - it is the whole block's (settlement + paid) over
        # the whole block's billed. Same formula as a group row, one level up.
        t = (x.group_by("Bucket")
               .agg((pl.col("Settlement_Amount").sum() + pl.col("Paid").sum()).alias("num"),
                    pl.col("Billed").sum().alias("den")))
        out[label] = ({(r[0], r[1]): r[2] for r in a.rows()},
                      {(r[0], r[1]): (r[3] / r[4] if r[4] else 0.0) for r in a.rows()},
                      {r[0]: (r[1] / r[2] if r[2] else 0.0) for r in t.rows()})
    return out, cur


def cp_settled(noi: pl.DataFrame, cur_month: int) -> dict:
    def num(c):
        return (pl.col(c).cast(pl.Utf8).str.replace_all(MONEY, "")
                  .cast(pl.Float64, strict=False))
    x = noi.select(pl.col("Hearing Date").cast(pl.Date, strict=False).alias("HD"),
                   num("Outstanding").alias("O"), num("Settlement Amount").alias("SA"))
    out = {}
    for m in range(1, cur_month + 1):
        s = x.filter((pl.col("HD").dt.year() == 2026) & (pl.col("HD").dt.month() == m))
        out[m] = (s.height, s["O"].sum() or 0.0, s["SA"].sum() or 0.0)
    return out
