"""All Providers: settlement grids and Delta Comparison (steps doc phases 4-6)."""
from __future__ import annotations

import polars as pl

from ...common import i64, keep_settlement_types, provider_groups
from ...period import Period, week_index_expr


def prepare(comb: pl.DataFrame, providers: pl.DataFrame, rules: dict,
            year: int) -> pl.DataFrame:
    """PHASES 5-6: attach Group, drop the unlisted providers, keep the report year."""
    d = (comb.with_columns(
            i64("Provider_ID").alias("Provider_ID"), i64("Case_ID").alias("Case_ID"),
            pl.col("Date").cast(pl.Date, strict=False).alias("D"),
            pl.col("Location").cast(pl.Utf8).str.strip_chars().str.to_lowercase().alias("loc"),
            pl.col("Settlement_Payment_Received").cast(pl.Utf8).str.strip_chars()
              .str.to_uppercase().alias("recv"))
         .join(provider_groups(providers, "Provider_ID"), on="Provider_ID", how="left"))
    if rules["delta"].get("drop_na_group", True):
        d = d.filter(pl.col("Group").is_not_null())
    return keep_settlement_types(d, rules).filter(pl.col("D").dt.year() == year)


def settlement_grids(d: pl.DataFrame, rules: dict, period: Period
                     ) -> dict[str, dict[tuple[str, str], float]]:
    """PHASE 5: one grid per Location: {(group, bucket): settlement amount}."""
    d = d.with_columns(
        pl.when(pl.col("D").dt.month() == period.month)
          .then(pl.lit("W") + week_index_expr("D", period).cast(pl.Utf8))
          .otherwise(pl.lit("M") + pl.col("D").dt.month().cast(pl.Utf8))
          .alias("Bucket"))
    return {label: {(g, b): v for g, b, v in
                    d.filter(pl.col("loc") == match.lower())
                     .group_by(["Group", "Bucket"])
                     .agg(pl.col("Settlement_Amount").sum()).rows()}
            for label, match in rules["delta"]["locations"].items()}


def delta_comparison(d: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """PHASE 6: Group x month x payment-received, over every Location."""
    r = rules["delta"]
    amount = pl.col("Settlement_Amount")
    return (d.with_columns(pl.col("D").dt.month().alias("Month"))
             .group_by(["Group", "Month"])
             .agg(amount.sum().alias("Total Settlement"),
                  amount.filter(pl.col("recv") == r["payment_received_yes"].upper())
                        .sum().alias("Pay Received - YES"),
                  amount.filter(pl.col("recv") == r["payment_received_no"].upper())
                        .sum().alias("Pay Received - NO"))
             .sort(["Group", "Month"]))
