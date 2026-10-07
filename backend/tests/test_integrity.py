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
    assert review["run"]["as_of"] == dt.date.today().isoformat()
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

def test_the_sign_in_limit_is_not_reset_by_a_restart(client):
    """The counts were a dict in the server's memory, so a restart - or a
    second server process - handed out a fresh budget of guesses."""
    from app.service import ratelimit
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

def test_health_reports_each_thing_it_depends_on(client):
    body = client.get("/api/health").json()
    assert body == {"ok": True, "queued_builds": 0,
                    "checks": {"database": True, "storage": True,
                               "disk_space": True, "worker": True}}


def test_health_fails_when_the_disk_is_nearly_full(client, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "MIN_FREE_MB", 10 ** 12)
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["ok"] is False and r.json()["checks"]["disk_space"] is False


def test_health_fails_when_the_worker_has_stopped(client):
    from app.jobs import worker
    worker.stop()
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["checks"]["worker"] is False


def test_health_fails_on_a_database_this_code_has_not_migrated(client):
    from app.db.session import engine
    with engine().begin() as c:
        c.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["checks"]["database"] is False


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
