"""All Providers: KPI High-Level (steps doc phases 8-9)."""
from __future__ import annotations
from dataclasses import dataclass, field

import polars as pl

from ...common import find_row as _find_row, norm, number


@dataclass
class KpiBlock:
    name: str
    header_row: int
    rows: dict[str, int] = field(default_factory=dict)


@dataclass
class KpiReport:
    month: str = ""
    column: str = ""
    written_blocks: list[str] = field(default_factory=list)
    skipped_blocks: list[str] = field(default_factory=list)
    unmapped_groups: list[tuple[str, str, float]] = field(default_factory=list)
    unknown_provider_ids: list[int] = field(default_factory=list)
    unknown_providers_named: list[str] = field(default_factory=list)
    scorecard_rows: int = 0
    scorecard_blocks: list[str] = field(default_factory=list)
    scorecard_missing: list[str] = field(default_factory=list)
    scorecard_note: str = ""
    totals: dict[str, float] = field(default_factory=dict)


def kpi_layout(rules: dict) -> dict[str, KpiBlock]:
    """The sheet's blocks and their rows, as written under kpi.layout."""
    return {name: KpiBlock(name, i, {label: r for r, label in enumerate(rows)})
            for i, (name, rows) in enumerate((rules["kpi"].get("layout") or {}).items())}


def _group_dim(provider_list: pl.DataFrame, k: dict) -> pl.DataFrame:
    """BUSINESSREGID -> Provider Group, one row per id."""
    return (provider_list
            .select(pl.col(k["provider_id_column"]).cast(pl.Float64, strict=False)
                      .round(0).cast(pl.Int64).alias("pid"),
                    pl.col(k["provider_group_column"]).cast(pl.Utf8).alias("Group"))
            .unique(subset=["pid"], keep="first"))


def _row_key_map(block: KpiBlock, provider_to_group: dict[str, str],
                 row_aliases: dict[str, str] | None = None) -> dict[str, str]:
    """Normalised group name -> the sheet row label that should carry it."""
    out: dict[str, str] = {}
    aliases = {norm(a): norm(b) for a, b in (row_aliases or {}).items()}
    for label in block.rows:
        out.setdefault(norm(label), label)
        g = provider_to_group.get(norm(label))
        if g:
            out.setdefault(norm(g), label)
        alias = aliases.get(norm(label))
        if alias:
            out.setdefault(alias, label)
    return out


def _lay_on_rows(block: KpiBlock, by_group: dict[str, float],
                 provider_to_group: dict[str, str], rep: KpiReport,
                 row_aliases: dict[str, str] | None = None,
                 names: dict[str, str] | None = None) -> dict[str, float]:
    """Spread a {group: value} map across the block's rows."""
    keys = _row_key_map(block, provider_to_group, row_aliases)
    vals = {label: 0.0 for label in block.rows}
    for g, v in by_group.items():
        label = keys.get(g)
        if label is None:
            if v:
                rep.unmapped_groups.append((block.name, (names or {}).get(g, g), v))
            continue
        vals[label] += v
    return vals


def _split_groups(block: KpiBlock, provider_to_group: dict[str, str]) -> set[str]:
    """Groups this block lists provider by provider rather than as one group row."""
    out: set[str] = set()
    for label in block.rows:
        g = provider_to_group.get(norm(label))
        if g and norm(g) != norm(label):
            out.add(norm(g))
    return out


def _lay_providers(block: KpiBlock,
                   items: list[tuple[str, str, str, float]],
                   provider_to_group: dict[str, str], rep: KpiReport,
                   row_aliases: dict[str, str] | None = None) -> dict[str, float]:
    """Spread KPI-numbers figures, one per PROVIDER, across the block's rows."""
    rows = {norm(label): label for label in block.rows}
    aliases = {norm(a): norm(b) for a, b in (row_aliases or {}).items()}
    groups = dict(rows)
    for label in block.rows:
        if aliases.get(norm(label)):
            groups.setdefault(aliases[norm(label)], label)
    split = _split_groups(block, provider_to_group)

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
    for written, v in extra.items():
        rep.unmapped_groups.append((block.name, written, v))
    return vals


