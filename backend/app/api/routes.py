"""The HTTP surface.

Deliberately thin. Every endpoint is a few lines over the service layer, so
the rules about Tuesday's and Thursday's Case ARs, about which upload a run
read, and about a run needing a person's approval live in one place and cannot
drift between the API and a background job.
"""
from __future__ import annotations
import datetime as dt
import io
import re
import tempfile
import threading
from pathlib import Path

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     Request, UploadFile)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from ..config import settings
from ..db.models import MonthSetting, Run, RunFigure, Upload, User
from ..db.session import session
from ..jobs import worker
from ..reports import CASE_AR_KEYS, REPORTS, load_rules
from ..service import audit, csvsafe, review as review_service, runner
from ..service.ingest import ingest, week_status
from ..storage.files import FileStore
from .deps import current_user, require_admin

# Applied to the whole router rather than route by route: a rule you have to
# remember to add is a rule that gets forgotten on the one route that mattered.
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _store() -> FileStore:
    return FileStore(settings.object_dir)


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


WEEK_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


def _week(week: str) -> str:
    """An ISO week label - 2026-W38 - or 400.

    Checked before anything else touches it. The label becomes part of a
    folder path (the parse cache lives under data/cache/<week>/), so an
    unchecked "../.." would write outside the data directory; it is compared
    as text to order weeks, so "2026-W5" would sort after "2026-W38"; and the
    column holds nine characters, which MySQL enforces and SQLite does not.
    """
    if not WEEK_RE.match(week or ""):
        raise HTTPException(400, f"{week!r} is not a week - use the form 2026-W38.")
    return week


@router.get("/reports", dependencies=[Depends(require_admin)])
def list_reports() -> list[dict]:
    """The two scorecards, and which files each one needs."""
    return [{
        "key": r.key, "label": r.label, "short": r.short,
        "send_day": r.send_day,
        "sheets": list(r.sheets),
        "sources": [{"key": s.key, "label": s.label, "required": s.required,
                     "per_report": s.key in CASE_AR_KEYS}
                    for s in r.sources],
    } for r in REPORTS.values()]


@router.get("/weeks", dependencies=[Depends(require_admin)])
def list_weeks() -> list[dict]:
    """Every week that has had anything uploaded, newest first."""
    with session() as s:
        weeks = [w for (w,) in s.execute(
            select(Upload.week).distinct().order_by(Upload.week.desc()))]
        return [week_status(s, w) for w in weeks]


@router.get("/weeks/{week}", dependencies=[Depends(require_admin)])
def get_week(week: str) -> dict:
    _week(week)
    with session() as s:
        return week_status(s, week)


@router.delete("/weeks/{week}")
def delete_week(week: str, request: Request,
                user=Depends(require_admin)) -> dict:
    """Delete a week: its builds, and every file uploaded for it.

    Deleting builds one at a time cannot get you back to a clean slate. Uploads
    outlive runs on purpose - they belong to the week, not to one build - so a
    week whose builds are all gone keeps its files and still offers a Build
    button with nothing behind it. This is how you actually remove a week you
    uploaded by mistake, or a test week you no longer want.

    It cannot be undone: the files would have to be uploaded again, which is
    why only an admin can do it.
    """
    _week(week)
    with session() as s:
        known = s.execute(select(Upload.id).where(Upload.week == week)
                          .limit(1)).scalar_one_or_none()
        has_runs = s.execute(select(Run.id).where(Run.week == week)
                             .limit(1)).scalar_one_or_none()
        if known is None and has_runs is None:
            raise HTTPException(404, f"nothing uploaded for {week}")
        try:
            out = runner.delete_week(s, week) | {"deleted_by": user.email}
        except ValueError as e:
            raise HTTPException(409, str(e))
    audit.record("week.delete", request=request, user=user, target=week,
                 detail={k: out[k] for k in ("runs_removed", "uploads_removed")})
    return out


def _save_upload(f: UploadFile, dest: Path, limit: int) -> None:
    """Stream one uploaded file to disk, refusing it past `limit` bytes."""
    size = 0
    with open(dest, "wb") as out:
        while chunk := f.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(
                    413, f"{dest.name} is larger than "
                         f"{settings.max_upload_mb} MB - is it the right file?")
            out.write(chunk)


