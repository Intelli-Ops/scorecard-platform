"""Slowing down guessing, per address.

The account lock stops guessing at ONE account. It does nothing about one
address trying a different account each time, and it hands anyone who knows
an email a way to lock that person out, over and over. Signing up, too, costs
a quarter of a second of password hashing, and anyone can do it.

So each address gets a budget of failures in a window. Kept in memory: the app
is one process (see jobs/worker.py), and a restart forgetting the counts only
ever errs towards letting someone in.
"""
from __future__ import annotations
import threading
import time
from collections import defaultdict, deque

# (how many, in how many seconds)
LOGIN_FAILURES = (20, 15 * 60)       # wrong sign-ins from one address
SIGNUPS = (10, 60 * 60)              # new accounts from one address
PASSWORD_FAILURES = (10, 15 * 60)    # wrong "current password" on one account

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def _live(key: str, window: int, now: float) -> deque:
    q = _hits[key]
    while q and q[0] <= now - window:
        q.popleft()
    return q


def blocked(key: str, rule: tuple[int, int]) -> int:
    """Seconds until `key` may try again, or 0 if it may now."""
    limit, window = rule
    now = time.monotonic()
    with _lock:
        q = _live(key, window, now)
        if len(q) < limit:
            if not q:
                _hits.pop(key, None)       # nothing to remember
            return 0
        return max(1, int(q[0] + window - now) + 1)


def hit(key: str, rule: tuple[int, int]) -> None:
    """Count one attempt against `key`."""
    _limit, window = rule
    now = time.monotonic()
    with _lock:
        _live(key, window, now).append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
