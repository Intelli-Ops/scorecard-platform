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
"""
from __future__ import annotations
import datetime as dt
import re

from fastapi import Depends, Header, HTTPException, Request

from ..db.models import User
from ..db.session import session
from ..service import audit, auth


def _token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else None


def signed_in(request: Request,
              authorization: str | None = Header(default=None)) -> User:
    """The signed-in user, or 401.

    401 rather than 403: the browser treats them differently, and the app sends
    someone to the sign-in page on a 401.
    """
    with session() as s:
        row = auth.session_for_token(s, _token(authorization))
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