def build_kpi_sql(sql_doc: pl.DataFrame,
                  provider_list: pl.DataFrame,
                  blocks: dict[str, KpiBlock],
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

    want_type = k.get("filter_type")
    if want_type:
        d = d.filter(pl.col("type").str.strip_chars().str.to_uppercase()
                     == want_type.upper())
    d = d.filter(pl.col("doc_month").str.strip_chars() == rep.month)

    d = d.join(_group_dim(provider_list, k), on="pid", how="left")
    missing = d.filter(pl.col("Group").is_null())
    if missing.height:
        rep.unknown_provider_ids = sorted({int(x) for x in missing["pid"].to_list()
                                           if x is not None})

    pivot = (d.drop_nulls("Group")
              .group_by(["Group", "doc_type"])
              .agg(pl.col("cases").sum().alias("cases")))

    p2g = _provider_to_group(provider_list, rules)
    out: dict[str, dict[str, float]] = {}
    for block_name, doc_type in (k.get("sql_blocks") or {}).items():
        block = blocks.get(block_name)
        if block is None:
            rep.skipped_blocks.append(block_name)
            continue
        want = norm(doc_type)
        by_group: dict[str, float] = {}
        names: dict[str, str] = {}
        for group, dt_, cases in pivot.iter_rows():
            if norm(dt_) == want:
                by_group[norm(group)] = by_group.get(norm(group), 0.0) + (cases or 0.0)
                names[norm(group)] = group
        vals = _lay_on_rows(block, by_group, p2g, rep, k.get("row_aliases"), names)
        out[block_name] = vals
        rep.written_blocks.append(block_name)
        rep.totals[block_name] = sum(vals.values())
    return out, rep


def _provider_to_group(provider_list: pl.DataFrame, rules: dict) -> dict[str, str]:
    k = rules["kpi"]
    sc = k.get("scorecard") or {}
    col = sc.get("lookup_column", "PROVIDER ID")
    out: dict[str, str] = {}
    for name, group in provider_list.select(
            pl.col(col).cast(pl.Utf8),
            pl.col(k["provider_group_column"]).cast(pl.Utf8)).iter_rows():
        if name:
            out.setdefault(norm(name), group)
    return out


def build_kpi_scorecard(table: pl.DataFrame | None,
                        provider_list: pl.DataFrame,
                        blocks: dict[str, KpiBlock],
                        rules: dict,
                        rep: KpiReport) -> dict[str, dict[str, float]]:
    """Phase 9: the litigation / scorecard numbers table pasted from email."""
    k = rules["kpi"]
    sc = k.get("scorecard") or {}
    wanted = list((sc.get("metrics") or {}).values()) + \
             [dest[0] for dest in (sc.get("totals") or {}).values()]

    if table is None or not (sc.get("metrics") or sc.get("totals")):
        rep.skipped_blocks.extend(dict.fromkeys(wanted))
        rep.scorecard_note = "no KPI-numbers file - those blocks show no data this week"
        return {}

    rows = [list(r) for r in table.iter_rows()]
    body: list[list] = []
    for start_marker, end_marker in (sc.get("block_markers") or {}).items():
        start = _find_row(rows, start_marker)
        end = _find_row(rows, end_marker)
        if start is None or end is None or end <= start:
            rep.scorecard_missing.append(f"block {start_marker!r}")
            continue
        rep.scorecard_blocks.append(start_marker)
        head = [norm(c) for c in rows[start]]
        body.extend([head_marker(head, r) for r in rows[start + 1:end]])
    if not body:
        rep.skipped_blocks.extend(dict.fromkeys(wanted))
        rep.scorecard_note = ("could not find any of the "
                              f"{list((sc.get('block_markers') or {}))} blocks in the "
                              "KPI-numbers sheet - nothing written")
        return {}
    rep.scorecard_rows = len(body)

    lookup = _provider_to_group(provider_list, rules)
    aliases = {norm(a): norm(b) for a, b in (sc.get("provider_aliases") or {}).items()}

    groups: list[str | None] = []
    keys: list[str] = []
    for _head, r in body:
        key = norm(r[0])
        g = lookup.get(key)
        if g is None and key in aliases:
            key = aliases[key]
            g = lookup.get(key)
        if g is None and str(r[0]).strip():
            rep.unknown_providers_named.append(str(r[0]))
        groups.append(g)
        keys.append(key)

    def column(head: list[str], name: str) -> int | None:
        n = norm(name)
        return head.index(n) if n in head else None

    p2g = _provider_to_group(provider_list, rules)
    out: dict[str, dict[str, float]] = {}

    for src, block_name in (sc.get("metrics") or {}).items():
        block = blocks.get(block_name)
        if block is None:
            rep.scorecard_missing.append(f"{src} -> no '{block_name}' block on the sheet")
            continue
        items: list[tuple[str, str, str, float]] = []
        hits = 0
        for g, key, (head, r) in zip(groups, keys, body):
            col = column(head, src)
            if col is None or g is None:
                continue
            hits += 1
            items.append((str(r[0]).strip(), key, g, number(r[col])))
        if not hits:
            rep.scorecard_missing.append(src)
            continue
        out[block_name] = _lay_providers(block, items, p2g, rep, k.get("row_aliases"))
        rep.written_blocks.append(block_name)
        rep.totals[block_name] = sum(out[block_name].values())

    for src, dest in (sc.get("totals") or {}).items():
        block_name, label = dest
        block = blocks.get(block_name)
        if block is None:
            rep.scorecard_missing.append(f"{src} -> no '{block_name}' block on the sheet")
            continue
        row_label = next((l for l in block.rows if norm(l) == norm(label)), None)
        if row_label is None:
            rep.scorecard_missing.append(f"{src} -> no '{label}' row in {block_name}")
            continue
        vals = out.setdefault(block_name, {l: 0.0 for l in block.rows})
        total = 0.0
        found = False
        for g, (head, r) in zip(groups, body):
            col = column(head, src)
            if col is None or g is None:
                continue
            found = True
            total += number(r[col])
        if not found:
            rep.scorecard_missing.append(src)
            continue
        vals[row_label] = total
        if block_name not in rep.written_blocks:
            rep.written_blocks.append(block_name)
        rep.totals[block_name] = sum(vals.values())

    rep.skipped_blocks.extend(b for b in dict.fromkeys(wanted) if b not in out)
    return out


def head_marker(head: list[str], row: list) -> tuple[list[str], list]:
    """Tag each source row with the header it was read under."""
    return head, row
