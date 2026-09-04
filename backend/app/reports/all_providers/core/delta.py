"""Settlement grids and Delta Comparison-2026 - steps doc Phases 4, 5 and 6.

Phase 4 combines WC Delta (WC workbook) + Med-Legal Delta + IMR Delta (MLCR
workbook) onto fifteen shared columns. That part is the same job the GFS pipeline
does, and it hits the same two traps: the MLCR workbook carries a stale WC Delta
sheet, and the three sheets spell the same field three different ways. Columns are
therefore matched BY NAME, never by the positions in the steps doc.

What is different from GFS begins after that:

  * NO "Type = GFS" filter and NO "drop anything closed" filter. The only row
    filter is "delete all NA in Group" - a provider the Supporting File does not
    list is inactive and drops out. Everything else counts.

  * NO Partial Paid rewrite. That rule belongs to the GFS delta sheet, which
    reports live settlements; this report totals the year as it stands.

  * The Delta Comparison-2026 sheet is not a row-level table with pivots over it.
    It is a finished grid: Group down the side, month across the top, each month
    split three ways - Total Settlement, Pay Received YES, Pay Received NO.

  * The Settlement grids are amounts only. The GFS sheet pairs every amount with a
    Settlement % column; this one does not have them.

Verified against the delivered Week-34 workbook, January 2026: all 24 In House
group figures, all 26 Delta Comparison group figures and both payment-received
splits reproduce to the cent, and a group's Delta figure equals its In House +
Board + CP Settled figures added together, which is the check that the grids are
over all locations and the Settlement grids over one location each.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl


def _i64(c: str) -> pl.Expr:
    return pl.col(c).cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


MONEY = r"[,$%\s]"


@dataclass
class DeltaReport:
    stages: list[tuple[str, int]] = field(default_factory=list)
    per_sheet: dict[str, int] = field(default_factory=dict)
    dropped_no_group: int = 0
    unknown_provider_ids: list[int] = field(default_factory=list)
    locations_seen: dict[str, int] = field(default_factory=dict)
    unknown_payment_received: list[str] = field(default_factory=list)
    current_month: int = 0
    # (rows, amount, buckets) dated in the current month but outside the week
    # columns this report covers - reported so nothing is lost in silence.
    outside_week_columns: tuple = (0, 0.0, [])

    def add(self, label: str, n: int) -> None:
        self.stages.append((label, n))

    def show(self) -> str:
        w = max(len(s) for s, _ in self.stages) + 2
        return "\n".join(f"  {s:<{w}} {n:>9,}" for s, n in self.stages)


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
            rep: DeltaReport | None = None) -> tuple[pl.DataFrame, DeltaReport]:
    """PHASES 5/6 - attach Group, drop the unlisted providers, keep the report year.

    This is the one table both the Settlement grids and the Delta Comparison grid
    are built from, so the filters live in one place and cannot drift apart.
    """
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

    d = d.filter(pl.col("D").dt.year() == r["year"])
    rep.add(f"2. keep {r['year']}", d.height)

    rep.locations_seen = {k: v for k, v in
                          d.group_by("loc").len().sort("len", descending=True).rows()}
    rep.current_month = int(d["D"].max().month) if d.height else 0
    return d, rep


def settlement_grids(d: pl.DataFrame, rules: dict, month: int, weeks: list[int],
                     rep: DeltaReport | None = None
                     ) -> dict[str, dict[tuple[str, str], float]]:
    """PHASE 5 - one grid per Location: {(group, bucket): settlement amount}.

    Buckets are "M1".."M12" for whole months and "W32".."W35" for the weeks of the
    month being reported. The week columns are the ones the sheet has - one per
    Monday of the month up to the week being reported - so a settlement dated
    outside them (1 August fell on a Saturday, and the last days of the month have
    not been reported yet) has nowhere to go. Those are counted and reported rather
    than dropped in silence.
    """
    r = rules["delta"]
    d = d.with_columns(
        pl.when(pl.col("D").dt.month() == month)
          .then(pl.lit("W") + pl.col("D").dt.week().cast(pl.Utf8))
          .otherwise(pl.lit("M") + pl.col("D").dt.month().cast(pl.Utf8))
          .alias("Bucket"))
    shown = {f"W{w}" for w in weeks}
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
    """PHASE 6 - Group x month x payment-received, over every Location.

    Returns one row per group and month with three measures, which is exactly the
    three columns the Delta Comparison-2026 sheet devotes to each month.
    """
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
    """Phase 7 - CP Settled Cases, from the Hearing Calendar.

    Sheet "NOI, CP Settlements", filtered to each month of the year so far. Three
    numbers per month: how many cases, what is outstanding, what was settled.
    """
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
