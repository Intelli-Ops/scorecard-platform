"""GFS: Delta Comparison (steps doc phases 4 and 6)."""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl

from ...common import StageLog, i64 as _i64

FINDING_AND_AWARD_NOTE = (
    "'FINDING & AWARD' collapses to CIC Pending, matching the week-34 sheet and the "
    "Case AR path. The week-35 sheet left 11 such rows uncollapsed."
)


@dataclass
class DeltaReport(StageLog):
    partial_paid_rewritten: int = 0
    per_sheet: dict[str, int] = field(default_factory=dict)
    duplicate_case_ids: int = 0
    comment_rows: dict[str, int] = field(default_factory=dict)
    comments_found: dict[str, tuple[int, int]] = field(default_factory=dict)


def combine_delta(sheets: dict[str, pl.DataFrame], rules: dict) -> tuple[pl.DataFrame, DeltaReport]:
    """PHASE 4 — three sheets onto one 15-column shape."""
    rep = DeltaReport()
    parts = []
    for spec in rules["delta"]["sources"]:
        name = spec["sheet"]
        df = sheets[name]
        missing = [src for src in spec["columns"].values() if src not in df.columns]
        if missing:
            raise KeyError(f"[{name}] missing expected column(s): {missing}")
        part = df.select([pl.col(src).alias(dst) for dst, src in spec["columns"].items()])
        part = part.with_columns(pl.lit(name).alias("_source_sheet"))
        parts.append(part)
        rep.per_sheet[name] = part.height
    comb = pl.concat(parts, how="vertical_relaxed")
    rep.add("PHASE 4  combined", comb.height)

    st = pl.col("Settlement_Type").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
    for sheet, types in (rules["delta"].get("keep_settlement_types") or {}).items():
        comb = comb.filter((pl.col("_source_sheet") != sheet)
                           | st.is_in([str(t).strip().lower() for t in types]))
        rep.add(f"         {sheet}: keep {', '.join(map(str, types))} only", comb.height)
    return comb, rep


