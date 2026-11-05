"""Builds: queueing, running, recording results, and deleting them."""
from __future__ import annotations
import datetime as dt
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from ..clock import utcnow
from ..config import settings
from ..db.models import (ACTIVE, MonthSetting, Run, RunFigure, RunInput, RunNote,
                         RunTable, Upload)
from ..db.session import after_commit
from ..reports import ReportType, get as get_report, load_rules
from ..reports.cache import ParquetCache
from ..reports.locate import SourceSet
from ..reports.period import reporting_period
from ..storage.files import FileStore, StoredFile
from . import blobs
from .figures import all_figures
from .holidays import with_holidays
from .providers import with_providers
from .ingest import latest_uploads, retire_uploads

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


def queue(session: Session, report_key: str, week: str,
          as_of: dt.date | None = None) -> Run:
    """Record a build to be made, and exactly what it will be made from."""
    report: ReportType = get_report(report_key)
    run = Run(report_key=report_key, week=week, status="pending",
              as_of=as_of or settings.today())
    session.add(run)
    _fix_working_days(session, run, with_holidays(session, load_rules(report_key)))
    session.flush()        # the database refuses a second active build here
    for upload in latest_uploads(session, report, week).values():
        session.add(RunInput(run_id=run.id, upload_id=upload.id))
    session.flush()
    return run


@dataclass
class Plan:
    """What one build reads, as plain values - nothing here needs the database,
    so the long part of a build holds no transaction open."""
    report_key: str
    week: str
    as_of: dt.date | None
    rules: dict
    sources: SourceSet
    upload_ids: dict[str, int]          # source_key -> the upload it came from


def plan(store: FileStore, run: Run) -> Plan:
    """The files and rules a queued run was promised - see queue()."""
    report: ReportType = get_report(run.report_key)
    uploads = {ri.upload.source_key: ri.upload for ri in run.inputs}
    found = {key: store.path(u.sha256, u.suffix) for key, u in uploads.items()}
    ss = SourceSet(report=report, found=found,
                   missing=tuple(s for s in report.sources if s.key not in found))
    if not found:
        raise FileNotFoundError(f"No files were uploaded for {run.week}.")

    return Plan(report_key=run.report_key, week=run.week, as_of=run.as_of,
                rules=rules_for(object_session(run), run.report_key, run.week,
                                run.working_days, run.working_days_source),
                sources=ss,
                upload_ids={key: u.id for key, u in uploads.items()})


def missing_inputs(run: Run) -> list[str]:
    """The files a build was made without - a partial build when there are any."""
    had = {ri.upload.source_key for ri in run.inputs}
    return sorted((s.label for s in get_report(run.report_key).sources
                   if s.required and s.key not in had), key=str.lower)


def rules_for(session: Session, report_key: str, week: str,
              working_days: int | None, source: str | None) -> dict:
    """A report's rules with the holidays, providers and any hand-entered working days."""
    rules = with_providers(session, with_holidays(session, load_rules(report_key)))
    if source == "entered":
        rules["working_days"] = {month_of(week, rules).key: working_days}
    return rules


def compute(p: Plan, cache: ParquetCache | None = None):
    """Read the sources and calculate."""
    read_sources, run_pipeline = _load(p.report_key)
    cache = cache or ParquetCache(
        settings.data_dir / "cache" / p.week / p.report_key)
    src = read_sources(p.sources, p.rules, cache)
    return src, run_pipeline(src, p.rules, as_of=p.as_of, week=p.week)


