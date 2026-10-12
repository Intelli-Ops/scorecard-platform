"""Who is asking.

Every endpoint that touches a week, a run or a file requires a signed-in
Appedology account. The check is one dependency, applied to the whole router,
rather than remembered on each route - a rule you have to remember to apply is
a rule that will eventually be forgotten on the one route that mattered.

Three levels:

  signed_in       any live session - enough to reach your own profile, which
                  is where a temporary password gets changed
  current_user    signed in AND not holding a temporary password - the app
  require_admin   current_user who is an admin - the Users and Activity screens

The session's id is left on request.state, so the profile screen can say
which of your sessions is the one you are using.

WHERE THE SESSION TOKEN TRAVELS. The browser holds it in a cookie it cannot
read: HttpOnly, so no script on the page - the app's own, or one that got in
through some future bug - can take it; SameSite=Strict, so the browser never
attaches it to a request another site started. It used to sit in
localStorage, where any script could read it and send it anywhere. An
`Authorization: Bearer` header is still accepted, for scripts and the tests.
"""
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
        # Over HTTPS, never sent on plain HTTP again. Not on a laptop's
        # http://localhost, where a Secure cookie would simply not be kept.
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
    """The signed-in user, or 401.

    401 rather than 403: the browser treats them differently, and the app sends
    someone to the sign-in page on a 401.
    """
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
    """Signed in, with a password of their own.

    After an admin reset, the only thing a temporary password opens is the
    form to replace it. 403 with a code the app recognises, so it shows that
    form instead of an error.
    """
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
    """Why an upload must not even be RECEIVED - (status, message) - or None
    if its sender is a signed-in admin.

    FastAPI reads a request's body before it works out who sent it, so the
    checks above only ran once the whole upload had arrived: anyone, signed
    in or not, could have the server take a gigabyte onto its disk before
    being told no. The middleware in main.py asks this first. It decides
    nothing new - the route's own require_admin still runs afterwards - it
    only asks the same question before the bytes instead of after them.
    """
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


# ------------------------------------------------------------------ inputs

WEEK_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


def valid_week(week: str) -> str:
    """An ISO week label that exists - 2026-W38 - or 400.

    Checked before anything else touches it. The label becomes part of a
    folder path (the parse cache lives under data/cache/<week>/), so an
    unchecked "../.." would write outside the data directory; it is compared
    as text to order weeks, so "2026-W5" would sort after "2026-W38"; and the
    column holds nine characters, which MySQL enforces and SQLite does not.
    """
    if not WEEK_RE.match(week or ""):
        raise HTTPException(400, f"{week!r} is not a week - use the form 2026-W38.")
    # The pattern allows W53 in every year; only some years have one (2026
    # does, 2027 does not), and the calendar raised on the others.
    try:
        dt.date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    except ValueError:
        raise HTTPException(400, f"{week[:4]} has no week {week[6:]}.") from None
    return week
