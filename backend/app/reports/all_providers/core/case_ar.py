"""Raw Data + Case AR for the All Providers scorecard - steps doc Phases 1, 2, 3.

Where this differs from the GFS pipeline, and why:

  * NO owner filter. GFS keeps only OWNER NAME in (GFS, GFS-SPV, Med Legal); the
    All Providers steps say only "In Case_Type column only select Alternative /
    CopyRecord / WC / Workers Compensation". Every owner is in scope here, and what
    narrows the set is the Provider List: a provider the Supporting File does not
    carry has no Group, and rows without a Group are dropped.

  * The Raw Data sheet is THIRTEEN columns, not twelve, and it keeps PROVIDER and
    CASETYPE, which the GFS sheet does not.

  * There is no FileStatus2 (Open/Closed) column. The All Providers Case AR pivot
    puts the raw File Status values down the side - all thirty-odd of them - where
    the GFS one uses Validity x Closing Order.

Checked against the delivered Week-34 workbook: the same filters run over the
Week-35 sources give 468,267 Raw Data rows against its 464,505, and every one of
its thirty-two File Status categories is reproduced.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

import polars as pl

from ...common import i64 as _i64


@dataclass
class BuildReport:
    """Row counts at each stage, so a wrong number can be located, not guessed at."""
    stages: list[tuple[str, int]] = field(default_factory=list)
    dropped_no_group: int = 0
    dropped_no_status: int = 0
    unknown_regids: list[int] = field(default_factory=list)
    validity_fixed: dict[str, int] = field(default_factory=dict)
    closing_order_collapsed: int = 0
    # One case whose BILLED is a large share of the whole report is almost always a
    # typo upstream, not a real bill. Week 35 carried a single Mesa Care case billed
    # 67.9 BILLION - 97% of the report - where the GFS extract of the same case id
    # reads 17,462.26. It would have gone out in the client's Case AR grand total.
    billed_outliers: list[tuple[int, str, float, float]] = field(default_factory=list)

    def add(self, label: str, n: int) -> None:
        self.stages.append((label, n))


def build_raw_data(owner_ar: pl.DataFrame,
                   provider_list: pl.DataFrame,
                   custom_ar: pl.DataFrame,
                   rules: dict) -> tuple[pl.DataFrame, BuildReport]:
    """Combined Owner Case AR -> the Raw Data sheet (13 columns)."""
    r = rules["case_ar"]
    rep = BuildReport()

    # ---- PHASE 1: the three case types. No owner filter - see the module docstring.
    df = owner_ar.filter(pl.col("CASETYPE").is_in(r["case_types"]))
    rep.add("1. filter case types", df.height)
    df = df.with_columns(_i64("BUSINESSREGID").alias("BUSINESSREGID"),
                         _i64("CASEID").alias("CASEID"))

    # ---- PHASE 2: Group from the Provider List -----------------------------------
    prov = (provider_list
            .select(_i64("BUSINESSREGID").alias("BUSINESSREGID"),
                    pl.col("Provider Group").alias("Group"))
            .unique(subset=["BUSINESSREGID"], keep="first"))   # VLOOKUP takes first
    df = df.join(prov, on="BUSINESSREGID", how="left")

    if r.get("drop_rows_without_group", True):
        no_group = df.filter(pl.col("Group").is_null())
        rep.dropped_no_group = no_group.height
        rep.unknown_regids = sorted(no_group["BUSINESSREGID"].unique().to_list())[:40]
        df = df.filter(pl.col("Group").is_not_null())
    rep.add("2. + Group, drop unmapped providers", df.height)

    # ---- PHASE 2: Closing Order / Validity / File Status from Custom Case AR ------
    cus = (custom_ar
           .with_columns(_i64("CASEID").alias("CASEID"))
           .unique(subset=["CASEID"], keep="first")            # VLOOKUP takes first
           .select(["CASEID", "Closing Order", "Case_Validity", "FileStatus"]))
    before = df.height
    how = "inner" if r.get("drop_rows_without_status", True) else "left"
    df = df.join(cus, on="CASEID", how=how)
    rep.dropped_no_status = before - df.height
    rep.add("3. + Closing Order/Validity/Status", df.height)

    # ---- PHASE 2: Case_Validity cleanup ------------------------------------------
    vmap = r.get("validity_map") or {}
    blank_to = r.get("validity_blank_becomes")
    rep.validity_fixed = {k: df.filter(pl.col("Case_Validity") == k).height
                          for k in vmap}
    if blank_to:
        rep.validity_fixed["(blank)"] = df["Case_Validity"].null_count()
    expr = pl.col("Case_Validity")
    if vmap:
        expr = expr.replace(vmap)
    if blank_to:
        expr = (pl.when(pl.col("Case_Validity").is_null())
                  .then(pl.lit(blank_to)).otherwise(expr))
    df = df.with_columns(expr.alias("Case_Validity"))

    # ---- PHASE 2: Closing Order - strip the prefix, then collapse -----------------
    df = df.with_columns(clean_closing_order(r).alias("Closing Order"))
    keep, default = r["closing_order_keep"], r["closing_order_default"]
    # `~col.is_in(...)` is null for null values and so drops them from the count.
    # Nulls ARE collapsed by the when/otherwise below, so count them explicitly.
    rep.closing_order_collapsed = df.filter(
        pl.col("Closing Order").is_null() | ~pl.col("Closing Order").is_in(keep)).height
    df = df.with_columns(
        pl.when(pl.col("Closing Order").is_in(keep))
          .then(pl.col("Closing Order"))
          .otherwise(pl.lit(default))
          .alias("Closing Order"))

    # ---- PHASE 3: the pivot that becomes Raw Data --------------------------------
    keys, measures = r["raw_data_group_by"], r["raw_data_measures"]
    raw = (df.group_by(keys)
             .agg([pl.col(m).sum().alias(m) for m in measures])
             .select(keys + measures)
             .sort(keys[0]))
    raw.columns = list(r["raw_data_headers"])
    rep.add("4. pivot -> Raw Data", raw.height)
    rep.billed_outliers = _billed_outliers(raw, r["raw_data_headers"])
    return raw, rep


def _billed_outliers(raw: pl.DataFrame, headers: list[str],
                     share: float = 0.01) -> list[tuple[int, str, float, float]]:
    """Cases whose BILLED is more than `share` of the whole report's BILLED."""
    caseid, group, billed = headers[0], headers[3], headers[8]
    total = raw[billed].sum() or 0.0
    if total <= 0:
        return []
    big = (raw.filter(pl.col(billed) > total * share)
              .select([caseid, group, billed])
              .sort(billed, descending=True)
              .head(10))
    return [(int(c), str(g), float(b), float(b) / total) for c, g, b in big.rows()]


def clean_closing_order(case_ar_rules: dict, column: str = "Closing Order") -> pl.Expr:
    """Strip the 'CLOSING ORDER: ' prefix and trim. Shared with the delta path."""
    prefix = case_ar_rules.get("closing_order_strip_prefix")
    co = pl.col(column)
    if prefix:
        co = co.str.replace(f"(?i)^{re.escape(prefix)}\\s*", "")
    return co.str.strip_chars()


def build_case_ar(raw: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """Raw Data -> the Case AR sheet: one row per File Status, six measures.

    The sheet itself is a live Excel pivot, so this table exists to be checked and
    to be the prototype's static copy - the delivered workbook rebuilds it from the
    Raw Data sheet when it opens.
    """
    h = rules["case_ar"]["raw_data_headers"]
    status, measures = h[7], h[8:]
    out = (raw.group_by(status)
              .agg(pl.len().alias("Count of Cases"),
                   *[pl.col(m).sum().alias(m.strip()) for m in measures])
              .sort(status))
    total = out.select([pl.lit("Grand Total").alias(status),
                        *[pl.col(c).sum().alias(c) for c in out.columns[1:]]])
    return pl.concat([out, total], how="vertical_relaxed")
