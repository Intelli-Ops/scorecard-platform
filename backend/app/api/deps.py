"""Request dependencies: who is signed in, role checks and input validation."""
from __future__ import annotations
import datetime as dt
import re

from fastapi import Depends, HTTPException, Request, Response

from ..db.models import User
from ..db.session import session
from ..service import audit, auth

COOKIE = "scorecard_session"


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE, token, max_age=int(auth.SESSION_MAX.total_seconds()),
        path="/api", httponly=True, samesite="strict",
        secure=request.url.scheme == "https")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/api", httponly=True, samesite="strict")


def _token(request: Request) -> str | None:
    """The session token this request carries: the header if there is one,
    otherwise the cookie."""
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, value = authorization.partition(" ")
        return value.strip() if scheme.lower() == "bearer" else None
    return request.cookies.get(COOKIE)


def signed_in(request: Request) -> User:
    """The signed-in user, or 401."""
    with session() as s:
        row = auth.session_for_token(s, _token(request))
        if row is None:
            raise HTTPException(401, "Sign in to continue.")
        auth.touch(s, row, audit.client_of(request)[0])
        request.state.session_id = row.id
        user = row.user
        s.expunge(user)
        return user


def current_user(user: User = Depends(signed_in)) -> User:
    """Signed in, with a password of their own."""
    if user.must_change_password:
        raise HTTPException(403, {"code": "password_change_required",
                                  "message": "Choose a new password to continue."})
    return user


def require_admin(request: Request, user: User = Depends(current_user)) -> User:
    """An admin, or 403 - and the attempt is logged, because someone trying
    admin routes without the role is exactly what the log is for."""
    if not user.is_admin:
        audit.record("admin.denied", request=request, user=user,
                     outcome="denied",
                     target=f"{request.method} {request.url.path}")
        raise HTTPException(403, "Only an admin can do that.")
    return user


def refuse_upload(request: Request) -> tuple[int, str] | None:
    """Why an upload must not even be received - (status, message) - or None if
    its sender is a signed-in admin."""
    with session() as s:
        row = auth.session_for_token(s, _token(request))
        if row is None:
            return 401, "Sign in to continue."
        user = row.user
        if user.must_change_password:
            return 403, "Choose a new password to continue."
        if user.is_admin:
            return None
        s.expunge(user)
    audit.record("admin.denied", request=request, user=user, outcome="denied",
                 target=f"{request.method} {request.url.path}")
    return 403, "Only an admin can do that."


WEEK_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


def valid_week(week: str) -> str:
    """An iso week label that exists - 2026-W38 - or 400."""
    if not WEEK_RE.match(week or ""):
        raise HTTPException(400, f"{week!r} is not a week - use the form 2026-W38.")
    try:
        dt.date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    except ValueError:
        raise HTTPException(400, f"{week[:4]} has no week {week[6:]}.") from None
    return week
