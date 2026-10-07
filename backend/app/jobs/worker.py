"""Running a build in the background, one at a time.

A run reads 385 MB and takes around a minute cold. A browser request cannot
wait that long, so the request queues the work and returns immediately; the
page polls until the run reaches `review`.

THE QUEUE IS THE DATABASE. A build waiting to be made is a `run` row with
status `pending` (written, with the files it will read, by runner.queue), and
this thread takes the oldest one. Nothing about a waiting build lives in this
process's memory, so:

  * a restart loses nothing - the rows are still there and are picked up;
  * a second server process is safe - a run is TAKEN with one UPDATE that
    only one process can win, and the database itself refuses a second build
    of the same report and week (Run.active_key).

ONE AT A TIME, per process. Two concurrent runs would each hold a
quarter-gigabyte spreadsheet in memory. Reports go out on different days and
a build takes a minute - there is nothing to gain from running them together,
and a machine that falls over under two builds is worse than one that
finishes them in order.

No Redis, no Celery: the one table already there does the job.
"""
from __future__ import annotations
import datetime as dt
import logging
import threading

from sqlalchemy import func, or_, select, update

from ..config import settings
from ..db.models import Run
from ..db.session import session
from ..service import runner
from ..storage.files import FileStore

log = logging.getLogger("scorecard.worker")

POLL = 5.0          # seconds between looks at the queue when nothing woke us
BEAT = 15.0         # seconds between heartbeats while building
# A build with no heartbeat for this long has lost its process. Several beats,
# so one slow write to a busy database is not taken for a death.
STALE = dt.timedelta(minutes=2)

_thread: threading.Thread | None = None
_stop: threading.Event | None = None      # the running thread's own
_lock = threading.Lock()
_wake = threading.Event()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _work(stop: threading.Event) -> None:
    last_reap = _now()
    while not stop.is_set():
        try:
            if _now() - last_reap > STALE / 2:
                last_reap = _now()
                recover()
            run_id = _claim()
        except Exception:
            # The database being away for a moment must not end the thread -
            # nothing would ever be built again until a restart.
            log.exception("could not read the build queue")
            run_id = None
        if run_id is None:
            _wake.wait(POLL)
            _wake.clear()
        else:
            _build(run_id)


def _claim() -> int | None:
    """Take the oldest waiting build, or None if there is none.

    Taken with an UPDATE that only matches while the run is still `pending`:
    of two processes that both saw it waiting, the database lets exactly one
    change it, and the other moves on to the next.
    """
    with session() as s:
        waiting = s.execute(select(Run.id).where(Run.status == "pending")
                            .order_by(Run.id).limit(5)).scalars().all()
        for run_id in waiting:
            now = _now()
            won = s.execute(
                update(Run).where(Run.id == run_id, Run.status == "pending")
                .values(status="running", started_at=now, heartbeat_at=now)
            ).rowcount
            if won:
                return run_id
    return None


def _build(run_id: int) -> None:
    """One build, as three short transactions around the long calculation:
    read what it was promised, calculate with no transaction open, record.

    Held in one transaction - as it used to be - the minute of calculating
    kept the run's row locked, so nobody could see it had started and, on
    SQLite, nothing else could write at all until it finished.
    """
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
                # Closed off while it was calculating - see recover().
                raise RuntimeError(f"run {run_id} is no longer this worker's "
                                   f"to finish")
            runner.record(s, run, plan, src, result)
    except BaseException as exc:
        # BaseException, not Exception: the spreadsheet reader and polars are
        # Rust underneath, and when one of them panics on a damaged file the
        # error that arrives here (PanicException) is NOT an Exception. Caught
        # as Exception it went straight past, ended this thread, and left the
        # run saying `running` with nothing alive to build anything else.
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
                          .values(heartbeat_at=_now()))
        except Exception:
            log.exception("could not write the heartbeat of run %s", run_id)


def _mark_failed(run_id: int, error: str) -> None:
    try:
        with session() as s:
            run = s.get(Run, run_id)
            if run is not None and run.status in ("pending", "running"):
                run.status = "failed"
                run.error = error
                run.finished_at = _now()
    except Exception:
        log.exception("could not record that run %s failed", run_id)


def recover() -> int:
    """Close off builds whose process died part-way.

    A run still `running` with no heartbeat for STALE was being built by a
    process that is gone - a crash, a reboot, a deploy - and would otherwise
    sit there forever: the page spins, and neither the run nor its week can
    be deleted or built again. It is marked failed with a reason a person can
    act on.

    ONLY those. A run with a fresh heartbeat belongs to a process that is
    alive - possibly another one - and a `pending` run is simply waiting its
    turn; before the queue was in the database, start-up failed all of them,
    which was only right while there could be no other process.

    Called at start-up and then every so often, so a build orphaned by ANOTHER
    process dying is found too. Returns how many were closed.
    """
    cutoff = _now() - STALE
    with session() as s:
        stale = s.execute(select(Run).where(
            Run.status == "running",
            or_(Run.heartbeat_at.is_(None), Run.heartbeat_at < cutoff)
        )).scalars().all()
        for run in stale:
            run.status = "failed"
            run.error = ("Interrupted: the server stopped before this build "
                         "finished. Build it again.")
            run.finished_at = _now()
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
    """Stop taking builds. One under way is not waited for beyond `timeout`:
    it stops beating with the process and is closed off by recover()."""
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
    """How many builds are waiting in front of this one. Shown so nobody
    wonders if it is stuck."""
    return s.execute(select(func.count()).select_from(Run).where(
        Run.status == "pending", Run.id < run_id)).scalar_one()


def depth() -> int:
    """How many builds are waiting."""
    with session() as s:
        return s.execute(select(func.count()).select_from(Run).where(
            Run.status == "pending")).scalar_one()
