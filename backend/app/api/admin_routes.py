"""The admin screens: accounts, and the activity log.

Every route here requires an admin (require_admin, applied to the whole
router), and every change an admin makes is itself written to the activity
log - the people who can change accounts are the people whose changes most
need a record.
"""
from __future__ import annotations
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db.models import Session as UserSession, User
from ..db.session import session
from ..service import audit, auth, detect
from .deps import require_admin

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class RoleChange(BaseModel):
    role: str


class ActiveChange(BaseModel):
    active: bool


class Access(BaseModel):
    reports: list[str]


class Approval(BaseModel):
    reports: list[str] | None = None


class ActivityDelete(BaseModel):
    """What to delete. `label` is how the screen named the choice - "29 Sep
    2026", "Week of 22 Sep" - kept in the log so the record reads plainly."""
    ids: list[int] | None = Field(default=None, max_length=audit.MAX_IDS)
    since: dt.datetime | None = None
    until: dt.datetime | None = None
    everything: bool = False
    label: str | None = Field(default=None, max_length=80)
    dry_run: bool = False


def _since(days: int) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)


# ------------------------------------------------------------------ accounts

@router.get("/users")
def list_users(admin: User = Depends(require_admin)) -> list[dict]:
    """Every account, waiting-for-approval first, then by role and email.

    Each row says what the signed-in admin may do to it (`can`), worked out
    by the same rules the actions themselves enforce - so the screen offers
    exactly the buttons that will work.
    """
    with session() as s:
        me = s.get(User, admin.id)
        live = dict(s.execute(
            select(UserSession.user_id, func.count())
            .where(UserSession.revoked.is_(False),
                   UserSession.expires_at > dt.datetime.now(dt.timezone.utc))
            .group_by(UserSession.user_id)).all())
        users = s.execute(select(User)).scalars().all()
        order = {"pending": 0, "locked": 1, "active": 2, "disabled": 3}
        rank = {"system_admin": 0, "admin": 1, "viewer": 2}
        return [auth.as_dict(u) | {"sessions": live.get(u.id, 0),
                                   "report_access": u.report_access or "",
                                   "can": auth.permissions(s, me, u)}
                for u in sorted(users, key=lambda u: (order[u.status],
                                                      rank.get(u.role, 9), u.email))]


def _change(request: Request, admin: User, user_id: int, action: str,
            do, detail=lambda target: {}) -> dict:
    """Load the account, apply the change, log it. One shape for every
    account action, so none of them can forget the log - or the refusal."""
    refused = None
    with session() as s:
        target = s.get(User, user_id)
        if target is None:
            raise HTTPException(404, "No such account.")
        actor = s.get(User, admin.id)
        email = target.email
        try:
            extra = do(s, actor, target) or {}
            out = (auth.as_dict(target) if target in s else {"id": user_id}) | extra
            what = detail(target)
        except auth.Forbidden as e:
            refused = str(e)
        except auth.AuthError as e:
            raise HTTPException(409, str(e))
        else:
            # In the change's own transaction: an account is never altered
            # without the row saying who altered it.
            audit.record(action, db=s, request=request, user=admin, target=email,
                         detail={"user_id": user_id, **what})
    if refused:
        audit.record(action, request=request, user=admin, target=email,
                     outcome="denied", detail={"user_id": user_id, "reason": refused})
        raise HTTPException(403, refused)
    return out


@router.post("/users/{user_id}/approve")
def approve_user(user_id: int, request: Request, body: Approval | None = None,
                 admin: User = Depends(require_admin)) -> dict:
    reports = body.reports if body else None
    return _change(request, admin, user_id, "admin.approve_user",
                   lambda s, a, t: auth.approve(s, a, t, reports) and None,
                   lambda t: {"reports": t.reports})


@router.post("/users/{user_id}/role")
def change_role(user_id: int, body: RoleChange, request: Request,
                admin: User = Depends(require_admin)) -> dict:
    return _change(request, admin, user_id, "admin.role",
                   lambda s, a, t: auth.set_role(s, a, t, body.role) and None,
                   lambda t: {"role": t.role})


@router.post("/users/{user_id}/access")
def change_access(user_id: int, body: Access, request: Request,
                  admin: User = Depends(require_admin)) -> dict:
    return _change(request, admin, user_id, "admin.access",
                   lambda s, a, t: auth.set_access(s, a, t, body.reports) and None,
                   lambda t: {"reports": t.reports})


