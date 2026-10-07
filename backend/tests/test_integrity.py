"""What the code review asked for: that nothing here depends on luck.

Each test is one way the app used to be able to end up inconsistent - a file
gone but its row still there, a build that read files nobody asked it to, an
action with no record of who took it, a rule that only held while there was
exactly one server process - and checks that it no longer can.

No real spreadsheets: the calculation is replaced by a stand-in, because
these are about what happens AROUND a build. The arithmetic is the golden
master's job.
"""
from __future__ import annotations
import datetime as dt
import time

import polars as pl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import session as db_session
from tests.accounts import PASSWORD, account, make_account

WEEK = "2026-W38"


@pytest.fixture
def client(tmp_path):
    settings.use(tmp_path / "data")
    db_session.reset()
    from app.db.session import create_all
    create_all()
    from app.main import app
    with TestClient(app) as c:
        c.headers.update(account(c, "tester@appedology.com", "APD-0001",
                                 role="admin"))
        yield c


def upload(client, name, body=b"stand-in", for_report=None, week=WEEK):
    r = client.post(f"/api/weeks/{week}/uploads",
                    files=[("files", (name, body, "application/octet-stream"))],
                    data={"for_report": for_report} if for_report else {})
    assert r.status_code == 200 and r.json()["accepted"], r.text
    return r.json()["accepted"][0]["sha256"]


def upload_everything(client, report="gfs", week=WEEK) -> dict[str, str]:
    """Every file `report` needs, each with bytes of its own. Returns the
    hash stored for each source."""
    from app.reports import CASE_AR_KEYS, REPORTS
    return {spec.key: upload(client, " ".join(spec.fragments) + spec.exts[0],
                             body=f"first {spec.key}".encode(), week=week,
                             for_report=report if spec.key in CASE_AR_KEYS else None)
            for spec in REPORTS[report].sources if spec.required}


class _Read:
    def __init__(self, source_key):
        self.source_key, self.rows, self.seconds = source_key, 7, 0.01


class _Result:
    seconds = 0.5
    notes: list = []

    def __init__(self):
        self.tables = {"raw_data": pl.DataFrame({"CASEID": ["1", "2", "3"]})}


@pytest.fixture
def stand_in_pipeline(monkeypatch):
    """A build that calculates nothing, and remembers which files it was
    handed - {source_key: the stored file's name, which is its hash}."""
    from app.service import runner
    seen: dict[str, str] = {}

    def read(sources, rules, cache):
        seen.update({k: p.stem for k, p in sources.found.items()})

        class Src:
            reads = [_Read(k) for k in sources.found]
        return Src()

    monkeypatch.setattr(runner, "_load", lambda key: (
        read, lambda src, rules, as_of=None, week=None: _Result()))
    monkeypatch.setattr(runner, "all_figures", lambda result: {"kpi": [{"a": 1}]})
    return seen


def _wait(client, run_id, timeout=20.0) -> dict:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["run"]["status"] not in ("pending", "running"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish: {body}")


def _run(status="review", week=WEEK, report="gfs", **more) -> int:
    from app.db.models import Run
    from app.db.session import session
    with session() as s:
        run = Run(report_key=report, week=week, status=status, **more)
        s.add(run)
        s.flush()
        return run.id


def _status(run_id) -> str:
    from app.db.models import Run
    from app.db.session import session
    with session() as s:
        return s.get(Run, run_id).status


def log(action=None):
    from app.db.models import ActivityLog
    from app.db.session import session
    with session() as s:
        stmt = select(ActivityLog).order_by(ActivityLog.id)
        if action:
            stmt = stmt.where(ActivityLog.action == action)
        return s.execute(stmt).scalars().all()


# ------------------------------------------------- a build reads what it was promised

def test_a_build_runs_from_the_queue_and_records_what_it_read(client, stand_in_pipeline):
    hashes = upload_everything(client)
    r = client.post(f"/api/runs?report=gfs&week={WEEK}")
    assert r.status_code == 200 and r.json()["queued_ahead"] == 0

    review = _wait(client, r.json()["run_id"])
    assert review["run"]["status"] == "review", review["run"]["error"]
    assert review["run"]["as_of"] == settings.today().isoformat()
    assert {i["sha256"] for i in review["inputs"]} == set(hashes.values())
    assert all(i["rows_read"] == 7 for i in review["inputs"])
    assert review["tables"][0]["name"] == "raw_data"
    assert stand_in_pipeline == hashes
    assert [r.action for r in log() if r.action.startswith("run.")] == [
        "run.start", "run.view"]


def test_a_queued_build_reads_the_files_it_was_queued_with(client, stand_in_pipeline):
    """A file replaced while the build waited went into a build that had been
    asked for before the replacement existed."""
    from app.db.models import Run
    from app.db.session import session
    from app.jobs import worker
    from app.service import runner
    worker.stop()                      # the build waits; nothing takes it yet
    hashes = upload_everything(client)
    run_id = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]

    corrected = upload(client, "supporting file.xlsx", body=b"a corrected copy")
    assert corrected != hashes["supporting"]

    assert worker._claim() == run_id
    worker._build(run_id)
    assert _status(run_id) == "review"
    assert stand_in_pipeline["supporting"] == hashes["supporting"]

    # ...and the next build, queued after the correction, reads the new one.
    with session() as s:
        again = runner.queue(s, "gfs", WEEK)
        s.flush()
        used = {ri.upload.source_key: ri.upload.sha256 for ri in again.inputs}
        s.get(Run, again.id).status = "failed"
    assert used["supporting"] == corrected


