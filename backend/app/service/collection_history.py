"""The year's collections month by month, for the table under the Collections tab:
January to September 2026 from migration 0008's table, later months from their builds."""
from __future__ import annotations

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import CollectionHistory, Provider, Run
from ..reports import load_rules
from ..reports.closed_weeks import closed_months
from ..reports.reading import name_key
from . import runner


def _shown_groups(rules: dict) -> list[str] | None:
    """The groups a report's Collections shows, in its sheet's order; None for all.

    GFS lists its rows under collections.group_rows; All Providers shows every group,
    in the order of its layout."""
    c = rules.get("collections") or {}
    if c.get("group_rows"):
        aliases = c.get("group_aliases") or {}
        return [aliases.get(g, g) for g in c["group_rows"]]
    return None


def _month_builds(s: Session, report_key: str, year: int, rules: dict) -> dict[int, Run]:
    """The build each finished month's collections are taken from: its last approved
    build, or failing that its last finished one."""
    out: dict[int, Run] = {}
    for r in s.scalars(select(Run).where(Run.report_key == report_key,
                                         Run.status.in_(("approved", "review")))
                       .order_by(Run.id.desc())):
        p = runner.month_of(r.week, rules)
        if p.year == year and (p.month not in out or (r.status == "approved"
                                                        and out[p.month].status != "approved")):
            out[p.month] = r
    return out


def for_run(s: Session, run: Run) -> dict:
    """The history table for one scorecard: every month of its year before the one
    it reports, by provider group."""
    rules = load_rules(run.report_key)
    period = runner.month_of(run.week, rules)
    year = period.year
    shown = _shown_groups(rules)
    keep = None if shown is None else {name_key(g) for g in shown}

    def wanted(g) -> bool:
        return g is not None and (keep is None or name_key(g) in keep)

    groups = {p.regid: p.provider_group for p in s.scalars(select(Provider))}
    builds = _month_builds(s, run.report_key, year, rules)
    from_builds = set(closed_months(period))

    totals: dict[tuple[str, int], float] = {}
    weeks: list[dict] = []
    months: list[dict] = []
    for m in range(1, period.month):
        build = builds.get(m) if m in from_builds else None
        if build is not None:
            coll = pl.read_parquet(runner.table_path(build, "collections"))
            for g, w, pt, pay in coll.select("Group", "Week", "PT", "Payment").rows():
                if not wanted(g):
                    continue
                weeks.append({"group": g, "month": m, "week": int(w), "pt": pt,
                              "payment": float(pay or 0.0)})
                totals[(g, m)] = totals.get((g, m), 0.0) + float(pay or 0.0)
            months.append({"month": m, "source": "build", "run_id": build.id,
                           "week": build.week, "status": build.status})
            continue
        held = s.scalars(select(CollectionHistory).where(
            CollectionHistory.year == year, CollectionHistory.month == m)).all()
        if not held:
            continue
        for h in held:
            g = groups.get(h.regid)
            if wanted(g):
                totals[(g, m)] = totals.get((g, m), 0.0) + h.amount
        months.append({"month": m, "source": "file"})

    order = shown if shown is not None else [
        str(x) for x in (rules.get("layout") or {}).get("collections") or []]
    return {"year": year, "order": order, "months": months,
            "totals": [{"group": g, "month": m, "amount": a}
                       for (g, m), a in sorted(totals.items())],
            "weeks": weeks}

