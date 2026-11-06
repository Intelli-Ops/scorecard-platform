"""GFS: Delta Comparison (steps doc phases 4 and 6)."""
from __future__ import annotations
from dataclasses import dataclass, field
import datetime as dt

import polars as pl

from ...common import (closing_order, i64, keep_settlement_types, mark_gfs,
                       provider_groups, stack_delta, validity)


@dataclass
class DeltaReport:
    """What the review notes need to know about the Delta rows."""
    duplicate_case_ids: int = 0
    comment_rows: dict[str, int] = field(default_factory=dict)
    comments_found: dict[str, tuple[int, int]] = field(default_factory=dict)


def combine_delta(sheets: dict[str, pl.DataFrame], rules: dict) -> pl.DataFrame:
    """PHASE 4: the sheets onto one shape, keeping only the Settlement Types wanted."""
    return keep_settlement_types(stack_delta(sheets, rules), rules)


def build_delta(comb: pl.DataFrame, gfs_cases: pl.DataFrame, providers: pl.DataFrame,
                custom_ar: pl.DataFrame, rules: dict, as_of: dt.date,
                rep: DeltaReport) -> pl.DataFrame:
    """PHASE 6: live GFS settlements with their lookups, bucketed by age, in sheet order."""
    r, ca = rules["delta"], rules["case_ar"]
    d = mark_gfs(comb.with_columns(i64("Case_ID").alias("Case_ID"),
                                   i64("Provider_ID").alias("Provider_ID")),
                 gfs_cases, "Case_ID", r["gfs_type_value"], r["other_type_value"])
    d = d.join(provider_groups(providers, "Provider_ID"), on="Provider_ID", how="left",
               maintain_order="left")
    if r.get("drop_na_group", True):
        d = d.filter(pl.col("Group").is_not_null())         # inactive providers
    if r.get("drop_non_gfs_type", True):
        d = d.filter(pl.col("Type") == r["gfs_type_value"])

    status = pl.col("File_Status").cast(pl.Utf8).str.to_lowercase()
    d = d.filter(~status.str.contains(r["closed_keyword"]) | pl.col("File_Status").is_null())
    partial = status.str.contains(r["partial_paid_keyword"])
    d = d.with_columns(pl.when(partial).then(pl.col(r["partial_paid_uses"]))
                         .otherwise(pl.col("Settlement_Amount")).alias("Settlement_Amount"))

    custom = (custom_ar.with_columns(i64("CASEID").alias("Case_ID"))
                       .unique(subset=["Case_ID"], keep="first")     # VLOOKUP takes the first
                       .select(["Case_ID", *r["custom_ar_columns"]]))
    d = d.join(custom, on="Case_ID", how="inner", maintain_order="left")   # drops NA status

    age = (pl.lit(as_of) - pl.col("Date").cast(pl.Date)).dt.total_days()
    aging = pl.lit(r["aging_default"])
    for days, label in reversed(r["aging_buckets"]):
        aging = pl.when(age <= days).then(pl.lit(label)).otherwise(aging)
    d = d.with_columns(validity(ca).alias("Case_Validity"),
                       closing_order(ca).alias("Closing Order"), aging.alias("Aging"))
    rep.duplicate_case_ids = d.height - d["Case_ID"].n_unique()
    return d


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
        part = (df.select([i64(key).alias("Case_ID"),
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
