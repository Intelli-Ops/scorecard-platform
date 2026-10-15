"""The current time, always in UTC."""
from __future__ import annotations
import datetime as dt


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)
