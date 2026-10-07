"""Weeks: what each report needs, the files uploaded for a week, and the
month's working days.

Admins only - uploading and deleting are the workspace's jobs. Deliberately
thin: every endpoint is a few lines over the service layer (service/ingest.py
and service/runner.py), so the rules about which file is which live in one
place.
"""
from __future__ import annotations
import calendar
import datetime as dt
import re
import tempfile
from pathlib import Path

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel
from sqlalchemy import select

from ..config import settings
from ..db.models import MonthSetting, Run, Upload
from ..db.session import session
from ..reports import CASE_AR_KEYS, REPORTS, load_rules
from ..service import audit, runner
from ..service.ingest import ingest, week_status
from ..storage.files import FileStore
from .deps import current_user, require_admin, valid_week as _week

# Applied to the whole router rather than route by route: a rule you have to
# remember to add is a rule that gets forgotten on the one route that mattered.
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _store() -> FileStore:
    return FileStore(settings.object_dir)


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
        audit.record("week.delete", db=s, request=request, user=user, target=week,
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
            audit.record(
                "upload.files", db=s, request=request, user=user, target=week,
                detail={"for_report": for_report,
                        "accepted": [{"file": a["filename"], "sha256": a["sha256"],
                                      "bytes": a["size_bytes"]}
                                     for a in out["accepted"]],
                        "rejected": [r["filename"] for r in out["rejected"]]})
    return out


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
    with session() as s:
        info = _month_info(s, week)
        key = info["month"]
        days_in_month = calendar.monthrange(int(key[:4]), int(key[5:]))[1]
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
        audit.record("month.working_days", db=s, request=request, user=user,
                     target=key,
                     detail={"was": info["working_days"], "now": out["working_days"],
                             "calendar": out["calendar_days"]})
    return out
