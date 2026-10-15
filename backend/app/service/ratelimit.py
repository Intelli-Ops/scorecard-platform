"""Per-address limits on failed sign-ins, sign-ups and codes."""
from __future__ import annotations
import datetime as dt

from sqlalchemy import delete, func, select

from ..clock import utcnow
from ..db.models import RateHit
from ..db.session import session

LOGIN_FAILURES = (100, 15 * 60)      # wrong sign-ins from one address
SIGNUPS = (10, 60 * 60)              # new accounts from one address
PASSWORD_FAILURES = (10, 15 * 60)    # wrong "current password" on one account
CODE_REQUESTS = (30, 60 * 60)        # codes asked for: "Forgot password?", resend
CODE_FAILURES = (50, 15 * 60)        # wrong codes entered

LONGEST = max(window for _, window in (LOGIN_FAILURES, SIGNUPS, PASSWORD_FAILURES,
                                       CODE_REQUESTS, CODE_FAILURES))


def blocked(key: str, rule: tuple[int, int]) -> int:
    """Seconds until `key` may try again, or 0 if it may now."""
    limit, window = rule
    now = utcnow()
    since = now - dt.timedelta(seconds=window)
    with session() as s:
        count, oldest = s.execute(
            select(func.count(), func.min(RateHit.at))
            .where(RateHit.key == key, RateHit.at > since)).one()
    if count < limit:
        return 0
    return max(1, int((oldest - since).total_seconds()) + 1)


def hit(key: str, rule: tuple[int, int]) -> None:
    """Count one attempt against `key`."""
    _limit, window = rule
    now = utcnow()
    with session() as s:
        s.execute(delete(RateHit).where(
            RateHit.key == key, RateHit.at <= now - dt.timedelta(seconds=window)))
        s.add(RateHit(key=key, at=now))


def clear(key: str) -> None:
    """Forget everything counted against `key` - it got the password right."""
    with session() as s:
        s.execute(delete(RateHit).where(RateHit.key == key))


def clear_prefix(prefix: str) -> None:
    """Forget every key that starts with `prefix` - an admin's unlock, which
    lifts an account's locks from every address at once."""
    with session() as s:
        s.execute(delete(RateHit).where(
            RateHit.key.startswith(prefix, autoescape=True)))


def purge() -> int:
    """Drop every hit too old for any rule to count."""
    with session() as s:
        return s.execute(delete(RateHit).where(
            RateHit.at <= utcnow() - dt.timedelta(seconds=LONGEST))).rowcount
