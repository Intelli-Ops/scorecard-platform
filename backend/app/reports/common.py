"""Calculation steps both reports take the same way."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

import polars as pl

MONEY = r"[,$%\s]"          # what a money cell carries besides the number


def i64(col: str) -> pl.Expr:
    """Excel hands integers back as floats (3120398.0)."""
    return pl.col(col).cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


def norm(s: object) -> str:
    """Match sheet labels to source groups ignoring case and punctuation."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def find_row(rows: list[list], marker: str) -> int | None:
    """The first row whose first cell reads `marker`, ignoring case and punctuation."""
    want = norm(marker)
    return next((i for i, r in enumerate(rows) if r and norm(r[0]) == want), None)


def column_index(head: list[str], name: str) -> int | None:
    """Where `name` is in a row of normalised headings, or None."""
    n = norm(name)
    return head.index(n) if n in head else None


def number(v) -> float:
    """A spreadsheet cell as a number: commas dropped, 0.0 if it is not one."""
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def provider_groups(providers: pl.DataFrame, key: str = "BUSINESSREGID",
                    id_col: str = "BUSINESSREGID",
                    group_col: str = "Provider Group") -> pl.DataFrame:
    """Provider id (as `key`) -> Group, one row per id: VLOOKUP takes the first."""
    return (providers.select(i64(id_col).alias(key), pl.col(group_col).cast(pl.Utf8).alias("Group"))
                     .unique(subset=[key], keep="first"))


def mark_gfs(d: pl.DataFrame, gfs_cases: pl.DataFrame, key: str,
             gfs: str, other: str) -> pl.DataFrame:
    """`d` with a Type column: `gfs` for a case on the GFS case list, `other` if not."""
    listed = (gfs_cases.select(i64("CASEID").alias(key)).unique()
                       .with_columns(pl.lit(True).alias("_gfs")))
    return (d.join(listed, on=key, how="left", maintain_order="left")
             .with_columns(pl.when(pl.col("_gfs").fill_null(False)).then(pl.lit(gfs))
                             .otherwise(pl.lit(other)).alias("Type"))
             .drop("_gfs"))


def validity(ca: dict) -> pl.Expr:
    """Case_Validity as the sheet has it: renamed by validity_map, blanks filled."""
    expr = pl.col("Case_Validity")
    if ca.get("validity_map"):
        expr = expr.replace(ca["validity_map"])
    if blank_to := ca.get("validity_blank_becomes"):
        expr = pl.when(pl.col("Case_Validity").is_null()).then(pl.lit(blank_to)).otherwise(expr)
    return expr


def closing_order(ca: dict) -> pl.Expr:
    """Closing Order without its prefix, anything not kept collapsed to the default."""
    co = pl.col("Closing Order")
    if prefix := ca.get("closing_order_strip_prefix"):
        co = co.str.replace(rf"(?i)^{re.escape(prefix)}\s*", "")
    co = co.str.strip_chars()
    return (pl.when(co.is_in(ca["closing_order_keep"])).then(co)
              .otherwise(pl.lit(ca["closing_order_default"])))


def case_ar_rows(owner_ar: pl.DataFrame, providers: pl.DataFrame,
                 custom_ar: pl.DataFrame, ca: dict) -> pl.DataFrame:
    """PHASES 2-3: Owner Case AR rows with their Group, and the Closing Order,
    Case_Validity and FileStatus the Custom Case AR gives each case."""
    df = (owner_ar.with_columns(i64("BUSINESSREGID").alias("BUSINESSREGID"),
                                i64("CASEID").alias("CASEID"))
                  .join(provider_groups(providers), on="BUSINESSREGID", how="left"))
    if ca.get("drop_rows_without_group", True):
        df = df.filter(pl.col("Group").is_not_null())
    custom = (custom_ar.with_columns(i64("CASEID").alias("CASEID"))
                       .unique(subset=["CASEID"], keep="first")      # VLOOKUP takes the first
                       .select(["CASEID", "Closing Order", "Case_Validity", "FileStatus"]))
    how = "inner" if ca.get("drop_rows_without_status", True) else "left"
    return (df.join(custom, on="CASEID", how=how)
              .with_columns(validity(ca).alias("Case_Validity"),
                            closing_order(ca).alias("Closing Order")))


