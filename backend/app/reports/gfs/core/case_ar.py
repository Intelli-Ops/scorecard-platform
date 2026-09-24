"""Case AR + Raw Data — steps doc Phases 1, 2 and 3.

Verified end to end against week 2026-W35:
    filter owners/casetypes  -> 414,413   (Supporting File 'GFS Cases')
    join Custom Case AR      -> 301,447   (GFS Formate sheet)
    pivot                    -> 278,930   (Raw Data sheet)
    Case AR                  -> 54/54 cells matched to the cent

All thresholds and value lists come from config/rules.yml, never hardcoded here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

import polars as pl


def _i64(col: str) -> pl.Expr:
    """Excel hands integers back as floats (3120398.0). Normalise before joining —
    a float/int mismatch on a join key silently produces zero matches."""
    return pl.col(col).cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


@dataclass
class BuildReport:
    """Row counts at each stage, so a wrong number can be located, not guessed at."""
    stages: list[tuple[str, int]] = field(default_factory=list)
    dropped_no_group: int = 0
    dropped_no_status: int = 0
    unknown_regids: list[int] = field(default_factory=list)
    validity_fixed: dict[str, int] = field(default_factory=dict)
    closing_order_collapsed: int = 0

    def add(self, label: str, n: int) -> None:
        self.stages.append((label, n))

    def show(self) -> str:
        w = max(len(s) for s, _ in self.stages) + 2
        out = [f"  {s:<{w}} {n:>9,}" for s, n in self.stages]
        return "\n".join(out)


def gfs_case_ids(owner_ar: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """PHASE 1 output: the GFS case list the manual process pastes into the Supporting
    File's 'GFS Cases' sheet. Built here from the same filter as Raw Data, so that
    sheet can stay empty - Delta, Settlement and Collections all read this instead."""
    r = rules["case_ar"]
    return (owner_ar
            .filter(pl.col("OWNER NAME").is_in(r["owner_names"])
                    & pl.col("CASETYPE").is_in(r["case_types"]))
            .select(_i64("CASEID").alias("CASEID"))
            .unique())


def build_raw_data(owner_ar: pl.DataFrame,
                   provider_list: pl.DataFrame,
                   custom_ar: pl.DataFrame,
                   rules: dict) -> tuple[pl.DataFrame, BuildReport]:
    """Combined Owner Case AR -> the Raw Data sheet (278,930 x 12)."""
    r = rules["case_ar"]
    rep = BuildReport()

    # ---- PHASE 1: keep only GFS-owned cases of the three relevant types ----------
    df = owner_ar.filter(
        pl.col("OWNER NAME").is_in(r["owner_names"])
        & pl.col("CASETYPE").is_in(r["case_types"])
    )
    rep.add("1. filter owners + case types", df.height)
    df = df.with_columns(_i64("BUSINESSREGID").alias("BUSINESSREGID"),
                         _i64("CASEID").alias("CASEID"))

    # ---- PHASE 2: attach Group from the Provider List ----------------------------
    prov = (provider_list
            .select(_i64("BUSINESSREGID").alias("BUSINESSREGID"),
                    pl.col("Provider Group").alias("Group"))
            .unique(subset=["BUSINESSREGID"], keep="first"))   # VLOOKUP takes the first
    df = df.join(prov, on="BUSINESSREGID", how="left")

    if r.get("drop_rows_without_group", True):
        no_group = df.filter(pl.col("Group").is_null())
        rep.dropped_no_group = no_group.height
        rep.unknown_regids = sorted(no_group["BUSINESSREGID"].unique().to_list())[:40]
        df = df.filter(pl.col("Group").is_not_null())
    rep.add("2. + Group, drop unmapped providers", df.height)

    # ---- PHASE 2: Closing Order / Validity / FileStatus from Custom Case AR -------
    cus = (custom_ar
           .with_columns(_i64("CASEID").alias("CASEID"))
           .unique(subset=["CASEID"], keep="first")            # VLOOKUP takes the first
           .select(["CASEID", "Closing Order", "Case_Validity", "FileStatus"]))
    before = df.height
    how = "inner" if r.get("drop_rows_without_status", True) else "left"
    df = df.join(cus, on="CASEID", how=how)
    rep.dropped_no_status = before - df.height
    rep.add("3. + Closing Order/Validity/Status", df.height)

    # ---- PHASE 2: Case_Validity cleanup ------------------------------------------
    vmap = r.get("validity_map") or {}
    blank_to = r.get("validity_blank_becomes")
    rep.validity_fixed = {
        k: df.filter(pl.col("Case_Validity") == k).height for k in vmap
    }
    if blank_to:
        rep.validity_fixed["(blank)"] = df["Case_Validity"].null_count()
    expr = pl.col("Case_Validity")
    if vmap:
        expr = expr.replace(vmap)
    if blank_to:
        expr = pl.when(pl.col("Case_Validity").is_null()).then(pl.lit(blank_to)).otherwise(expr)
    df = df.with_columns(expr.alias("Case_Validity"))

    # ---- PHASE 2: Closing Order — strip prefix, then collapse ---------------------
    prefix = r.get("closing_order_strip_prefix")
    co = pl.col("Closing Order")
    if prefix:
        co = co.str.replace(f"(?i)^{re.escape(prefix)}\s*", "")
    df = df.with_columns(co.str.strip_chars().alias("Closing Order"))
    keep, default = r["closing_order_keep"], r["closing_order_default"]
    # NB: `~col.is_in(...)` evaluates to null for null values and so silently drops
    # them from the count. Nulls ARE collapsed by the when/otherwise below, so count
    # them explicitly or this number understates by ~110k.
    rep.closing_order_collapsed = df.filter(
        pl.col("Closing Order").is_null() | ~pl.col("Closing Order").is_in(keep)).height
    df = df.with_columns(
        pl.when(pl.col("Closing Order").is_in(keep))
          .then(pl.col("Closing Order"))
          .otherwise(pl.lit(default))
          .alias("Closing Order"))

    # ---- PHASE 3: FileStatus2 (Open / Closed) ------------------------------------
    closed = r["file_status_closed_value"]
    df = df.with_columns(
        pl.when(pl.col("FileStatus") == closed)
          .then(pl.lit(closed))
          .otherwise(pl.lit(r["file_status_open_value"]))
          .alias("FileStatus2"))

    # ---- PHASE 2/3: the pivot that becomes Raw Data ------------------------------
    keys, measures = r["raw_data_group_by"], r["raw_data_measures"]
    raw = (df.group_by(keys)
             .agg([pl.col(m).sum().alias(m) for m in measures])
             .select(keys[:2] + ["Group"] + keys[3:] + measures))
    rep.add("4. pivot -> Raw Data", raw.height)
    return raw, rep


def build_case_ar(raw: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """Raw Data -> the Case AR sheet: Validity x Closing Order, six measures."""
    r = rules["case_ar"]
    rows, measures = r["case_ar_rows"], r["raw_data_measures"]
    out = (raw.group_by(rows)
              .agg(pl.len().alias("# Of Cases"),
                   *[pl.col(m).sum().alias(m) for m in measures]))
    v_order = {v: i for i, v in enumerate(r["case_ar_row_order"])}
    c_order = {c: i for i, c in enumerate(r["case_ar_closing_order_order"])}
    return (out
            .with_columns(pl.col(rows[0]).replace_strict(v_order, default=99).alias("_v"),
                          pl.col(rows[1]).replace_strict(c_order, default=99).alias("_c"))
            .sort(["_v", "_c"]).drop(["_v", "_c"]))