def test_files_a_queued_build_will_read_cannot_be_deleted_under_it(client):
    from app.jobs import worker
    worker.stop()
    upload_everything(client)
    client.post(f"/api/runs?report=gfs&week={WEEK}")
    r = client.delete(f"/api/weeks/{WEEK}")
    assert r.status_code == 409 and "still has a build" in r.json()["detail"]
    assert len(list(settings.object_dir.rglob("*.xlsx"))) == 7


# ------------------------------------------------- the golden master's reference

def test_an_approved_build_can_be_kept_as_the_reference(client, stand_in_pipeline,
                                                       tmp_path):
    """What tests/golden compares against: the files an approved run read and
    what it produced, copied somewhere new uploads never touch."""
    from app.db.models import Run
    from app.db.session import session
    from app.service import golden, runner
    hashes = upload_everything(client)
    run_id = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]
    assert _wait(client, run_id)["run"]["status"] == "review"
    kept = tmp_path / "golden"

    with session() as s:
        with pytest.raises(ValueError, match="not approved"):
            golden.save(s.get(Run, run_id), kept)
    assert golden.load("gfs", kept) is None

    client.post(f"/api/runs/{run_id}/approve")
    with session() as s:
        golden.save(s.get(Run, run_id), kept)

    # The week can now be deleted from the app; the reference stands alone.
    assert client.delete(f"/api/weeks/{WEEK}").status_code == 200
    ref = golden.load("gfs", kept)
    assert ref.meta["week"] == WEEK and ref.meta["run_id"] == run_id
    assert {i["source_key"]: i["sha256"] for i in ref.meta["inputs"]} == hashes
    assert all(i["rows_read"] == 7 for i in ref.meta["inputs"])
    assert ref.meta["figures"] == {"kpi": [{"a": 1}]}

    stand_in_pipeline.clear()
    _, result = runner.compute(ref.plan())
    assert stand_in_pipeline == hashes               # read from the kept copies
    assert result.tables["raw_data"].equals(pl.read_parquet(ref.tables["raw_data"]))


def test_saving_a_new_reference_drops_the_files_only_the_old_one_needed(
        client, stand_in_pipeline, tmp_path):
    from app.db.models import Run
    from app.db.session import session
    from app.service import golden
    kept = tmp_path / "golden"

    def approved_build():
        run_id = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]
        _wait(client, run_id)
        client.post(f"/api/runs/{run_id}/approve")
        with session() as s:
            golden.save(s.get(Run, run_id), kept)

    first = upload_everything(client)
    approved_build()
    corrected = upload(client, "supporting file.xlsx", body=b"a corrected copy")
    approved_build()

    have = {p.stem for p in (kept / "objects").rglob("*") if p.is_file()}
    assert corrected in have and first["supporting"] not in have
    assert len(have) == len(first)


# ------------------------------------------------- the queue is the database

def test_a_waiting_build_survives_a_restart(client, stand_in_pipeline):
    """The queue was a list in the server's memory; start-up used to mark
    every waiting build failed, because it had nothing left to run them from."""
    from app.jobs import worker
    worker.stop()
    upload_everything(client)
    run_id = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]

    with TestClient(client.app):                    # the server starts again
        assert _wait(client, run_id)["run"]["status"] == "review"


def test_only_a_build_whose_process_died_is_closed_off(client):
    """Start-up failed every unfinished build - including, with a second
    server process, the one the other process was in the middle of."""
    from app.jobs import worker
    worker.stop()
    now = dt.datetime.now(dt.timezone.utc)
    alive = _run("running", week="2026-W36", heartbeat_at=now)
    waiting = _run("pending", week="2026-W37")
    dead = _run("running", heartbeat_at=now - worker.STALE - dt.timedelta(seconds=1))

    assert worker.recover() == 1
    assert (_status(alive), _status(waiting), _status(dead)) == (
        "running", "pending", "failed")


def test_a_build_is_taken_by_exactly_one_worker(client):
    from app.jobs import worker
    worker.stop()
    first, second = _run("pending", week="2026-W36"), _run("pending", week="2026-W37")
    assert worker._claim() == first          # oldest first
    assert worker._claim() == second         # never the same one twice
    assert worker._claim() is None
    assert _status(first) == "running"