def record(session: Session, run: Run, p: Plan, src, result,
           results: FileStore | None = None) -> Run:
    """Write down what a build read and produced, and hand it to a person."""
    results = results or FileStore(settings.results_dir)

    stored: dict[str, StoredFile] = {}
    for name, df in result.tables.items():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{name}.parquet"
            df.write_parquet(path)
            stored[name] = results.put(path)
        blobs.discard_on_rollback(session, results, stored[name], ".parquet",
                                  RunTable.sha256)

    rows_by_source: dict[str, int] = {}
    secs_by_source: dict[str, float] = {}
    for r in src.reads:
        rows_by_source[r.source_key] = rows_by_source.get(r.source_key, 0) + r.rows
        secs_by_source[r.source_key] = secs_by_source.get(r.source_key, 0.0) + r.seconds
    by_upload = {ri.upload_id: ri for ri in run.inputs}
    for key, upload_id in p.upload_ids.items():
        by_upload[upload_id].rows_read = rows_by_source.get(key)
        by_upload[upload_id].seconds = secs_by_source.get(key)

    for name, df in result.tables.items():
        session.add(RunTable(run_id=run.id, name=name, rows=df.height,
                             columns=df.width, sha256=stored[name].sha256,
                             bytes=stored[name].size))

    for name, records in all_figures(result).items():
        session.add(RunFigure(run_id=run.id, name=name, data=records))

    for i, note in enumerate(result.notes):
        session.add(RunNote(run_id=run.id, seq=i, code=note.code,
                            severity=note.severity, text=note.message,
                            detail=note.detail))

    run.status = "review"          # a person still has to look at STEP 4
    run.seconds = result.seconds
    run.finished_at = utcnow()
    session.flush()
    return run


def execute(session: Session, store: FileStore, report_key: str, week: str,
            as_of: dt.date | None = None,
            results: FileStore | None = None) -> Run:
    """Build one report for one week, start to finish, in the caller's own
    transaction."""
    run = queue(session, report_key, week, as_of)
    run.status = "running"
    session.flush()
    try:
        p = plan(store, run)
        src, result = compute(p)
        return record(session, run, p, src, result, results)
    except Exception as exc:
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = utcnow()
        session.flush()
        raise


def month_of(week: str, rules: dict | None = None):
    """The reporting month a week belongs to (the month of its Wednesday)."""
    return reporting_period(week, (rules or {}).get("holidays"),
                            (rules or {}).get("working_days"))


def _fix_working_days(session: Session, run: Run, rules: dict) -> None:
    """Note on the run the working days it will pace on - those entered for its
    month, if any, or the calendar's - as they stand when it is queued."""
    key = month_of(run.week, rules).key
    row = session.get(MonthSetting, key)
    if row is not None:
        rules["working_days"] = {key: row.working_days}
    period = month_of(run.week, rules)
    run.working_days = period.business_days
    run.working_days_source = "entered" if row is not None else "calendar"


def table_row(run: Run, name: str) -> RunTable:
    row = next((t for t in run.tables if t.name == name), None)
    if row is None:
        raise KeyError(f"run {run.id} produced no table {name!r} "
                       f"(has: {', '.join(t.name for t in run.tables)})")
    return row


def table_path(run: Run, name: str, results: FileStore | None = None) -> Path:
    results = results or FileStore(settings.results_dir)
    return results.path(table_row(run, name).sha256, ".parquet")


def table_page(run: Run, name: str, offset: int, limit: int,
               results: FileStore | None = None) -> tuple[pl.DataFrame, int, dict]:
    """One page of a produced table: (rows, total row count, column kinds)."""
    row = table_row(run, name)
    lazy = pl.scan_parquet(table_path(run, name, results))
    return (lazy.slice(offset, limit).collect(), row.rows,
            column_kinds(lazy.collect_schema()))


_INTS = (pl.Int8, pl.Int16, pl.Int32, pl.Int64,
         pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64)


def column_kinds(schema) -> dict[str, str]:
    """How the browser should draw each column: float, int or text."""
    return {c: ("float" if t in (pl.Float32, pl.Float64)
                else "int" if t in _INTS else "text")
            for c, t in schema.items()}


def approve(session: Session, run: Run, by: str) -> Run:
    """Sign a run off after the STEP 4 review."""
    if run.status != "review":
        raise ValueError(f"run {run.id} is {run.status}, not waiting for review")
    run.status = "approved"
    run.approved_at = utcnow()
    run.approved_by = by
    session.flush()
    return run


def unapprove(session: Session, run: Run, by: str) -> Run:
    """Take an approval back."""
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


