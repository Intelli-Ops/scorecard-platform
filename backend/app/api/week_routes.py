"""Weeks: uploading files and setting a month's working days."""
from __future__ import annotations
import calendar
import re
import tempfile
from pathlib import Path

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel
from sqlalchemy import select

from ..clock import utcnow
from ..config import settings
from ..db.models import MonthSetting, Run, Upload
from ..db.session import session
from ..reports import CASE_AR_KEYS, REPORTS, load_rules
from ..service import audit, runner
from ..service.holidays import with_holidays
from ..service.ingest import ingest, source, too_long, week_status
from ..storage.files import FileStore
from .deps import current_user, require_admin, valid_week as _week

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _store() -> FileStore:
    return FileStore(settings.object_dir)


def _refuse(request: Request, user, action: str, target: str, why: str):
    """403 for an input this admin has not been given, logged as denied."""
    audit.record(action, request=request, user=user, target=target,
                 outcome="denied", detail={"reason": why})
    raise HTTPException(403, why)


NOT_YOURS = ("A system admin has not given your account {label} to upload - "
             "ask one, or an admin who has it")


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
    """Delete a week: its builds, and every file uploaded for it."""
    _week(week)
    if not user.uploads_all:
        _refuse(request, user, "week.delete", week,
                "Deleting a week takes every file in it, and your account may "
                "upload only some of them. Ask an admin who may upload them all.")
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


@router.post("/weeks/{week}/uploads")
def upload(week: str, request: Request,
           files: list[UploadFile] = File(...),
           for_report: str | None = Form(None),
           as_source: str | None = Form(None),
           user=Depends(require_admin)) -> dict:
    """Receive this week's files - as the inputs their names say, or all as
    `as_source` whatever they are called."""
    _week(week)
    if for_report and for_report not in REPORTS:
        raise HTTPException(400, f"unknown report {for_report!r}")
    if as_source and source(as_source) is None:
        raise HTTPException(400, f"unknown input {as_source!r}")
    if as_source and as_source not in user.uploads:
        _refuse(request, user, "upload.files", week,
                NOT_YOURS.format(label=source(as_source).label) + ".")

    with tempfile.TemporaryDirectory() as tmp:
        landed: list[Path] = []
        refused: list[tuple[str, str]] = []
        for i, f in enumerate(files):
            name = re.split(r"[\\/]", f.filename or "")[-1].strip()
            if name in ("", ".", ".."):
                name = "unnamed"
            if too_long(name):
                refused.append((name[:60] + "...", too_long(name)))
                continue
            dest = Path(tmp) / str(i) / name
            dest.parent.mkdir()
            _save_upload(f, dest, settings.max_upload_mb * 1024 * 1024)
            landed.append(dest)

        with session() as s:
            result = ingest(s, _store(), week, landed, for_report=for_report,
                            uploaded_by=user.email, as_source=as_source,
                            may_upload=None if user.uploads_all else set(user.uploads))
            out = {
                "week": week,
                "accepted": [{"source_key": a.source_key, "label": a.label,
                              "filename": a.filename, "scope": a.report_key or "shared",
                              "size_bytes": a.size_bytes, "sha256": a.sha256,
                              "already_held": a.deduplicated}
                             for a in result.accepted],
                "rejected": [{"filename": n, "reason": why}
                             for n, why in refused + result.rejected],
                "status": week_status(s, week),
            }
            audit.record(
                "upload.files", db=s, request=request, user=user, target=week,
                detail={"for_report": for_report, "as_source": as_source,
                        "accepted": [{"file": a["filename"], "sha256": a["sha256"],
                                      "bytes": a["size_bytes"]}
                                     for a in out["accepted"]],
                        "rejected": [r["filename"] for r in out["rejected"]]})
    return out


@router.delete("/weeks/{week}/uploads/{upload_id}")
def remove_upload(week: str, upload_id: int, request: Request,
                  user=Depends(require_admin)) -> dict:
    """Take back one uploaded file - the wrong one, sent by mistake - without
    deleting the week."""
    _week(week)
    with session() as s:
        row = s.get(Upload, upload_id)
        if row is None or row.week != week:
            raise HTTPException(404, "No such file in this week.")
        if row.source_key not in user.uploads:
            spec = source(row.source_key)
            label = spec.label if spec else row.source_key
            s.rollback()
            _refuse(request, user, "upload.delete", week,
                    NOT_YOURS.format(label=label)
                    + ", so it cannot take this file back either.")
        try:
            gone = runner.remove_upload(s, row)
        except ValueError as e:
            raise HTTPException(409, str(e))
        audit.record("upload.delete", db=s, request=request, user=user,
                     target=week, detail={"file": gone["filename"],
                                          "sha256": gone["sha256"]})
        return gone | {"status": week_status(s, week)}


class WorkingDays(BaseModel):
    working_days: int | None = None      # None goes back to the calendar


def _month_info(s, week: str) -> dict:
    rules = with_holidays(s, load_rules("gfs"))
    period = runner.month_of(week, rules)
    row = s.get(MonthSetting, period.key)
    if row is not None:
        period = runner.month_of(week, {**rules, "working_days": {period.key: row.working_days}})
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


@router.get("/weeks/{week}/month", dependencies=[Depends(require_admin)])
def week_month(week: str) -> dict:
    """The month a week belongs to, and the working days its pace uses."""
    _week(week)
    with session() as s:
        return _month_info(s, week)


@router.put("/weeks/{week}/month")
def set_working_days(week: str, body: WorkingDays, request: Request,
                     user=Depends(require_admin)) -> dict:
    """Set the working days of the month `week` belongs to - for every build in
    that month from now on."""
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
            row.set_at = utcnow()
        s.flush()
        out = _month_info(s, week)
        audit.record("month.working_days", db=s, request=request, user=user,
                     target=key,
                     detail={"was": info["working_days"], "now": out["working_days"],
                             "calendar": out["calendar_days"]})
    return out
