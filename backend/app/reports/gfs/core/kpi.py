"""GFS: KPI High-Level (steps doc phases 8-9)."""
from __future__ import annotations

import polars as pl

from ...common import (KpiReport, column_index, doc_type_counts, find_row, norm, number,
                       sql_doc_counts)


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


def build_kpi_sql(sql_doc: pl.DataFrame, providers: pl.DataFrame, rules: dict,
                  year: int, month: int, rep: KpiReport) -> dict[str, dict[str, float]]:
    """PHASE 8: the SQL-Doc KPI counts per group, for the blocks it feeds."""
    k = rules["kpi"]
    counts = sql_doc_counts(sql_doc, providers, k, year, month, k["gfs_type_value"], rep)
    out: dict[str, dict[str, float]] = {}
    for name, spec in k["blocks"].items():
        if spec.get("source") == "sql_doc":
            by_group, names = doc_type_counts(counts, spec["document_type"])
            out[name] = _to_rows(spec, by_group, name, rep, names)
    return out


def build_kpi_scorecard(table: pl.DataFrame | None,
                        providers: pl.DataFrame,
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
    start = find_row(rows, sc["block_start"])
    end = find_row(rows, sc["block_end"])
    if start is None or end is None or end <= start:
        rep.skipped_blocks.extend(blocks)
        return {}

    head = [norm(c) for c in rows[start]]
    body = rows[start + 1:end]

    lookup = {norm(name): group for name, group in
              providers.select(pl.col(sc["lookup_column"]).cast(pl.Utf8),
                               pl.col(k["provider_group_column"]).cast(pl.Utf8)).iter_rows()}

    groups: list[str | None] = []
    for r in body:
        g = lookup.get(norm(r[0]))
        if g is None and str(r[0]).strip():
            rep.unknown_providers_named.append(str(r[0]))
        groups.append(g)

    out: dict[str, dict[str, float]] = {}

    for src, block in (sc.get("metrics") or {}).items():
        spec, col = k["blocks"].get(block), column_index(head, src)
        if spec is None or col is None:
            rep.scorecard_missing.append(src)
            continue
        items = [(str(r[0]).strip(), g, number(r[col]))
                 for g, r in zip(groups, body, strict=True) if g is not None]
        out[block] = _lay_providers(spec, items, lookup, block, rep)

    for src, dest in (sc.get("totals") or {}).items():
        block, label = dest
        spec, col = k["blocks"].get(block), column_index(head, src)
        if spec is None or col is None or label not in spec["rows"]:
            rep.scorecard_missing.append(src)
            continue
        vals = out.setdefault(block, {lbl: 0.0 for lbl in spec["rows"]})
        vals[label] = sum(number(r[col]) for g, r in zip(groups, body, strict=True)
                          if g is not None)

    rep.skipped_blocks.extend(b for b in blocks if b not in out)
    return out
