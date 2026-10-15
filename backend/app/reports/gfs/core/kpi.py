"""GFS: KPI High-Level (steps doc phases 8-9)."""
from __future__ import annotations
from dataclasses import dataclass, field

import polars as pl

from ...common import find_row as _find_row, norm, number


@dataclass
class KpiReport:
    month: str = ""
    written_blocks: list[str] = field(default_factory=list)
    skipped_blocks: list[str] = field(default_factory=list)
    unmapped_groups: list[tuple[str, str, float]] = field(default_factory=list)
    rows_added: list[str] = field(default_factory=list)     # STEP 4 messages
    unknown_providers: list[int] = field(default_factory=list)
    unknown_providers_named: list[str] = field(default_factory=list)
    scorecard_rows: int = 0
    scorecard_missing: list[str] = field(default_factory=list)
    scorecard_note: str = ""
    totals: dict[str, float] = field(default_factory=dict)


def _group_dim(provider_list: pl.DataFrame, k: dict) -> pl.DataFrame:
    """BUSINESSREGID -> Provider Group, one row per id."""
    return (provider_list
            .select(pl.col(k["provider_id_column"]).cast(pl.Float64, strict=False)
                      .round(0).cast(pl.Int64).alias("pid"),
                    pl.col(k["provider_group_column"]).cast(pl.Utf8).alias("Group"))
            .unique(subset=["pid"], keep="first"))


def _to_rows(spec: dict, by_group: dict[str, float], block: str,
             rep: KpiReport, names: dict[str, str] | None = None) -> dict[str, float]:
    """Lay a {group: value} map onto the block's sheet rows."""
    vals = {label: by_group.pop(norm(label), 0.0) for label in spec["rows"]}
    for leftover, v in by_group.items():
        if v:
            rep.unmapped_groups.append((block, (names or {}).get(leftover, leftover), v))
    return vals


def _lay_providers(spec: dict, items: list[tuple[str, str, float]],
                   provider_to_group: dict[str, str], block: str,
                   rep: KpiReport) -> dict[str, float]:
    """Spread KPI-numbers figures, one per PROVIDER, across the block's rows."""
    rows = {norm(label): label for label in spec["rows"]}
    split = {norm(g) for label in spec["rows"]
             if (g := provider_to_group.get(norm(label))) and norm(g) != norm(label)}
    vals = {label: 0.0 for label in spec["rows"]}
    extra: dict[str, float] = {}
    for written, group, v in items:
        if not v:
            continue
        label = rows.get(norm(written))
        if label is None and norm(group) not in split:
            label = rows.get(norm(group))
        if label is None:
            extra[written] = extra.get(written, 0.0) + v
        else:
            vals[label] += v
    for written, v in extra.items():
        rep.unmapped_groups.append((block, written, v))
    return vals


def build_kpi_sql(sql_doc: pl.DataFrame,
                  provider_list: pl.DataFrame,
                  rules: dict,
                  year: int,
                  month: int,
                  rep: KpiReport | None = None
                  ) -> tuple[dict[str, dict[str, float]], KpiReport]:
    """Phase 8: the SQL-Doc KPI counts per group."""
    k = rules["kpi"]
    rep = rep or KpiReport()
    rep.month = f"{year}-{month:02d}"
    cols = k["sql_doc_columns"]

    d = sql_doc.select(
        pl.col(cols["provider_id"]).cast(pl.Float64, strict=False)
          .round(0).cast(pl.Int64).alias("pid"),
        pl.col(cols["type"]).cast(pl.Utf8).alias("type"),
        pl.col(cols["month"]).cast(pl.Utf8).alias("doc_month"),
        pl.col(cols["document_type"]).cast(pl.Utf8).alias("doc_type"),
        pl.col(cols["cases"]).cast(pl.Float64, strict=False).alias("cases"))

    d = d.filter(pl.col("type").str.strip_chars().str.to_uppercase()
                 == k["gfs_type_value"].upper())
    d = d.filter(pl.col("doc_month").str.strip_chars() == rep.month)

    d = d.join(_group_dim(provider_list, k), on="pid", how="left")

    missing = d.filter(pl.col("Group").is_null())
    if missing.height:
        rep.unknown_providers = sorted({int(x) for x in missing["pid"].to_list()
                                        if x is not None})

    pivot = (d.drop_nulls("Group")
              .group_by(["Group", "doc_type"])
              .agg(pl.col("cases").sum().alias("cases")))

    out: dict[str, dict[str, float]] = {}
    for name, spec in k["blocks"].items():
        if spec.get("source") != "sql_doc":
            continue
        want = norm(spec["document_type"])
        by_group: dict[str, float] = {}
        names: dict[str, str] = {}
        for group, doc_type, cases in pivot.iter_rows():
            if norm(doc_type) == want:
                by_group[norm(group)] = by_group.get(norm(group), 0.0) + (cases or 0.0)
                names[norm(group)] = group
        vals = _to_rows(spec, by_group, name, rep, names)
        out[name] = vals
        rep.written_blocks.append(name)
        rep.totals[name] = sum(vals.values())

    return out, rep


