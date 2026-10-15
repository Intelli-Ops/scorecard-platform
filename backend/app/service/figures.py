"""Flattens a build's grid results into rows the dashboard can draw."""
from __future__ import annotations


def _split(value):
    """The two pipelines hand back different grid shapes."""
    if isinstance(value, tuple):
        amounts, pcts, totals = value
        return amounts, pcts, totals
    return value, {}, {}


def settlement_records(grids: dict) -> list[dict]:
    """Settlement grids to one row per cell."""
    out: list[dict] = []
    for block, value in grids.items():
        amounts, pcts, _totals = _split(value)
        for (group, bucket), amount in amounts.items():
            out.append({
                "block": block,              # In House | Board
                "group": group,
                "bucket": bucket,            # W2 (week of the month) or M5 (month)
                "period": "week" if bucket.startswith("W") else "month",
                "amount": float(amount),
                **({"settlement_pct": float(pcts[(group, bucket)])}
                   if (group, bucket) in pcts else {}),
            })
    return sorted(out, key=lambda r: (r["block"], r["group"], r["bucket"]))


def settlement_total_records(grids: dict) -> list[dict]:
    """The Total row, which is not the sum of the rows above it."""
    rows = []
    for block, value in grids.items():
        _a, _p, totals = _split(value)
        for bucket, pct in totals.items():
            rows.append({"block": block, "bucket": bucket,
                         "period": "week" if bucket.startswith("W") else "month",
                         "settlement_pct": float(pct)})
    return sorted(rows, key=lambda r: (r["block"], r["bucket"]))


def cp_settled_records(cp: dict) -> list[dict]:
    """CP Settled Cases to one row per month."""
    return [{"month": int(m), "cases": int(cases),
             "outstanding": float(outstanding), "settled": float(settled)}
            for m, (cases, outstanding, settled) in sorted(cp.items())]


def kpi_records(kpi: dict) -> list[dict]:
    """{block: {group: value}} -> one row per block per group."""
    out: list[dict] = []
    for block, by_group in kpi.items():
        if not isinstance(by_group, dict):
            continue
        for group, value in by_group.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out.append({"block": block, "group": group,
                            "value": float(value)})
    return sorted(out, key=lambda r: (r["block"], r["group"]))


def settlement_pace_records(paced: dict) -> list[dict]:
    """{block: {(group, week): paced}} -> one row per cell."""
    return sorted(
        ({"block": block, "group": group, "bucket": bucket, "period": "week",
          "pace": float(value)}
         for block, cells in paced.items()
         for (group, bucket), value in cells.items()),
        key=lambda r: (r["block"], r["group"], r["bucket"]))


def collections_pace_records(paced: dict) -> list[dict]:
    """{(group, week): paced} -> one row per cell."""
    return sorted(
        ({"group": group, "bucket": bucket, "period": "week",
          "pace": float(value)}
         for (group, bucket), value in paced.items()),
        key=lambda r: (r["group"], r["bucket"]))


def all_figures(result) -> dict[str, list[dict]]:
    """Everything a dashboard needs that is not one of the four tables."""
    return {
        "settlement": settlement_records(result.settlement_grids),
        "settlement_totals": settlement_total_records(result.settlement_grids),
        "settlement_pace": settlement_pace_records(
            getattr(result, "settlement_pace", {}) or {}),
        "collections_pace": collections_pace_records(
            getattr(result, "collections_pace", {}) or {}),
        "cp_settled": cp_settled_records(result.cp_settled),
        "kpi": kpi_records(result.kpi),
        "meta": [{"current_month": result.current_month,
                  "year": getattr(result, "year", None)}],
    }
