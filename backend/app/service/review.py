"""What the review screen needs, assembled from what a run recorded.

This is the STEP 4 look, turned from console output into something a person
can actually work with. The .bat pipeline could tell you "112,960 AR rows
dropped". It could not tell you that last week it was 112,900, because last
week's message no longer existed anywhere.

Everything here is derived from rows the run already wrote. Nothing is
recalculated, so opening the review of a run from three months ago costs a
couple of queries and does not need the source files to still exist.
"""
from __future__ import annotations
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Run, RunNote
from ..reports import get as get_report
from ..reports.notes import ACTION, WARNING, INFO, SEVERITY_ORDER


def previous_run(session: Session, run: Run) -> Run | None:
    """The last run of the same report for an EARLIER week.

    Week labels sort correctly as text (2026-W35 < 2026-W36 < 2027-W01), so
    this is an ordering, not a date calculation. Failed runs are skipped -
    comparing against a run that stopped half way would invent differences.
    """
    stmt = (select(Run)
            .where(Run.report_key == run.report_key,
                   Run.week < run.week,
                   Run.status.in_(("review", "approved")))
            .order_by(Run.week.desc(), Run.id.desc())
            .limit(1))
    return session.execute(stmt).scalar_one_or_none()


def _note_rows(run: Run) -> list[dict]:
    return [{"code": n.code, "severity": n.severity, "text": n.text,
             "detail": n.detail or {}} for n in run.notes]


def _compare_notes(run: Run, prev: Run | None) -> list[dict]:
    """Which warnings are new, which have gone, and which counts moved.

    A warning that appears every week is background noise. A warning that is
    NEW this week, or whose count has jumped, is the thing worth a person's
    attention - and it is only findable because notes carry a stable code and
    their numbers rather than being sentences.
    """
    if prev is None:
        return [dict(n, change="no previous run") for n in _note_rows(run)]

    before = {n.code: (n.detail or {}) for n in prev.notes}
    out: list[dict] = []

    for n in run.notes:
        detail = n.detail or {}
        row = {"code": n.code, "severity": n.severity, "text": n.text,
               "detail": detail}
        if n.code not in before:
            row["change"] = "new this week"
        else:
            was, now = before[n.code], detail
            moved = {k: {"was": was[k], "now": now[k]}
                     for k in now
                     if k in was and isinstance(now[k], (int, float))
                     and not isinstance(now[k], bool) and was[k] != now[k]}
            row["change"] = "changed" if moved else "same as last week"
            if moved:
                row["moved"] = moved
        out.append(row)

    gone = [c for c in before if c not in {n.code for n in run.notes}]
    out += [{"code": c, "severity": INFO, "text": "no longer reported",
             "detail": {}, "change": "resolved since last week"} for c in gone]
    return out


def _compare_tables(run: Run, prev: Run | None) -> list[dict]:
    was = {t.name: t.rows for t in prev.tables} if prev else {}
    rows = []
    for t in sorted(run.tables, key=lambda t: -t.rows):
        before = was.get(t.name)
        rows.append({
            "name": t.name, "rows": t.rows, "columns": t.columns,
            "bytes": t.bytes, "sha256": t.sha256,
            "rows_last_week": before,
            "change": None if before is None else t.rows - before,
        })
    return rows


def review(session: Session, run: Run) -> dict:
    """Everything the review screen shows for one run."""
    prev = previous_run(session, run)
    report = get_report(run.report_key)
    notes = _compare_notes(run, prev)

    counts = {s: sum(1 for n in run.notes if n.severity == s)
              for s in (ACTION, WARNING, INFO)}

    return {
        "run": {
            "id": run.id, "report": report.label, "report_key": run.report_key,
            "week": run.week, "status": run.status, "as_of": run.as_of,
            "seconds": run.seconds, "started_at": run.started_at,
            "finished_at": run.finished_at, "error": run.error,
            "approved_by": run.approved_by, "approved_at": run.approved_at,
        },
        "compared_with": None if prev is None else {"id": prev.id, "week": prev.week},
        "needs_attention": counts[ACTION] > 0
                           or any(n.get("change") == "new this week"
                                  and n["severity"] != INFO for n in notes),
        "note_counts": counts,
        "notes": sorted(notes, key=lambda n: SEVERITY_ORDER.get(n["severity"], 9)),
        "tables": _compare_tables(run, prev),
        "inputs": [{
            "source_key": ri.upload.source_key,
            "filename": ri.upload.filename,
            "scope": ri.upload.report_key or "shared",
            "size_bytes": ri.upload.size_bytes,
            "sha256": ri.upload.sha256,
            "uploaded_at": ri.upload.uploaded_at,
            "uploaded_by": ri.upload.uploaded_by,
            "rows_read": ri.rows_read,
            "seconds": ri.seconds,
        } for ri in sorted(run.inputs, key=lambda r: -(r.rows_read or 0))],
    }


def history(session: Session, report_key: str, limit: int = 20) -> list[dict]:
    """Every run of one report, newest first. The thing folders could not do."""
    stmt = (select(Run).where(Run.report_key == report_key)
            .order_by(Run.week.desc(), Run.id.desc()).limit(limit))
    runs = session.execute(stmt).scalars().all()
    return [{
        "id": r.id, "week": r.week, "status": r.status,
        "seconds": r.seconds, "started_at": r.started_at,
        "approved_by": r.approved_by,
        "actions": sum(1 for n in r.notes if n.severity == ACTION),
        "warnings": sum(1 for n in r.notes if n.severity == WARNING),
        "rows": {t.name: t.rows for t in r.tables},
    } for r in runs]


def metric_over_time(session: Session, report_key: str, code: str,
                     field: str) -> list[dict]:
    """One number from one warning, across every week that reported it.

    The reason notes carry their numbers. "How many AR rows are we dropping
    each week, and is it growing?" was unanswerable when the warning was a
    printed sentence.
    """
    stmt = (select(Run, RunNote)
            .join(RunNote, RunNote.run_id == Run.id)
            .where(Run.report_key == report_key, RunNote.code == code,
                   Run.status.in_(("review", "approved")))
            .order_by(Run.week))
    out = []
    for run, note in session.execute(stmt):
        value = (note.detail or {}).get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append({"week": run.week, "run_id": run.id, "value": value})
    return out
