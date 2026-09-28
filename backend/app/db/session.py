"""Database connection.

SQLite locally so the project runs with nothing installed; MySQL on the server
by setting SCORECARD_DB (see config.py). SQLAlchemy hides the difference, which
is why the models avoid anything either one lacks.
"""
from __future__ import annotations
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .models import Base
from . import migrate

_engine = None
_Session: sessionmaker | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        settings.ensure()
        options = {"future": True}
        if settings.database_url.startswith("mysql"):
            options.update(
                # MySQL closes a connection that has sat idle for eight hours
                # (wait_timeout). Without these the first request of the
                # morning fails with "MySQL server has gone away".
                pool_pre_ping=True,
                pool_recycle=3600,
                pool_size=10,
                max_overflow=10,
            )
        _engine = create_engine(settings.database_url, **options)
        _Session = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def create_all() -> None:
    """Make the database match the models: new tables, new columns, and the
    guard that keeps the activity log append-only."""
    e = engine()
    Base.metadata.create_all(e)
    migrate.add_missing_columns(e, Base.metadata)
    migrate.upgrade_roles(e)
    migrate.protect_activity_log(e)


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
