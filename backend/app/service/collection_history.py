"""The year's collections month by month, for the table under the Collections tab.

January to September 2026 are held in the collection_history table, loaded once by
migration 0008 from the file management gave. From October 2026 each finished month
comes from that month's last build, kept week by week and payment type by payment
type, since each week's payment report holds only its own month."""
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


def _month_build(s: Session, report_key: str, year: int, month: int,
                 rules: dict) -> Run | None:
    """The build a finished month's collections are taken from: its last approved
    build, or failing that its last finished one."""
    runs = s.scalars(select(Run).where(Run.report_key == report_key,
                                       Run.status.in_(("approved", "review")))
                     .order_by(Run.id.desc())).all()
    mine = [r for r in runs if (p := runner.month_of(r.week, rules)).year == year
            and p.month == month]
    return next((r for r in mine if r.status == "approved"), mine[0] if mine else None)


def for_run(s: Session, run: Run) -> dict:
    """The history table for one scorecard: every month of its year before the one
    it reports, by provider group."""
    rules = load_rules(run.report_key)
    period = runner.month_of(run.week, rules)
    year = period.year
    shown = _shown_groups(rules)
    keep = None if shown is None else {name_key(g) for g in shown}
    wanted = lambda g: g is not None and (keep is None or name_key(g) in keep)  # noqa: E731

    groups = {p.regid: p.provider_group for p in s.scalars(select(Provider))}
    from_builds = set(closed_months(period))

    totals: dict[tuple[str, int], float] = {}
    weeks: list[dict] = []
    months: list[dict] = []
    for m in range(1, period.month):
        build = _month_build(s, run.report_key, year, m, rules) if m in from_builds else None
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

