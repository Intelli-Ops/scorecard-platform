"""The HTTP surface.

Deliberately thin. Every endpoint is a few lines over the service layer, so
the rules about Tuesday's and Thursday's Case ARs, about which upload a run
read, and about a run needing a person's approval live in one place and cannot
drift between the API and a background job.
"""
from __future__ import annotations
import datetime as dt
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select

from ..config import settings
from ..db.models import Run, RunFigure, Upload
from ..db.session import session
from ..jobs import worker
from ..reports import CASE_AR_SOURCES, REPORTS, get as get_report
from ..service import review as review_service, runner
from ..service.ingest import ingest, week_status
from ..storage.files import FileStore

router = APIRouter(prefix="/api")


def _store() -> FileStore:
    return FileStore(settings.object_dir)


@router.get("/health")
def health() -> dict:
    return {"ok": True, "queued_builds": worker.depth()}


@router.get("/reports")
def list_reports() -> list[dict]:
    """The two scorecards, and which files each one needs."""
    case_ar = {s.key for s in CASE_AR_SOURCES}
    return [{
        "key": r.key, "label": r.label, "send_day": r.send_day,
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
                 uploaded_by: str | None = Form(None)) -> dict:
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
                            uploaded_by=uploaded_by)
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
def list_runs(report: str | None = Query(None), limit: int = 20) -> list[dict]:
    with session() as s:
        keys = [report] if report else list(REPORTS)
        out: list[dict] = []
        for k in keys:
            out += review_service.history(s, k, limit=limit)
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
def approve_run(run_id: int, by: str = Query(...)) -> dict:
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        try:
            runner.approve(s, run, by=by)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"run_id": run.id, "status": run.status,
                "approved_by": run.approved_by, "approved_at": run.approved_at}


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
        return {"name": name, "rows": df.height, "columns": df.columns,
                "offset": offset, "limit": limit,
                "data": page.to_dicts()}
