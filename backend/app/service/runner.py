"""Executing a run and recording everything about it.

The .bat pipeline's equivalent was main(): read, calculate, write the workbook,
print some warnings, exit. Nothing survived except four parquet files and
whatever the person happened to read before closing the window.

Here a run is a row that outlives it. What it read (down to the hash of the
bytes), how long each file took, what it produced, and every warning it raised
are all recorded, so a question in December has an answer that does not depend
on anyone's memory.
"""
from __future__ import annotations
import datetime as dt
import tempfile
from pathlib import Path

import polars as pl
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Run, RunFigure, RunInput, RunNote, RunTable
from ..reports import ReportType, get as get_report
from ..reports.cache import ParquetCache
from ..storage.files import FileStore
from .figures import all_figures
from .ingest import source_set

# One pipeline per report. The two are different code on purpose - see
# app/reports/__init__.py.
_PIPELINES = {
    "gfs": ("app.reports.gfs.readers", "read_gfs",
            "app.reports.gfs.pipeline", "run"),
    "all_providers": ("app.reports.all_providers.readers", "read_all_providers",
                      "app.reports.all_providers.pipeline", "run"),
}


def _load(report_key: str):
    import importlib
    if report_key not in _PIPELINES:
        raise NotImplementedError(
            f"no pipeline wired for {report_key!r} yet - "
            f"available: {', '.join(sorted(_PIPELINES))}")
    rmod, rfn, pmod, pfn = _PIPELINES[report_key]
    return (getattr(importlib.import_module(rmod), rfn),
            getattr(importlib.import_module(pmod), pfn))


def execute(session: Session, store: FileStore, report_key: str, week: str,
            as_of: dt.date | None = None,
            results: FileStore | None = None,
            run_id: int | None = None) -> Run:
    """Build one report for one week. Returns the recorded Run.

    run_id attaches to a row the queue already created, so a build that is
    waiting is visible as `pending` before any work starts. Without it the run
    only appears once it is under way, and a queued build looks like nothing
    happened.
    """
    report: ReportType = get_report(report_key)
    results = results or FileStore(settings.results_dir)
    read_sources, run_pipeline = _load(report_key)

    if run_id is None:
        run = Run(report_key=report_key, week=week, status="running", as_of=as_of)
        session.add(run)
    else:
        run = session.get(Run, run_id)
        if run is None:
            raise KeyError(f"no run {run_id}")
        run.status = "running"
        run.started_at = dt.datetime.now(dt.timezone.utc)
    session.flush()

    try:
        ss, uploads = source_set(session, store, report, week)
        if not ss.ok:
            raise FileNotFoundError("; ".join(ss.problems()))

        rules = yaml.safe_load(report.rules_path.read_text())
        cache = ParquetCache(settings.data_dir / "cache" / week / report_key)
        src = read_sources(ss, rules, cache)
        result = run_pipeline(src, rules, as_of=as_of, week=week)

        # What was read, tied to the exact bytes. Several reads can come from
        # one uploaded file - the delta workbooks give three sheets from two
        # files - so they are added up per upload rather than looked up one to
        # one, which silently recorded those two files as contributing nothing.
        rows_by_source: dict[str, int] = {}
        secs_by_source: dict[str, float] = {}
        for r in src.reads:
            rows_by_source[r.source_key] = rows_by_source.get(r.source_key, 0) + r.rows
            secs_by_source[r.source_key] = secs_by_source.get(r.source_key, 0.0) + r.seconds
        for key, upload in uploads.items():
            session.add(RunInput(run_id=run.id, upload_id=upload.id,
                                 rows_read=rows_by_source.get(key),
                                 seconds=secs_by_source.get(key)))

        # What was produced. Parquet into the store, pointer into the database.
        for name, df in result.tables.items():
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / f"{name}.parquet"
                df.write_parquet(p)
                stored = results.put(p)
            session.add(RunTable(run_id=run.id, name=name, rows=df.height,
                                 columns=df.width, sha256=stored.sha256,
                                 bytes=stored.size))

        # The sheet-shaped results, which only ever lived inside the workbook.
        for name, records in all_figures(result).items():
            session.add(RunFigure(run_id=run.id, name=name, data=records))

        for i, note in enumerate(result.notes):
            session.add(RunNote(run_id=run.id, seq=i, code=note.code,
                                severity=note.severity, text=note.message,
                                detail=note.detail))

        run.status = "review"          # a person still has to look at STEP 4
        run.seconds = result.seconds
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        return run

    except Exception as exc:
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        raise


def table(session: Session, run: Run, name: str,
          results: FileStore | None = None) -> pl.DataFrame:
    """Read one table a run produced back out of the store."""
    results = results or FileStore(settings.results_dir)
    row = next((t for t in run.tables if t.name == name), None)
    if row is None:
        raise KeyError(f"run {run.id} produced no table {name!r} "
                       f"(has: {', '.join(t.name for t in run.tables)})")
    return pl.read_parquet(results.path(row.sha256, ".parquet"))


def approve(session: Session, run: Run, by: str) -> Run:
    """Sign a run off after the STEP 4 review."""
    if run.status != "review":
        raise ValueError(f"run {run.id} is {run.status}, not waiting for review")
    run.status = "approved"
    run.approved_at = dt.datetime.now(dt.timezone.utc)
    run.approved_by = by
    session.flush()
    return run


def unapprove(session: Session, run: Run, by: str) -> Run:
    """Take an approval back.

    Approving is a person clicking a button, and people click the wrong button.
    Without this the only way back was to build the week again, which changes
    the run id every screenshot and email already refers to.

    The run returns to `review` - the state it was in before - so it is once
    again visibly waiting on somebody, rather than sitting in a limbo state
    nothing else in the app knows how to read.
    """
    if run.status != "approved":
        raise ValueError(f"run {run.id} is {run.status}, not approved")
    session.add(RunNote(
        run_id=run.id, seq=_next_seq(session, run), code="approval.withdrawn",
        severity="info",
        text=f"Approval withdrawn by {by} "
             f"(was approved by {run.approved_by or 'unknown'}).",
        detail={"was_approved_by": run.approved_by,
                "was_approved_at": run.approved_at.isoformat()
                if run.approved_at else None}))
    run.status = "review"
    run.approved_at = None
    run.approved_by = None
    session.flush()
    return run


def _next_seq(session: Session, run: Run) -> int:
    return 1 + max((n.seq for n in run.notes), default=0)


def delete(session: Session, run: Run, results: FileStore | None = None) -> dict:
    """Remove a run and everything it recorded.

    Two things are deliberately NOT touched:

      * the uploaded source files, which belong to the week and to the other
        report as well - deleting a run must never cost you the inputs;
      * any result parquet another run also produced. Results are addressed by
        the hash of their own bytes, so two identical builds share one file.
        A blob is removed only once nothing points at it any more.
    """
    results = results or FileStore(settings.results_dir)
    mine = [(t.sha256, t.rows) for t in run.tables]
    summary = {"run_id": run.id, "report_key": run.report_key, "week": run.week,
               "tables": len(mine), "rows": sum(r for _, r in mine)}

    session.delete(run)          # cascades to inputs, notes, figures, tables
    session.flush()

    freed = 0
    for sha, _ in mine:
        still_used = session.execute(
            select(RunTable.id).where(RunTable.sha256 == sha).limit(1)
        ).scalar_one_or_none()
        if still_used is None and results.remove(sha, ".parquet"):
            freed += 1
    summary["files_removed"] = freed
    return summary
