"""The activity log: writing entries, searching, exporting and deleting."""
from __future__ import annotations
import csv
import datetime as dt
import io
import logging
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import and_, delete as sql_delete, func, or_, select, true
from sqlalchemy.orm import Session

from ..clock import utcnow
from ..db.models import ActivityLog, User
from ..db.session import session
from .csvsafe import cell

log = logging.getLogger("scorecard.audit")

ACTIONS: dict[str, str] = {
    "auth.signup":            "Signed up",
    "auth.login":             "Signed in",
    "auth.logout":            "Signed out",
    "auth.locked":            "Account locked",
    "auth.password_change":   "Changed password",
    "auth.session_revoke":    "Ended a session",
    "auth.profile_update":    "Updated profile",
    "auth.email_verify":      "Confirmed email address",
    "auth.verify_resend":     "Asked for a new confirmation code",
    "auth.password_forgot":   "Asked for a password reset code",
    "auth.reset_code":        "Entered a password reset code",
    "auth.password_reset":    "Reset password with an emailed code",
    "upload.files":           "Uploaded files",
    "upload.delete":          "Removed an uploaded file",
    "run.start":              "Started a build",
    "run.view":               "Opened a scorecard",
    "run.approve":            "Approved a run",
    "run.unapprove":          "Withdrew an approval",
    "run.delete":             "Deleted a run",
    "week.delete":            "Deleted a week",
    "table.export":           "Exported a table",
    "admin.approve_user":     "Approved an account",
    "admin.role":             "Changed a role",
    "admin.access":           "Changed scorecard access",
    "admin.delete_user":      "Deleted an account",
    "month.working_days":     "Set working days",
    "holiday.add":            "Added a holiday",
    "holiday.delete":         "Deleted a holiday",
    "provider.add":           "Added a provider",
    "provider.edit":          "Changed a provider",
    "provider.delete":        "Deleted a provider",
    "admin.disable":          "Disabled an account",
    "admin.enable":           "Enabled an account",
    "admin.unlock":           "Unlocked an account",
    "admin.password_reset":   "Forced a password reset",
    "admin.sign_out":         "Signed a user out",
    "admin.activity_export":  "Exported the activity log",
    "admin.activity_delete":  "Deleted activity",
    "admin.denied":           "Tried an admin action",
}

CATEGORIES: dict[str, str] = {
    "auth": "Sign-in & accounts", "upload": "Uploads",
    "run": "Builds & approvals", "week": "Weeks", "month": "Working days",
    "holiday": "Holidays", "provider": "Providers",
    "table": "Exports", "admin": "Admin",
}


def client_of(request: Request | None) -> tuple[str | None, str | None]:
    """The caller's address and browser."""
    if request is None:
        return None, None
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, (ua[:400] if ua else None)


class AuditUnavailable(RuntimeError):
    """The activity log could not be written, so the action is refused."""


def record(action: str, *, db: Session | None = None,
           request: Request | None = None,
           user: User | None = None, email: str | None = None,
           outcome: str = "success", target: str | None = None,
           detail: dict | None = None) -> None:
    """Write one row - in the caller's transaction when given `db`, in one of
    its own otherwise."""
    ip, ua = client_of(request)
    who = user.email if user else email
    row = ActivityLog(
        user_id=user.id if user else None,
        email=who,
        action=action, outcome=outcome,
        target=(target or None) and str(target)[:200],
        detail=detail or {}, ip=ip, user_agent=ua)
    if db is not None:
        db.flush()      # the caller's own changes first: a fault in those
    try:
        if db is not None:
            db.add(row)
            db.flush()
        else:
            with session() as s:
                s.add(row)
    except Exception as exc:
        log.exception("could not write to the activity log: %s %s by %s",
                      action, outcome, who)
        raise AuditUnavailable(
            "The activity log could not be written, so this was not done. "
            "Try again; if it keeps happening, tell an admin.") from exc


def record_once(action: str, *, db: Session, user: User, target: str,
                request: Request,
                within: dt.timedelta = dt.timedelta(minutes=10)) -> None:
    """record(), unless this person did the same thing to the same target a
    moment ago."""
    since = utcnow() - within
    seen = db.execute(select(ActivityLog.id).where(
        ActivityLog.user_id == user.id, ActivityLog.action == action,
        ActivityLog.target == target, ActivityLog.at >= since)
        .limit(1)).scalar_one_or_none()
    if seen is None:
        record(action, db=db, request=request, user=user, target=target)


@dataclass
class Filters:
    action: str | None = None        # exact action, or a prefix ending "."
    email: str | None = None         # substring
    outcome: str | None = None
    ip: str | None = None
    since: dt.datetime | None = None
    until: dt.datetime | None = None


