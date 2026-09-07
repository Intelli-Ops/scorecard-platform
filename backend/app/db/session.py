"""Database connection.

SQLite locally so the project runs with nothing installed; Postgres in
production by setting SCORECARD_DB. SQLAlchemy hides the difference, which is
why the models avoid anything either one lacks.
"""
from __future__ import annotations
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .models import Base

_engine = None
_Session: sessionmaker | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        settings.ensure()
        _engine = create_engine(settings.database_url, future=True)
        _Session = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def create_all() -> None:
    Base.metadata.create_all(engine())


def reset() -> None:
    """Forget the cached engine, so a new data directory takes effect."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


@contextmanager
def session() -> Session:
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
