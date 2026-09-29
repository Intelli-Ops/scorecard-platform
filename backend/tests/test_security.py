"""The security layer: the activity log, the account protections, the admin
screens, and the bugs the audit found.

Each test is one promise made to whoever reviews this app's security - that a
failed sign-in is recorded, that the record cannot be edited, that a locked
account stays locked - checked against the API the way the browser uses it.
"""
from __future__ import annotations
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import settings
from app.db import session as db_session
from tests.accounts import PASSWORD, account, make_account, sign_in

ADMIN = "boss@appedology.com"
USER = "worker@appedology.com"


@pytest.fixture
def client(tmp_path):
    settings.use(tmp_path / "data")
    db_session.reset()
    from app.db.session import create_all
    create_all()
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    return account(client, ADMIN, "APD-0001", role="admin")


@pytest.fixture
def user(client):
    return account(client, USER, "APD-0002")


def log(action=None):
    from app.db.models import ActivityLog
    from app.db.session import session
    with session() as s:
        stmt = select(ActivityLog).order_by(ActivityLog.id)
        if action:
            stmt = stmt.where(ActivityLog.action == action)
        return s.execute(stmt).scalars().all()


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ------------------------------------------------------------ the activity log

def test_sign_ins_and_failures_are_logged_with_where_from(client):
    make_account(USER, "APD-0002")
    login(client, USER, PASSWORD)
    login(client, USER, "wrong password")
    login(client, "nobody@appedology.com", "whatever at all")

    rows = log("auth.login")
    assert [(r.email, r.outcome) for r in rows] == [
        (USER, "success"), (USER, "failure"), ("nobody@appedology.com", "failure")]
    assert rows[0].ip and rows[0].user_agent
    assert rows[1].detail["reason"] == "wrong_password"
    assert rows[2].user_id is None and rows[2].detail["reason"] == "no_account"


def test_a_log_row_cannot_be_edited(client):
    """Enforced by the database, not by the app choosing not to. A row can be
    deleted (by a system admin, and that is logged) but never rewritten."""
    make_account(USER, "APD-0002")
    login(client, USER, PASSWORD)
    from app.db.session import engine
    with pytest.raises(Exception, match="cannot be changed"):
        with engine().begin() as c:
            c.execute(text("UPDATE activity_log SET email = 'someone-else'"))
    assert log()[0].email == USER


def test_the_actions_people_take_are_logged(client, admin):
    client.headers.update(admin)
    client.post("/api/weeks/2026-W35/uploads",
                files=[("files", ("Supporting File.xlsx", b"x", "application/x"))])
    run_id = _run()
    client.get(f"/api/runs/{run_id}")
    client.get(f"/api/runs/{run_id}")            # one visit, one row
    client.post(f"/api/runs/{run_id}/approve")
    client.post(f"/api/runs/{run_id}/unapprove")
    client.delete(f"/api/runs/{run_id}")

    actions = [r.action for r in log() if r.action != "auth.login"]
    assert actions == ["upload.files", "run.view", "run.approve",
                       "run.unapprove", "run.delete"]
    upload = log("upload.files")[0]
    assert upload.target == "2026-W35"
    assert upload.detail["accepted"][0]["file"] == "Supporting File.xlsx"
    assert log("run.unapprove")[0].detail["was_approved_by"] == ADMIN


def _run(week="2026-W35", status="review", report="gfs"):
    from app.db.models import Run
    from app.db.session import session
    with session() as s:
        run = Run(report_key=report, week=week, status=status, seconds=1.0)
        s.add(run)
        s.flush()
        return run.id


# ------------------------------------------------------------ account safety

def test_five_wrong_passwords_lock_the_account(client):
    make_account(USER, "APD-0002")
    for _ in range(4):
        assert "do not match" in login(client, USER, "nope nope").json()["detail"]
    r = login(client, USER, "nope nope")
    assert "locked" in r.json()["detail"]
    # Even the right password is refused while it is locked.
    r = login(client, USER, PASSWORD)
    assert r.status_code == 401 and "locked" in r.json()["detail"]
    assert len(log("auth.locked")) == 1


