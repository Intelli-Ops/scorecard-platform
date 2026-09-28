"""Running a build in the background, one at a time.

A run reads 385 MB and takes around a minute cold. A browser request cannot
wait that long, so the request queues the work and returns immediately; the
page polls until the run reaches `review`.

DELIBERATELY ONE AT A TIME. Two concurrent runs would each hold a
quarter-gigabyte spreadsheet in memory, and both would be writing the same
week's cache. Reports go out on different days and a build takes a minute -
there is nothing to gain from running them together, and a machine that falls
over under two uploads is worse than one that finishes them in order.

No Redis, no Celery. Those earn their place when jobs must survive a restart
or spread across machines; here a run that dies with the process can simply be
started again, and its inputs are still in the store. When that stops being
true, the queue swaps out without anything above it changing.
"""
from __future__ import annotations
import datetime as dt
import queue
import threading
import traceback

from sqlalchemy import select

from ..config import settings
from ..db.models import Run
from ..db.session import session
from ..service import runner
from ..storage.files import FileStore

_jobs: queue.Queue = queue.Queue()
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _work() -> None:
    while True:
        run_id, report_key, week, as_of = _jobs.get()
        try:
            with session() as s:
                store = FileStore(settings.object_dir)
                runner.execute(s, store, report_key, week, as_of=as_of,
                               run_id=run_id)
        except Exception as exc:
            # execute() marks the run failed, but in the SAME session - and the
            # exception that follows rolls that session back, "failed" and
            # all. The run was left saying `pending` forever, which also
            # blocked deleting it or its week. So the failure is written again
            # here, in a session of its own that nothing rolls back.
            traceback.print_exc()
            _mark_failed(run_id, f"{type(exc).__name__}: {exc}")
        finally:
            _jobs.task_done()


def _mark_failed(run_id: int, error: str) -> None:
    try:
        with session() as s:
            run = s.get(Run, run_id)
            if run is not None and run.status in ("pending", "running"):
                run.status = "failed"
                run.error = error
                run.finished_at = dt.datetime.now(dt.timezone.utc)
    except Exception:
        traceback.print_exc()


def recover() -> int:
    """Close off builds a previous server process never finished.

    The queue lives in memory, so a restart - a deploy, a reboot, a crash -
    forgets whatever was waiting or under way, and those runs sat at
    `pending` or `running` forever: the page spun, and neither the run nor its
    week could be deleted. Called once at start-up, before the worker takes
    anything new, they are marked failed with a reason a person can act on.

    Assumes one server process, which is how this app runs (one background
    thread, see the module docstring).
    """
    with session() as s:
        stale = s.execute(select(Run).where(
            Run.status.in_(("pending", "running")))).scalars().all()
        for run in stale:
            run.status = "failed"
            run.error = ("Interrupted: the server restarted before this build "
                         "finished. Build it again.")
            run.finished_at = dt.datetime.now(dt.timezone.utc)
        return len(stale)


def start() -> None:
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_work, daemon=True,
                                       name="scorecard-runs")
            _thread.start()


def submit(report_key: str, week: str, as_of: dt.date | None = None) -> int:
    """Queue a build. Returns the run id immediately, before any work starts."""
    start()
    with session() as s:
        run = Run(report_key=report_key, week=week, status="pending",
                  as_of=as_of)
        s.add(run)
        s.flush()
        run_id = run.id
    _jobs.put((run_id, report_key, week, as_of))
    return run_id


def depth() -> int:
    """How many builds are waiting. Shown so nobody wonders if it is stuck."""
    return _jobs.qsize()
