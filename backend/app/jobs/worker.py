"""Background worker that runs queued builds one at a time."""
from __future__ import annotations
import datetime as dt
import logging
import threading

from sqlalchemy import func, or_, select, update

from ..clock import utcnow
from ..config import settings
from ..db.models import ACTIVE, Run
from ..db.session import session
from ..service import runner
from ..storage.files import FileStore

log = logging.getLogger("scorecard.worker")

POLL = 5.0
BEAT = 15.0         # seconds between heartbeats while building
STALE = dt.timedelta(minutes=2)

_thread: threading.Thread | None = None
_stop: threading.Event | None = None      # the running thread's own
_lock = threading.Lock()
_wake = threading.Event()


def _work(stop: threading.Event) -> None:
    last_reap = utcnow()
    while not stop.is_set():
        try:
            if utcnow() - last_reap > STALE / 2:
                last_reap = utcnow()
                recover()
            run_id = _claim()
        except Exception:
            log.exception("could not read the build queue")
            run_id = None
        if run_id is None:
            _wake.wait(POLL)
            _wake.clear()
        else:
            _build(run_id)


def _claim() -> int | None:
    """Take the oldest waiting build, or None if there is none."""
    with session() as s:
        waiting = s.execute(select(Run.id).where(Run.status == "pending")
                            .order_by(Run.id).limit(5)).scalars().all()
        for run_id in waiting:
            now = utcnow()
            won = s.execute(
                update(Run).where(Run.id == run_id, Run.status == "pending")
                .values(status="running", started_at=now, heartbeat_at=now)
            ).rowcount
            if won:
                return run_id
    return None


def _build(run_id: int) -> None:
    """One build, as three short transactions around the long calculation: read
    what it was promised, calculate with no transaction open, record."""
    done = threading.Event()
    beat = threading.Thread(target=_heartbeat, args=(run_id, done), daemon=True,
                            name=f"scorecard-run-{run_id}-heartbeat")
    beat.start()
    try:
        with session() as s:
            plan = runner.plan(FileStore(settings.object_dir), s.get(Run, run_id))
        src, result = runner.compute(plan)
        with session() as s:
            run = s.get(Run, run_id)
            if run is None or run.status != "running":
                raise RuntimeError(f"run {run_id} is no longer this worker's "
                                   f"to finish")
            runner.record(s, run, plan, src, result)
    except BaseException as exc:
        log.exception("run %s failed", run_id)
        _mark_failed(run_id, f"{type(exc).__name__}: {exc}")
    finally:
        done.set()
        beat.join()


def _heartbeat(run_id: int, done: threading.Event) -> None:
    """Say, every few seconds, that this run is still being worked on."""
    while not done.wait(BEAT):
        try:
            with session() as s:
                s.execute(update(Run).where(Run.id == run_id,
                                            Run.status == "running")
                          .values(heartbeat_at=utcnow()))
        except Exception:
            log.exception("could not write the heartbeat of run %s", run_id)


def _mark_failed(run_id: int, error: str) -> None:
    try:
        with session() as s:
            run = s.get(Run, run_id)
            if run is not None and run.status in ACTIVE:
                run.status = "failed"
                run.error = error
                run.finished_at = utcnow()
    except Exception:
        log.exception("could not record that run %s failed", run_id)


def recover() -> int:
    """Close off builds whose process died part-way."""
    cutoff = utcnow() - STALE
    with session() as s:
        stale = s.execute(select(Run).where(
            Run.status == "running",
            or_(Run.heartbeat_at.is_(None), Run.heartbeat_at < cutoff)
        )).scalars().all()
        for run in stale:
            run.status = "failed"
            run.error = ("Interrupted: the server stopped before this build "
                         "finished. Build it again.")
            run.finished_at = utcnow()
        return len(stale)


def start() -> None:
    global _thread, _stop
    with _lock:
        if _thread is None or not _thread.is_alive():
            _stop = threading.Event()
            _thread = threading.Thread(target=_work, args=(_stop,), daemon=True,
                                       name="scorecard-runs")
            _thread.start()


def stop(timeout: float = 5.0) -> None:
    """Stop taking builds."""
    global _thread, _stop
    with _lock:
        if _thread is None:
            return
        _stop.set()
        _wake.set()
        _thread.join(timeout)
        _thread, _stop = None, None


def wake() -> None:
    """A build was just queued - look now rather than at the next poll."""
    _wake.set()


def alive() -> bool:
    return _thread is not None and _thread.is_alive()


def ahead(s, run_id: int) -> int:
    """How many builds are waiting in front of this one."""
    return s.execute(select(func.count()).select_from(Run).where(
        Run.status == "pending", Run.id < run_id)).scalar_one()


def depth() -> int:
    """How many builds are waiting."""
    with session() as s:
        return s.execute(select(func.count()).select_from(Run).where(
            Run.status == "pending")).scalar_one()