def test_an_admin_can_unlock(client, admin):
    uid = make_account(USER, "APD-0002")
    for _ in range(5):
        login(client, USER, "nope nope")
    client.post(f"/api/admin/users/{uid}/unlock", headers=admin)
    assert login(client, USER, PASSWORD).status_code == 200


def test_session_tokens_are_stored_hashed(client):
    make_account(USER, "APD-0002")
    token = login(client, USER, PASSWORD).json()["token"]
    from app.db.models import Session
    from app.db.session import session
    with session() as s:
        stored = s.execute(select(Session.token)).scalar_one()
    assert stored != token and len(stored) == 64


def test_changing_your_password_ends_your_other_sessions(client):
    make_account(USER, "APD-0002")
    here, laptop = sign_in(client, USER), sign_in(client, USER)

    r = client.post("/api/me/password", headers=here,
                    json={"current": "wrong", "new": "brand new password"})
    assert r.status_code == 400
    assert log("auth.password_change")[-1].outcome == "failure"

    r = client.post("/api/me/password", headers=here,
                    json={"current": PASSWORD, "new": "brand new password"})
    assert r.json()["other_sessions_ended"] == 1
    assert client.get("/api/auth/me", headers=here).status_code == 200
    assert client.get("/api/auth/me", headers=laptop).status_code == 401
    assert login(client, USER, "brand new password").status_code == 200


def test_you_can_see_and_end_your_own_sessions(client, user):
    other = sign_in(client, USER)
    sessions = client.get("/api/me/sessions", headers=user).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    theirs = next(s for s in sessions if not s["current"])
    assert client.delete(f"/api/me/sessions/{theirs['id']}",
                         headers=user).status_code == 200
    assert client.get("/api/auth/me", headers=other).status_code == 401


def test_you_cannot_end_someone_elses_session(client, user, admin):
    theirs = client.get("/api/me/sessions", headers=admin).json()[0]["id"]
    assert client.delete(f"/api/me/sessions/{theirs}",
                         headers=user).status_code == 404


def test_profile_name_can_be_changed(client, user):
    r = client.patch("/api/me", headers=user, json={"display_name": "  Ali  Asghar "})
    assert r.json()["display_name"] == "Ali Asghar"
    assert r.json()["name"] == "Ali Asghar"


# ------------------------------------------------------------ admin

def test_admin_screens_refuse_other_people_and_log_the_attempt(client, user):
    for method, path in [("get", "/api/admin/users"),
                         ("get", "/api/admin/activity"),
                         ("get", "/api/admin/alerts"),
                         ("post", "/api/admin/users/1/role")]:
        assert getattr(client, method)(path, headers=user).status_code == 403
    denied = log("admin.denied")
    assert len(denied) == 4 and all(r.outcome == "denied" for r in denied)


def test_only_an_admin_can_delete(client, user):
    run_id = _run()
    assert client.delete(f"/api/runs/{run_id}", headers=user).status_code == 403
    assert client.delete("/api/weeks/2026-W35", headers=user).status_code == 403


def test_approving_a_new_account(client, admin):
    client.post("/api/auth/signup", json={"email": "new@appedology.com",
                                          "apd_id": "APD-0003",
                                          "password": PASSWORD})
    users = client.get("/api/admin/users", headers=admin).json()
    new = users[0]                                   # waiting ones come first
    assert new["email"] == "new@appedology.com" and new["status"] == "pending"
    client.post(f"/api/admin/users/{new['id']}/approve", headers=admin)
    assert login(client, "new@appedology.com", PASSWORD).status_code == 200
    assert log("admin.approve_user")[0].target == "new@appedology.com"


