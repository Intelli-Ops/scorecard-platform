"""Builds: starting them, reading their results, approving and exporting."""
from __future__ import annotations
import datetime as dt
import io
import itertools
import threading

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db.models import ACTIVE, Run, RunFigure, User, name_from_email
from ..db.session import session
from ..jobs import worker
from ..reports import REPORTS, load_rules
from ..service import audit, csvsafe, review as review_service, runner
from ..service.ingest import week_status
from .deps import current_user, require_admin, valid_week as _week

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _readable(run: Run | None, user: User, request: Request) -> Run:
    """The run, if this person may read it - or 404."""
    if run is None:
        raise HTTPException(404, "No such run.")
    if user.is_admin:
        return run
    if run.status == "approved" and run.report_key in user.reports:
        return run
    audit.record("admin.denied", request=request, user=user, outcome="denied",
                 target=f"run {run.id}")
    raise HTTPException(404, "No such run.")


_heavy = threading.BoundedSemaphore(2)
HEAVY_WAIT = 20.0


def _building(s, report: str, week: str) -> int | None:
    """The run already building this report and week, if there is one."""
    return s.execute(select(Run.id).where(
        Run.report_key == report, Run.week == week,
        Run.status.in_(ACTIVE)).limit(1)).scalar_one_or_none()


def _already_building(run_id: int | None) -> HTTPException:
    return HTTPException(409, {"message": "This week is already being built.",
                               "run_id": run_id})


@router.post("/runs")
def start_run(request: Request, report: str = Query(...),
              week: str = Query(...), as_of: dt.date | None = Query(None),
              user=Depends(require_admin)) -> dict:
    """Queue a build."""
    _week(week)
    if report not in REPORTS:
        raise HTTPException(404, f"unknown report {report!r}")

    with session() as s:
        busy = _building(s, report, week)
        if busy is not None:
            raise _already_building(busy)
        st = week_status(s, week)["reports"][report]
        if not st["ready"]:
            raise HTTPException(
                409, {"message": f"Nothing has been uploaded for {st['label']} "
                                 f"in {week} yet.",
                      "missing": st["missing"]})
        try:
            run = runner.queue(s, report, week, as_of)
        except IntegrityError:
            s.rollback()
            busy = _building(s, report, week)
            if busy is not None:
                raise _already_building(busy) from None
            raise HTTPException(
                409, {"message": "This week's files changed while the build "
                                 "was being started. Press Build again."}
            ) from None
        audit.record("run.start", db=s, request=request, user=user,
                     target=f"run {run.id}",
                     detail={"report": report, "week": week})
        out = {"run_id": run.id, "status": "pending",
               "queued_ahead": worker.ahead(s, run.id)}
    worker.wake()
    return out


@router.get("/scorecards/current")
def current_scorecards(user=Depends(current_user)) -> list[dict]:
    """The scorecard to read right now, per report: the latest approved one."""
    out = []
    with session() as s:
        for r in (r for r in REPORTS.values() if r.key in user.reports):
            approved = s.execute(
                select(Run).where(Run.report_key == r.key, Run.status == "approved")
                .order_by(Run.week.desc(), Run.approved_at.desc(), Run.id.desc())
                .limit(1)).scalar_one_or_none()
            newer = select(Run).where(
                Run.report_key == r.key,
                Run.status.in_(("pending", "running", "review")))
            if approved is not None:
                newer = newer.where(Run.week > approved.week)
            newer = s.execute(newer.order_by(Run.week.desc(), Run.id.desc())
                              .limit(1)).scalar_one_or_none()

            approver = None
            if approved is not None and approved.approved_by:
                u = s.execute(select(User).where(
                    User.email == approved.approved_by)).scalar_one_or_none()
                approver = u.name if u else name_from_email(approved.approved_by)

            out.append({
                "key": r.key, "label": r.label, "short": r.short,
                "send_day": r.send_day,
                "run": None if approved is None else {
                    "id": approved.id, "week": approved.week,
                    "approved_by": approved.approved_by,
                    "approver_name": approver,
                    "approved_at": approved.approved_at,
                    "finished_at": approved.finished_at,
                    "missing": runner.missing_inputs(approved),
                },
                "waiting": None if newer is None else {
                    "id": newer.id, "week": newer.week, "status": newer.status},
            })
    return out


@router.get("/runs", dependencies=[Depends(require_admin)])
def list_runs(report: str | None = Query(None),
              weeks: int = Query(12, ge=1, le=104)) -> list[dict]:
    """Run history for the last `weeks` weeks - twelve by default."""
    with session() as s:
        keys = [report] if report else list(REPORTS)
        out: list[dict] = []
        for k in keys:
            out += review_service.history(s, k, weeks=weeks)
        return sorted(out, key=lambda r: (r["week"], r["id"]), reverse=True)


