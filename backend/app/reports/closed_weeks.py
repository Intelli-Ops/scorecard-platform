"""Closed months opened back into their weeks, for the Settlement grids' + button."""
from __future__ import annotations

import polars as pl

from .period import Period, month_period, week_index_expr

# Months before this were only ever reported as totals, so they stay that way.
WEEKS_KEPT_FROM = (2026, 10)


def closed_months(period: Period) -> list[int]:
    """The months of the reporting year that are over and kept week by week."""
    year, month = WEEKS_KEPT_FROM
    if period.year < year:
        return []
    return list(range(month if period.year == year else 1, period.month))


def settlement_month_weeks(d: pl.DataFrame, locations: dict[str, str], period: Period,
                           with_pct: bool = False) -> list[dict]:
    """One row per block, month, week and group; with `with_pct`, also each week's
    Total row (group None), whose % is not the sum of the rows above it.

    `d` is the settled Delta rows: D, loc, Group, Settlement_Amount, and Paid and
    Billed when `with_pct`."""
    out: list[dict] = []
    sums = [pl.col("Settlement_Amount").sum().alias("amt")]
    if with_pct:
        sums += [(pl.col("Settlement_Amount").sum() + pl.col("Paid").sum()).alias("num"),
                 pl.col("Billed").sum().alias("den")]

    def rec(label, m, row, group):
        r = {"block": label, "month": m, "bucket": row["Bucket"], "group": group,
             "amount": float(row["amt"] or 0.0)}
        if with_pct:
            r["settlement_pct"] = float(row["num"] / row["den"]) if row["den"] else 0.0
        return r

    for m in closed_months(period):
        whole = month_period(period.year, m, period.holidays)
        x = (d.filter(pl.col("D").dt.month() == m)
              .with_columns((pl.lit("W") + week_index_expr("D", whole).cast(pl.Utf8))
                            .alias("Bucket")))
        for label, loc in locations.items():
            y = x.filter(pl.col("loc") == loc.lower())
            for row in y.group_by(["Group", "Bucket"]).agg(sums).iter_rows(named=True):
                out.append(rec(label, m, row, row["Group"]))
            if with_pct:
                for row in y.group_by("Bucket").agg(sums).iter_rows(named=True):
                    out.append(rec(label, m, row, None))
    return sorted(out, key=lambda r: (r["block"], r["month"], r["bucket"],
                                      r["group"] is None, r["group"] or ""))


def week_spans(period: Period) -> dict[str, list[dict]]:
    """The days each week covers: this month's and every closed month's kept by week."""
    def spans(weeks):
        return [{"week": i, "first": a.isoformat(), "last": b.isoformat()}
                for i, (a, b) in enumerate(weeks, 1)]
    out = {str(period.month): spans(period.month_weeks)}
    for m in closed_months(period):
        out[str(m)] = spans(month_period(period.year, m).month_weeks)
    return out
