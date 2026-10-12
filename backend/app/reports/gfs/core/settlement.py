"""Phase 5 - Settlement High-Level: the In House / Board grids and CP Settled Cases.

Copied VERBATIM from scripts/run_week.py in the .bat pipeline, where these two
functions were left sitting among the Excel-writing code.

Weeks are weeks of the MONTH ("W1".."W5", see period.py), and nothing dated
after the week being reported is counted - a Week-37 report does not show
settlements from Week 38 that happen to be in the delta files already.

They live here because they are calculations, not rendering. The All-Providers
pipeline already keeps its equivalents in ap/marts/delta.py; this brings GFS in
line with that.

The .bat pipeline still has its own copies and is not modified.
"""
from __future__ import annotations

import polars as pl

from ...period import Period, week_index_expr
from ...common import i64

MONEY = r"[,$%\s]"


def settlement_grids(comb: pl.DataFrame, gfs_cases: pl.DataFrame, prov: pl.DataFrame,
                     period: Period) -> dict:
    """Phase 5: settlement amount and % by group, for each past month (bucket 'M<m>')
    and each week of the current month so far (bucket 'W<i>', i = week of the month)."""
    d = comb.with_columns(
        i64("Case_ID").alias("Case_ID"), i64("Provider_ID").alias("Provider_ID"),
        pl.col("Date").cast(pl.Date, strict=False).alias("D"),
        pl.col("Location").cast(pl.Utf8).str.strip_chars().str.to_lowercase().alias("loc"))
    # Med-Legal F&F only is already applied in combine_delta.
    g = (gfs_cases.select(i64("CASEID").alias("Case_ID")).unique()
                  .with_columns(pl.lit(True).alias("_g")))
    d = (d.join(g, on="Case_ID", how="left")
           .with_columns(pl.when(pl.col("_g").fill_null(False)).then(pl.lit("GFS"))
                           .otherwise(pl.lit("Other")).alias("Type")).drop("_g"))
    p = (prov.select(i64("BUSINESSREGID").alias("Provider_ID"),
                     pl.col("Provider Group").alias("Group"))
             .unique(subset=["Provider_ID"], keep="first"))
    d = (d.join(p, on="Provider_ID", how="left")
           .filter(pl.col("D").dt.year() == period.year)
           .filter(pl.col("D") <= period.last_day)
           .filter(pl.col("Group").is_not_null())
           .filter(pl.col("Type") == "GFS"))
    d = d.with_columns(
        pl.when(pl.col("D").dt.month() == period.month)
          .then(pl.lit("W") + week_index_expr("D", period).cast(pl.Utf8))
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
