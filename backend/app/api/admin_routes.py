"""Admin API: managing accounts and reading the activity log."""
from __future__ import annotations
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..clock import utcnow
from ..db.models import Holiday, Provider, Session as UserSession, User
from ..db.session import session
from ..service import audit, auth, detect
from ..service.providers import as_dict as _provider
from .deps import require_admin

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class RoleChange(BaseModel):
    role: str


class ActiveChange(BaseModel):
    active: bool


class Access(BaseModel):
    reports: list[str]


class UploadAccess(BaseModel):
    inputs: list[str] | None = None          # None: every input


class Approval(BaseModel):
    reports: list[str] | None = None


class NewHoliday(BaseModel):
    day: dt.date
    name: str = Field(min_length=1, max_length=120)


class ProviderIn(BaseModel):
    regid: int = Field(ge=1)
    provider_id: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=32)
    provider_group: str = Field(min_length=1, max_length=200)

    def cleaned(self) -> dict:
        out = {k: (v.strip() or None) if isinstance(v, str) else v
               for k, v in self.model_dump().items()}
        for k, what in (("provider_id", "a provider ID"), ("provider_group", "a group")):
            if not out[k]:
                raise HTTPException(400, f"Give the provider {what}.")
        return out


class ActivityDelete(BaseModel):
    """What to delete."""
    ids: list[int] | None = Field(default=None, max_length=audit.MAX_IDS)
    since: dt.datetime | None = None
    until: dt.datetime | None = None
    everything: bool = False
    label: str | None = Field(default=None, max_length=80)
    dry_run: bool = False


def _since(days: int) -> dt.datetime:
    return utcnow() - dt.timedelta(days=days)


@router.get("/users")
def list_users(admin: User = Depends(require_admin)) -> list[dict]:
    """Every account, waiting-for-approval first, then by role and email."""
    with session() as s:
        me = s.get(User, admin.id)
        live = dict(s.execute(
            select(UserSession.user_id, func.count())
            .where(UserSession.revoked.is_(False),
                   UserSession.expires_at > utcnow())
            .group_by(UserSession.user_id)).all())
        users = s.execute(select(User)).scalars().all()
        order = {"pending": 0, "unverified": 1, "locked": 2, "active": 3,
                 "disabled": 4}
        rank = {"system_admin": 0, "admin": 1, "viewer": 2}
        return [auth.as_dict(u) | {"sessions": live.get(u.id, 0),
                                   "report_access": u.report_access or "",
                                   "can": auth.permissions(s, me, u)}
                for u in sorted(users, key=lambda u: (order[u.status],
                                                      rank.get(u.role, 9), u.email))]


def _change(request: Request, admin: User, user_id: int, action: str,
            do, detail=lambda target: {}) -> dict:
    """Load the account, apply the change, log it."""
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


@router.post("/users/{user_id}/uploads")
def change_upload_access(user_id: int, body: UploadAccess, request: Request,
                         admin: User = Depends(require_admin)) -> dict:
    return _change(request, admin, user_id, "admin.upload_access",
                   lambda s, a, t: auth.set_upload_access(s, a, t, body.inputs) and None,
                   lambda t: {"inputs": None if t.uploads_all else t.uploads})


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
    """Force a password reset: the password stops working and the owner is emailed."""
    def do(s, a, t):
        auth.force_reset(s, a, t)
        return {"notified": t.email}
    return _change(request, admin, user_id, "admin.password_reset", do)


@router.post("/users/{user_id}/sign-out")
def sign_out_user(user_id: int, request: Request,
                  admin: User = Depends(require_admin)) -> dict:
    return _change(request, admin, user_id, "admin.sign_out",
                   lambda s, a, t: {"ended": auth.sign_out_everywhere(s, a, t)})


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request,
                admin: User = Depends(require_admin)) -> dict:
    """Remove an account for good."""
    return _change(request, admin, user_id, "admin.delete_user",
                   lambda s, a, t: {"deleted": auth.delete_user(s, a, t)})


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
    audit.record("admin.activity_export", request=request, user=admin,
                 detail={"action": action, "email": email, "outcome": outcome,
                         "ip": ip, "days": days})
    stamp = utcnow().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        audit.export_csv(_filters(action, email, outcome, ip, days)),
        media_type="text/csv",
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
    """Delete events from the log - system admins only."""
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
        audit.record("admin.activity_delete", db=s, request=request, user=admin,
                     target=body.label or what, detail=detail)
    return {"deleted": n}