def stack_delta(sheets: dict[str, pl.DataFrame], rules: dict) -> pl.DataFrame:
    """PHASE 4: the Delta sheets uploaded so far onto one shape, each row tagged with
    its sheet."""
    parts = []
    for spec in rules["delta"]["sources"]:
        name = spec["sheet"]
        if name not in sheets:          # its file is not in yet - a partial build
            continue
        df = sheets[name]
        missing = [src for src in spec["columns"].values() if src not in df.columns]
        if missing:
            raise KeyError(f"[{name}] missing expected column(s): {missing}")
        parts.append(df.select([pl.col(src).alias(dst) for dst, src in spec["columns"].items()])
                       .with_columns(pl.lit(name).alias("_source_sheet")))
    return pl.concat(parts, how="vertical_relaxed")


def keep_settlement_types(d: pl.DataFrame, rules: dict) -> pl.DataFrame:
    """Only the Settlement Types rules.yml keeps, on the sheets it names."""
    st = pl.col("Settlement_Type").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
    for sheet, types in (rules["delta"].get("keep_settlement_types") or {}).items():
        d = d.filter((pl.col("_source_sheet") != sheet)
                     | st.is_in([str(t).strip().lower() for t in types]))
    return d


def cp_settled(noi: pl.DataFrame, year: int, upto_month: int) -> dict[int, tuple]:
    """CP Settled Cases from the Hearing Calendar: {month: (cases, outstanding, settled)}."""
    def money(c: str) -> pl.Expr:
        return pl.col(c).cast(pl.Utf8).str.replace_all(MONEY, "").cast(pl.Float64, strict=False)
    x = noi.select(pl.col("Hearing Date").cast(pl.Date, strict=False).alias("HD"),
                   money("Outstanding").alias("O"), money("Settlement Amount").alias("SA"))
    out = {}
    for m in range(1, upto_month + 1):
        s = x.filter((pl.col("HD").dt.year() == year) & (pl.col("HD").dt.month() == m))
        out[m] = (s.height, s["O"].sum() or 0.0, s["SA"].sum() or 0.0)
    return out


@dataclass
class KpiReport:
    """What the KPI build could not place, for the review notes."""
    skipped_blocks: list[str] = field(default_factory=list)
    unmapped_groups: list[tuple[str, str, float]] = field(default_factory=list)
    unknown_providers: list[int] = field(default_factory=list)
    unknown_providers_named: list[str] = field(default_factory=list)
    scorecard_missing: list[str] = field(default_factory=list)


def sql_doc_counts(sql_doc: pl.DataFrame, providers: pl.DataFrame, k: dict,
                   year: int, month: int, type_value: str | None,
                   rep: KpiReport) -> pl.DataFrame:
    """PHASE 8: the SQL-Doc's case counts for the month, by Group and document type.
    Provider ids not on the provider list are noted on `rep` and left out."""
    cols = k["sql_doc_columns"]
    d = sql_doc.select(i64(cols["provider_id"]).alias("pid"),
                       pl.col(cols["type"]).cast(pl.Utf8).alias("type"),
                       pl.col(cols["month"]).cast(pl.Utf8).alias("doc_month"),
                       pl.col(cols["document_type"]).cast(pl.Utf8).alias("doc_type"),
                       pl.col(cols["cases"]).cast(pl.Float64, strict=False).alias("cases"))
    if type_value:
        d = d.filter(pl.col("type").str.strip_chars().str.to_uppercase() == type_value.upper())
    d = (d.filter(pl.col("doc_month").str.strip_chars() == f"{year}-{month:02d}")
          .join(provider_groups(providers, "pid", k["provider_id_column"],
                                k["provider_group_column"]), on="pid", how="left"))
    missing = d.filter(pl.col("Group").is_null())
    rep.unknown_providers = sorted({int(x) for x in missing["pid"].to_list() if x is not None})
    return (d.drop_nulls("Group").group_by(["Group", "doc_type"])
             .agg(pl.col("cases").sum().alias("cases")))


def doc_type_counts(counts: pl.DataFrame, doc_type: str
                    ) -> tuple[dict[str, float], dict[str, str]]:
    """One document type's counts as {normalised group: cases}, and each group's own name."""
    want = norm(doc_type)
    by_group: dict[str, float] = {}
    names: dict[str, str] = {}
    for group, kind, cases in counts.iter_rows():
        if norm(kind) == want:
            by_group[norm(group)] = by_group.get(norm(group), 0.0) + (cases or 0.0)
            names[norm(group)] = group
    return by_group, names
