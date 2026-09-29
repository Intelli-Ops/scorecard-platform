"""Runs: starting a build, reading what it produced, approving it, and
getting its tables out.

Admins build, approve and delete; a viewer reads the APPROVED runs of the
reports it has been given (see _readable). Deliberately thin: every endpoint
is a few lines over service/runner.py and service/review.py, so the rules
about a run needing a person's approval live in one place and cannot drift
between the API and the background job.
"""
from __future__ import annotations
import datetime as dt
import io
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..db.models import Run, RunFigure, User
from ..db.session import session
from ..jobs import worker
from ..reports import REPORTS, load_rules
from ..service import audit, csvsafe, review as review_service, runner
from ..service.ingest import week_status
from .deps import current_user, require_admin, valid_week as _week

# Applied to the whole router rather than route by route: a rule you have to
# remember to add is a rule that gets forgotten on the one route that mattered.
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _readable(run: Run | None, user: User, request: Request) -> Run:
    """The run, if this person may read it - or 404.

    Admins read every run. A viewer reads APPROVED runs of the reports they
    have been given, and nothing else. 404 rather than 403 for the rest: a
    viewer has no business learning which run ids exist.
    """
    if run is None:
        raise HTTPException(404, "No such run.")
    if user.is_admin:
        return run
    if run.status == "approved" and run.report_key in user.reports:
        return run
    audit.record("admin.denied", request=request, user=user, outcome="denied",
                 target=f"run {run.id}")
    raise HTTPException(404, "No such run.")


_submitting = threading.Lock()


@router.post("/runs")
def start_run(request: Request, report: str = Query(...),
              week: str = Query(...), as_of: dt.date | None = Query(None),
              user=Depends(require_admin)) -> dict:
    """Queue a build. Returns straight away - poll /api/runs/{id} for progress.

    One build per report and week at a time. A double-click, or two people
    pressing Build together, used to queue the same work twice.
    """
    _week(week)
    if report not in REPORTS:
        raise HTTPException(404, f"unknown report {report!r}")

    # Checked and queued under one lock. Two presses arriving together each
    # found nothing running, and both queued the same build.
    with _submitting:
        with session() as s:
            busy = s.execute(select(Run.id).where(
                Run.report_key == report, Run.week == week,
                Run.status.in_(("pending", "running"))).limit(1)).scalar_one_or_none()
            if busy is not None:
                raise HTTPException(409, {"message": "This week is already being "
                                                     "built.", "run_id": busy})
            st = week_status(s, week)["reports"][report]
            if not st["ready"]:
                raise HTTPException(
                    409, {"message": f"{st['label']} cannot be built yet",
                          "missing": st["missing"]})
        run_id = worker.submit(report, week, as_of)
    audit.record("run.start", request=request, user=user,
                 target=f"run {run_id}", detail={"report": report, "week": week})
    return {"run_id": run_id, "status": "pending", "queued_ahead": worker.depth() - 1}


@router.get("/scorecards/current")
def current_scorecards(user=Depends(current_user)) -> list[dict]:
    """The scorecard to read right now, per report: the latest APPROVED one.

    Approved, not merely built: a run still in review may yet be rebuilt or
    corrected, and this is the page for people who read the scorecard rather
    than make it. If a newer week is built but not yet approved, that is said
    too, so nobody mistakes last week's figures for this week's.
    """
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
                approver = u.name if u else approved.approved_by.split("@")[0]

            out.append({
                "key": r.key, "label": r.label, "short": r.short,
                "send_day": r.send_day,
                "run": None if approved is None else {
                    "id": approved.id, "week": approved.week,
                    "approved_by": approved.approved_by,
                    "approver_name": approver,
                    "approved_at": approved.approved_at,
                    "finished_at": approved.finished_at,
                },
                "waiting": None if newer is None else {
                    "id": newer.id, "week": newer.week, "status": newer.status},
            })
    return out


