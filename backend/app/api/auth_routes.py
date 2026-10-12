"""Sign up, sign in, sign out - and your own profile.

The /api/auth routes are open: they are how someone gets a token in the first
place. The /api/me routes need a session but NOT a password of your own, since
changing a temporary password is done from there.

Every outcome is written to the activity log, failures above all. What
succeeded is logged in the same transaction as the change itself. A failed
sign-in is recorded AFTER its database session has committed, so the count of
wrong passwords sticks even though the request ends in an error.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..db.models import User
from ..db.session import session
from ..service import audit, auth, ratelimit
from .deps import (_token, clear_session_cookie, set_session_cookie, signed_in)

router = APIRouter(prefix="/api/auth")
me_router = APIRouter(prefix="/api/me")


# Bounded before anything reads them. The email of a failed sign-in is stored
# in the activity log as typed; longer than its column, MySQL refuses the row
# and the failure goes unrecorded. The rest keep a request body a request body.
Email = Field(max_length=320)
Password = Field(max_length=256)


class SignUp(BaseModel):
    email: str = Email
    apd_id: str = Field(max_length=16)
    password: str = Password


class SignIn(BaseModel):
    email: str = Email
    password: str = Password


class Profile(BaseModel):
    display_name: str | None = Field(default=None, max_length=400)


class PasswordChange(BaseModel):
    current: str = Password
    new: str = Password


def _too_many(key: str, rule: tuple[int, int], what: str) -> None:
    wait = ratelimit.blocked(key, rule)
    if wait:
        minutes = max(1, round(wait / 60))
        raise HTTPException(
            429, f"Too many {what}. Try again in {minutes} "
                 f"minute{'s' if minutes != 1 else ''}.",
            headers={"Retry-After": str(wait)})


@router.get("/rules")
def rules() -> dict:
    """What the sign-up form should tell people before they get it wrong."""
    return {
        "email_domain": auth.EMAIL_DOMAIN,
        "apd_format": "APD-1234",
        "min_password": auth.MIN_PASSWORD,
    }


@router.post("/signup")
def signup(body: SignUp, request: Request) -> dict:
    """Create an account. It waits for an admin before it can sign in, so no
    token comes back - see auth.sign_up for why."""
    ip = audit.client_of(request)[0] or "?"
    _too_many(f"signup:{ip}", ratelimit.SIGNUPS, "new accounts from this address")
    ratelimit.hit(f"signup:{ip}", ratelimit.SIGNUPS)
    with session() as s:
        try:
            user = auth.sign_up(s, body.email, body.apd_id, body.password)
            out = {"pending": True, "user": auth.as_dict(user),
                   "message": "Account created. An admin has to approve it "
                              "before you can sign in."}
        except auth.AuthError as e:
            raise HTTPException(400, str(e))
        audit.record("auth.signup", db=s, request=request, user=user,
                     detail={"apd_id": user.apd_id})
    return out


@router.post("/login")
def login(body: SignIn, request: Request, response: Response) -> dict:
    """Sign in. The session travels in a cookie the page's scripts cannot
    read (see deps.py); the token in the answer is for scripts and tests,
    and the app itself does not keep it."""
    ip, ua = audit.client_of(request)
    _too_many(f"login:{ip}", ratelimit.LOGIN_FAILURES,
              "failed sign-ins from this address")
    refused: auth.LoginRefused | None = None
    with session() as s:
        try:
            user, token = auth.sign_in(s, body.email, body.password,
                                       ip=ip, user_agent=ua)
            out = {"token": token, "user": auth.as_dict(user)}
        except auth.LoginRefused as e:
            refused = e                 # let the session commit the counters
        else:
            # With the session it opens: nobody is signed in unrecorded.
            audit.record("auth.login", db=s, request=request, user=user)

    if refused is not None:
        ratelimit.hit(f"login:{ip}", ratelimit.LOGIN_FAILURES)
        audit.record("auth.login", request=request, user=refused.user,
                     email=refused.email, outcome="failure",
                     detail={"reason": refused.reason})
        if refused.locked_now:
            audit.record("auth.locked", request=request, user=refused.user,
                         detail={"minutes": auth.LOCK_MINUTES})
        raise HTTPException(401, str(refused))
    set_session_cookie(request, response, token)
    return out


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    with session() as s:
        user = auth.sign_out(s, _token(request))
        if user is not None:
            audit.record("auth.logout", db=s, request=request, user=user)
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(signed_in)) -> dict:
    return auth.as_dict(user)


# ------------------------------------------------------------------ profile

@me_router.get("")
def my_profile(user: User = Depends(signed_in)) -> dict:
    return auth.as_dict(user)


@me_router.patch("")
def update_profile(body: Profile, request: Request,
                   user: User = Depends(signed_in)) -> dict:
    with session() as s:
        row = s.get(User, user.id)
        before = row.display_name
        try:
            auth.update_profile(s, row, body.display_name)
        except auth.AuthError as e:
            raise HTTPException(400, str(e))
        out = auth.as_dict(row)
        audit.record("auth.profile_update", db=s, request=request, user=user,
                     detail={"display_name": {"was": before,
                                              "now": out["display_name"]}})
    return out


@me_router.post("/password")
def change_password(body: PasswordChange, request: Request,
                    user: User = Depends(signed_in)) -> dict:
    """Change your own password. Your other sessions are signed out; this one
    stays, so changing it does not throw you back to the sign-in page.

    Wrong current passwords are limited per account: a session left open on
    someone else's screen must not be a way to guess the password itself."""
    key = f"password:{user.id}"
    _too_many(key, ratelimit.PASSWORD_FAILURES, "wrong passwords")
    failed: str | None = None
    guess = False
    with session() as s:
        row = s.get(User, user.id)
        try:
            ended = auth.change_password(s, row, body.current, body.new,
                                         keep_session=request.state.session_id)
            out = {"ok": True, "other_sessions_ended": ended,
                   "user": auth.as_dict(row)}
        except auth.AuthError as e:
            # Only a wrong CURRENT password is a guess. A new one that is too
            # short, or the same as the old, used to be counted too - and ten
            # of those shut the form with "too many wrong passwords".
            failed, guess = str(e), isinstance(e, auth.WrongPassword)
        else:
            audit.record("auth.password_change", db=s, request=request, user=user,
                         detail={"other_sessions_ended": ended,
                                 "was_temporary": bool(user.must_change_password)})
    if failed:
        if guess:
            ratelimit.hit(key, ratelimit.PASSWORD_FAILURES)
        audit.record("auth.password_change", request=request, user=user,
                     outcome="failure", detail={"reason": failed})
        raise HTTPException(400, failed)
    return out


