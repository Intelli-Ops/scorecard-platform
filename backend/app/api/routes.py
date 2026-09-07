"""The HTTP surface.

Deliberately thin. Every endpoint is a few lines over the service layer, so
the rules about Tuesday's and Thursday's Case ARs, about which upload a run
read, and about a run needing a person's approval live in one place and cannot
drift between the API and a background job.
"""
from __future__ import annotations
import datetime as dt
import io
import shutil
import tempfile
from pathlib import Path

import polars as pl

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..config import settings
from ..db.models import Run, RunFigure, Upload
from ..db.session import session
from ..jobs import worker
from ..reports import CASE_AR_SOURCES, REPORTS, get as get_report
from ..service import review as review_service, runner
from ..service.ingest import ingest, week_status
from ..storage.files import FileStore
from .deps import current_user

# Applied to the whole router rather than route by route: a rule you have to
# remember to add is a rule that gets forgotten on the one route that mattered.
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _store() -> FileStore:
    return FileStore(settings.object_dir)


@router.get("/reports")
def list_reports() -> list[dict]:
    """The two scorecards, and which files each one needs."""
    case_ar = {s.key for s in CASE_AR_SOURCES}
    return [{
        "key": r.key, "label": r.label, "short": r.short,
        "send_day": r.send_day,
        "sheets": list(r.sheets),
        "sources": [{"key": s.key, "label": s.label, "required": s.required,
                     "per_report": s.key in case_ar}
                    for s in r.sources],
    } for r in REPORTS.values()]


@router.get("/weeks")
def list_weeks() -> list[dict]:
    """Every week that has had anything uploaded, newest first."""
    with session() as s:
        weeks = [w for (w,) in s.execute(
            select(Upload.week).distinct().order_by(Upload.week.desc()))]
        return [week_status(s, w) for w in weeks]


@router.get("/weeks/{week}")
def get_week(week: str) -> dict:
    with session() as s:
        return week_status(s, week)


@router.post("/weeks/{week}/uploads")
async def upload(week: str,
                 files: list[UploadFile] = File(...),
                 for_report: str | None = Form(None),
                 user=Depends(current_user)) -> dict:
    """Receive this week's files.

    for_report is needed only for the two Case AR files. Anything that is not
    one of the nine inputs is reported back rather than stored - the week
    folder always contained delivered workbooks alongside the sources, and
    reading one of those by mistake would be worse than refusing it.
    """
    if for_report and for_report not in REPORTS:
        raise HTTPException(400, f"unknown report {for_report!r}")

    with tempfile.TemporaryDirectory() as tmp:
        landed: list[Path] = []
        for f in files:
            # Streamed to disk in chunks: a 240 MB upload is never held whole
            # in the server's memory.
            dest = Path(tmp) / Path(f.filename or "unnamed").name
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out, length=1024 * 1024)
            landed.append(dest)

        with session() as s:
            result = ingest(s, _store(), week, landed, for_report=for_report,
                            uploaded_by=user.email)
            return {
                "week": week,
                "accepted": [{"source_key": a.source_key, "label": a.label,
                              "filename": a.filename, "scope": a.report_key or "shared",
                              "size_bytes": a.size_bytes, "sha256": a.sha256,
                              "already_held": a.deduplicated}
                             for a in result.accepted],
                "rejected": [{"filename": n, "reason": why}
                             for n, why in result.rejected],
                "status": week_status(s, week),
            }


@router.post("/runs")
def start_run(report: str = Query(...), week: str = Query(...),
              as_of: dt.date | None = Query(None)) -> dict:
    """Queue a build. Returns straight away - poll /api/runs/{id} for progress."""
    if report not in REPORTS:
        raise HTTPException(404, f"unknown report {report!r}")

    with session() as s:
        st = week_status(s, week)["reports"][report]
        if not st["ready"]:
            raise HTTPException(
                409, {"message": f"{st['label']} cannot be built yet",
                      "missing": st["missing"]})

    run_id = worker.submit(report, week, as_of)
    return {"run_id": run_id, "status": "pending", "queued_ahead": worker.depth() - 1}


@router.get("/runs")
def list_runs(report: str | None = Query(None),
              weeks: int = Query(12, ge=1, le=104)) -> list[dict]:
    """Run history for the last `weeks` weeks - twelve by default.

    Bounded by weeks and not by rows: a week holds two runs when both reports
    are built and more when one is rebuilt, so a row limit would cut the list
    in the middle of a week.
    """
    with session() as s:
        keys = [report] if report else list(REPORTS)
        out: list[dict] = []
        for k in keys:
            out += review_service.history(s, k, weeks=weeks)
        return sorted(out, key=lambda r: (r["week"], r["id"]), reverse=True)