def test_a_password_reset_must_be_changed_before_anything_else(client, admin):
    uid = make_account(USER, "APD-0002")
    old = sign_in(client, USER)
    temp = client.post(f"/api/admin/users/{uid}/reset-password",
                       headers=admin).json()["temporary_password"]

    assert client.get("/api/auth/me", headers=old).status_code == 401  # signed out
    headers = sign_in(client, USER, temp)
    r = client.get("/api/scorecards/current", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "password_change_required"

    client.post("/api/me/password", headers=headers,
                json={"current": temp, "new": "my own password now"})
    assert client.get("/api/scorecards/current", headers=headers).status_code == 200
    # The log says it was reset, never what to.
    assert temp not in str([r.detail for r in log()])


def test_disabling_an_account_signs_it_out(client, admin):
    uid = make_account(USER, "APD-0002")
    theirs = sign_in(client, USER)
    client.post(f"/api/admin/users/{uid}/active", headers=admin,
                json={"active": False})
    assert client.get("/api/auth/me", headers=theirs).status_code == 401
    assert "disabled" in login(client, USER, PASSWORD).json()["detail"]


def test_admins_cannot_lock_themselves_out(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()["id"]
    r = client.post(f"/api/admin/users/{me}/role", headers=admin,
                    json={"role": "viewer"})
    assert r.status_code == 403 and "your own" in r.json()["detail"]
    r = client.post(f"/api/admin/users/{me}/active", headers=admin,
                    json={"active": False})
    assert r.status_code == 403
    assert log("admin.disable")[0].outcome == "denied"


def test_a_system_admin_can_demote_an_admin_and_it_takes_effect(client, admin):
    boss = account(client, "root@appedology.com", "APD-0009", role="system_admin")
    me = client.get("/api/auth/me", headers=admin).json()["id"]
    assert client.post(f"/api/admin/users/{me}/role", headers=boss,
                       json={"role": "viewer"}).status_code == 200
    assert client.get("/api/admin/users", headers=admin).status_code == 403
    assert log("admin.role")[0].detail["role"] == "viewer"


def test_activity_can_be_searched_paged_and_exported(client, admin):
    make_account(USER, "APD-0002")
    for _ in range(3):
        login(client, USER, "wrong password")
    page = client.get("/api/admin/activity?outcome=failure&limit=2",
                      headers=admin).json()
    assert len(page["items"]) == 2 and page["next"]
    rest = client.get(f"/api/admin/activity?outcome=failure&limit=2"
                      f"&before_id={page['next']}", headers=admin).json()
    assert len(rest["items"]) == 1 and rest["next"] is None

    csv = client.get("/api/admin/activity/csv?action=auth.", headers=admin)
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.count(USER) == 3
    assert log("admin.activity_export")


# ------------------------------------------------------------ detection

def _alerts(client, admin):
    return {a["code"]: a for a in
            client.get("/api/admin/alerts?days=1", headers=admin).json()["alerts"]}


def test_password_guessing_and_list_attacks_are_flagged(client, admin):
    make_account(USER, "APD-0002")
    for _ in range(5):
        login(client, USER, "guess guess")
    for n in range(3):
        login(client, f"made-up-{n}@appedology.com", "guess guess")
    found = _alerts(client, admin)
    assert found["password_guessing"]["email"] == USER
    assert found["spraying"]["count"] == 8           # one address, all of it
    assert "locked" in found


def test_bulk_exports_are_flagged(client, admin):
    from app.service import detect
    from app.db.models import ActivityLog
    from app.db.session import session
    now = dt.datetime.now(dt.timezone.utc)
    with session() as s:
        for i in range(detect.EXPORTS_PER_HOUR):
            s.add(ActivityLog(email=USER, action="table.export",
                              at=now - dt.timedelta(minutes=i)))
    assert _alerts(client, admin)["bulk_export"]["count"] == detect.EXPORTS_PER_HOUR


def test_a_new_address_is_flagged_but_a_first_sign_in_is_not(client, admin):
    from app.db.models import ActivityLog
    from app.db.session import session
    now = dt.datetime.now(dt.timezone.utc)
    with session() as s:
        s.add(ActivityLog(user_id=99, email=USER, action="auth.login",
                          ip="10.0.0.1", at=now - dt.timedelta(days=3)))
        s.add(ActivityLog(user_id=99, email=USER, action="auth.login",
                          ip="203.0.113.9", at=now))
    new = [a for a in client.get("/api/admin/alerts?days=1", headers=admin)
           .json()["alerts"] if a["code"] == "new_address"]
    assert [a["ip"] for a in new] == ["203.0.113.9"]


# ------------------------------------------------------------ audit fixes

@pytest.mark.parametrize("week", ["2026-W5", "2026-W54", "2026W35", "2026-W35x"])
def test_week_labels_are_checked(client, admin, week):
    assert client.get(f"/api/weeks/{week}", headers=admin).status_code == 400
    assert client.post(f"/api/runs?report=gfs&week={week}",
                       headers=admin).status_code == 400


def test_a_week_cannot_climb_out_of_the_data_folder(client, admin):
    """In a query string ".." is not tidied away by the URL, so it reached the
    cache path as data/cache/../../<anything>."""
    r = client.post("/api/runs?report=gfs&week=../../escape", headers=admin)
    assert r.status_code == 400


def test_a_week_cannot_be_built_twice_at_once(client, admin):
    running = _run(status="running")
    from app.service import ingest
    import app.api.routes as routes
    orig = ingest.week_status
    routes.week_status = lambda s, w: {"reports": {"gfs": {"ready": True}}}
    try:
        r = client.post("/api/runs?report=gfs&week=2026-W35", headers=admin)
    finally:
        routes.week_status = orig
    assert r.status_code == 409 and r.json()["detail"]["run_id"] == running


def test_a_failed_build_is_recorded_as_failed(client, monkeypatch):
    """It was rolled back to `pending` and stayed there forever."""
    from app.jobs import worker
    from app.service import runner

    def boom(s, store, report_key, week, as_of=None, run_id=None, **_):
        from app.db.models import Run
        run = s.get(Run, run_id)
        run.status = "running"
        s.flush()
        raise ValueError("the spreadsheet is not what it should be")

    monkeypatch.setattr(runner, "execute", boom)
    run_id = worker.submit("gfs", "2026-W35")
    worker._jobs.join()
    from app.db.models import Run
    from app.db.session import session
    with session() as s:
        run = s.get(Run, run_id)
        assert run.status == "failed"
        assert "not what it should be" in run.error


def test_builds_interrupted_by_a_restart_are_closed_off(client):
    from app.jobs import worker
    stuck = _run(status="running")
    assert worker.recover() == 1
    from app.db.models import Run
    from app.db.session import session
    with session() as s:
        assert s.get(Run, stuck).status == "failed"


def test_a_windows_path_in_an_upload_name_is_cut_to_the_file(client, admin):
    r = client.post("/api/weeks/2026-W35/uploads", headers=admin, files=[
        ("files", ("C:\\Users\\x\\Supporting File.xlsx", b"x", "application/x"))])
    assert r.json()["accepted"][0]["filename"] == "Supporting File.xlsx"


def test_deleting_a_week_removes_its_cached_data(client, admin):
    client.post("/api/weeks/2026-W35/uploads", headers=admin,
                files=[("files", ("Supporting File.xlsx", b"x", "application/x"))])
    cache = settings.data_dir / "cache" / "2026-W35" / "gfs"
    cache.mkdir(parents=True)
    (cache / "case_ar.parquet").write_bytes(b"client data")
    client.delete("/api/weeks/2026-W35", headers=admin)
    assert not (settings.data_dir / "cache" / "2026-W35").exists()


def test_times_come_back_in_utc(client, user):
    """A bare time is read by the browser as local time - hours out."""
    me = client.get("/api/auth/me", headers=user).json()
    assert me["created_at"].endswith(("+00:00", "Z"))


# ------------------------------------------------------------ the database

def test_an_older_database_gains_the_new_columns(tmp_path):
    """The laptop's existing database, created before roles and the rest."""
    from sqlalchemy import create_engine
    from app.db import migrate
    from app.db.models import Base
    e = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with e.begin() as c:
        c.execute(text("CREATE TABLE user_account (id INTEGER PRIMARY KEY, "
                       "email VARCHAR(320), apd_id VARCHAR(8), "
                       "password_hash VARCHAR(255), created_at DATETIME, "
                       "last_login_at DATETIME, is_active BOOLEAN)"))
        c.execute(text("INSERT INTO user_account VALUES "
                       "(1, 'a@appedology.com', 'APD-1111', 'x', NULL, NULL, 1)"))
    added = migrate.add_missing_columns(e, Base.metadata)
    assert "user_account.role" in added
    assert migrate.add_missing_columns(e, Base.metadata) == []      # idempotent
    migrate.upgrade_roles(e)
    with e.connect() as c:
        row = c.execute(text("SELECT role, report_access, pending, failed_logins "
                             "FROM user_account")).one()
    # It could see everything before; as a viewer it still can.
    assert tuple(row) == ("viewer", "gfs,all_providers", 0, 0)


def test_every_table_is_valid_mysql():
    """No MySQL server here, so the schema is compiled against its dialect -
    which catches a column type MySQL lacks or an unquoted reserved word."""
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateIndex, CreateTable
    from app.db.models import Base
    d = mysql.dialect()
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=d))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=d))
        assert "DATETIME(6)" in ddl or "DATETIME" not in ddl
    ddl = str(CreateTable(Base.metadata.tables["run_table"]).compile(dialect=d))
    assert "`rows`" in ddl                      # ROWS is reserved in MySQL 8