@router.get("/runs/{run_id}")
def get_run(run_id: int, request: Request,
            user=Depends(current_user)) -> dict:
    """The review screen: what it produced, what changed, what it warns about."""
    with session() as s:
        run = _readable(s.get(Run, run_id), user, request)
        if run.status in ACTIVE:
            return {"run": {"id": run.id, "report_key": run.report_key,
                            "week": run.week, "status": run.status,
                            "started_at": run.started_at},
                    "queued_ahead": worker.ahead(s, run.id)}
        out = review_service.review(s, run)
        if not user.is_admin:
            for k in ("notes", "inputs", "compared_with", "needs_attention"):
                out.pop(k, None)
        audit.record_once("run.view", db=s, user=user, target=f"run {run_id}",
                          request=request)
    return out


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: int, request: Request,
                user=Depends(require_admin)) -> dict:
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
        out = {"run_id": run.id, "status": run.status,
               "approved_by": run.approved_by, "approved_at": run.approved_at}
        audit.record("run.approve", db=s, request=request, user=user,
                     target=f"run {run_id}",
                     detail={"report": run.report_key, "week": run.week,
                             "missing": runner.missing_inputs(run)})
    return out


@router.post("/runs/{run_id}/unapprove")
def unapprove_run(run_id: int, request: Request,
                  user=Depends(require_admin)) -> dict:
    """Take an approval back."""
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        was = run.approved_by
        try:
            runner.unapprove(s, run, by=user.email)
        except ValueError as e:
            raise HTTPException(409, str(e))
        audit.record("run.unapprove", db=s, request=request, user=user,
                     target=f"run {run_id}",
                     detail={"report": run.report_key, "week": run.week,
                             "was_approved_by": was})
    return {"run_id": run_id, "status": "review",
            "approved_by": None, "approved_at": None}


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, request: Request,
               user=Depends(require_admin)) -> dict:
    """Delete a scorecard."""
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        if run.status in ACTIVE:
            raise HTTPException(
                409, "This build is still running. Wait for it to finish.")
        out = runner.delete(s, run) | {"deleted_by": user.email}
        audit.record("run.delete", db=s, request=request, user=user,
                     target=f"run {run_id}",
                     detail={k: out[k] for k in ("report_key", "week", "rows")})
    return out


@router.get("/runs/{run_id}/figures/{name}")
def get_figures(run_id: int, name: str, request: Request,
                user=Depends(current_user)) -> list[dict]:
    """Settlement grids, CP Settled Cases, KPI blocks - the dashboard's data."""
    with session() as s:
        _readable(s.get(Run, run_id), user, request)
        row = s.execute(select(RunFigure).where(
            RunFigure.run_id == run_id, RunFigure.name == name)).scalar_one_or_none()
        if row is None:
            have = [f.name for f in s.execute(
                select(RunFigure).where(RunFigure.run_id == run_id)).scalars()]
            raise HTTPException(404, f"run {run_id} has no {name!r} figures "
                                     f"(has: {', '.join(have) or 'none'})")
        return row.data


@router.get("/runs/{run_id}/tables/{name}")
def get_table(run_id: int, name: str, request: Request,
              limit: int = Query(100, ge=1, le=5000),
              offset: int = Query(0, ge=0),
              user=Depends(current_user)) -> dict:
    """A page of one produced table."""
    with session() as s:
        run = _readable(s.get(Run, run_id), user, request)
        try:
            page, rows, kinds = runner.table_page(run, name, offset, limit)
        except KeyError as e:
            raise HTTPException(404, str(e))
    return {"name": name, "rows": rows, "columns": list(kinds),
            "kinds": kinds, "offset": offset, "limit": limit,
            "data": page.to_dicts()}


@router.get("/runs/{run_id}/case-ar")
def get_case_ar(run_id: int, request: Request, group: str | None = None,
                file_status: str | None = None, validity: str | None = None,
                user=Depends(current_user)) -> dict:
    """The Case AR pivot, re-built from Raw Data for the filters chosen."""
    from ..service.case_ar_view import case_ar
    with session() as s:
        run = _readable(s.get(Run, run_id), user, request)
        key = run.report_key
        try:
            path = runner.table_path(run, "raw_data")
        except KeyError as e:
            raise HTTPException(404, str(e))
    if not _heavy.acquire(timeout=HEAVY_WAIT):
        raise HTTPException(503, "The server is busy with other Case AR "
                                 "requests. Try again in a moment.",
                            headers={"Retry-After": "5"})
    try:
        return case_ar(pl.read_parquet(path), load_rules(key), key,
                       {"group": group, "file_status": file_status,
                        "validity": validity})
    finally:
        _heavy.release()


@router.get("/runs/{run_id}/tables/{name}/csv")
def download_table(run_id: int, name: str, request: Request,
                   user=Depends(current_user)):
    """The whole table as a CSV file."""
    with session() as s:
        run = _readable(s.get(Run, run_id), user, request)
        try:
            rows = runner.table_row(run, name).rows
            chunks = runner.table_chunks(run, name)
            first = next(chunks)            # a missing file fails here, not
        except (KeyError, FileNotFoundError) as e:     # half-way down a download
            raise HTTPException(404, str(e))
        filename = f"{run.report_key}-{run.week}-{name}.csv"
        audit.record("table.export", db=s, request=request, user=user,
                     target=f"run {run_id} / {name}",
                     detail={"rows": rows, "file": filename})

    def body():
        for i, df in enumerate(itertools.chain([first], chunks)):
            buf = io.BytesIO()
            csvsafe.frame(df).write_csv(buf, include_header=i == 0)
            yield buf.getvalue()

    return StreamingResponse(
        body(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Row-Count": str(rows)})
