"""One-time codes: confirming a new account's email, and Forgot password."""
from __future__ import annotations
import datetime as dt
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..clock import utcnow
from ..config import settings
from ..db.models import OneTimeCode, User
from . import emails, mail, ratelimit
from .auth import (AuthError, burn_time, check_password, digest, hash_password,
                   revoke_sessions, verify_password)

CODE_TTL = dt.timedelta(minutes=5)       # a mailed 6-digit code
CODE_TRIES = 5                           # wrong guesses before a code is spent
CODE_GAP = dt.timedelta(seconds=60)      # between two codes to one account
CODES_PER_HOUR = (5, 60 * 60)            # codes of one kind to one account
TICKET_TTL = dt.timedelta(minutes=10)    # to choose the new password, once

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"
RESET_TICKET = "reset_ticket"

WRONG_CODE = ("That code is wrong or has expired. Check the newest email, or "
              "ask for a new code.")


class TooSoon(AuthError):
    """A new code asked for too soon after the last."""

    def __init__(self, seconds: int):
        minutes = round(seconds / 60)
        wait = (f"{seconds} seconds" if seconds < 90
                else f"{minutes} minute{'s' if minutes != 1 else ''}")
        super().__init__(f"A code was sent a moment ago. You can ask for "
                         f"another in {wait}.")
        self.seconds = seconds


class WrongCode(AuthError):
    """A code that did not match."""


def _clean_code(code: str | None) -> str | None:
    """Six digits, however they were typed or pasted ("123 456", "123-456")."""
    digits = re.sub(r"\D", "", code or "")
    return digits if len(digits) == 6 else None


def _live_code(db: DbSession, user: User, purpose: str) -> OneTimeCode | None:
    """The newest code of this kind that can still be used."""
    return db.execute(select(OneTimeCode).where(
        OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose,
        OneTimeCode.used_at.is_(None), OneTimeCode.expires_at > utcnow())
        .order_by(OneTimeCode.id.desc())).scalars().first()


def _issue_code(db: DbSession, user: User, purpose: str, *,
                limit: bool = True) -> str:
    """A new code for `user`, retiring any before it."""
    now = utcnow()
    if limit:
        last = db.execute(select(OneTimeCode.created_at).where(
            OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose)
            .order_by(OneTimeCode.id.desc())).scalars().first()
        if last and now - last < CODE_GAP:
            raise TooSoon(int((CODE_GAP - (now - last)).total_seconds()) + 1)
        key = f"code:{user.id}:{purpose}"
        wait = ratelimit.blocked(key, CODES_PER_HOUR)
        if wait:
            raise TooSoon(wait)
        ratelimit.hit(key, CODES_PER_HOUR)

    for row in db.execute(select(OneTimeCode).where(
            OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose,
            OneTimeCode.used_at.is_(None))).scalars():
        row.used_at = now
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.add(OneTimeCode(user_id=user.id, purpose=purpose,
                       secret=hash_password(code), created_at=now,
                       expires_at=now + CODE_TTL))
    db.flush()
    return code


def _use_code(db: DbSession, user: User | None, purpose: str,
              code: str | None) -> None:
    """Spend `user`'s code if `code` is it - or raise WrongCode, having counted
    the guess."""
    typed = _clean_code(code)
    row = _live_code(db, user, purpose) if user is not None else None
    if row is None or typed is None:
        burn_time(typed or "")
        raise WrongCode(WRONG_CODE)
    if not verify_password(typed, row.secret):
        row.attempts += 1
        if row.attempts >= CODE_TRIES:
            row.used_at = utcnow()            # spent: ask for a new one
        db.flush()
        raise WrongCode(WRONG_CODE)
    row.used_at = utcnow()
    db.flush()


def _account(db: DbSession, email: str | None) -> User | None:
    return db.execute(select(User).where(
        User.email == (email or "").strip().lower())).scalar_one_or_none()


def ttl_minutes(ttl: dt.timedelta) -> int:
    return int(ttl.total_seconds() // 60)


def send_verification(db: DbSession, user: User, *, first: bool = False) -> None:
    """Mail the code that proves the address is theirs."""
    code = _issue_code(db, user, VERIFY_EMAIL, limit=not first)
    m = emails.verify_email(user.email, code, ttl_minutes(CODE_TTL))
    mail.send(user.email, m.subject, m.text, m.html)


def resend_verification(db: DbSession, email: str, password: str) -> User | None:
    """Mail the confirmation code again - to someone who knows the password, so
    it cannot be used to fill a colleague's inbox."""
    user = _account(db, email)
    if user is None:
        burn_time(password or "")
        return None
    if not verify_password(password or "", user.password_hash):
        return None
    if not user.pending or user.email_verified_at:
        return None
    send_verification(db, user)
    return user


def verify_email(db: DbSession, email: str, code: str) -> User:
    """Confirm the address with the code mailed to it."""
    user = _account(db, email)
    if user is not None and (user.email_verified_at or not user.pending):
        user = None                 # nothing to confirm: same answer as wrong
    _use_code(db, user, VERIFY_EMAIL, code)
    user.email_verified_at = utcnow()
    db.flush()
    return user


def request_reset(db: DbSession, email: str) -> User | None:
    """Mail a reset code, if `email` is an account that may have one."""
    user = _account(db, email)
    if user is None or (not user.is_active and not user.pending):
        hash_password("000000")         # as long as issuing a code takes
        return None
    try:
        code = _issue_code(db, user, RESET_PASSWORD)
    except TooSoon:
        hash_password("000000")
        return None
    m = emails.reset_code(user.email, code, ttl_minutes(CODE_TTL))
    mail.send_later(user.email, m.subject, m.text, m.html)
    return user


def check_reset_code(db: DbSession, email: str, code: str) -> tuple[User, str]:
    """A right reset code, exchanged for the ticket that lets the next screen
    set the password."""
    user = _account(db, email)
    _use_code(db, user, RESET_PASSWORD, code)
    secret = secrets.token_urlsafe(32)
    now = utcnow()
    row = OneTimeCode(user_id=user.id, purpose=RESET_TICKET, secret=digest(secret),
                      created_at=now, expires_at=now + TICKET_TTL)
    db.add(row)
    db.flush()
    return user, f"{row.id}.{secret}"


def complete_reset(db: DbSession, ticket: str, new: str) -> User:
    """Set the new password with the ticket a right code was exchanged for."""
    check_password(new)
    row_id, _, secret = (ticket or "").partition(".")
    row = db.get(OneTimeCode, int(row_id)) if row_id.isdigit() else None
    if (row is None or row.purpose != RESET_TICKET or row.used_at is not None
            or row.expires_at < utcnow()
            or not hmac.compare_digest(row.secret, digest(secret))):
        raise AuthError("This reset has expired. Start again with "
                        "\"Forgot password?\".")
    user = row.user
    ratelimit.clear_prefix(f"lock:{user.id}:")      # before this session writes
    row.used_at = utcnow()
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    user.locked_until = None
    user.email_verified_at = user.email_verified_at or utcnow()
    db.flush()
    revoke_sessions(db, user.id)
    m = emails.password_changed(user.email, settings.public_url)
    mail.send_later(user.email, m.subject, m.text, m.html)
    return user


def emergency_reset_code(db: DbSession, user: User) -> str:
    """A reset code for the server's command line to show, rather than mail:
    for when mail itself is what is broken."""
    return _issue_code(db, user, RESET_PASSWORD, limit=False)