def _where(f: Filters):
    conds = []
    if f.action:
        conds.append(ActivityLog.action.startswith(f.action)
                     if f.action.endswith(".") else ActivityLog.action == f.action)
    if f.email:
        conds.append(ActivityLog.email.contains(f.email.strip().lower()))
    if f.outcome:
        conds.append(ActivityLog.outcome == f.outcome)
    if f.ip:
        conds.append(ActivityLog.ip == f.ip.strip())
    if f.since:
        conds.append(ActivityLog.at >= f.since)
    if f.until:
        conds.append(ActivityLog.at < f.until)
    return and_(*conds) if conds else true()


def as_dict(row: ActivityLog) -> dict:
    return {"id": row.id, "at": row.at, "user_id": row.user_id,
            "email": row.email, "action": row.action,
            "label": ACTIONS.get(row.action, row.action),
            "outcome": row.outcome, "target": row.target,
            "detail": row.detail or {}, "ip": row.ip,
            "user_agent": row.user_agent}


def search(s: Session, f: Filters, limit: int = 100,
           before_id: int | None = None) -> dict:
    """Newest first, a page at a time."""
    stmt = select(ActivityLog).where(_where(f))
    if before_id is not None:
        stmt = stmt.where(ActivityLog.id < before_id)
    rows = s.execute(stmt.order_by(ActivityLog.id.desc())
                     .limit(limit + 1)).scalars().all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [as_dict(r) for r in rows],
            "next": rows[-1].id if more and rows else None}


EXPORT_BATCH = 2000


def export_csv(f: Filters):
    """The rows `f` matches as CSV text, newest first, a batch at a time."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "at_utc", "email", "action", "label", "outcome",
                "target", "ip", "user_agent", "detail"])
    stmt = (select(ActivityLog).where(_where(f))
            .order_by(ActivityLog.id.desc())
            .execution_options(yield_per=EXPORT_BATCH))
    with session() as s:
        for i, r in enumerate(s.execute(stmt).scalars(), 1):
            w.writerow([cell(v) for v in (
                r.id, r.at.isoformat(), r.email or "", r.action,
                ACTIONS.get(r.action, r.action), r.outcome, r.target or "",
                r.ip or "", r.user_agent or "", str(r.detail or ""))])
            if i % EXPORT_BATCH == 0:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
    yield buf.getvalue()


def summary(s: Session, since: dt.datetime) -> dict:
    """The tiles along the top of the Activity screen."""
    def n(*conds) -> int:
        return s.execute(select(func.count()).select_from(ActivityLog)
                         .where(ActivityLog.at >= since, *conds)).scalar_one()

    people = s.execute(select(func.count(func.distinct(ActivityLog.user_id)))
                       .where(ActivityLog.at >= since,
                              ActivityLog.user_id.is_not(None))).scalar_one()
    return {
        "events": n(),
        "sign_ins": n(ActivityLog.action == "auth.login",
                      ActivityLog.outcome == "success"),
        "failed_sign_ins": n(ActivityLog.action == "auth.login",
                             ActivityLog.outcome == "failure"),
        "exports": n(or_(ActivityLog.action == "table.export",
                         ActivityLog.action == "admin.activity_export")),
        "denied": n(ActivityLog.outcome == "denied"),
        "active_people": people,
    }


def for_user(s: Session, user_id: int, limit: int = 20) -> list[dict]:
    rows = s.execute(select(ActivityLog).where(ActivityLog.user_id == user_id)
                     .order_by(ActivityLog.id.desc()).limit(limit)).scalars()
    return [as_dict(r) for r in rows]


MAX_IDS = 1000


class DeleteRequest:
    """Which rows to delete: chosen ids, a period, or everything."""

    def __init__(self, ids=None, since=None, until=None, everything=False):
        modes = [bool(ids), since is not None or until is not None, everything]
        if sum(modes) != 1:
            raise ValueError("Choose events, a period, or everything - one of them.")
        if ids and len(ids) > MAX_IDS:
            raise ValueError(f"Choose at most {MAX_IDS} events at a time.")
        if modes[1] and (since is None or until is None or since >= until):
            raise ValueError("A period needs a start before its end.")
        self.ids, self.since, self.until = ids, since, until
        self.everything = everything

    def where(self):
        if self.everything:
            return true()
        if self.ids:
            return ActivityLog.id.in_(self.ids)
        return and_(ActivityLog.at >= self.since, ActivityLog.at < self.until)


def delete(s: Session, req: DeleteRequest, dry_run: bool = False) -> int:
    """Delete the rows `req` names, or with dry_run only count them."""
    n = s.execute(select(func.count()).select_from(ActivityLog)
                  .where(req.where())).scalar_one()
    if n and not dry_run:
        s.execute(sql_delete(ActivityLog).where(req.where()))
    return n
