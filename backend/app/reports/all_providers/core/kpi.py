"""All Providers: KPI High-Level (steps doc phases 8-9)."""
from __future__ import annotations
from dataclasses import dataclass, field

import polars as pl

from ...common import (KpiReport, column_index, doc_type_counts, find_row, norm, number,
                       sql_doc_counts)


@dataclass
class KpiBlock:
    """One block of the KPI sheet and its rows, in the sheet's order."""
    name: str
    rows: dict[str, int] = field(default_factory=dict)


def kpi_layout(rules: dict) -> dict[str, KpiBlock]:
    """The sheet's blocks and their rows, as written under kpi.layout."""
    return {name: KpiBlock(name, {label: r for r, label in enumerate(rows)})
            for name, rows in (rules["kpi"].get("layout") or {}).items()}


def _provider_to_group(providers: pl.DataFrame, rules: dict) -> dict[str, str]:
    """Normalised provider name -> its group; the first row wins."""
    k = rules["kpi"]
    col = (k.get("scorecard") or {}).get("lookup_column", "PROVIDER ID")
    out: dict[str, str] = {}
    for name, group in providers.select(
            pl.col(col).cast(pl.Utf8), pl.col(k["provider_group_column"]).cast(pl.Utf8)).iter_rows():
        if name:
            out.setdefault(norm(name), group)
    return out


def _row_key_map(block: KpiBlock, provider_to_group: dict[str, str],
                 aliases: dict[str, str]) -> dict[str, str]:
    """Normalised group name -> the sheet row label that should carry it."""
    out: dict[str, str] = {}
    for label in block.rows:
        out.setdefault(norm(label), label)
        if g := provider_to_group.get(norm(label)):
            out.setdefault(norm(g), label)
        if alias := aliases.get(norm(label)):
            out.setdefault(alias, label)
    return out


def _lay_on_rows(block: KpiBlock, by_group: dict[str, float],
                 provider_to_group: dict[str, str], rep: KpiReport,
                 aliases: dict[str, str], names: dict[str, str]) -> dict[str, float]:
    """Spread a {group: value} map across the block's rows."""
    keys = _row_key_map(block, provider_to_group, aliases)
    vals = {label: 0.0 for label in block.rows}
    for g, v in by_group.items():
        label = keys.get(g)
        if label is not None:
            vals[label] += v
        elif v:
            rep.unmapped_groups.append((block.name, names.get(g, g), v))
    return vals


def _lay_providers(block: KpiBlock, items: list[tuple[str, str, str, float]],
                   provider_to_group: dict[str, str], rep: KpiReport,
                   aliases: dict[str, str]) -> dict[str, float]:
    """Spread KPI-numbers figures, one per PROVIDER, across the block's rows."""
    rows = {norm(label): label for label in block.rows}
    groups = dict(rows)
    for label in block.rows:
        if alias := aliases.get(norm(label)):
            groups.setdefault(alias, label)
    # Groups this block lists provider by provider rather than as one group row.
    split = {norm(g) for label in block.rows
             if (g := provider_to_group.get(norm(label))) and norm(g) != norm(label)}

    vals = {label: 0.0 for label in block.rows}
    extra: dict[str, float] = {}
    for written, key, group, v in items:
        if not v:
            continue
        label = rows.get(norm(written)) or rows.get(key)
        if label is None and norm(group) not in split:
            label = groups.get(norm(group))
        if label is None:
            extra[written] = extra.get(written, 0.0) + v
        else:
            vals[label] += v
    rep.unmapped_groups += [(block.name, written, v) for written, v in extra.items()]
    return vals


def _aliases(rules: dict) -> dict[str, str]:
    return {norm(a): norm(b) for a, b in (rules["kpi"].get("row_aliases") or {}).items()}