@me_router.get("/sessions")
def my_sessions(request: Request, user: User = Depends(signed_in)) -> list[dict]:
    """Where you are signed in. The one you are using is marked."""
    with session() as s:
        return [auth.session_dict(r, request.state.session_id)
                for r in auth.active_sessions(s, user.id)]


@me_router.delete("/sessions/{session_id}")
def end_session(session_id: int, request: Request,
                user: User = Depends(signed_in)) -> dict:
    with session() as s:
        if not auth.revoke_session(s, user.id, session_id):
            raise HTTPException(404, "No such session.")
        audit.record("auth.session_revoke", db=s, request=request, user=user,
                     target=f"session {session_id}")
    return {"ok": True}


@me_router.post("/sessions/end-others")
def end_other_sessions(request: Request,
                       user: User = Depends(signed_in)) -> dict:
    with session() as s:
        n = auth.revoke_sessions(s, user.id, keep=request.state.session_id)
        if n:
            audit.record("auth.session_revoke", db=s, request=request, user=user,
                         target="all other sessions", detail={"ended": n})
    return {"ended": n}


@me_router.get("/activity")
def my_activity(user: User = Depends(signed_in)) -> list[dict]:
    """Your own recent activity. Seeing a sign-in you did not make is how most
    people find out their password is known to someone else."""
    with session() as s:
        return audit.for_user(s, user.id, limit=25)
