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
from sqlalchemy.orm import Session, selectinload

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


# Routine notes older runs stored. The filters that produce them run every
# week and are doing their job; on the review they only buried the checks that
# matter. Newer runs do not record them at all (see reports/review_notes.py).
HIDDEN = {"ar_rows_dropped_no_group", "ar_rows_dropped_no_status",
          "case_validity_corrected", "delta_partial_paid_rewritten",
          "supporting_file_contents"}

# Which part of the review a note belongs to.
SECTIONS = {
    "kpi_new_provider": "providers", "kpi_group_not_in_layout": "providers",
    "new_group": "providers", "kpi_rows_dropped_unknown_provider": "providers",
    "sqldoc_rows_dropped_unknown_provider": "providers",
    "kpi_block_without_source": "no_data", "kpi_block_empty": "no_data",
    "kpi_columns_not_found": "no_data", "kpi_numbers_not_supplied": "no_data",
    "collections_empty": "no_data",
    "delta_duplicate_case_ids": "duplicates",
    "delta_comments_missing": "no_data",
}


def _shown(notes) -> list:
    return [n for n in notes if n.code not in HIDDEN]


def _key(code: str, detail: dict) -> tuple:
    """One note per code is not enough: two new providers share a code, and
    each has to be matched with its own line from last week."""
    return (code, detail.get("block"), detail.get("provider"))


def _note_rows(run: Run) -> list[dict]:
    return [{"code": n.code, "severity": n.severity, "text": n.text,
             "detail": n.detail or {}, "section": SECTIONS.get(n.code, "other")}
            for n in _shown(run.notes)]


def _compare_notes(run: Run, prev: Run | None) -> list[dict]:
    """Which checks are new, which have gone, and which counts moved.

    A check that appears every week is background. One that is NEW this week,
    or whose count has jumped, is the thing worth a person's attention.
    """
    if prev is None:
        return [dict(n, change="no previous run") for n in _note_rows(run)]

    before = {_key(n.code, n.detail or {}): n for n in _shown(prev.notes)}
    out: list[dict] = []
    now_keys = set()

    for row in _note_rows(run):
        k = _key(row["code"], row["detail"])
        now_keys.add(k)
        if k not in before:
            row["change"] = "new this week"
        else:
            was, now = before[k].detail or {}, row["detail"]
            moved = {f: {"was": was[f], "now": now[f]}
                     for f in now
                     if f in was and isinstance(now[f], (int, float))
                     and not isinstance(now[f], bool) and was[f] != now[f]}
            row["change"] = "changed" if moved else "same as last week"
            if moved:
                row["moved"] = moved
        out.append(row)

    out += [{"code": n.code, "severity": INFO, "text": n.text,
             "detail": n.detail or {}, "section": SECTIONS.get(n.code, "other"),
             "change": "resolved since last week"}
            for k, n in before.items() if k not in now_keys]
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

    severities = [n.severity for n in _shown(run.notes)]
    counts = {s: severities.count(s) for s in (ACTION, WARNING, INFO)}

    return {
        "run": {
            "id": run.id, "report": report.label, "report_key": run.report_key,
            "week": run.week, "status": run.status, "as_of": run.as_of,
            "seconds": run.seconds, "started_at": run.started_at,
            "finished_at": run.finished_at, "error": run.error,
            "approved_by": run.approved_by, "approved_at": run.approved_at,
            "working_days": run.working_days,
            "working_days_source": run.working_days_source,
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


def history(session: Session, report_key: str, weeks: int = 12) -> list[dict]:
    """Runs of one report for the last `weeks` weeks, newest first.

    Bounded by WEEKS rather than by a row count. A row limit cuts in the wrong
    place: rebuild Week 36 four times and a limit of 20 rows quietly drops
    Week 32 off the screen even though the list still claims to be a history.
    Twelve weeks is a quarter - far enough back to see a trend, short enough
    that the page stays a page.
    """
    recent = [w for (w,) in session.execute(
        select(Run.week).where(Run.report_key == report_key)
        .distinct().order_by(Run.week.desc()).limit(weeks))]
    if not recent:
        return []

    # Notes and tables in two more queries for all the runs, rather than two
    # per run as each row's were first touched.
    stmt = (select(Run)
            .where(Run.report_key == report_key, Run.week.in_(recent))
            .order_by(Run.week.desc(), Run.id.desc())
            .options(selectinload(Run.notes), selectinload(Run.tables)))
    runs = session.execute(stmt).scalars().all()
    report = get_report(report_key)
    out = []
    for r in runs:
        severities = [n.severity for n in _shown(r.notes)]
        out.append({
            "id": r.id, "week": r.week, "status": r.status,
            # The history shows both reports together, so each row has to say
            # which one it is. Without it a week is two rows that look identical.
            "report_key": r.report_key, "report": report.short,
            "report_full": report.label,
            "seconds": r.seconds, "started_at": r.started_at,
            "approved_by": r.approved_by, "approved_at": r.approved_at,
            "actions": severities.count(ACTION),
            "warnings": severities.count(WARNING),
            "rows": {t.name: t.rows for t in r.tables},
        })
    return out


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
