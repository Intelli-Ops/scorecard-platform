"""Sign up, sign in, sign out.

Open routes - they are how someone gets a token in the first place. Everything
else requires one.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..db.session import session
from ..service import auth
from .deps import _token, current_user
from fastapi import Depends

router = APIRouter(prefix="/api/auth")


class SignUp(BaseModel):
    email: str
    apd_id: str
    password: str


class SignIn(BaseModel):
    email: str
    password: str


@router.get("/rules")
def rules() -> dict:
    """What the sign-up form should tell people before they get it wrong."""
    return {
        "email_domain": auth.EMAIL_DOMAIN,
        "apd_format": "APD-1234",
        "min_password": auth.MIN_PASSWORD,
    }


@router.post("/signup")
def signup(body: SignUp) -> dict:
    with session() as s:
        try:
            user = auth.sign_up(s, body.email, body.apd_id, body.password)
            token = auth.start_session(s, user)      # signed in straight away
            return {"token": token, "user": auth.as_dict(user)}
        except auth.AuthError as e:
            raise HTTPException(400, str(e))


@router.post("/login")
def login(body: SignIn) -> dict:
    with session() as s:
        try:
            user, token = auth.sign_in(s, body.email, body.password)
            return {"token": token, "user": auth.as_dict(user)}
        except auth.AuthError as e:
            raise HTTPException(401, str(e))


@router.post("/logout")
def logout(authorization: str | None = Header(default=None)) -> dict:
    with session() as s:
        auth.sign_out(s, _token(authorization))
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)) -> dict:
    return auth.as_dict(user)