def test_the_database_itself_refuses_a_second_build_of_a_week(client):
    """A lock in one process stopped two presses in that process. This holds
    in any process, because it is the database saying no."""
    from app.db.models import Run
    from app.db.session import session
    _run("pending")
    with pytest.raises(IntegrityError):
        _run("running")
    _run("pending", report="all_providers")          # another report is fine

    with session() as s:
        for run in s.execute(select(Run)).scalars():
            run.status = "failed"
    _run("pending")                                  # and the week is free again


def test_two_presses_at_once_get_one_build_and_one_refusal(client, monkeypatch):
    """Both found nothing building; the second is refused on the way in."""
    import app.api.run_routes as routes
    from app.jobs import worker
    worker.stop()
    upload_everything(client)
    monkeypatch.setattr(routes, "_building", lambda s, report, week: None)
    assert client.post(f"/api/runs?report=gfs&week={WEEK}").status_code == 200
    r = client.post(f"/api/runs?report=gfs&week={WEEK}")
    assert r.status_code == 409 and "already being built" in r.json()["detail"]["message"]
    assert len(log("run.start")) == 1


# ------------------------------------------------- files and rows stay in step

def test_a_delete_that_does_not_commit_removes_no_file(client):
    """The files went first, inside the transaction. When the commit then
    failed the rows came back - pointing at files that were gone."""
    from app.db.models import Run, RunInput, RunTable, Upload
    from app.db.session import session
    from app.service import runner
    from app.storage.files import FileStore

    sha = upload(client, "Supporting File.xlsx")
    result = settings.results_dir / "aa" / ("a" * 64 + ".parquet")
    result.parent.mkdir(parents=True)
    result.write_bytes(b"pretend parquet")
    with session() as s:
        run = Run(report_key="gfs", week=WEEK, status="review")
        s.add(run)
        s.flush()
        s.add(RunTable(run_id=run.id, name="raw_data", rows=1, columns=1,
                       sha256="a" * 64, bytes=1))
        s.add(RunInput(run_id=run.id,
                       upload_id=s.execute(select(Upload.id)).scalar_one()))
        run_id = run.id
    blob = FileStore(settings.object_dir).path(sha, ".xlsx")

    with pytest.raises(RuntimeError, match="the commit failed"):
        with session() as s:
            out = runner.delete(s, s.get(Run, run_id))
            assert (out["files_removed"], out["upload_files_removed"]) == (1, 1)
            raise RuntimeError("the commit failed")
    assert _status(run_id) == "review"
    assert blob.exists() and result.exists()

    assert client.delete(f"/api/runs/{run_id}").status_code == 200
    assert not blob.exists() and not result.exists()


def test_an_upload_that_is_not_saved_leaves_no_file_behind(client):
    from app.db.session import session
    from app.service.ingest import ingest
    from app.storage.files import FileStore

    src = settings.data_dir / "Supporting File.xlsx"
    src.write_bytes(b"never recorded")
    with pytest.raises(RuntimeError):
        with session() as s:
            ingest(s, FileStore(settings.object_dir), WEEK, [src])
            assert list(settings.object_dir.rglob("*.xlsx"))
            raise RuntimeError("the database went away")
    assert not list(settings.object_dir.rglob("*.xlsx"))


def test_a_failed_save_does_not_take_a_file_another_row_names(client):
    """Identical bytes are stored once. Rolling back the second upload of
    them must not remove the file the first upload's row points at."""
    from app.db.session import session
    from app.service.ingest import ingest
    from app.storage.files import FileStore

    upload(client, "Supporting File.xlsx", body=b"the same bytes")
    src = settings.data_dir / "Supporting File.xlsx"
    src.write_bytes(b"the same bytes")
    with pytest.raises(RuntimeError):
        with session() as s:
            ingest(s, FileStore(settings.object_dir), "2026-W39", [src])
            raise RuntimeError("the database went away")
    assert len(list(settings.object_dir.rglob("*.xlsx"))) == 1


def test_a_build_that_cannot_be_recorded_leaves_no_result_behind(client, stand_in_pipeline,
                                                               monkeypatch):
    from app.jobs import worker
    from app.service import runner
    worker.stop()
    upload_everything(client)
    run_id = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]

    def figures(result):
        raise RuntimeError("could not flatten the figures")
    monkeypatch.setattr(runner, "all_figures", figures)
    assert worker._claim() == run_id
    worker._build(run_id)

    assert _status(run_id) == "failed"
    assert not list(settings.results_dir.rglob("*.parquet"))