@router.get("/runs/{run_id}")
def get_run(run_id: int) -> dict:
    """The review screen: what it produced, what changed, what it warns about."""
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        if run.status in ("pending", "running"):
            return {"run": {"id": run.id, "report_key": run.report_key,
                            "week": run.week, "status": run.status,
                            "started_at": run.started_at},
                    "queued_ahead": worker.depth()}
        return review_service.review(s, run)


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: int, user=Depends(current_user)) -> dict:
    """Approving is a person's act, so it is recorded as that person - taken
    from the signed-in account rather than from whatever the caller typed."""
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        try:
            runner.approve(s, run, by=user.email)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"run_id": run.id, "status": run.status,
                "approved_by": run.approved_by, "approved_at": run.approved_at}


@router.post("/runs/{run_id}/unapprove")
def unapprove_run(run_id: int, user=Depends(current_user)) -> dict:
    """Take an approval back.

    People click the wrong button. Before this the only way out was to build
    the week again, which changes the run id that screenshots and emails
    already point at.
    """
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        try:
            runner.unapprove(s, run, by=user.email)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"run_id": run.id, "status": run.status,
                "approved_by": None, "approved_at": None}


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, user=Depends(current_user)) -> dict:
    """Delete a scorecard.

    A build that was started for the wrong week, or twice by mistake, should
    not sit in the history forever confusing the next person.

    Uploads are untouched - they belong to the week and to the other report as
    well. A running build cannot be deleted out from under itself.

    Anyone signed in can do this today. Restricting it to an admin is a later
    step and needs a role on the account first; there is no admin to be.
    """
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        if run.status in ("pending", "running"):
            raise HTTPException(
                409, "This build is still running. Wait for it to finish.")
        return runner.delete(s, run) | {"deleted_by": user.email}


@router.get("/runs/{run_id}/figures/{name}")
def get_figures(run_id: int, name: str) -> list[dict]:
    """Settlement grids, CP Settled Cases, KPI blocks - the dashboard's data."""
    with session() as s:
        row = s.execute(select(RunFigure).where(
            RunFigure.run_id == run_id, RunFigure.name == name)).scalar_one_or_none()
        if row is None:
            have = [f.name for f in s.execute(
                select(RunFigure).where(RunFigure.run_id == run_id)).scalars()]
            raise HTTPException(404, f"run {run_id} has no {name!r} figures "
                                     f"(has: {', '.join(have) or 'none'})")
        return row.data


@router.get("/runs/{run_id}/tables/{name}")
def get_table(run_id: int, name: str, limit: int = Query(100, le=5000),
              offset: int = 0) -> dict:
    """A page of one produced table.

    Raw Data is 278,930 rows. It stays in the store and is paged from here,
    which is why the dashboard opens instantly where the 21 MB workbook took
    20 seconds.
    """
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        try:
            df = runner.table(s, run, name)
        except KeyError as e:
            raise HTTPException(404, str(e))
        page = df.slice(offset, limit)
        # The column types travel with the page. Guessing per cell in the
        # browser made one money column render "$3,071" beside a bare "614",
        # because 614.0 is a whole number and 3070.59 is not.
        kinds = {c: ("float" if dt in (pl.Float32, pl.Float64)
                     else "int" if dt in (pl.Int8, pl.Int16, pl.Int32, pl.Int64,
                                          pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64)
                     else "text")
                 for c, dt in zip(df.columns, df.dtypes)}
        return {"name": name, "rows": df.height, "columns": df.columns,
                "kinds": kinds, "offset": offset, "limit": limit,
                "data": page.to_dicts()}


# A separate path segment, not a ".csv" suffix: "{name}" would otherwise match
# "raw_data.csv" first and look for a table by that name.
@router.get("/runs/{run_id}/tables/{name}/csv")
def download_table(run_id: int, name: str):
    """The whole table as a CSV file.

    Not a page - the whole thing, 278,930 rows of Raw Data included. The
    dashboard is for reading; this is for the times someone needs the figures
    somewhere else, and a scorecard nobody can get data out of just gets worked
    around.

    Written to a buffer with polars rather than assembled by hand, so quoting,
    commas inside values and nulls come out the way every spreadsheet expects.
    """
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        try:
            df = runner.table(s, run, name)
        except KeyError as e:
            raise HTTPException(404, str(e))

        buf = io.BytesIO()
        df.write_csv(buf)
        buf.seek(0)
        filename = f"{run.report_key}-{run.week}-{name}.csv"
        return StreamingResponse(
            buf, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"',
                     "X-Row-Count": str(df.height)})
