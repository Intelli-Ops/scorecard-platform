"""Accounts: signing up, signing in, and staying signed in.

The two company rules live here, not in the browser. A form can be bypassed by
anyone who opens the developer console; the API cannot.

  * the email must end @appedology.com
  * the APD id is APD- followed by exactly four digits

Passwords are never stored. What is stored is a PBKDF2-HMAC-SHA256 hash with a
fresh 16-byte random salt per user, at 240,000 iterations - deliberately slow,
so that guessing at scale costs real time. Standard library only; no dependency
to keep patched.
"""
from __future__ import annotations
from dataclasses import dataclass
import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db.models import Session, User

EMAIL_DOMAIN = "@appedology.com"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@appedology\.com$", re.IGNORECASE)
APD_RE = re.compile(r"^APD-\d{4}$")

MIN_PASSWORD = 8
ITERATIONS = 240_000
SESSION_DAYS = 14


class AuthError(Exception):
    """Something the person can fix, with wording safe to show them."""


@dataclass(frozen=True)
class Credentials:
    email: str
    apd_id: str
    password: str


# ------------------------------------------------------------------ validation

def clean_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not email:
        raise AuthError("Enter your work email address.")
    if not EMAIL_RE.match(email):
        raise AuthError(f"Use your Appedology email - it must end {EMAIL_DOMAIN}.")
    return email


def clean_apd(raw: str) -> str:
    """APD-1234. Upper-cased, and a bare 1234 is accepted and completed.

    People type what is on their badge, and half of them will leave the prefix
    off. Rejecting that teaches nothing; completing it is unambiguous, because
    four digits can only mean one thing here.
    """
    apd = (raw or "").strip().upper().replace(" ", "")
    if re.fullmatch(r"\d{4}", apd):
        apd = f"APD-{apd}"
    if not APD_RE.match(apd):
        raise AuthError("The APD ID looks like APD-1234 - four digits.")
    return apd


def check_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD} characters.")
    return password


# ------------------------------------------------------------------ hashing

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 _unb64(salt_b64), int(iterations))
    except (ValueError, TypeError):
        return False
    # Constant-time: a comparison that returns early leaks how much matched.
    return hmac.compare_digest(dk, _unb64(hash_b64))


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


# ------------------------------------------------------------------ accounts

def sign_up(db: DbSession, email: str, apd_id: str, password: str) -> User:
    email = clean_email(email)
    apd_id = clean_apd(apd_id)
    check_password(password)

    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise AuthError("That email already has an account. Sign in instead.")
    if db.execute(select(User).where(User.apd_id == apd_id)).scalar_one_or_none():
        raise AuthError(f"{apd_id} is already registered to another account.")

    user = User(email=email, apd_id=apd_id, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user


def sign_in(db: DbSession, email: str, password: str) -> tuple[User, str]:
    """Returns the user and a session token.

    One message for a wrong email and a wrong password alike. Saying which was
    wrong tells someone who is guessing which addresses have accounts.
    """
    lookup = (email or "").strip().lower()
    user = db.execute(select(User).where(User.email == lookup)).scalar_one_or_none()

    if user is None or not verify_password(password or "", user.password_hash):
        raise AuthError("That email and password do not match.")
    if not user.is_active:
        raise AuthError("This account has been disabled.")

    user.last_login_at = dt.datetime.now(dt.timezone.utc)
    return user, start_session(db, user)


# ------------------------------------------------------------------ sessions

def start_session(db: DbSession, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Session(
        token=token, user_id=user.id,
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=SESSION_DAYS)))
    db.flush()
    return token


def user_for_token(db: DbSession, token: str | None) -> User | None:
    if not token:
        return None
    row = db.execute(select(Session).where(Session.token == token)).scalar_one_or_none()
    if row is None or row.revoked:
        return None

    expires = row.expires_at
    if expires.tzinfo is None:                  # SQLite hands back naive datetimes
        expires = expires.replace(tzinfo=dt.timezone.utc)
    if expires < dt.datetime.now(dt.timezone.utc):
        return None

    return row.user if row.user and row.user.is_active else None


def sign_out(db: DbSession, token: str | None) -> None:
    if not token:
        return
    row = db.execute(select(Session).where(Session.token == token)).scalar_one_or_none()
    if row is not None:
        row.revoked = True
        db.flush()


def as_dict(user: User) -> dict:
    return {"id": user.id, "email": user.email, "apd_id": user.apd_id,
            "name": user.name, "created_at": user.created_at,
            "last_login_at": user.last_login_at}
