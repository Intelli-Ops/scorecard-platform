"""All Providers: settlement grids and Delta Comparison (steps doc phases 4-6)."""
from __future__ import annotations
from dataclasses import dataclass, field

import polars as pl

from ...period import Period, week_index_expr
from ...common import StageLog, i64 as _i64


MONEY = r"[,$%\s]"


@dataclass
class DeltaReport(StageLog):
    per_sheet: dict[str, int] = field(default_factory=dict)
    dropped_no_group: int = 0
    unknown_provider_ids: list[int] = field(default_factory=list)
    locations_seen: dict[str, int] = field(default_factory=dict)
    unknown_payment_received: list[str] = field(default_factory=list)
    outside_week_columns: tuple = (0, 0.0, [])


def combine_delta(sheets: dict[str, pl.DataFrame], rules: dict
                  ) -> tuple[pl.DataFrame, DeltaReport]:
    """PHASE 4 - three sheets onto one fifteen-column shape."""
    rep = DeltaReport()
    parts = []
    for spec in rules["delta"]["sources"]:
        name = spec["sheet"]
        df = sheets[name]
        missing = [src for src in spec["columns"].values() if src not in df.columns]
        if missing:
            raise KeyError(f"[{name}] missing expected column(s): {missing}")
        part = df.select([pl.col(src).alias(dst)
                          for dst, src in spec["columns"].items()])
        parts.append(part.with_columns(pl.lit(name).alias("_source_sheet")))
        rep.per_sheet[name] = part.height
    comb = pl.concat(parts, how="vertical_relaxed")
    rep.add("PHASE 4  combined", comb.height)
    return comb, rep


def prepare(comb: pl.DataFrame, provider_list: pl.DataFrame, rules: dict,
            year: int, rep: DeltaReport | None = None
            ) -> tuple[pl.DataFrame, DeltaReport]:
    """phases 5/6 - attach Group, drop the unlisted providers, keep the report year."""
    r = rules["delta"]
    rep = rep or DeltaReport()

    d = comb.with_columns(
        _i64("Provider_ID").alias("Provider_ID"),
        _i64("Case_ID").alias("Case_ID"),
        pl.col("Date").cast(pl.Date, strict=False).alias("D"),
        pl.col("Location").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
          .alias("loc"),
        pl.col("Settlement_Payment_Received").cast(pl.Utf8).str.strip_chars()
          .str.to_uppercase().alias("recv"))

    prov = (provider_list
            .select(_i64("BUSINESSREGID").alias("Provider_ID"),
                    pl.col("Provider Group").alias("Group"))
            .unique(subset=["Provider_ID"], keep="first"))
    d = d.join(prov, on="Provider_ID", how="left")

    if r.get("drop_na_group", True):
        no_group = d.filter(pl.col("Group").is_null())
        rep.dropped_no_group = no_group.height
        rep.unknown_provider_ids = sorted(
            {int(x) for x in no_group["Provider_ID"].to_list() if x is not None})[:40]
        d = d.filter(pl.col("Group").is_not_null())
    rep.add("1. drop NA Group (providers not in the Provider List)", d.height)

    keep = r.get("keep_settlement_types") or {}
    st = pl.col("Settlement_Type").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
    for sheet, types in keep.items():
        d = d.filter((pl.col("_source_sheet") != sheet)
                     | st.is_in([str(t).strip().lower() for t in types]))
        rep.add(f"2. {sheet}: keep {', '.join(map(str, types))} only", d.height)

    d = d.filter(pl.col("D").dt.year() == year)
    rep.add(f"3. keep {year}", d.height)

    rep.locations_seen = {k: v for k, v in
                          d.group_by("loc").len().sort("len", descending=True).rows()}
    return d, rep


def settlement_grids(d: pl.DataFrame, rules: dict, period: Period,
                     rep: DeltaReport | None = None
                     ) -> dict[str, dict[tuple[str, str], float]]:
    """PHASE 5 - one grid per Location: {(group, bucket): settlement amount}."""
    r = rules["delta"]
    month = period.month
    d = d.with_columns(
        pl.when(pl.col("D").dt.month() == month)
          .then(pl.lit("W") + week_index_expr("D", period).cast(pl.Utf8))
          .otherwise(pl.lit("M") + pl.col("D").dt.month().cast(pl.Utf8))
          .alias("Bucket"))
    shown = {f"W{i}" for i in range(1, period.weeks_so_far + 1)}
    if rep is not None:
        stray = d.filter((pl.col("D").dt.month() == month)
                         & ~pl.col("Bucket").is_in(list(shown)))
        rep.outside_week_columns = (stray.height,
                                    float(stray["Settlement_Amount"].sum() or 0.0),
                                    sorted({b for b in stray["Bucket"].to_list()}))
    out: dict[str, dict[tuple[str, str], float]] = {}
    for label, match in r["locations"].items():
        x = d.filter(pl.col("loc") == match.lower())
        agg = (x.group_by(["Group", "Bucket"])
                .agg(pl.col("Settlement_Amount").sum().alias("amt")))
        out[label] = {(g, b): v for g, b, v in agg.rows()}
    return out


def delta_comparison(d: pl.DataFrame, rules: dict, rep: DeltaReport
                     ) -> pl.DataFrame:
    """PHASE 6 - Group x month x payment-received, over every Location."""
    r = rules["delta"]
    yes, no = r["payment_received_yes"].upper(), r["payment_received_no"].upper()
    seen = {v for v in d["recv"].unique().to_list() if v is not None}
    rep.unknown_payment_received = sorted(seen - {yes, no})
    return (d.with_columns(pl.col("D").dt.month().alias("Month"))
             .group_by(["Group", "Month"])
             .agg(pl.col("Settlement_Amount").sum().alias("Total Settlement"),
                  pl.col("Settlement_Amount")
                    .filter(pl.col("recv") == yes).sum().alias("Pay Received - YES"),
                  pl.col("Settlement_Amount")
                    .filter(pl.col("recv") == no).sum().alias("Pay Received - NO"))
             .sort(["Group", "Month"]))


def cp_settled(noi: pl.DataFrame, year: int, upto_month: int) -> dict[int, tuple]:
    """Phase 7 - CP Settled Cases, from the Hearing Calendar."""
    def num(c: str) -> pl.Expr:
        return (pl.col(c).cast(pl.Utf8).str.replace_all(MONEY, "")
                  .cast(pl.Float64, strict=False))
    x = noi.select(pl.col("Hearing Date").cast(pl.Date, strict=False).alias("HD"),
                   num("Outstanding").alias("O"),
                   num("Settlement Amount").alias("SA"))
    out = {}
    for m in range(1, upto_month + 1):
        s = x.filter((pl.col("HD").dt.year() == year) & (pl.col("HD").dt.month() == m))
        out[m] = (s.height, s["O"].sum() or 0.0, s["SA"].sum() or 0.0)
    return out
