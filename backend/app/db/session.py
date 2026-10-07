"""Database connection.

SQLite locally so the project runs with nothing installed; MySQL on the server
by setting SCORECARD_DB (see config.py). SQLAlchemy hides the difference, which
is why the models avoid anything either one lacks.
"""
from __future__ import annotations
import logging
from contextlib import contextmanager
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from . import migrate

log = logging.getLogger("scorecard.db")

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
    """Bring the database up to date - every migration it has not had (see
    migrate.py) - and add the guard that stops activity log rows being edited."""
    e = engine()
    migrate.upgrade(e)
    migrate.protect_activity_log(e)


def reset() -> None:
    """Forget the cached engine, so a new data directory takes effect."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def after_commit(s: Session, fn: Callable[[], None]) -> None:
    """Run `fn` once `s` has committed - and not at all if it does not.

    For what a database cannot take back: deleting a file. Done inside the
    transaction, a commit that then fails leaves rows pointing at files that
    are gone. Done after, the worst a failure leaves is a file nothing points
    at.
    """
    s.info.setdefault(_AFTER_COMMIT, []).append(fn)


def after_rollback(s: Session, fn: Callable[[], None]) -> None:
    """Run `fn` if `s` is rolled back - to take back a file written for rows
    that were then never saved."""
    s.info.setdefault(_AFTER_ROLLBACK, []).append(fn)


_AFTER_COMMIT, _AFTER_ROLLBACK = "after_commit", "after_rollback"


def _run_hooks(s: Session, which: str) -> None:
    for fn in s.info.pop(which, []):
        try:
            fn()
        except Exception:
            # The transaction is already decided; a clean-up that fails must
            # not turn a saved change into an error, or hide the real one.
            log.exception("%s clean-up failed", which.replace("_", " "))


@contextmanager
def session() -> Session:
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        _run_hooks(s, _AFTER_ROLLBACK)
        raise
    else:
        _run_hooks(s, _AFTER_COMMIT)
    finally:
        s.close()