@router.get("/runs", dependencies=[Depends(require_admin)])
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
def get_run(run_id: int, request: Request,
            user=Depends(current_user)) -> dict:
    """The review screen: what it produced, what changed, what it warns about."""
    with session() as s:
        run = _readable(s.get(Run, run_id), user, request)
        if run.status in ("pending", "running"):
            return {"run": {"id": run.id, "report_key": run.report_key,
                            "week": run.week, "status": run.status,
                            "started_at": run.started_at},
                    "queued_ahead": worker.depth()}
        out = review_service.review(s, run)
        if not user.is_admin:
            # The review's working - which files, which warnings - is for the
            # people who build the scorecard, not the people who read it.
            for k in ("notes", "inputs", "compared_with", "needs_attention"):
                out.pop(k, None)
    audit.record_once("run.view", user=user, target=f"run {run_id}",
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
        what = {"report": run.report_key, "week": run.week}
    audit.record("run.approve", request=request, user=user,
                 target=f"run {run_id}", detail=what)
    return out


@router.post("/runs/{run_id}/unapprove")
def unapprove_run(run_id: int, request: Request,
                  user=Depends(require_admin)) -> dict:
    """Take an approval back.

    People click the wrong button. Before this the only way out was to build
    the week again, which changes the run id that screenshots and emails
    already point at.
    """
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        was = run.approved_by
        try:
            runner.unapprove(s, run, by=user.email)
        except ValueError as e:
            raise HTTPException(409, str(e))
        what = {"report": run.report_key, "week": run.week,
                "was_approved_by": was}
    audit.record("run.unapprove", request=request, user=user,
                 target=f"run {run_id}", detail=what)
    return {"run_id": run_id, "status": "review",
            "approved_by": None, "approved_at": None}


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, request: Request,
               user=Depends(require_admin)) -> dict:
    """Delete a scorecard.

    A build that was started for the wrong week, or twice by mistake, should
    not sit in the history forever confusing the next person.

    The files it read go with it, but only the ones nothing else needs: an
    upload feeds both reports and every rebuild of its week, so it is removed
    once no surviving run consumes it. Delete the GFS run and All Providers
    keeps its inputs; delete the last run for a week and the files go too.

    A running build cannot be deleted out from under itself.

    Admins only. It cannot be undone, and a scorecard that has been sent to
    a client should not be removable by whoever happens to be signed in.
    """
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        if run.status in ("pending", "running"):
            raise HTTPException(
                409, "This build is still running. Wait for it to finish.")
        out = runner.delete(s, run) | {"deleted_by": user.email}
    audit.record("run.delete", request=request, user=user,
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
    """A page of one produced table.

    Raw Data is 278,930 rows. It stays in the store and is paged from here,
    which is why the dashboard opens instantly where the 21 MB workbook took
    20 seconds.
    """
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
            raw = runner.table(s, run, "raw_data")
        except KeyError as e:
            raise HTTPException(404, str(e))
    return case_ar(raw, load_rules(key), key, {"group": group, "file_status": file_status,
                                     "validity": validity})


# A separate path segment, not a ".csv" suffix: "{name}" would otherwise match
# "raw_data.csv" first and look for a table by that name.
@router.get("/runs/{run_id}/tables/{name}/csv")
def download_table(run_id: int, name: str, request: Request,
                   user=Depends(current_user)):
    """The whole table as a CSV file.

    Not a page - the whole thing, 278,930 rows of Raw Data included. The
    dashboard is for reading; this is for the times someone needs the figures
    somewhere else, and a scorecard nobody can get data out of just gets worked
    around.

    Written to a buffer with polars rather than assembled by hand, so quoting,
    commas inside values and nulls come out the way every spreadsheet expects.
    """
    with session() as s:
        run = _readable(s.get(Run, run_id), user, request)
        try:
            df = runner.table(s, run, name)
        except KeyError as e:
            raise HTTPException(404, str(e))

        buf = io.BytesIO()
        csvsafe.frame(df).write_csv(buf)
        buf.seek(0)
        filename = f"{run.report_key}-{run.week}-{name}.csv"
        audit.record("table.export", request=request, user=user,
                     target=f"run {run_id} / {name}",
                     detail={"rows": df.height, "file": filename})
        return StreamingResponse(
            buf, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"',
                     "X-Row-Count": str(df.height)})