def test_a_plain_mysql_address_gets_the_driver_and_charset():
    from app.config import database_url
    assert database_url("mysql://u:p@db/scorecard") == \
        "mysql+pymysql://u:p@db/scorecard?charset=utf8mb4"
    assert database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_copying_an_old_database_into_a_new_one(tmp_path, capsys):
    """The move from the laptop's SQLite file to the server's MySQL, rehearsed
    SQLite to SQLite: an old database, from before the activity log, copies
    across whole - and a target that already has rows is refused."""
    from sqlalchemy import create_engine
    from app import manage
    old = tmp_path / "old.db"
    e = create_engine(f"sqlite:///{old.as_posix()}")
    with e.begin() as c:
        c.execute(text("CREATE TABLE user_account (id INTEGER PRIMARY KEY, "
                       "email VARCHAR(320), apd_id VARCHAR(8), "
                       "password_hash VARCHAR(255), created_at DATETIME, "
                       "last_login_at DATETIME, is_active BOOLEAN)"))
        c.execute(text("INSERT INTO user_account VALUES (7, 'a@appedology.com', "
                       "'APD-1111', 'x', '2026-09-01 10:00:00', NULL, 1)"))
    settings.use(tmp_path / "new")
    db_session.reset()
    manage.main(["copy-db", f"sqlite:///{old.as_posix()}"])
    from app.db.models import User
    from app.db.session import session
    with session() as s:
        user = s.get(User, 7)
        assert user.email == "a@appedology.com" and user.role == "viewer"
        assert user.reports == ["gfs", "all_providers"]     # kept what it could see
        assert user.created_at.tzinfo is not None
    with pytest.raises(SystemExit, match="not empty"):
        manage.main(["copy-db", f"sqlite:///{old.as_posix()}"])


