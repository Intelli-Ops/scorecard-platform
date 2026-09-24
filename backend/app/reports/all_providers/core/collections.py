"""Collections - steps doc Phase 7 (Payment Detailed Report).

Same source and same shape as the GFS Collection High-Level sheet, with one rule
removed: there is no "Type = GFS" filter. Every provider the Supporting File lists
is reported, so the only rows that leave are payments against a provider the
Provider List does not carry (and any case type listed in rules.yml
`drop_case_types` - empty today: PI payments count on this report).

Two things the steps doc leaves implicit, both confirmed against the delivered
Week-34 workbook:

  * "in payment type make 'board reps' & 'in house rep', 'settlement'" means BOARD
    REPS and IN HOUSE REPS are folded INTO the SETTLEMENT bucket, not renamed
    alongside it.
  * The sheet's "Week 01..05" columns are Excel WEEKNUM buckets, not week-of-month.
    For August 2026 that is weeks 32, 33, 34 - which is exactly the three week
    blocks the Week-34 file carries, with period starts 3, 10 and 17 August.

Verified: Artheon, Russman, Medvantage and Med-Legal reproduce to the cent for
weeks 32 and 33 against the delivered workbook.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl


def _i64(c: str) -> pl.Expr:
    return pl.col(c).cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


def excel_weeknum(col: str, year: int) -> pl.Expr:
    """Excel WEEKNUM, default return type: weeks start Sunday, 1 Jan is week 1."""
    offset = dt.date(year, 1, 1).weekday() % 7          # Mon=0 .. Sun=6 -> Sun=0
    return ((pl.col(col).dt.ordinal_day() + offset - 1) // 7 + 1)


@dataclass
class CollectionReport:
    stages: list[tuple[str, int]] = field(default_factory=list)
    weeks: list[int] = field(default_factory=list)
    dropped_no_group: int = 0
    unknown_regids: list[int] = field(default_factory=list)
    payment_types_seen: list[str] = field(default_factory=list)

    def add(self, label: str, n: int) -> None:
        self.stages.append((label, n))

    def show(self) -> str:
        w = max(len(s) for s, _ in self.stages) + 2
        return "\n".join(f"  {s:<{w}} {n:>9,}" for s, n in self.stages)


def build_collections(payments: pl.DataFrame,
                      provider_list: pl.DataFrame,
                      rules: dict,
                      year: int,
                      month: int | None = None,
                      week_expr: pl.Expr | None = None,
                      after: dt.date | None = None) -> tuple[pl.DataFrame, CollectionReport]:
    """Payment Detailed Report -> Group x week x payment-type totals.

    `month` keeps only that month's payments; `week_expr` numbers the weeks over the
    `paid_on` column (the week of the month - see ap/period.py; Excel WEEKNUM when not
    given); `after` keeps only payments dated later than that day."""
    r = rules["collections"]
    rep = CollectionReport()

    d = payments.select(
        _i64("BUSINESSREGID").alias("regid"),
        pl.col("CASETYPE").cast(pl.Utf8).alias("case_type"),
        pl.col("PAYMENT_TYPE").cast(pl.Utf8).str.strip_chars().str.to_uppercase()
          .alias("ptype"),
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
    d = d.filter(~pl.col("case_type").str.to_uppercase().is_in(drop)
                 | pl.col("case_type").is_null())
    rep.add(f"after dropping {'/'.join(r['drop_case_types']) or 'no case types'}",
            d.height)

    prov = (provider_list
            .select(_i64("BUSINESSREGID").alias("regid"),
                    pl.col("Provider Group").alias("Group"))
            .unique(subset=["regid"], keep="first"))
    d = d.join(prov, on="regid", how="left")
    no_group = d.filter(pl.col("Group").is_null())
    rep.dropped_no_group = no_group.height
    rep.unknown_regids = sorted({int(x) for x in no_group["regid"].to_list()
                                 if x is not None})[:40]
    d = d.filter(pl.col("Group").is_not_null())
    rep.add("after Group lookup", d.height)

    to_settlement = [x.upper() for x in r["fold_into_settlement"]]
    d = d.with_columns(
        pl.when(pl.col("ptype").is_in(to_settlement)).then(pl.lit("SETTLEMENT"))
          .when(pl.col("ptype") == "RE BILLING").then(pl.lit("REBILLING"))
          .otherwise(pl.col("ptype")).alias("PT"))
    rep.payment_types_seen = sorted(
        {v for v in d["PT"].unique().to_list() if v is not None})

    wk = week_expr if week_expr is not None else excel_weeknum("paid_on", year)
    d = d.with_columns(wk.alias("Week"))
    rep.weeks = sorted(x for x in d["Week"].unique().to_list() if x is not None)

    return (d.group_by(["Group", "Week", "PT"])
             .agg(pl.col("payment").sum().alias("Payment"))
             .sort(["Group", "Week", "PT"]), rep)