def _holiday(h: Holiday) -> dict:
    return {"day": h.day.isoformat(), "name": h.name,
            "set_by": h.set_by, "set_at": h.set_at}


@router.get("/holidays")
def list_holidays() -> list[dict]:
    """Every day off pacing leaves out, earliest first."""
    with session() as s:
        return [_holiday(h) for h in s.scalars(select(Holiday).order_by(Holiday.day))]


@router.post("/holidays")
def add_holiday(body: NewHoliday, request: Request,
                admin: User = Depends(require_admin)) -> dict:
    """A new day off: its week and month lose a working day."""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Give the holiday a name.")
    if body.day.weekday() >= 5:
        raise HTTPException(400, f"{body.day:%a %d %b %Y} is a weekend - it is "
                                 f"not a working day anyway.")
    with session() as s:
        if s.get(Holiday, body.day) is not None:
            raise HTTPException(409, f"{body.day:%d %b %Y} is already a holiday.")
        h = Holiday(day=body.day, name=name, set_by=admin.email, set_at=utcnow())
        s.add(h)
        s.flush()
        audit.record("holiday.add", db=s, request=request, user=admin,
                     target=body.day.isoformat(), detail={"name": name})
        return _holiday(h)


@router.delete("/holidays/{day}")
def delete_holiday(day: dt.date, request: Request,
                   admin: User = Depends(require_admin)) -> dict:
    """Make a holiday a working day again."""
    with session() as s:
        h = s.get(Holiday, day)
        if h is None:
            raise HTTPException(404, "That day is not a holiday.")
        gone = _holiday(h)
        s.delete(h)
        audit.record("holiday.delete", db=s, request=request, user=admin,
                     target=day.isoformat(), detail={"name": gone["name"]})
        return gone


@router.get("/providers")
def list_providers() -> list[dict]:
    """The provider list, by BUSINESSREGID."""
    with session() as s:
        return [_provider(p) | {"set_by": p.set_by, "set_at": p.set_at}
                for p in s.scalars(select(Provider).order_by(Provider.regid))]


@router.post("/providers")
def add_provider(body: ProviderIn, request: Request,
                 admin: User = Depends(require_admin)) -> dict:
    """A new provider - its cases count under its group in builds from now on."""
    row = body.cleaned()
    with session() as s:
        if s.get(Provider, row["regid"]) is not None:
            raise HTTPException(409, f"BUSINESSREGID {row['regid']} is already in "
                                     f"the list - change that row instead.")
        p = Provider(**row, set_by=admin.email, set_at=utcnow())
        s.add(p)
        s.flush()
        audit.record("provider.add", db=s, request=request, user=admin,
                     target=str(p.regid), detail=_provider(p))
        return _provider(p) | {"set_by": p.set_by, "set_at": p.set_at}


@router.put("/providers/{regid}")
def edit_provider(regid: int, body: ProviderIn, request: Request,
                  admin: User = Depends(require_admin)) -> dict:
    """Change a provider's details - its BUSINESSREGID can change too."""
    row = body.cleaned()
    with session() as s:
        p = s.get(Provider, regid)
        if p is None:
            raise HTTPException(404, "No provider has that BUSINESSREGID.")
        if row["regid"] != regid and s.get(Provider, row["regid"]) is not None:
            raise HTTPException(409, f"BUSINESSREGID {row['regid']} is already in "
                                     f"the list.")
        was = _provider(p)
        if row["regid"] != regid:
            s.delete(p)
            s.flush()
            p = Provider(**row)
            s.add(p)
        else:
            for k, v in row.items():
                setattr(p, k, v)
        p.set_by, p.set_at = admin.email, utcnow()
        s.flush()
        now = _provider(p)
        audit.record("provider.edit", db=s, request=request, user=admin,
                     target=str(regid),
                     detail={k: {"was": was[k], "now": now[k]}
                             for k in now if was[k] != now[k]})
        return now | {"set_by": p.set_by, "set_at": p.set_at}


@router.delete("/providers/{regid}")
def delete_provider(regid: int, request: Request,
                    admin: User = Depends(require_admin)) -> dict:
    """Take a provider off the list - its cases no longer count under a group."""
    with session() as s:
        p = s.get(Provider, regid)
        if p is None:
            raise HTTPException(404, "No provider has that BUSINESSREGID.")
        gone = _provider(p)
        s.delete(p)
        audit.record("provider.delete", db=s, request=request, user=admin,
                     target=str(regid), detail=gone)
        return gone