def test_sessions_from_before_hashing_are_closed(client):
    """Their stored token is the raw one, so they can never be used again -
    they only cluttered the profile screen as "Unknown device"."""
    from app.db.models import Session
    from app.db.session import session
    from app.service import auth
    uid = make_account(USER, "APD-0002")
    with session() as s:
        s.add(Session(token="raw-old-token", user_id=uid,
                      expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)))
    live = sign_in(client, USER)
    with session() as s:
        assert auth.retire_unhashed_sessions(s) == 1
    assert len(client.get("/api/me/sessions", headers=live).json()) == 1


# ------------------------------------------------------------ second audit

def test_one_address_is_slowed_after_many_failed_sign_ins(client):
    """The account lock stops guessing at one account; this stops one address
    working through many of them."""
    from app.service import ratelimit
    limit, _ = ratelimit.LOGIN_FAILURES
    for n in range(limit):
        assert login(client, f"nobody-{n}@appedology.com", "x" * 8).status_code == 401
    r = login(client, "one-more@appedology.com", "x" * 8)
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_a_right_password_does_not_count_against_the_address(client, user):
    from app.service import ratelimit
    limit, _ = ratelimit.LOGIN_FAILURES
    for _ in range(limit + 2):
        assert login(client, USER, PASSWORD).status_code == 200