def build_delta(comb: pl.DataFrame,
                gfs_cases: pl.DataFrame,
                provider_list: pl.DataFrame,
                custom_ar: pl.DataFrame,
                rules: dict,
                as_of: dt.date | None = None,
                rep: DeltaReport | None = None) -> tuple[pl.DataFrame, DeltaReport]:
    """PHASE 6 — filter to live GFS settlements, attach lookups, bucket by age."""
    r = rules["delta"]
    ca = rules["case_ar"]
    rep = rep or DeltaReport()
    as_of = as_of or dt.date.today()

    d = comb.with_columns(_i64("Case_ID").alias("Case_ID"),
                          _i64("Provider_ID").alias("Provider_ID"))

    gset = gfs_cases.select(_i64("CASEID").alias("Case_ID")).unique()
    d = d.join(gset.with_columns(pl.lit(True).alias("_gfs")), on="Case_ID", how="left")
    d = d.with_columns(
        pl.when(pl.col("_gfs").fill_null(False))
          .then(pl.lit(r["gfs_type_value"]))
          .otherwise(pl.lit(r["other_type_value"])).alias("Type")).drop("_gfs")

    prov = (provider_list
            .select(_i64("BUSINESSREGID").alias("Provider_ID"),
                    pl.col("Provider Group").alias("Group"))
            .unique(subset=["Provider_ID"], keep="first"))
    d = d.join(prov, on="Provider_ID", how="left")

    if r.get("drop_na_group", True):
        d = d.filter(pl.col("Group").is_not_null())
        rep.add("1. drop NA Group (inactive providers)", d.height)
    if r.get("drop_non_gfs_type", True):
        d = d.filter(pl.col("Type") == r["gfs_type_value"])
        rep.add("2. drop non-GFS Type", d.height)

    kw = r["closed_keyword"]
    status_lc = pl.col("File_Status").cast(pl.Utf8).str.to_lowercase()
    d = d.filter(~status_lc.str.contains(kw) | pl.col("File_Status").is_null())
    rep.add(f"3. drop File_Status containing '{kw}'", d.height)

    pp = status_lc.str.contains(r["partial_paid_keyword"])
    rep.partial_paid_rewritten = d.filter(pp).height
    d = d.with_columns(pl.when(pp).then(pl.col(r["partial_paid_uses"]))
                         .otherwise(pl.col("Settlement_Amount")).alias("Settlement_Amount"))

    cols = r["custom_ar_columns"]
    cus = (custom_ar.with_columns(_i64("CASEID").alias("Case_ID"))
                    .unique(subset=["Case_ID"], keep="first")     # VLOOKUP takes first
                    .select(["Case_ID", *cols]))
    d = d.join(cus, on="Case_ID", how="inner")                    # inner == drop NA status
    rep.add("4. join Custom Case AR", d.height)

    vmap = ca.get("validity_map") or {}
    blank_to = ca.get("validity_blank_becomes")
    expr = pl.col("Case_Validity")
    if vmap:
        expr = expr.replace(vmap)
    if blank_to:
        expr = pl.when(pl.col("Case_Validity").is_null()).then(pl.lit(blank_to)).otherwise(expr)
    d = d.with_columns(expr.alias("Case_Validity"))

    prefix = ca.get("closing_order_strip_prefix")
    co = pl.col("Closing Order")
    if prefix:
        co = co.str.replace(rf"(?i)^{prefix}\s*", "")
    d = d.with_columns(co.str.strip_chars().alias("Closing Order"))
    d = d.with_columns(
        pl.when(pl.col("Closing Order").is_in(ca["closing_order_keep"]))
          .then(pl.col("Closing Order"))
          .otherwise(pl.lit(ca["closing_order_default"])).alias("Closing Order"))

    age = (pl.lit(as_of) - pl.col("Date").cast(pl.Date)).dt.total_days()
    expr = pl.lit(r["aging_default"])
    for days, label in reversed(r["aging_buckets"]):
        expr = pl.when(age <= days).then(pl.lit(label)).otherwise(expr)
    d = d.with_columns(expr.alias("Aging"))

    rep.duplicate_case_ids = d.height - d["Case_ID"].n_unique()
    return d, rep


def attach_comments(d: pl.DataFrame, comments: dict[str, pl.DataFrame],
                    rules: dict, rep: DeltaReport) -> pl.DataFrame:
    """Tuesday: the litigation team's Ongoing DOR Status / Details, by Case ID."""
    c = rules["delta"].get("comments") or {}
    cols = list(c.get("columns") or [])
    if not cols:
        return d
    out = d.with_columns([pl.lit(None, dtype=pl.Utf8).alias(x) for x in cols])
    if not comments:
        return out
    key = c.get("key", "Case Id")
    parts = []
    for sheet, df in comments.items():
        missing = [x for x in (key, *cols) if x not in df.columns]
        if missing:
            raise KeyError(f"[{sheet} comments] missing expected column(s): {missing}")
        part = (df.select([_i64(key).alias("Case_ID"),
                           *[pl.col(x).cast(pl.Utf8) for x in cols]])
                  .drop_nulls("Case_ID")
                  .unique(subset=["Case_ID"], keep="first", maintain_order=True)
                  .with_columns(pl.lit(sheet).alias("_source_sheet"),
                                pl.lit(True).alias("_commented")))
        rep.comment_rows[sheet] = part.height
        parts.append(part)
    out = (out.drop(cols)
              .join(pl.concat(parts, how="vertical_relaxed"),
                    on=["Case_ID", "_source_sheet"], how="left", maintain_order="left"))
    for sheet in d["_source_sheet"].unique(maintain_order=True).to_list():
        rows = out.filter(pl.col("_source_sheet") == sheet)
        rep.comments_found[sheet] = (int(rows["_commented"].sum() or 0), rows.height)
    return out.drop("_commented")
