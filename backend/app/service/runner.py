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
import shutil
import tempfile
from pathlib import Path

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import (MonthSetting, Run, RunFigure, RunInput, RunNote,
                         RunTable, Upload)
from ..reports import ReportType, get as get_report, load_rules
from ..reports.cache import ParquetCache
from ..reports.period import reporting_period
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

        rules = load_rules(report_key)
        _apply_working_days(session, run, rules, week)
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


def month_of(week: str, rules: dict | None = None):
    """The reporting period a week belongs to - by the rule that a week is in
    the month of its Wednesday - with the month's working days as entered."""
    return reporting_period(week, (rules or {}).get("holidays"),
                            (rules or {}).get("working_days"))


def _apply_working_days(session: Session, run: Run, rules: dict, week: str) -> None:
    """Hand the build the working days entered for its month, if any, and
    note on the run which number it paced on."""
    key = month_of(week, rules).key
    row = session.get(MonthSetting, key)
    if row is not None:
        rules["working_days"] = {key: row.working_days}
    period = month_of(week, rules)
    run.working_days = period.business_days
    run.working_days_source = "entered" if row is not None else "calendar"


def _table_row(run: Run, name: str) -> RunTable:
    row = next((t for t in run.tables if t.name == name), None)
    if row is None:
        raise KeyError(f"run {run.id} produced no table {name!r} "
                       f"(has: {', '.join(t.name for t in run.tables)})")
    return row


def _table_path(run: Run, name: str, results: FileStore | None) -> Path:
    results = results or FileStore(settings.results_dir)
    return results.path(_table_row(run, name).sha256, ".parquet")


def table(session: Session, run: Run, name: str,
          results: FileStore | None = None) -> pl.DataFrame:
    """Read one table a run produced back out of the store."""
    return pl.read_parquet(_table_path(run, name, results))


def table_page(run: Run, name: str, offset: int, limit: int,
               results: FileStore | None = None) -> tuple[pl.DataFrame, int, dict]:
    """One page of a produced table: (rows, total row count, column kinds).

    Only the page is read. Loading all 278,930 rows of Raw Data to hand back
    fifty of them made every Next press cost a full read of the file.
    """
    row = _table_row(run, name)
    lazy = pl.scan_parquet(_table_path(run, name, results))
    return (lazy.slice(offset, limit).collect(), row.rows,
            column_kinds(lazy.collect_schema()))


_INTS = (pl.Int8, pl.Int16, pl.Int32, pl.Int64,
         pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64)


def column_kinds(schema) -> dict[str, str]:
    """How the browser should draw each column: "float", "int" or "text".

    Sent with the rows rather than guessed per cell - a guess put "$3,071"
    beside a bare "614" in one money column, because 614.0 is a whole number
    and 3070.59 is not.
    """
    return {c: ("float" if t in (pl.Float32, pl.Float64)
                else "int" if t in _INTS else "text")
            for c, t in schema.items()}


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


def _retire_uploads(session: Session, upload_ids, objects: FileStore) -> tuple[int, int]:
    """Remove uploads nothing reads any more, and the bytes behind them.

    Two levels of reference counting, because both are shared on purpose:

      * the ROW goes only once no RunInput names it. An upload belongs to the
        week, not to one run - the seven shared files feed both reports and
        every rebuild reads them again.
      * the BLOB goes only once no Upload row names its hash. Identical files
        are stored once, and Thursday's Case AR is often byte-for-byte
        Tuesday's, so one stored file can back two rows - and two weeks.

    Returns (rows removed, blobs unlinked).
    """
    rows_gone, blobs_gone = 0, 0
    for upload_id in upload_ids:
        still_read = session.execute(
            select(RunInput.id).where(RunInput.upload_id == upload_id).limit(1)
        ).scalar_one_or_none()
        if still_read is not None:
            continue                      # another run still reads this file
        upload = session.get(Upload, upload_id)
        if upload is None:
            continue
        sha, suffix = upload.sha256, upload.suffix
        session.delete(upload)
        session.flush()
        rows_gone += 1
        shared = session.execute(
            select(Upload.id).where(Upload.sha256 == sha).limit(1)
        ).scalar_one_or_none()
        if shared is None and objects.remove(sha, suffix):
            blobs_gone += 1
    return rows_gone, blobs_gone


def delete(session: Session, run: Run, results: FileStore | None = None,
           objects: FileStore | None = None) -> dict:
    """Remove a run, everything it recorded, and the files it consumed.

    Everything is reference counted, never deleted outright - see
    _retire_uploads for the inputs. The same holds for the outputs: a result
    parquet is addressed by the hash of its own bytes, so two identical builds
    share one file, and the blob goes only once no RunTable points at the hash.

    Deleting the GFS run leaves the files All Providers still needs; the last
    run to be deleted takes them with it. An upload no run ever read is not
    this run's to remove - use delete_week for that.
    """
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
        if still_used is None and results.remove(sha, ".parquet"):
            freed += 1
    summary["files_removed"] = freed

    rows_gone, blobs_gone = _retire_uploads(session, consumed, objects)
    summary["uploads_removed"] = rows_gone
    summary["upload_files_removed"] = blobs_gone
    return summary


def delete_week(session: Session, week: str, results: FileStore | None = None,
                objects: FileStore | None = None) -> dict:
    """Remove a whole week: its builds, and every file uploaded for it.

    This exists because deleting runs one by one cannot get you back to a clean
    slate. Uploads OUTLIVE runs by design - they are the week's inputs, not one
    build's - so a week whose builds have all been deleted keeps its files and
    goes on offering a Build button with nothing behind it. Reference counting
    has nothing left to count against; only asking for the week itself does.

    Runs go first, so each one retires what it alone was holding, and whatever
    remains is what no build ever read.
    """
    results = results or FileStore(settings.results_dir)
    objects = objects or FileStore(settings.object_dir)

    runs = session.execute(select(Run).where(Run.week == week)).scalars().all()
    busy = [r.id for r in runs if r.status in ("pending", "running")]
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
    rows_gone, blobs_gone = _retire_uploads(session, left, objects)
    summary["uploads_removed"] += rows_gone
    summary["upload_files_removed"] += blobs_gone

    # The parquet copies the readers cached from this week's spreadsheets. They
    # are the client's case data in another format, and deleting the week used
    # to leave them behind on disk.
    cache = settings.data_dir / "cache" / week
    if cache.is_dir():
        shutil.rmtree(cache, ignore_errors=True)
    return summary