def build_kpi_scorecard(table: pl.DataFrame | None,
                        provider_list: pl.DataFrame,
                        rules: dict,
                        rep: KpiReport) -> dict[str, dict[str, float]]:
    """Phase 9: the KPI-numbers table pasted from email."""
    k = rules["kpi"]
    sc = k.get("scorecard") or {}
    blocks = [n for n, s in k["blocks"].items() if s.get("source") == "scorecard"]

    if table is None or not (sc.get("metrics") or sc.get("totals")):
        rep.skipped_blocks.extend(blocks)
        return {}

    rows = [list(r) for r in table.iter_rows()]
    start = _find_row(rows, sc["block_start"])
    end = _find_row(rows, sc["block_end"])
    if start is None or end is None or end <= start:
        rep.skipped_blocks.extend(blocks)
        rep.scorecard_note = (
            f"could not find the '{sc['block_start']}' .. '{sc['block_end']}' block "
            f"in the KPI-numbers sheet - nothing written")
        return {}

    head = [norm(c) for c in rows[start]]
    body = rows[start + 1:end]
    rep.scorecard_rows = len(body)

    lookup = {norm(r[0]): r[1] for r in
              provider_list.select(pl.col(sc["lookup_column"]).cast(pl.Utf8),
                                   pl.col(k["provider_group_column"]).cast(pl.Utf8)
                                   ).iter_rows()}

    def column(name: str) -> int | None:
        n = norm(name)
        return head.index(n) if n in head else None

    groups: list[str | None] = []
    for r in body:
        g = lookup.get(norm(r[0]))
        if g is None and str(r[0]).strip():
            rep.unknown_providers_named.append(str(r[0]))
        groups.append(g)

    out: dict[str, dict[str, float]] = {}

    for src, block in (sc.get("metrics") or {}).items():
        spec, col = k["blocks"].get(block), column(src)
        if spec is None or col is None:
            rep.scorecard_missing.append(src)
            continue
        items = [(str(r[0]).strip(), g, number(r[col]))
                 for g, r in zip(groups, body) if g is not None]
        out[block] = _lay_providers(spec, items, lookup, block, rep)
        rep.written_blocks.append(block)
        rep.totals[block] = sum(out[block].values())

    for src, dest in (sc.get("totals") or {}).items():
        block, label = dest
        spec, col = k["blocks"].get(block), column(src)
        if spec is None or col is None or label not in spec["rows"]:
            rep.scorecard_missing.append(src)
            continue
        vals = out.setdefault(block, {lbl: 0.0 for lbl in spec["rows"]})
        vals[label] = sum(number(r[col]) for g, r in zip(groups, body) if g is not None)
        if block not in rep.written_blocks:
            rep.written_blocks.append(block)
        rep.totals[block] = sum(vals.values())

    rep.skipped_blocks.extend(b for b in blocks if b not in out)
    return out