def build_kpi_sql(sql_doc: pl.DataFrame, providers: pl.DataFrame,
                  blocks: dict[str, KpiBlock], rules: dict, year: int, month: int,
                  rep: KpiReport) -> dict[str, dict[str, float]]:
    """PHASE 8: the SQL-Doc KPI counts per group, for the blocks it feeds."""
    k = rules["kpi"]
    counts = sql_doc_counts(sql_doc, providers, k, year, month, k.get("filter_type"), rep)
    p2g, aliases = _provider_to_group(providers, rules), _aliases(rules)
    out: dict[str, dict[str, float]] = {}
    for block_name, doc_type in (k.get("sql_blocks") or {}).items():
        block = blocks.get(block_name)
        if block is None:
            rep.skipped_blocks.append(block_name)
            continue
        by_group, names = doc_type_counts(counts, doc_type)
        out[block_name] = _lay_on_rows(block, by_group, p2g, rep, aliases, names)
    return out


def build_kpi_scorecard(table: pl.DataFrame | None, providers: pl.DataFrame,
                        blocks: dict[str, KpiBlock], rules: dict,
                        rep: KpiReport) -> dict[str, dict[str, float]]:
    """PHASE 9: the litigation / scorecard numbers table pasted from email."""
    sc = rules["kpi"].get("scorecard") or {}
    wanted = list(dict.fromkeys([*(sc.get("metrics") or {}).values(),
                                 *(dest[0] for dest in (sc.get("totals") or {}).values())]))
    if table is None or not (sc.get("metrics") or sc.get("totals")):
        rep.skipped_blocks.extend(wanted)
        return {}

    # Each row of the marked blocks, with the headings it was read under.
    rows = [list(r) for r in table.iter_rows()]
    body: list[tuple[list[str], list]] = []
    for start_marker, end_marker in (sc.get("block_markers") or {}).items():
        start, end = find_row(rows, start_marker), find_row(rows, end_marker)
        if start is None or end is None or end <= start:
            rep.scorecard_missing.append(f"block {start_marker!r}")
            continue
        head = [norm(c) for c in rows[start]]
        body += [(head, r) for r in rows[start + 1:end]]
    if not body:
        rep.skipped_blocks.extend(wanted)
        return {}

    p2g = _provider_to_group(providers, rules)
    provider_aliases = {norm(a): norm(b)
                        for a, b in (sc.get("provider_aliases") or {}).items()}
    groups: list[str | None] = []
    keys: list[str] = []
    for _head, r in body:
        key = norm(r[0])
        g = p2g.get(key)
        if g is None and key in provider_aliases:
            key = provider_aliases[key]
            g = p2g.get(key)
        if g is None and str(r[0]).strip():
            rep.unknown_providers_named.append(str(r[0]))
        groups.append(g)
        keys.append(key)

    def cells(src: str):
        """(row, its value under `src`, key, group) for each row with a group and that column."""
        for g, key, (head, r) in zip(groups, keys, body, strict=True):
            col = column_index(head, src)
            if col is not None and g is not None:
                yield r, number(r[col]), key, g

    aliases = _aliases(rules)
    out: dict[str, dict[str, float]] = {}
    for src, block_name in (sc.get("metrics") or {}).items():
        block = blocks.get(block_name)
        if block is None:
            rep.scorecard_missing.append(f"{src} -> no '{block_name}' block on the sheet")
            continue
        items = [(str(r[0]).strip(), key, g, v) for r, v, key, g in cells(src)]
        if not items:
            rep.scorecard_missing.append(src)
            continue
        out[block_name] = _lay_providers(block, items, p2g, rep, aliases)

    for src, (block_name, label) in (sc.get("totals") or {}).items():
        block = blocks.get(block_name)
        if block is None:
            rep.scorecard_missing.append(f"{src} -> no '{block_name}' block on the sheet")
            continue
        row_label = next((lbl for lbl in block.rows if norm(lbl) == norm(label)), None)
        if row_label is None:
            rep.scorecard_missing.append(f"{src} -> no '{label}' row in {block_name}")
            continue
        vals = out.setdefault(block_name, {lbl: 0.0 for lbl in block.rows})
        found = [v for _r, v, _key, _g in cells(src)]
        if not found:
            rep.scorecard_missing.append(src)
            continue
        vals[row_label] = sum(found)

    rep.skipped_blocks.extend(b for b in wanted if b not in out)
    return out
