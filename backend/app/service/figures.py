"""Flattening the sheet-shaped results so a dashboard can read them.

Settlement grids, CP Settled Cases and the KPI blocks never existed as tables.
The .bat pipeline calculated them into Python dictionaries keyed by things like
(group, bucket) and wrote them straight into Excel cells, so the only place
they ever lived was the workbook.

A dashboard needs them back, and a chart wants one row per value rather than a
grid. These functions do that and nothing else - no arithmetic, so nothing here
can change a number.

The bucket labels are the .bat pipeline's own: "W32" is week 32 of the current
month, "M5" is the month-5 total. Both appear because the report shows weekly
detail for the current month and monthly totals for the ones before it.
"""
from __future__ import annotations


def settlement_records(grids: dict) -> list[dict]:
    """{block: (amounts, pcts, totals)} -> one row per group per bucket."""
    out: list[dict] = []
    for block, (amounts, pcts, _totals) in grids.items():
        for (group, bucket), amount in amounts.items():
            out.append({
                "block": block,              # In House | Board
                "group": group,
                "bucket": bucket,            # W32 (week) or M5 (month)
                "period": "week" if bucket.startswith("W") else "month",
                "amount": float(amount),
                "settlement_pct": float(pcts.get((group, bucket), 0.0)),
            })
    return sorted(out, key=lambda r: (r["block"], r["group"], r["bucket"]))


def settlement_total_records(grids: dict) -> list[dict]:
    """The Total row, which is not the sum of the rows above it.

    Its Settlement % is the whole block's (settlement + paid) over the whole
    block's billed - the same formula as a group row, one level up. Kept
    separate so nobody can total the group rows and expect to get it.
    """
    return sorted(
        [{"block": block, "bucket": bucket,
          "period": "week" if bucket.startswith("W") else "month",
          "settlement_pct": float(pct)}
         for block, (_a, _p, totals) in grids.items()
         for bucket, pct in totals.items()],
        key=lambda r: (r["block"], r["bucket"]))


def cp_settled_records(cp: dict) -> list[dict]:
    """{month: (cases, outstanding, settled)} -> one row per month."""
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


def all_figures(result) -> dict[str, list[dict]]:
    """Everything a dashboard needs that is not one of the four tables."""
    return {
        "settlement": settlement_records(result.settlement_grids),
        "settlement_totals": settlement_total_records(result.settlement_grids),
        "cp_settled": cp_settled_records(result.cp_settled),
        "kpi": kpi_records(result.kpi),
        "meta": [{"current_month": result.current_month}],
    }
