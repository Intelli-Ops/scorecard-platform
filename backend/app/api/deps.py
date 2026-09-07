"""Who is asking.

Every endpoint that touches a week, a run or a file requires a signed-in
Appedology account. The check is one dependency, applied to the whole router,
rather than remembered on each route - a rule you have to remember to apply is
a rule that will eventually be forgotten on the one route that mattered.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

from ..db.models import User
from ..db.session import session
from ..service import auth


def _token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else None


def current_user(authorization: str | None = Header(default=None)) -> User:
    """The signed-in user, or 401.

    401 rather than 403: the browser treats them differently, and the app sends
    someone to the sign-in page on a 401.
    """
    with session() as s:
        user = auth.user_for_token(s, _token(authorization))
        if user is None:
            raise HTTPException(401, "Sign in to continue.")
        s.expunge(user)
        return user