def test_guessing_the_current_password_from_an_open_session_is_limited(client, user):
    from app.service import ratelimit
    limit, _ = ratelimit.PASSWORD_FAILURES
    for _ in range(limit):
        r = client.post("/api/me/password", headers=user,
                        json={"current": "not it at all", "new": "a new password"})
        assert r.status_code == 400
    r = client.post("/api/me/password", headers=user,
                    json={"current": PASSWORD, "new": "a new password"})
    assert r.status_code == 429


def test_an_overlong_email_is_refused_before_it_reaches_the_log(client):
    r = login(client, "a" * 400 + "@appedology.com", "whatever1")
    assert r.status_code == 422


def test_the_activity_export_cannot_carry_a_formula_into_excel(client, admin):
    """The browser string of a failed sign-in is written exactly as sent."""
    client.post("/api/auth/login", json={"email": "x@appedology.com", "password": "y" * 8},
                headers={"User-Agent": "=HYPERLINK(\"http://evil\",\"click\")"})
    body = client.get("/api/admin/activity/csv?days=1", headers=admin).text
    assert "'=HYPERLINK" in body
    assert ",=HYPERLINK" not in body and '"=HYPERLINK' not in body


def test_csv_cells_are_defused_but_numbers_are_not():
    import polars as pl
    from app.service import csvsafe
    assert csvsafe.cell("=1+1") == "'=1+1"
    assert csvsafe.cell("@SUM(A1)") == "'@SUM(A1)"
    assert csvsafe.cell("-12.5") == "-12.5"
    assert csvsafe.cell(-3) == -3
    df = csvsafe.frame(pl.DataFrame({"t": ["=cmd", "-1,200", "ok", None],
                                     "n": [1.0, -2.0, 3.0, 4.0]}))
    assert df["t"].to_list() == ["'=cmd", "-1,200", "ok", None]
    assert df["n"].to_list() == [1.0, -2.0, 3.0, 4.0]


def test_responses_carry_the_security_headers(client, user):
    r = client.get("/api/auth/me", headers=user)
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"


def test_a_table_page_cannot_ask_for_a_negative_offset(client, admin):
    r = client.get("/api/runs/1/tables/raw_data?offset=-5", headers=admin)
    assert r.status_code == 422
    r = client.get("/api/runs/1/tables/raw_data?limit=0", headers=admin)
    assert r.status_code == 422