def test_files_nothing_names_can_be_found_and_removed(client, capsys):
    """What a killed process can still leave: a file written, its row never
    saved. Nothing in the database knows to look for it."""
    import os
    from app import manage
    from app.storage.files import FileStore
    sha = upload(client, "Supporting File.xlsx")
    named = FileStore(settings.object_dir).path(sha, ".xlsx")
    old = settings.object_dir / "bb" / ("b" * 64 + ".xlsx")
    new = settings.results_dir / "cc" / ("c" * 64 + ".parquet")
    for path in (old, new):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"left behind")
    long_ago = time.time() - 2 * 3600
    os.utime(old, (long_ago, long_ago))
    os.utime(named, (long_ago, long_ago))

    manage.main(["clean-files"])
    assert old.exists() and "1 file(s)" in capsys.readouterr().out   # only lists
    manage.main(["clean-files", "--delete"])
    assert not old.exists()
    assert named.exists()            # a row names it
    assert new.exists()              # too recent to be sure of


# ------------------------------------------------- no record, no action

@pytest.fixture
def broken_log(client):
    """The activity log refuses every new row, as a full disk or a lost
    privilege would make it."""
    from app.db.session import engine
    with engine().begin() as c:
        c.execute(text("CREATE TRIGGER activity_log_down BEFORE INSERT ON "
                       "activity_log BEGIN SELECT RAISE(ABORT, 'not writable'); END"))


def test_an_action_that_cannot_be_logged_does_not_happen(client, broken_log):
    """The log used to fail open: the approval went through and the missing
    row was only mentioned in the server's own output."""
    run_id = _run("review")
    r = client.post(f"/api/runs/{run_id}/approve")
    assert r.status_code == 503 and "activity log" in r.json()["detail"]
    assert _status(run_id) == "review"

    assert client.delete(f"/api/runs/{run_id}").status_code == 503
    assert _status(run_id) == "review"


def test_a_sign_in_that_cannot_be_logged_opens_no_session(client, broken_log):
    from app.db.models import Session
    from app.db.session import session
    make_account("someone@appedology.com", "APD-0002")
    with session() as s:
        before = len(s.execute(select(Session)).scalars().all())
    r = client.post("/api/auth/login", json={"email": "someone@appedology.com",
                                             "password": PASSWORD})
    assert r.status_code == 503
    with session() as s:
        assert len(s.execute(select(Session)).scalars().all()) == before


def test_an_export_that_cannot_be_logged_hands_over_nothing(client, broken_log, tmp_path):
    from app.db.models import RunTable
    from app.db.session import session
    from app.storage.files import FileStore
    p = tmp_path / "raw_data.parquet"
    pl.DataFrame({"CASEID": ["1"]}).write_parquet(p)
    stored = FileStore(settings.results_dir).put(p)
    run_id = _run("review")
    with session() as s:
        s.add(RunTable(run_id=run_id, name="raw_data", rows=1, columns=1,
                       sha256=stored.sha256, bytes=stored.size))
    r = client.get(f"/api/runs/{run_id}/tables/raw_data/csv")
    assert r.status_code == 503 and "CASEID" not in r.text


def test_the_change_and_its_log_row_are_saved_together(client, monkeypatch):
    """They were two commits: the change, then the row. Here the change fails
    AFTER the row was written, and the row goes with it."""
    import app.api.run_routes as routes
    run_id = _run("review")

    real = routes.audit.record

    def record_then_fail(action, **kw):
        real(action, **kw)
        raise RuntimeError("the request died before it could commit")
    monkeypatch.setattr(routes.audit, "record", record_then_fail)

    with pytest.raises(RuntimeError):
        client.post(f"/api/runs/{run_id}/approve")
    assert _status(run_id) == "review" and log("run.approve") == []


# ------------------------------------------------- limits that survive a restart

def test_the_sign_in_limit_is_not_reset_by_a_restart(client, monkeypatch):
    """The counts were a dict in the server's memory, so a restart - or a
    second server process - handed out a fresh budget of guesses."""
    from app.service import ratelimit
    monkeypatch.setattr(ratelimit, "LOGIN_FAILURES", (6, 15 * 60))
    limit, _ = ratelimit.LOGIN_FAILURES

    def guess(c):
        return c.post("/api/auth/login", json={"email": "nobody@appedology.com",
                                               "password": "x" * 8})
    for _ in range(limit):
        assert guess(client).status_code == 401
    assert guess(client).status_code == 429

    with TestClient(client.app) as restarted:
        assert guess(restarted).status_code == 429


def test_old_attempts_stop_counting(client):
    from app.db.models import RateHit
    from app.db.session import session
    from app.service import ratelimit
    limit, window = ratelimit.SIGNUPS
    long_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=window + 5)
    with session() as s:
        s.add_all(RateHit(key="signup:1.2.3.4", at=long_ago) for _ in range(limit))
    assert ratelimit.blocked("signup:1.2.3.4", ratelimit.SIGNUPS) == 0

    for _ in range(limit):
        ratelimit.hit("signup:1.2.3.4", ratelimit.SIGNUPS)
    wait = ratelimit.blocked("signup:1.2.3.4", ratelimit.SIGNUPS)
    assert window - 5 <= wait <= window + 1
    with session() as s:        # and the spent ones were cleared on the way
        assert len(s.execute(select(RateHit)).scalars().all()) == limit


