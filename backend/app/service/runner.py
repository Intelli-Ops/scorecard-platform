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
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import (MonthSetting, Run, RunFigure, RunInput, RunNote,
                         RunTable, Upload)
from ..db.session import after_commit
from ..reports import ReportType, get as get_report, load_rules
from ..reports.cache import ParquetCache
from ..reports.locate import SourceSet
from ..reports.period import reporting_period
from ..storage.files import FileStore, StoredFile
from . import blobs
from .figures import all_figures
from .ingest import latest_uploads, retire_uploads

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


def queue(session: Session, report_key: str, week: str,
          as_of: dt.date | None = None) -> Run:
    """Record a build to be made, and EXACTLY what it will be made from.

    Everything a build depends on is fixed here, in the transaction that
    creates the run, and not looked up again when the worker gets to it: which
    upload each source resolves to, the date it is built as of, and the
    month's working days. A build can wait in the queue - behind another
    build, or across a restart - and before this it read whatever was newest
    when it finally STARTED, so a file replaced in between went into a build
    asked for before it existed.

    The RunInput rows written here also hold the files: an upload a queued
    run names cannot be retired from under it (see retire_uploads).
    """
    report: ReportType = get_report(report_key)
    run = Run(report_key=report_key, week=week, status="pending",
              as_of=as_of or settings.today())
    session.add(run)
    _fix_working_days(session, run, load_rules(report_key))
    session.flush()        # the database refuses a second active build here
    for upload in latest_uploads(session, report, week).values():
        session.add(RunInput(run_id=run.id, upload_id=upload.id))
    session.flush()
    return run


@dataclass
class Plan:
    """What one build reads, as plain values - nothing here needs the
    database, so the long part of a build holds no transaction open."""
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
    if not ss.ok:
        raise FileNotFoundError("; ".join(ss.problems()))

    return Plan(report_key=run.report_key, week=run.week, as_of=run.as_of,
                rules=rules_for(run.report_key, run.week, run.working_days,
                                run.working_days_source),
                sources=ss,
                upload_ids={key: u.id for key, u in uploads.items()})


def rules_for(report_key: str, week: str, working_days: int | None,
              source: str | None) -> dict:
    """A report's rules, with the working days a run was fixed on if they
    were entered by hand rather than taken from the calendar."""
    rules = load_rules(report_key)
    if source == "entered":
        rules["working_days"] = {month_of(week, rules).key: working_days}
    return rules


def compute(p: Plan, cache: ParquetCache | None = None):
    """Read the sources and calculate. The minute-long part; no database."""
    read_sources, run_pipeline = _load(p.report_key)
    cache = cache or ParquetCache(
        settings.data_dir / "cache" / p.week / p.report_key)
    src = read_sources(p.sources, p.rules, cache)
    return src, run_pipeline(src, p.rules, as_of=p.as_of, week=p.week)


def record(session: Session, run: Run, p: Plan, src, result,
           results: FileStore | None = None) -> Run:
    """Write down what a build read and produced, and hand it to a person."""
    results = results or FileStore(settings.results_dir)

    # What was produced. Parquet into the store, pointer into the database -
    # the files first, so the transaction that follows is only rows. A file
    # written for a row that is then never saved is taken back out.
    stored: dict[str, StoredFile] = {}
    for name, df in result.tables.items():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{name}.parquet"
            df.write_parquet(path)
            stored[name] = results.put(path)
        blobs.discard_on_rollback(session, results, stored[name], ".parquet",
                                  RunTable.sha256)

    # What was read, tied to the exact bytes. Several reads can come from
    # one uploaded file - the delta workbooks give three sheets from two
    # files - so they are added up per upload rather than looked up one to
    # one, which silently recorded those two files as contributing nothing.
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


