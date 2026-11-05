"""Sign-up, sign-in, one-time codes and your own profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..db.models import User
from ..db.session import session
from ..service import audit, auth, codes, ratelimit
from .deps import (_token, clear_session_cookie, set_session_cookie, signed_in)

router = APIRouter(prefix="/api/auth")
me_router = APIRouter(prefix="/api/me")


Email = Field(max_length=320)
Password = Field(max_length=256)


class SignUp(BaseModel):
    email: str = Email
    apd_id: str = Field(max_length=16)
    password: str = Password


class SignIn(BaseModel):
    email: str = Email
    password: str = Password


class CodeEntry(BaseModel):
    email: str = Email
    code: str = Field(max_length=20)


class Forgot(BaseModel):
    email: str = Email


class NewPassword(BaseModel):
    ticket: str = Field(max_length=100)
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
        "email": "any work email; temporary addresses are refused",
        "apd_format": "APD-1234",
        "min_password": auth.MIN_PASSWORD,
    }


@router.post("/signup")
def signup(body: SignUp, request: Request) -> dict:
    """Create an account and mail the 6-digit code that confirms the address."""
    ip = audit.client_of(request)[0] or "?"
    _too_many(f"signup:{ip}", ratelimit.SIGNUPS, "new accounts from this address")
    ratelimit.hit(f"signup:{ip}", ratelimit.SIGNUPS)
    with session() as s:
        try:
            user = auth.sign_up(s, body.email, body.apd_id, body.password)
        except auth.AuthError as e:
            raise HTTPException(400, str(e))
        codes.send_verification(s, user, first=True)
        out = {"pending": True, "email": user.email, "user": auth.as_dict(user),
               "minutes": codes.ttl_minutes(codes.CODE_TTL),
               "message": f"We have emailed a 6-digit code to {user.email}. "
                          f"Enter it to confirm the address is yours."}
        audit.record("auth.signup", db=s, request=request, user=user,
                     detail={"apd_id": user.apd_id})
    return out


def _wrong_code(request: Request, action: str, email: str) -> HTTPException:
    """Count a wrong code against the address it came from, and log it."""
    ip = audit.client_of(request)[0] or "?"
    ratelimit.hit(f"code:{ip}", ratelimit.CODE_FAILURES)
    audit.record(action, request=request, email=email.strip().lower(),
                 outcome="failure", detail={"reason": "wrong_code"})
    return HTTPException(400, codes.WRONG_CODE)


def _guard_codes(request: Request) -> None:
    ip = audit.client_of(request)[0] or "?"
    _too_many(f"code:{ip}", ratelimit.CODE_FAILURES, "wrong codes from this address")


def _guard_requests(request: Request, what: str) -> None:
    ip = audit.client_of(request)[0] or "?"
    _too_many(f"codereq:{ip}", ratelimit.CODE_REQUESTS, what)
    ratelimit.hit(f"codereq:{ip}", ratelimit.CODE_REQUESTS)


@router.post("/verify-email")
def verify_email(body: CodeEntry, request: Request) -> dict:
    """Confirm a new account's email with the code mailed to it."""
    _guard_codes(request)
    wrong = False
    with session() as s:
        try:
            user = codes.verify_email(s, body.email, body.code)
        except codes.WrongCode:
            wrong = True                # let the session commit the count
        else:
            audit.record("auth.email_verify", db=s, request=request, user=user)
    if wrong:
        raise _wrong_code(request, "auth.email_verify", body.email)
    return {"ok": True,
            "message": "Email confirmed. An admin will now approve your "
                       "account; you can sign in once they have."}


@router.post("/verify-email/resend")
def resend_verification(body: SignIn, request: Request) -> dict:
    """Mail the confirmation code again."""
    _guard_requests(request, "requests from this address")
    with session() as s:
        try:
            user = codes.resend_verification(s, body.email, body.password)
        except codes.TooSoon as e:
            raise HTTPException(429, str(e), headers={"Retry-After": str(e.seconds)})
        if user is not None:
            audit.record("auth.verify_resend", db=s, request=request, user=user)
    return {"ok": True,
            "message": "If that account is waiting for its email to be "
                       "confirmed, a new code is on its way."}


@router.post("/password/forgot")
def forgot_password(body: Forgot, request: Request) -> dict:
    """"Forgot password?" - mail a reset code."""
    _guard_requests(request, "password reset requests from this address")
    with session() as s:
        user = codes.request_reset(s, body.email)
        if user is not None:
            audit.record("auth.password_forgot", db=s, request=request, user=user)
    return {"ok": True, "minutes": codes.ttl_minutes(codes.CODE_TTL),
            "message": "If an account uses that email, we have sent it a "
                       "6-digit code."}


@router.post("/password/verify-code")
def check_reset_code(body: CodeEntry, request: Request) -> dict:
    """A right reset code, exchanged for the ticket the next screen uses to set
    the password - see codes.check_reset_code."""
    _guard_codes(request)
    wrong = False
    with session() as s:
        try:
            user, ticket = codes.check_reset_code(s, body.email, body.code)
        except codes.WrongCode:
            wrong = True                # let the session commit the count
        else:
            audit.record("auth.reset_code", db=s, request=request, user=user)
    if wrong:
        raise _wrong_code(request, "auth.reset_code", body.email)
    return {"ok": True, "ticket": ticket,
            "minutes": codes.ttl_minutes(codes.TICKET_TTL)}


@router.post("/password/reset")
def reset_password(body: NewPassword, request: Request) -> dict:
    """Set the new password."""
    with session() as s:
        try:
            user = codes.complete_reset(s, body.ticket, body.password)
        except auth.AuthError as e:
            raise HTTPException(400, str(e))
        audit.record("auth.password_reset", db=s, request=request, user=user)
    return {"ok": True, "message": "Password changed. Sign in with it now."}


@router.post("/login")
def login(body: SignIn, request: Request, response: Response) -> dict:
    """Sign in."""
    ip, ua = audit.client_of(request)
    _too_many(f"login:{ip}", ratelimit.LOGIN_FAILURES,
              "failed sign-ins from this address")
    refused: auth.LoginRefused | None = None
    with session() as s:
        try:
            user, token = auth.sign_in(s, body.email, body.password,
                                       ip=ip, user_agent=ua)
            out = {"user": auth.as_dict(user)}
        except auth.LoginRefused as e:
            refused = e                 # let the session commit the counters
        else:
            audit.record("auth.login", db=s, request=request, user=user)

    if refused is not None:
        ratelimit.hit(f"login:{ip}", ratelimit.LOGIN_FAILURES)
        audit.record("auth.login", request=request, user=refused.user,
                     email=refused.email, outcome="failure",
                     detail={"reason": refused.reason})
        if refused.locked_now:
            audit.record("auth.locked", request=request, user=refused.user,
                         detail={"minutes": auth.LOCK_MINUTES})
        if refused.reason == "unverified":
            raise HTTPException(401, {"code": "email_unverified",
                                      "message": str(refused)})
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
    """Change your own password."""
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
    """Where you are signed in."""
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
    """Your own recent activity."""
    with session() as s:
        return audit.for_user(s, user.id, limit=25)