# ------------------------------------------------- a health check that checks

@pytest.fixture
def on_the_server(client, monkeypatch):
    """A client asking from the server itself, the way the installer and a
    monitor do - and with no remembered answer, so each test sees its own."""
    import app.main as main
    monkeypatch.setattr(main, "HEALTH_TTL", 0)
    return TestClient(client.app, client=("127.0.0.1", 50000))


def test_health_reports_each_thing_it_depends_on(on_the_server):
    body = on_the_server.get("/api/health").json()
    assert body == {"ok": True, "queued_builds": 0,
                    "checks": {"database": True, "storage": True,
                               "disk_space": True, "worker": True}}


def test_health_fails_when_the_disk_is_nearly_full(on_the_server, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "MIN_FREE_MB", 10 ** 12)
    r = on_the_server.get("/api/health")
    assert r.status_code == 503
    assert r.json()["ok"] is False and r.json()["checks"]["disk_space"] is False


def test_health_fails_when_the_worker_has_stopped(on_the_server):
    from app.jobs import worker
    worker.stop()
    r = on_the_server.get("/api/health")
    assert r.status_code == 503 and r.json()["checks"]["worker"] is False


def test_health_fails_on_a_database_this_code_has_not_migrated(on_the_server):
    from app.db.session import engine
    with engine().begin() as c:
        c.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    r = on_the_server.get("/api/health")
    assert r.status_code == 503 and r.json()["checks"]["database"] is False


def test_health_tells_a_stranger_only_whether_it_is_healthy(client, on_the_server,
                                                          monkeypatch):
    """Anyone can ask. Only someone on the server is told WHAT is wrong."""
    import app.main as main
    assert client.get("/api/health").json() == {"ok": True}
    monkeypatch.setattr(main, "MIN_FREE_MB", 10 ** 12)
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json() == {"ok": False}


def test_health_is_not_worked_out_afresh_for_every_caller(client, monkeypatch):
    """It reads the database and writes to the disk, and needs no sign-in:
    asked a thousand times a second, it must not do that a thousand times."""
    import app.main as main
    calls = []
    monkeypatch.setattr(main, "_storage_ok", lambda: calls.append(1) or True)
    for _ in range(25):
        assert client.get("/api/health").status_code == 200
    assert len(calls) <= 1


# ------------------------------------------------- the second audit

def test_a_crash_inside_the_calculation_does_not_kill_the_worker(client,
                                                                stand_in_pipeline,
                                                                monkeypatch):
    """A damaged spreadsheet can make the reader PANIC, which is not an
    ordinary error. It went past the worker's `except`, ended its thread, and
    left the run `running` and every later build waiting for ever."""
    import polars.exceptions
    from app.jobs import worker
    from app.service import runner
    real = runner.compute

    def panic(plan, cache=None):
        raise polars.exceptions.PanicException("index out of bounds")
    monkeypatch.setattr(runner, "compute", panic)
    upload_everything(client)
    first = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]
    body = _wait(client, first)
    assert body["run"]["status"] == "failed"
    assert "PanicException" in body["run"]["error"]
    assert worker.alive()

    monkeypatch.setattr(runner, "compute", real)     # and the next one builds
    second = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]
    assert _wait(client, second)["run"]["status"] == "review"


def _run_with_table(rows: int, tmp_path) -> int:
    from app.db.models import RunTable
    from app.db.session import session
    from app.storage.files import FileStore
    p = tmp_path / "raw_data.parquet"
    pl.DataFrame({"CASEID": [f"C{i}" for i in range(rows)],
                  "Group": ["A" if i % 2 else "B" for i in range(rows)],
                  "Paid": [float(i) for i in range(rows)]}).write_parquet(p)
    stored = FileStore(settings.results_dir).put(p)
    run_id = _run("review")
    with session() as s:
        s.add(RunTable(run_id=run_id, name="raw_data", rows=rows, columns=3,
                       sha256=stored.sha256, bytes=stored.size))
    return run_id


def test_a_table_is_exported_in_pieces_and_arrives_whole(client, tmp_path,
                                                        monkeypatch):
    """The whole table, and then the whole CSV, used to sit in the server's
    memory for every export. Now only a piece at a time does."""
    from app.service import runner
    monkeypatch.setattr(runner, "TABLE_CHUNK", 100)
    run_id = _run_with_table(250, tmp_path)
    seen = []
    import app.api.run_routes as routes
    frame = routes.csvsafe.frame
    monkeypatch.setattr(routes.csvsafe, "frame",
                        lambda df: seen.append(df.height) or frame(df))

    r = client.get(f"/api/runs/{run_id}/tables/raw_data/csv")
    lines = r.text.splitlines()
    assert r.headers["X-Row-Count"] == "250"
    assert lines[0] == "CASEID,Group,Paid" and len(lines) == 251     # one header
    assert lines[1].startswith("C0,") and lines[-1].startswith("C249,")
    assert seen == [100, 100, 50]


