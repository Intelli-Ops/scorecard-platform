"""The days off pacing leaves out, as admins keep them on the Holidays screen."""
from __future__ import annotations
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Holiday


def dates(s: Session) -> list[dt.date]:
    return list(s.scalars(select(Holiday.day).order_by(Holiday.day)))


def with_holidays(s: Session, rules: dict) -> dict:
    """`rules` with the holidays as they stand now."""
    rules["holidays"] = dates(s)
    return rules
