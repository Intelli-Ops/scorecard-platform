"""Database engine, sessions, and commit/rollback hooks."""
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
                pool_pre_ping=True,
                pool_recycle=3600,
                pool_size=10,
                max_overflow=10,
            )
        _engine = create_engine(settings.database_url, **options)
        _Session = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def create_all() -> None:
    """Apply pending migrations and add the activity log trigger."""
    if not settings.migrate_database_url:
        e = engine()
        migrate.upgrade(e)
        migrate.protect_activity_log(e)
        return
    settings.ensure()
    e = create_engine(settings.migrate_database_url, future=True)
    try:
        migrate.upgrade(e)
        migrate.protect_activity_log(e)
    finally:
        e.dispose()


class SchemaOutOfDate(RuntimeError):
    pass


def check_schema() -> None:
    """Refuse to run on a database the migrations have not reached."""
    have, want = migrate.revision(engine()), migrate.head()
    if have != want:
        raise SchemaOutOfDate(
            f"the database is at migration {have or 'none'}, this code needs "
            f"{want}. Run: sudo scorecard-manage upgrade")


def reset() -> None:
    """Forget the cached engine, so a new data directory takes effect."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def after_commit(s: Session, fn: Callable[[], None]) -> None:
    """Run `fn` once `s` has committed - and not at all if it does not."""
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