@router.post("/users/{user_id}/active")
def change_active(user_id: int, body: ActiveChange, request: Request,
                  admin: User = Depends(require_admin)) -> dict:
    return _change(request, admin, user_id,
                   "admin.enable" if body.active else "admin.disable",
                   lambda s, a, t: auth.set_active(s, a, t, body.active) and None)


@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: int, request: Request,
                admin: User = Depends(require_admin)) -> dict:
    return _change(request, admin, user_id, "admin.unlock",
                   lambda s, a, t: auth.unlock(s, a, t) and None)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request,
                   admin: User = Depends(require_admin)) -> dict:
    """Returns the temporary password - once. It is not stored and not
    logged; the log records only THAT it was reset, and by whom."""
    return _change(request, admin, user_id, "admin.password_reset",
                   lambda s, a, t: {"temporary_password":
                                    auth.reset_password(s, t, actor=a)})


@router.post("/users/{user_id}/sign-out")
def sign_out_user(user_id: int, request: Request,
                  admin: User = Depends(require_admin)) -> dict:
    return _change(request, admin, user_id, "admin.sign_out",
                   lambda s, a, t: {"ended": auth.sign_out_everywhere(s, a, t)})


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request,
                admin: User = Depends(require_admin)) -> dict:
    """Remove an account for good. Its history stays in the activity log."""
    return _change(request, admin, user_id, "admin.delete_user",
                   lambda s, a, t: {"deleted": auth.delete_user(s, a, t)})


# ------------------------------------------------------------------ activity

def _filters(action, email, outcome, ip, days) -> audit.Filters:
    return audit.Filters(action=action or None, email=email or None,
                         outcome=outcome or None, ip=ip or None,
                         since=_since(days) if days else None)


@router.get("/actions")
def actions() -> dict:
    """What the Activity screen's filter offers."""
    return {"actions": audit.ACTIONS, "categories": audit.CATEGORIES}


@router.get("/activity")
def activity(action: str | None = None, email: str | None = None,
             outcome: str | None = None, ip: str | None = None,
             days: int = Query(30, ge=0, le=3650),
             before_id: int | None = None,
             limit: int = Query(100, ge=1, le=500)) -> dict:
    with session() as s:
        return audit.search(s, _filters(action, email, outcome, ip, days),
                            limit=limit, before_id=before_id)


@router.get("/activity/csv")
def activity_csv(request: Request, action: str | None = None,
                 email: str | None = None, outcome: str | None = None,
                 ip: str | None = None, days: int = Query(30, ge=0, le=3650),
                 admin: User = Depends(require_admin)):
    f = _filters(action, email, outcome, ip, days)
    with session() as s:
        buf = audit.export_csv(s, f)
        audit.record("admin.activity_export", db=s, request=request, user=admin,
                     detail={"action": action, "email": email, "outcome": outcome,
                             "ip": ip, "days": days})
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="activity-{stamp}.csv"'})


@router.get("/alerts")
def alerts(days: int = Query(7, ge=1, le=365)) -> dict:
    since = _since(days)
    with session() as s:
        return {"days": days, "summary": audit.summary(s, since),
                "alerts": detect.alerts(s, since)}


@router.post("/activity/delete")
def delete_activity(body: ActivityDelete, request: Request,
                    admin: User = Depends(require_admin)) -> dict:
    """Delete events from the log - system admins only.

    One event, a chosen few, a day, a week, a month or all of it. `dry_run`
    only counts, so the screen can say "this deletes 132 events" before it
    does. The deletion is logged AFTER the rows go, so even "everything"
    leaves one row behind: who emptied the log, and when.
    """
    if not admin.is_system_admin:
        audit.record("admin.denied", request=request, user=admin, outcome="denied",
                     target="delete activity")
        raise HTTPException(403, "Only a system admin can delete activity.")
    try:
        req = audit.DeleteRequest(body.ids, body.since, body.until, body.everything)
    except ValueError as e:
        raise HTTPException(400, str(e))
    with session() as s:
        n = audit.delete(s, req, dry_run=body.dry_run)
        if body.dry_run:
            return {"count": n}

        what = ("everything" if body.everything
                else f"{len(body.ids)} chosen" if body.ids else "a period")
        detail = {"deleted": n, "scope": what, "label": body.label}
        if body.ids:
            detail["ids"] = body.ids[:50]
        if body.since:
            detail |= {"since": body.since.isoformat(),
                       "until": body.until.isoformat()}
        # With the deletion, not after it: the rows cannot go without the row
        # saying who removed them.
        audit.record("admin.activity_delete", db=s, request=request, user=admin,
                     target=body.label or what, detail=detail)
    return {"deleted": n}