def test_an_upload_over_the_size_limit_is_refused(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    big = b"x" * (1024 * 1024 + 1)
    r = client.post("/api/weeks/2026-W35/uploads", headers=admin,
                    files=[("files", ("Supporting File.xlsx", big, "application/x"))])
    assert r.status_code == 413
    assert not any(settings.object_dir.rglob("*.xlsx"))


@pytest.mark.parametrize("name", ["..", ".", "  "])
def test_an_upload_named_like_a_folder_is_not_a_server_error(client, admin, name):
    r = client.post("/api/weeks/2026-W35/uploads", headers=admin,
                    files=[("files", (name, b"x", "application/x"))])
    assert r.status_code == 200
    assert r.json()["rejected"][0]["filename"] == "unnamed"


def test_an_older_weaker_password_hash_is_upgraded_at_sign_in(client, user):
    import hashlib, secrets
    from app.db.models import User
    from app.db.session import session
    from app.service import auth
    salt = secrets.token_bytes(16)
    old = "pbkdf2_sha256$240000${}${}".format(
        auth._b64(salt),
        auth._b64(hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), salt, 240_000)))
    with session() as s:
        s.execute(select(User).where(User.email == USER)).scalar_one().password_hash = old
    assert login(client, USER, PASSWORD).status_code == 200
    with session() as s:
        now = s.execute(select(User).where(User.email == USER)).scalar_one().password_hash
    assert now.split("$")[1] == str(auth.ITERATIONS)
    assert auth.verify_password(PASSWORD, now)


# ------------------------------------------------------------ deleting activity

SYSADMIN = "owner@appedology.com"


@pytest.fixture
def sysadmin(client):
    return account(client, SYSADMIN, "APD-0009", role="system_admin")


def _seed(days_ago: list[int]) -> list[int]:
    from app.db.models import ActivityLog
    from app.db.session import session
    now = dt.datetime.now(dt.timezone.utc)
    with session() as s:
        rows = [ActivityLog(email=USER, action="run.view", at=now - dt.timedelta(days=d))
                for d in days_ago]
        s.add_all(rows)
        s.flush()
        return [r.id for r in rows]


def _delete(client, headers, **body):
    return client.post("/api/admin/activity/delete", headers=headers, json=body)


def test_only_a_system_admin_can_delete_activity(client, admin):
    ids = _seed([0])
    r = _delete(client, admin, ids=ids)
    assert r.status_code == 403
    assert log("admin.denied")[-1].target == "delete activity"
    assert any(row.id == ids[0] for row in log())


def test_chosen_events_are_deleted_and_the_deletion_is_logged(client, sysadmin):
    ids = _seed([0, 0, 0])
    assert _delete(client, sysadmin, ids=ids[:2], dry_run=True).json() == {"count": 2}
    assert len([r for r in log() if r.id in ids]) == 3     # a dry run deletes nothing
    assert _delete(client, sysadmin, ids=ids[:2]).json() == {"deleted": 2}
    left = {r.id for r in log()}
    assert ids[2] in left and not left & set(ids[:2])
    record = log("admin.activity_delete")[-1]
    assert record.email == SYSADMIN and record.detail["deleted"] == 2


def test_a_period_is_deleted_and_nothing_outside_it(client, sysadmin):
    ids = _seed([0, 10, 40])
    now = dt.datetime.now(dt.timezone.utc)
    r = _delete(client, sysadmin, since=(now - dt.timedelta(days=15)).isoformat(),
                until=(now - dt.timedelta(days=5)).isoformat(), label="a week")
    assert r.json() == {"deleted": 1}
    left = {r.id for r in log()}
    assert ids[0] in left and ids[2] in left and ids[1] not in left
    assert log("admin.activity_delete")[-1].target == "a week"


def test_deleting_everything_leaves_only_the_record_of_it(client, sysadmin):
    _seed([0, 3, 400])
    assert _delete(client, sysadmin, everything=True).json()["deleted"] >= 3
    rows = log()
    assert [r.action for r in rows] == ["admin.activity_delete"]
    assert rows[0].detail["scope"] == "everything"


@pytest.mark.parametrize("body", [
    {},                                                    # nothing named is not "all"
    {"ids": [1], "everything": True},
    {"since": "2026-09-01T00:00:00Z"},
    {"since": "2026-09-02T00:00:00Z", "until": "2026-09-01T00:00:00Z"},
])
def test_an_unclear_delete_is_refused(client, sysadmin, body):
    _seed([0])
    before = len(log())
    assert _delete(client, sysadmin, **body).status_code == 400
    assert len(log()) == before
