"""Slowing down guessing, per address.

The account lock stops guessing at ONE account. It does nothing about one
address trying a different account each time, and it hands anyone who knows
an email a way to lock that person out, over and over. Signing up, too, costs
a quarter of a second of password hashing, and anyone can do it.

So each address gets a budget of failures in a window. The counts are rows in
the database (RateHit), not a dict in the server's memory: held in memory, a
restart handed everyone a fresh budget, and each server process kept a count
of its own - two processes, twice the guesses.
"""
from __future__ import annotations
import datetime as dt

from sqlalchemy import delete, func, select

from ..db.models import RateHit
from ..db.session import session

# (how many, in how many seconds)
LOGIN_FAILURES = (20, 15 * 60)       # wrong sign-ins from one address
SIGNUPS = (10, 60 * 60)              # new accounts from one address
PASSWORD_FAILURES = (10, 15 * 60)    # wrong "current password" on one account

LONGEST = max(window for _, window in (LOGIN_FAILURES, SIGNUPS, PASSWORD_FAILURES))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def blocked(key: str, rule: tuple[int, int]) -> int:
    """Seconds until `key` may try again, or 0 if it may now."""
    limit, window = rule
    now = _now()
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
    now = _now()
    with session() as s:
        # This key's spent hits go as the new one arrives, so the table holds
        # only what is still being counted.
        s.execute(delete(RateHit).where(
            RateHit.key == key, RateHit.at <= now - dt.timedelta(seconds=window)))
        s.add(RateHit(key=key, at=now))


def purge() -> int:
    """Drop every hit too old for any rule to count. Run at start-up: a key
    that is never hit again would otherwise keep its last rows forever."""
    with session() as s:
        return s.execute(delete(RateHit).where(
            RateHit.at <= _now() - dt.timedelta(seconds=LONGEST))).rowcount