def test_only_so_many_case_ar_pivots_run_at_once(client, tmp_path, monkeypatch):
    """Each one holds all of Raw Data in memory. Past the limit a request
    waits its turn, and is told to try again rather than joining the pile."""
    import app.api.run_routes as routes
    run_id = _run_with_table(10, tmp_path)
    monkeypatch.setattr(routes, "HEAVY_WAIT", 0.05)
    for _ in range(2):
        assert routes._heavy.acquire(timeout=1)       # two already under way
    try:
        r = client.get(f"/api/runs/{run_id}/case-ar")
        assert r.status_code == 503 and "busy" in r.json()["detail"]
    finally:
        for _ in range(2):
            routes._heavy.release()
    # ...and a turn taken is always handed back, even by a request that fails
    # (this stand-in table has none of the columns a real pivot needs).
    try:
        client.get(f"/api/runs/{run_id}/case-ar", params={"group": "A"})
    except Exception:
        pass
    assert routes._heavy.acquire(timeout=1) and routes._heavy.acquire(timeout=1)
    routes._heavy.release(); routes._heavy.release()


def test_a_build_is_dated_where_the_business_is(monkeypatch):
    """A server on UTC is five hours behind Karachi: at 02:00 on Tuesday there
    it still said Monday, and every age in days came out one short."""
    import app.config as config

    class At2130Utc(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 10, 5, 21, 30, tzinfo=dt.timezone.utc).astimezone(tz)
    monkeypatch.setattr(config.dt, "datetime", At2130Utc)
    monkeypatch.setattr(settings, "timezone", "Asia/Karachi")
    assert settings.today() == dt.date(2026, 10, 6)       # already Tuesday there
    monkeypatch.setattr(settings, "timezone", "UTC")
    assert settings.today() == dt.date(2026, 10, 5)


def test_a_wrong_file_can_be_taken_back(client):
    """Before this, a file uploaded by mistake stayed until the whole week
    was deleted. Nothing comes back in its place: the copy it replaced went
    when it was replaced."""
    earlier = upload(client, "Supporting File.xlsx", body=b"the first copy")
    wrong = upload(client, "Supporting File.xlsx", body=b"sent by mistake")
    assert not list(settings.object_dir.rglob(f"{earlier}*"))   # replaced, gone
    assert client.get(f"/api/weeks/{WEEK}").json()["files"] == 1
    cache = settings.data_dir / "cache" / WEEK / "gfs"
    cache.mkdir(parents=True)
    (cache / f"supporting-{wrong[:16]}-15-1.parquet").write_bytes(b"parsed")

    have = client.get(f"/api/weeks/{WEEK}").json()["reports"]["gfs"]["have"][0]
    assert have["sha256"] == wrong and have["read_by_a_build"] is False

    r = client.delete(f"/api/weeks/{WEEK}/uploads/{have['id']}")
    assert r.status_code == 200 and r.json()["file_removed"] is True
    assert r.json()["status"]["reports"]["gfs"]["have"] == []   # empty, not the old one
    assert "Supporting File" in r.json()["status"]["reports"]["gfs"]["missing"]
    assert not list(settings.object_dir.rglob("*.xlsx"))
    assert not list(cache.iterdir())                  # its parsed copy too
    assert log("upload.delete")[0].detail["file"] == "Supporting File.xlsx"

    assert client.delete(f"/api/weeks/{WEEK}/uploads/{have['id']}").status_code == 404
    assert client.delete("/api/weeks/2026-W39/uploads/1").status_code == 404


def test_a_file_a_build_has_read_cannot_be_taken_back(client, stand_in_pipeline):
    """That build's record of what it was made from has to stay true."""
    upload_everything(client)
    run_id = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]
    _wait(client, run_id)
    have = client.get(f"/api/weeks/{WEEK}").json()["reports"]["gfs"]["have"]
    assert all(h["read_by_a_build"] for h in have)
    r = client.delete(f"/api/weeks/{WEEK}/uploads/{have[0]['id']}")
    assert r.status_code == 409 and f"build {run_id}" in r.json()["detail"]

    viewer = account(client, "reader@appedology.com", "APD-0002")
    assert client.delete(f"/api/weeks/{WEEK}/uploads/{have[0]['id']}",
                         headers=viewer).status_code == 403