# A plain def, not async: FastAPI runs it on a worker thread. Everything in it
# blocks - copying, hashing, the database - and in an async def that stalled
# the whole server, every other request included, for as long as a 385 MB
# upload took.
@router.post("/weeks/{week}/uploads")
def upload(week: str, request: Request,
           files: list[UploadFile] = File(...),
           for_report: str | None = Form(None),
           user=Depends(require_admin)) -> dict:
    """Receive this week's files.

    for_report is needed only for the two Case AR files. Anything that is not
    one of the nine inputs is reported back rather than stored - the week
    folder always contained delivered workbooks alongside the sources, and
    reading one of those by mistake would be worse than refusing it.
    """
    _week(week)
    if for_report and for_report not in REPORTS:
        raise HTTPException(400, f"unknown report {for_report!r}")

    with tempfile.TemporaryDirectory() as tmp:
        landed: list[Path] = []
        for i, f in enumerate(files):
            # Streamed to disk in chunks: a 240 MB upload is never held whole
            # in the server's memory. One folder per file, so two files that
            # share a name cannot overwrite each other before they are read.
            # The name is cut at either kind of slash: a browser on Windows
            # may send "C:\\...\\file.xlsx", which Path on Linux would take
            # as one long filename.
            name = re.split(r"[\\/]", f.filename or "")[-1].strip()
            if name in ("", ".", ".."):
                name = "unnamed"
            dest = Path(tmp) / str(i) / name
            dest.parent.mkdir()
            _save_upload(f, dest, settings.max_upload_mb * 1024 * 1024)
            landed.append(dest)

        with session() as s:
            result = ingest(s, _store(), week, landed, for_report=for_report,
                            uploaded_by=user.email)
            out = {
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
    audit.record("upload.files", request=request, user=user, target=week,
                 detail={"for_report": for_report,
                         "accepted": [{"file": a["filename"], "sha256": a["sha256"],
                                       "bytes": a["size_bytes"]}
                                      for a in out["accepted"]],
                         "rejected": [r["filename"] for r in out["rejected"]]})
    return out


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


class WorkingDays(BaseModel):
    working_days: int | None = None      # None goes back to the calendar


def _month_info(s, week: str) -> dict:
    rules = _rules()
    period = runner.month_of(week, rules)
    row = s.get(MonthSetting, period.key)
    if row is not None:
        period = runner.month_of(week, {**rules, "working_days": {period.key: row.working_days}})
    # The working days gone by the end of this week: what the pace divides
    # the month-to-date by (never more than the month's working days).
    n = period.weeks_so_far
    return {"month": period.key, "label": period.label,
            "calendar_days": period.calendar_days,
            "working_days": period.business_days,
            "entered": row is not None,
            "set_by": row.set_by if row else None,
            "set_at": row.set_at if row else None,
            "week_of_month": n,
            "days_passed": period.pace_divisor(n),
            "passed_through": period.month_weeks[n - 1][1]}


def _rules() -> dict:
    """The holidays both reports' rules agree on - what the calendar count
    leaves out. The two rules files keep the same list."""
    return load_rules("gfs")


@router.get("/weeks/{week}/month", dependencies=[Depends(require_admin)])
def week_month(week: str) -> dict:
    """The month a week belongs to, and the working days its pace uses."""
    _week(week)
    with session() as s:
        return _month_info(s, week)


@router.put("/weeks/{week}/month")
def set_working_days(week: str, body: WorkingDays, request: Request,
                     user=Depends(require_admin)) -> dict:
    """Set the working days of the month `week` belongs to - for every build
    in that month from now on. Builds already made keep the number they were
    paced on (it is recorded on each run); build again to use the new one."""
    _week(week)
    import calendar as cal
    with session() as s:
        info = _month_info(s, week)
        key = info["month"]
        days_in_month = cal.monthrange(int(key[:4]), int(key[5:]))[1]
        row = s.get(MonthSetting, key)
        if body.working_days is None:
            if row is not None:
                s.delete(row)
        else:
            if not 1 <= body.working_days <= days_in_month:
                raise HTTPException(400, f"{info['label']} has {days_in_month} days "
                                         f"- enter between 1 and {days_in_month}.")
            if row is None:
                row = MonthSetting(month=key, working_days=body.working_days)
                s.add(row)
            row.working_days = body.working_days
            row.set_by = user.email
            row.set_at = dt.datetime.now(dt.timezone.utc)
        s.flush()
        out = _month_info(s, week)
    audit.record("month.working_days", request=request, user=user, target=key,
                 detail={"was": info["working_days"], "now": out["working_days"],
                         "calendar": out["calendar_days"]})
    return out


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