def execute(session: Session, store: FileStore, report_key: str, week: str,
            as_of: dt.date | None = None,
            results: FileStore | None = None) -> Run:
    """Build one report for one week, start to finish, in the caller's own
    transaction. Returns the recorded Run.

    For a script or a test, where nothing else is using the database. The
    server does not call this: its worker runs the same four steps - queue,
    plan, compute, record - as separate short transactions, so a minute of
    calculating never holds one open (see jobs/worker.py).
    """
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
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        raise


def month_of(week: str, rules: dict | None = None):
    """The reporting period a week belongs to - by the rule that a week is in
    the month of its Wednesday - with the month's working days as entered."""
    return reporting_period(week, (rules or {}).get("holidays"),
                            (rules or {}).get("working_days"))


def _fix_working_days(session: Session, run: Run, rules: dict) -> None:
    """Note on the run the working days it will pace on - those entered for
    its month, if any, or the calendar's - as they stand when it is queued."""
    key = month_of(run.week, rules).key
    row = session.get(MonthSetting, key)
    if row is not None:
        rules["working_days"] = {key: row.working_days}
    period = month_of(run.week, rules)
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


def remove_upload(session: Session, upload: Upload,
                  objects: FileStore | None = None) -> dict:
    """Take back ONE uploaded file - the wrong one, sent by mistake.

    Before this the only way to be rid of a wrong file was to upload a right
    one over it or to delete the whole week.

    Refused once a build has read it: that build's record of what it was made
    from must stay true. Delete the build first, which then takes the file
    with it if nothing else reads it.

    Nothing comes back in its place. A newer upload replaces the one before
    it for good (see ingest), so removing a file leaves that input empty
    until the right one is uploaded.
    """
    readers = session.execute(
        select(RunInput.run_id).where(RunInput.upload_id == upload.id)
    ).scalars().all()
    if readers:
        raise ValueError(
            f"{upload.filename} was read by build {readers[0]}. Delete that "
            f"build first - its record of what it read has to stay true.")
    out = {"upload_id": upload.id, "week": upload.week,
           "filename": upload.filename, "source_key": upload.source_key,
           "sha256": upload.sha256}
    _, blobs_gone = retire_uploads(session, [upload.id],
                                   objects or FileStore(settings.object_dir))
    return out | {"file_removed": bool(blobs_gone)}


TABLE_CHUNK = 50_000


def table_chunks(run: Run, name: str, results: FileStore | None = None):
    """A produced table, TABLE_CHUNK rows at a time.

    For sending a whole table somewhere without ever holding the whole table:
    Raw Data is 278,930 rows, and a few people exporting it at once each held
    a full copy in the server's memory.
    """
    rows = _table_row(run, name).rows
    lazy = pl.scan_parquet(_table_path(run, name, results))
    for offset in range(0, max(rows, 1), TABLE_CHUNK):
        yield lazy.slice(offset, TABLE_CHUNK).collect()


def delete(session: Session, run: Run, results: FileStore | None = None,
           objects: FileStore | None = None) -> dict:
    """Remove a run, everything it recorded, and the files it consumed.

    Everything is reference counted, never deleted outright - see
    retire_uploads for the inputs. The same holds for the outputs: a result
    parquet is addressed by the hash of its own bytes, so two identical builds
    share one file, and the blob goes only once no RunTable points at the hash.

    Deleting the GFS run leaves the files All Providers still needs; the last
    run to be deleted takes them with it. An upload no run ever read is not
    this run's to remove - use delete_week for that.

    Nothing leaves the disk until the caller's transaction commits (see
    retire_uploads); the counts returned are of what will then go.
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
    rows_gone, blobs_gone = retire_uploads(session, left, objects)
    summary["uploads_removed"] += rows_gone
    summary["upload_files_removed"] += blobs_gone

    # The parquet copies the readers cached from this week's spreadsheets. They
    # are the client's case data in another format, and deleting the week used
    # to leave them behind on disk. After the commit, like every other file.
    cache = settings.data_dir / "cache" / week
    after_commit(session, lambda: shutil.rmtree(cache, ignore_errors=True))
    return summary
