"""KPI High-Level - steps doc Phase 8 (SQL-Doc) and Phase 9 (scorecard numbers email).

Phase 8, verified against week 2026-W35:

    DDE  (BillingDocs)   9 group rows + total matched the manual file exactly (22)
    SBR  (Appeals/SBR)   same logic; the manual file's August figures were keyed from
                         an EARLIER SQL-Doc pull, so every one of them is lower than
                         the 01-Sep pull in the inputs folder. Reported in STEP 4.

The group written on the sheet is NOT the SQL-Doc's own Provider_GROUP column. It is
the Supporting File's Provider Group, looked up on ProviderID = BUSINESSREGID. That
distinction is what makes the numbers come out right: SQL-Doc reports "Inland Empire
Healthcare" as its own group, but the Supporting File files it under A Miles, and the
sheet's A Miles DDE cell (15) is Andrew Miles (12) + Inland Empire (3).

Phase 9, the KPI-numbers table pasted from email, fills PMR, NTP, Medical Index, DOR,
Med Legal and Enforcement Of Agreement. Verified against 2026-08: every group total the
grouping produced reproduced that file's own GFS Total row exactly, all nine metrics.

**10635 (DDEL) has no column in the KPI-numbers file and no source anywhere else**, so
it is the one block still carried forward from the template rather than computed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

import polars as pl


def norm(s: object) -> str:
    """Match sheet labels to source groups ignoring case and punctuation.
    The sheet says 'BayCo', the Supporting File says 'Bayco'."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


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
    """Lay a {group: value} map onto the block's sheet rows.

    Anything left over is a group the sheet has no row for. Those are collected under
    their real name, and the run adds a row for each one (write_kpi_sheet) - a provider
    that starts sending appeals would otherwise never appear in the client's total.
    """
    vals = {label: by_group.pop(norm(label), 0.0) for label in spec["rows"]}
    for leftover, v in by_group.items():
        if v:
            rep.unmapped_groups.append((block, (names or {}).get(leftover, leftover), v))
    return vals


def _lay_providers(spec: dict, items: list[tuple[str, str, float]],
                   provider_to_group: dict[str, str], block: str,
                   rep: KpiReport) -> dict[str, float]:
    """Spread KPI-numbers figures, one per PROVIDER, across the block's rows.

    `items` is (name as written in the numbers file, its group, value). Each figure
    goes to, in order:
      * a row named after that provider
      * the group's row ("A Miles" takes Andrew Miles and Inland Empire Healthcare) -
        unless the block lists that group provider by provider, i.e. has a row named
        after one of its providers ("BVHS" for Dr Dorian)
      * otherwise a NEW row, named exactly as the numbers file names the provider.
        That is how the sheet is kept by hand: a new provider gets its own row in
        whichever block it has a figure for.
    """
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
    """Phase 8: SQL-Doc -> {block name: {sheet row label: value}}.

    The steps doc describes this as a pivot - Filters(Type), Rows(Provider_Group),
    Columns(Document_Type), Values(Cases) - then a VLOOKUP of the SBR and DDE columns
    into the sheet. The group-by below is that pivot; the row map in config is the
    VLOOKUP.
    """
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

    # Filters("Type") -> GFS, and only the month being reported. Today's export holds
    # one month, but a wider pull must not silently add other months into the cells.
    d = d.filter(pl.col("type").str.strip_chars().str.to_uppercase()
                 == k["gfs_type_value"].upper())
    d = d.filter(pl.col("doc_month").str.strip_chars() == rep.month)

    # Rows("Provider_Group") - taken from the Supporting File, not from SQL-Doc.
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
    """Phase 9: the KPI-numbers table pasted from email.

    The sheet stacks three blocks - GFS, Russman, Others - each with its own header
    row and Total. Only the GFS block belongs on this report, so everything between
    `block_start` and `block_end` is read and the rest ignored.

    Its first column names a provider, not a group. The group comes from the Supporting
    File's PROVIDER ID column, which is what folds Andrew Miles + Inland Empire
    Healthcare into A Miles, MHE Pharmacy + MHE Assets into MH Express, and Eagle Eye +
    Novatech + Progressive Orthopedic into POS. A provider the sheet has its own row
    for, or has no row for at all, is kept apart - see _lay_providers. Verified for
    2026-08: every group total reproduced the file's own GFS Total row exactly, all
    nine metrics.

    Two shapes of destination:

      `metrics` columns spread across a block whose rows are provider groups.
      `totals`  columns land in ONE cell, because those blocks list metrics rather than
                groups - the Med Legal block's rows are NOI (COST), Cost Petition and
                so on, so the column's whole GFS total is the value.

    The table must be read with no header row: the header is found by its marker, not
    by position, because the GFS block does not start at row 1.
    """
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

    # Headings carry non-breaking spaces ("DOR Filing "), so normalise before matching.
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

    def number(v) -> float:
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0

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


def _find_row(rows: list[list], marker: str) -> int | None:
    want = norm(marker)
    for i, r in enumerate(rows):
        if r and norm(r[0]) == want:
            return i
    return None