def remove_upload(session: Session, upload: Upload,
                  objects: FileStore | None = None, by: str | None = None) -> dict:
    """Delete one file from its week - from both scorecards when they share it.

    Every copy of that input held for the week goes, so an older copy cannot take
    its place. A copy no build read is removed for good; one a build read is
    withdrawn instead: gone from the week and from the next build, but kept so the
    scorecards built from it still say truly what they read. Deleting those
    builds later removes it for good."""
    same = session.execute(select(Upload).where(
        Upload.week == upload.week, Upload.source_key == upload.source_key,
        Upload.report_key.is_(None) if upload.report_key is None
        else Upload.report_key == upload.report_key,
        Upload.withdrawn_at.is_(None))).scalars().all()
    ids = [u.id for u in same]
    kept_for = sorted(set(session.execute(
        select(RunInput.run_id).where(RunInput.upload_id.in_(ids))).scalars()))
    out = {"upload_id": upload.id, "week": upload.week,
           "filename": upload.filename, "source_key": upload.source_key,
           "report_key": upload.report_key, "sha256": upload.sha256,
           "kept_for_builds": kept_for}
    now = utcnow()
    for u in same:
        u.withdrawn_at, u.withdrawn_by = now, by
    session.flush()
    _, blobs_gone = retire_uploads(session, ids,
                                   objects or FileStore(settings.object_dir))
    return out | {"file_removed": bool(blobs_gone)}


TABLE_CHUNK = 50_000


def table_chunks(run: Run, name: str, results: FileStore | None = None):
    """A produced table, TABLE_CHUNK rows at a time."""
    rows = table_row(run, name).rows
    lazy = pl.scan_parquet(table_path(run, name, results))
    for offset in range(0, max(rows, 1), TABLE_CHUNK):
        yield lazy.slice(offset, TABLE_CHUNK).collect()


def delete(session: Session, run: Run, results: FileStore | None = None,
           objects: FileStore | None = None) -> dict:
    """Remove a run, everything it recorded, and the files it consumed."""
    results = results or FileStore(settings.results_dir)
    objects = objects or FileStore(settings.object_dir)

    mine = [(t.sha256, t.rows) for t in run.tables]
    consumed = [i.upload_id for i in run.inputs]
    summary = {"run_id": run.id, "report_key": run.report_key, "week": run.week,
               "tables": len(mine), "rows": sum(r for _, r in mine)}

    session.delete(run)          # cascades to inputs, notes, figures, tables
    session.flush()

    freed = 0
    for sha, _ in mine:
        still_used = session.execute(
            select(RunTable.id).where(RunTable.sha256 == sha).limit(1)
        ).scalar_one_or_none()
        if still_used is None and blobs.remove_after_commit(
                session, results, sha, ".parquet", RunTable.sha256):
            freed += 1
    summary["files_removed"] = freed

    rows_gone, blobs_gone = retire_uploads(session, consumed, objects)
    summary["uploads_removed"] = rows_gone
    summary["upload_files_removed"] = blobs_gone
    return summary


def delete_week(session: Session, week: str, results: FileStore | None = None,
                objects: FileStore | None = None) -> dict:
    """Remove a whole week: its builds, and every file uploaded for it."""
    results = results or FileStore(settings.results_dir)
    objects = objects or FileStore(settings.object_dir)

    runs = session.execute(select(Run).where(Run.week == week)).scalars().all()
    busy = [r.id for r in runs if r.status in ACTIVE]
    if busy:
        raise ValueError(
            f"week {week} still has a build running (run {busy[0]}). "
            f"Wait for it to finish.")

    summary = {"week": week, "runs_removed": 0, "tables": 0, "rows": 0,
               "files_removed": 0, "uploads_removed": 0,
               "upload_files_removed": 0}
    for run in runs:
        one = delete(session, run, results, objects)
        summary["runs_removed"] += 1
        for key in ("tables", "rows", "files_removed", "uploads_removed",
                    "upload_files_removed"):
            summary[key] += one[key]

    left = [u.id for u in session.execute(
        select(Upload).where(Upload.week == week)).scalars()]
    rows_gone, blobs_gone = retire_uploads(session, left, objects)
    summary["uploads_removed"] += rows_gone
    summary["upload_files_removed"] += blobs_gone

    cache = settings.data_dir / "cache" / week
    after_commit(session, lambda: shutil.rmtree(cache, ignore_errors=True))
    return summary