def test_a_file_name_too_long_to_store_is_refused_with_a_reason(client):
    """A name the disk cannot hold was a server error for the whole upload -
    the good files in it included."""
    name = "Supporting File " + "x" * 400 + ".xlsx"
    r = client.post(f"/api/weeks/{WEEK}/uploads", files=[
        ("files", (name, b"x", "application/octet-stream")),
        ("files", ("Payment Detail.xlsx", b"y", "application/octet-stream"))])
    assert r.status_code == 200
    assert [a["filename"] for a in r.json()["accepted"]] == ["Payment Detail.xlsx"]
    assert "longer than 240" in r.json()["rejected"][0]["reason"]


def test_the_session_is_a_cookie_the_page_cannot_read(client):
    make_account("someone@appedology.com", "APD-0002")
    browser = TestClient(client.app)
    r = browser.post("/api/auth/login", json={"email": "someone@appedology.com",
                                              "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/api" in cookie and "secure" not in cookie      # plain http here

    # No header, no stored token: the cookie alone is the sign-in.
    assert browser.get("/api/auth/me").json()["email"] == "someone@appedology.com"
    assert browser.post("/api/auth/logout").status_code == 200
    assert browser.get("/api/auth/me").status_code == 401

    over_https = TestClient(client.app, base_url="https://testserver")
    r = over_https.post("/api/auth/login", json={"email": "someone@appedology.com",
                                                 "password": PASSWORD})
    assert "secure" in r.headers["set-cookie"].lower()
    assert "max-age=31536000" in r.headers["strict-transport-security"]


def test_wrong_passwords_lock_out_the_guesser_not_the_owner(client):
    """The lock was on the account: anyone who knew a colleague's email could
    keep them out all day with five wrong passwords every fifteen minutes."""
    uid = make_account("someone@appedology.com", "APD-0002")
    guesser = TestClient(client.app, client=("203.0.113.9", 50000))
    owner = TestClient(client.app, client=("198.51.100.7", 50000))

    def sign_in(c, password):
        return c.post("/api/auth/login", json={"email": "someone@appedology.com",
                                               "password": password})
    for _ in range(4):
        assert "do not match" in sign_in(guesser, "a wrong guess").json()["detail"]
    assert "locked" in sign_in(guesser, "a wrong guess").json()["detail"]
    # Even the right password is refused from the address that was guessing...
    r = sign_in(guesser, PASSWORD)
    assert r.status_code == 401 and "locked" in r.json()["detail"]
    # ...while the owner, from their own, signs in as if nothing had happened.
    assert sign_in(owner, PASSWORD).status_code == 200
    assert len(log("auth.locked")) == 1

    # The Users screen still shows it and an admin can still lift it.
    users = {u["id"]: u for u in client.get("/api/admin/users").json()}
    assert users[uid]["status"] == "locked" and users[uid]["can"]["unlock"]
    client.post(f"/api/admin/users/{uid}/unlock")
    assert sign_in(guesser, PASSWORD).status_code == 200


def test_the_right_password_clears_the_count_for_that_address(client):
    """Four mistypes, then in: the next mistype is the first, not the fifth."""
    make_account("someone@appedology.com", "APD-0002")

    def sign_in(password):
        return client.post("/api/auth/login", json={
            "email": "someone@appedology.com", "password": password})
    for _ in range(4):
        sign_in("a wrong guess")
    assert sign_in(PASSWORD).status_code == 200
    for _ in range(4):
        assert "do not match" in sign_in("a wrong guess").json()["detail"]


def test_a_session_ends_after_an_hour_of_nothing(client):
    """Two weeks, however long it sat unused, is a long time for a browser
    left open on someone else's desk."""
    from app.db.models import Session
    from app.db.session import session
    from app.service import auth
    make_account("someone@appedology.com", "APD-0002")
    r = client.post("/api/auth/login", json={"email": "someone@appedology.com",
                                             "password": PASSWORD})
    me = {"Authorization": f"Bearer {r.json()['token']}"}
    now = dt.datetime.now(dt.timezone.utc)

    def row(s):
        return s.execute(select(Session).order_by(Session.id.desc())).scalars().first()

    with session() as s:                  # 50 minutes in, still working
        row(s).last_seen_at = now - dt.timedelta(minutes=50)
        row(s).expires_at = now + dt.timedelta(minutes=10)
    assert client.get("/api/auth/me", headers=me).status_code == 200
    with session() as s:                  # ...which bought another hour
        left = row(s).expires_at - now
        assert dt.timedelta(minutes=59) < left <= auth.SESSION_IDLE + dt.timedelta(seconds=5)

    with session() as s:                  # but never past twelve hours in all
        row(s).created_at = now - auth.SESSION_MAX + dt.timedelta(minutes=5)
        row(s).last_seen_at = now - dt.timedelta(minutes=2)
    assert client.get("/api/auth/me", headers=me).status_code == 200
    with session() as s:
        assert row(s).expires_at - now <= dt.timedelta(minutes=5, seconds=5)

    with session() as s:                  # an hour of nothing
        row(s).expires_at = now - dt.timedelta(seconds=1)
    assert client.get("/api/auth/me", headers=me).status_code == 401


def test_a_server_that_requires_https_refuses_plain_http(client, monkeypatch):
    """HTTPS was a step in the instructions. Skipped, the server still took
    passwords - over the network, unencrypted."""
    monkeypatch.setattr(settings, "require_https", True)
    r = client.post("/api/auth/login", json={"email": "tester@appedology.com",
                                             "password": PASSWORD})
    assert r.status_code == 400 and "HTTPS" in r.json()["detail"]
    assert "set-cookie" not in r.headers

    over_https = TestClient(client.app, base_url="https://testserver")
    assert over_https.post("/api/auth/login", json={
        "email": "tester@appedology.com", "password": PASSWORD}).status_code == 200
    # The installer and a monitor, asking from the server itself, still can.
    local = TestClient(client.app, client=("127.0.0.1", 50000))
    assert local.get("/api/health").status_code == 200


def test_a_reference_that_cannot_be_saved_leaves_the_old_one_whole(
        client, stand_in_pipeline, tmp_path, monkeypatch):
    """The old reference was deleted first and the new one copied after. A
    copy that failed half way left neither."""
    from app.db.models import Run
    from app.db.session import session
    from app.service import golden
    kept = tmp_path / "golden"

    def approved_build() -> int:
        run_id = client.post(f"/api/runs?report=gfs&week={WEEK}").json()["run_id"]
        _wait(client, run_id)
        client.post(f"/api/runs/{run_id}/approve")
        return run_id

    upload_everything(client)
    first = approved_build()
    with session() as s:
        golden.save(s.get(Run, first), kept)
    before = sorted(p.name for p in (kept / "gfs").iterdir())

    second = approved_build()
    monkeypatch.setattr(golden, "_check", lambda folder, run: (_ for _ in ()).throw(
        ValueError("raw_data was copied with 2 rows; the run recorded 3")))
    with session() as s:
        with pytest.raises(ValueError, match="copied with 2 rows"):
            golden.save(s.get(Run, second), kept)

    ref = golden.load("gfs", kept)
    assert ref.meta["run_id"] == first                      # still the old one
    assert sorted(p.name for p in (kept / "gfs").iterdir()) == before
    assert [p.name for p in kept.iterdir() if p.name.startswith(".")] == []
    assert all(ref.objects.has(i["sha256"], i["suffix"]) for i in ref.meta["inputs"])


# ------------------------------------------------- versioned migrations

def _engine(path):
    from sqlalchemy import create_engine
    return create_engine(f"sqlite:///{path.as_posix()}")


def test_the_migrations_build_exactly_the_schema_the_models_describe(tmp_path):
    """The check that stops the two drifting apart: a column added to a model
    with no migration to add it fails here, not on the server."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from app.db import migrate
    from app.db.models import Base

    e = _engine(tmp_path / "new.db")
    migrate.upgrade(e)
    assert migrate.revision(e) == migrate.head()
    with e.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    assert diff == []


def test_a_database_from_before_migrations_is_brought_into_them(tmp_path):
    """The laptop's existing database: made by the old start-up, at whatever
    shape it then had, with no record of which changes it has had."""
    from sqlalchemy import inspect
    from app.db import migrate

    e = _engine(tmp_path / "old.db")
    with e.begin() as c:
        c.execute(text("CREATE TABLE user_account (id INTEGER PRIMARY KEY, "
                       "email VARCHAR(320), apd_id VARCHAR(8), "
                       "password_hash VARCHAR(255), created_at DATETIME, "
                       "last_login_at DATETIME, is_active BOOLEAN)"))
        c.execute(text("INSERT INTO user_account VALUES "
                       "(1, 'a@appedology.com', 'APD-1111', 'x', NULL, NULL, 1)"))
        c.execute(text("CREATE TABLE run (id INTEGER PRIMARY KEY, "
                       "report_key VARCHAR(32), week VARCHAR(9), "
                       "status VARCHAR(16), started_at DATETIME)"))
        c.execute(text("INSERT INTO run VALUES (1, 'gfs', '2026-W35', 'pending', NULL),"
                       " (2, 'gfs', '2026-W34', 'approved', NULL)"))

    migrate.upgrade(e)
    migrate.upgrade(e)                                   # and again does nothing
    assert migrate.revision(e) == migrate.head()
    have = inspect(e)
    assert {"rate_hit", "month_setting", "activity_log"} <= set(have.get_table_names())
    assert {"active_key", "heartbeat_at", "working_days"} <= {
        c["name"] for c in have.get_columns("run")}
    with e.connect() as c:
        assert c.execute(text("SELECT role, report_access FROM user_account")
                         ).one() == ("viewer", "gfs,all_providers")
        # Queued by the old code, with nothing recorded to build it from.
        assert dict(c.execute(text("SELECT id, status FROM run")).all()) == {
            1: "failed", 2: "approved"}
