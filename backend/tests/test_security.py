"""Tests for the activity log, account protections and password resets."""
from __future__ import annotations
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import settings
from app.db import session as db_session
from tests.accounts import (PASSWORD, account, age_codes, confirm_email,
                            last_mail, mailed_code, make_account, sign_in,
                            token_of)

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
    """Enforced by the database, not by the app choosing not to."""
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
                files=[("files", ("Hearing Calendar.xlsx", b"x", "application/x"))])
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
    assert upload.detail["accepted"][0]["file"] == "Hearing Calendar.xlsx"
    assert log("run.unapprove")[0].detail["was_approved_by"] == ADMIN


def _run(week="2026-W35", status="review", report="gfs"):
    from app.db.models import Run
    from app.db.session import session
    with session() as s:
        run = Run(report_key=report, week=week, status=status, seconds=1.0)
        s.add(run)
        s.flush()
        return run.id


def test_five_wrong_passwords_lock_the_account(client):
    make_account(USER, "APD-0002")
    for _ in range(4):
        assert "do not match" in login(client, USER, "nope nope").json()["detail"]
    r = login(client, USER, "nope nope")
    assert "locked" in r.json()["detail"]
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
    token = token_of(login(client, USER, PASSWORD))
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
    confirm_email(client, "new@appedology.com")
    users = client.get("/api/admin/users", headers=admin).json()
    new = users[0]                                   # waiting ones come first
    assert new["email"] == "new@appedology.com" and new["status"] == "pending"
    client.post(f"/api/admin/users/{new['id']}/approve", headers=admin)
    assert login(client, "new@appedology.com", PASSWORD).status_code == 200
    assert log("admin.approve_user")[0].target == "new@appedology.com"


def forgot(client, email=USER):
    return client.post("/api/auth/password/forgot", json={"email": email})


def enter_code(client, code, email=USER):
    return client.post("/api/auth/password/verify-code",
                       json={"email": email, "code": code})


def new_password(client, ticket, password="my own password now"):
    return client.post("/api/auth/password/reset",
                       json={"ticket": ticket, "password": password})


def test_forgot_password_end_to_end(client):
    """Forgot password? -> a code by email -> the code -> a new password."""
    make_account(USER, "APD-0002")
    old = sign_in(client, USER)
    assert forgot(client).status_code == 200
    r = enter_code(client, mailed_code(USER))
    assert r.status_code == 200
    assert new_password(client, r.json()["ticket"]).status_code == 200

    assert login(client, USER, PASSWORD).status_code == 401        # old one: gone
    assert login(client, USER, "my own password now").status_code == 200
    assert client.get("/api/auth/me", headers=old).status_code == 401  # signed out
    assert last_mail(USER)["Subject"] == "Your Scorecard password was changed"
    assert {e.action for e in log()} >= {"auth.password_forgot", "auth.reset_code",
                                         "auth.password_reset"}


def test_forgot_password_says_the_same_whoever_asks(client):
    from app.service import mail
    make_account(USER, "APD-0002")
    before = len(mail.outbox)
    real, made_up = forgot(client), forgot(client, "nobody@appedology.com")
    assert real.status_code == made_up.status_code == 200
    assert real.json() == made_up.json()
    assert len(mail.outbox) == before + 1             # only the real one is sent


def test_asking_for_a_reset_does_not_change_the_password(client):
    """Anyone can type a colleague's email into "Forgot password?" - that alone
    must not lock them out."""
    make_account(USER, "APD-0002")
    forgot(client)
    assert login(client, USER, PASSWORD).status_code == 200


def test_a_reset_code_expires_after_five_minutes(client):
    make_account(USER, "APD-0002")
    forgot(client)
    code = mailed_code(USER)
    age_codes(minutes=5, seconds=1)
    assert enter_code(client, code).status_code == 400


def test_five_wrong_reset_codes_spend_it(client):
    from app.service import codes
    make_account(USER, "APD-0002")
    forgot(client)
    code = mailed_code(USER)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(codes.CODE_TRIES):
        assert enter_code(client, wrong).status_code == 400
    assert enter_code(client, code).status_code == 400
    assert log("auth.reset_code")[-1].outcome == "failure"


def test_a_reset_code_and_its_ticket_work_once(client):
    make_account(USER, "APD-0002")
    forgot(client)
    code = mailed_code(USER)
    ticket = enter_code(client, code).json()["ticket"]
    assert enter_code(client, code).status_code == 400              # code: spent
    assert new_password(client, ticket).status_code == 200
    assert new_password(client, ticket, "yet another password").status_code == 400
    assert new_password(client, "1.made-up").status_code == 400
    assert new_password(client, "nonsense").status_code == 400


def test_only_the_newest_reset_code_works(client):
    make_account(USER, "APD-0002")
    forgot(client)
    first = mailed_code(USER)
    age_codes(seconds=61)
    forgot(client)
    second = mailed_code(USER)
    if first != second:
        assert enter_code(client, first).status_code == 400
    assert enter_code(client, second).status_code == 200


def test_reset_codes_are_not_sent_back_to_back(client):
    from app.service import mail
    make_account(USER, "APD-0002")
    forgot(client)
    before = len(mail.outbox)
    assert forgot(client).status_code == 200           # same answer...
    assert len(mail.outbox) == before                  # ...but nothing sent


def test_a_disabled_account_gets_no_reset_code(client, admin):
    from app.service import mail
    uid = make_account(USER, "APD-0002")
    client.post(f"/api/admin/users/{uid}/active", headers=admin, json={"active": False})
    before = len(mail.outbox)
    assert forgot(client).status_code == 200
    assert len(mail.outbox) == before


def test_an_admin_forced_reset_shuts_the_old_password_out(client, admin):
    """For a stolen laptop or a leaked password: the admin sees and chooses
    nothing; the owner is mailed, and gets back in with Forgot password?."""
    uid = make_account(USER, "APD-0002")
    theirs = sign_in(client, USER)
    r = client.post(f"/api/admin/users/{uid}/reset-password", headers=admin)
    assert r.status_code == 200 and r.json()["notified"] == USER
    assert not {"temporary_password", "code", "ticket"} & set(r.json())
    assert client.get("/api/auth/me", headers=theirs).status_code == 401
    assert login(client, USER, PASSWORD).status_code == 401
    assert last_mail(USER)["Subject"] == "Choose a new Scorecard password"

    forgot(client)
    ticket = enter_code(client, mailed_code(USER)).json()["ticket"]
    new_password(client, ticket)
    assert login(client, USER, "my own password now").status_code == 200


def test_the_server_command_shows_a_code_for_when_mail_is_down(client, capsys):
    """The printed code replaces a mailed one and works on the code screen."""
    from app import manage
    make_account(USER, "APD-0002")
    forgot(client)
    mailed = mailed_code(USER)
    manage.main(["reset-password", USER])
    out = capsys.readouterr().out
    code = out.split(f"Reset code for {USER}: ")[1].split()[0]
    if code != mailed:
        assert enter_code(client, mailed).status_code == 400
    ticket = enter_code(client, code).json()["ticket"]
    assert new_password(client, ticket).status_code == 200


def test_an_old_temporary_password_expires(client):
    """Handed out on Teams before resets were mailed links; one still sitting
    in a chat must not open the account for ever."""
    from app.db.models import User
    from app.db.session import session
    from app.service import auth
    make_account(USER, "APD-0002")
    with session() as s:
        u = s.query(User).filter_by(email=USER).one()
        u.must_change_password = True
        u.password_changed_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    headers = sign_in(client, USER)                      # an hour old: still fine
    r = client.get("/api/scorecards/current", headers=headers)
    assert r.json()["detail"]["code"] == "password_change_required"

    with session() as s:
        u = s.query(User).filter_by(email=USER).one()
        u.password_changed_at -= auth.TEMPORARY_TTL
    r = login(client, USER, PASSWORD)
    assert r.status_code == 401 and "expired" in r.json()["detail"]


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


@pytest.mark.parametrize("week", ["2026-W5", "2026-W54", "2026W35", "2026-W35x",
                                  "2027-W53"])
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
    import app.api.run_routes as routes
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

    def boom(plan):
        raise ValueError("the spreadsheet is not what it should be")

    monkeypatch.setattr(runner, "plan", lambda store, run: None)
    monkeypatch.setattr(runner, "compute", boom)
    run_id = _run(status="running")
    worker._build(run_id)
    from app.db.models import Run
    from app.db.session import session
    with session() as s:
        run = s.get(Run, run_id)
        assert run.status == "failed"
        assert "not what it should be" in run.error
        assert run.active_key is None           # the week can be built again


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
        ("files", ("C:\\Users\\x\\Hearing Calendar.xlsx", b"x", "application/x"))])
    assert r.json()["accepted"][0]["filename"] == "Hearing Calendar.xlsx"


def test_deleting_a_week_removes_its_cached_data(client, admin):
    client.post("/api/weeks/2026-W35/uploads", headers=admin,
                files=[("files", ("Hearing Calendar.xlsx", b"x", "application/x"))])
    cache = settings.data_dir / "cache" / "2026-W35" / "gfs"
    cache.mkdir(parents=True)
    (cache / "case_ar.parquet").write_bytes(b"client data")
    client.delete("/api/weeks/2026-W35", headers=admin)
    assert not (settings.data_dir / "cache" / "2026-W35").exists()


def test_times_come_back_in_utc(client, user):
    """A bare time is read by the browser as local time - hours out."""
    me = client.get("/api/auth/me", headers=user).json()
    assert me["created_at"].endswith(("+00:00", "Z"))


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
    assert tuple(row) == ("viewer", "gfs,all_providers", 0, 0)


def test_migrations_run_as_the_migration_account(tmp_path, monkeypatch):
    """create_all uses the migration account; the app only checks the schema."""
    from sqlalchemy import create_engine
    from app.db import migrate
    from app.db.session import SchemaOutOfDate, check_schema, create_all
    settings.use(tmp_path / "data")
    db_session.reset()
    with pytest.raises(SchemaOutOfDate, match="scorecard-manage upgrade"):
        check_schema()                      # an empty database: refuses to start

    elsewhere = f"sqlite:///{(tmp_path / 'other.db').as_posix()}"
    monkeypatch.setattr(settings, "migrate_database_url", elsewhere)
    create_all()
    assert migrate.revision(create_engine(elsewhere)) == migrate.head()
    with pytest.raises(SchemaOutOfDate):
        check_schema()                      # the app's database was not touched

    monkeypatch.setattr(settings, "migrate_database_url", settings.database_url)
    create_all()
    check_schema()                          # now it is current, and starts


def test_the_upgrade_does_not_shut_out_people_already_using_the_app(tmp_path):
    """Accounts an admin approved before email confirmation existed count as
    confirmed; ones still waiting must confirm."""
    from alembic import command
    from sqlalchemy import create_engine
    from app.db import migrate
    e = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    command.upgrade(migrate._config(e), "0002")
    with e.begin() as c:
        for i, pending in ((1, 0), (2, 1)):
            c.execute(text(
                "INSERT INTO user_account (id, email, apd_id, password_hash, created_at, "
                "is_active, role, report_access, pending, must_change_password, "
                "failed_logins) VALUES (:i, :e, :a, 'x', '2026-09-01 10:00:00', 1, "
                "'viewer', '', :p, 0, 0)"),
                {"i": i, "e": f"u{i}@appedology.com", "a": f"APD-000{i}", "p": pending})
    migrate.upgrade(e)
    with e.connect() as c:
        rows = dict(c.execute(text("SELECT id, email_verified_at FROM user_account")).all())
    assert rows[1] is not None and rows[2] is None


def test_a_migration_account_address_is_read_from_the_environment(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("SCORECARD_MIGRATE_DB", "mysql://m:p@db/scorecard")
    monkeypatch.setenv("SCORECARD_AUTO_MIGRATE", "0")
    s = Settings()
    assert s.migrate_database_url == "mysql+pymysql://m:p@db/scorecard?charset=utf8mb4"
    assert s.auto_migrate is False
    monkeypatch.delenv("SCORECARD_MIGRATE_DB")
    assert Settings().migrate_database_url is None


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
    """An old SQLite database copies into a new one; a non-empty target is refused."""
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


@pytest.fixture
def small_limits(monkeypatch):
    """Lower rate limits, so a test reaches them in a few tries."""
    from app.service import ratelimit
    monkeypatch.setattr(ratelimit, "LOGIN_FAILURES", (6, 15 * 60))


def test_one_address_is_slowed_after_many_failed_sign_ins(client, small_limits):
    """The account lock stops guessing at one account; this stops one address
    working through many of them."""
    from app.service import ratelimit
    limit, _ = ratelimit.LOGIN_FAILURES
    for n in range(limit):
        assert login(client, f"nobody-{n}@appedology.com", "x" * 8).status_code == 401
    r = login(client, "one-more@appedology.com", "x" * 8)
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_a_right_password_does_not_count_against_the_address(client, user, small_limits):
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


def test_a_new_password_that_is_refused_is_not_a_wrong_password(client, user):
    """Too short, or the same as the old one: the person knew their password."""
    from app.service import ratelimit
    limit, _ = ratelimit.PASSWORD_FAILURES
    for _ in range(limit):
        r = client.post("/api/me/password", headers=user,
                        json={"current": PASSWORD, "new": "short"})
        assert r.status_code == 400 and "at least" in r.json()["detail"]
    r = client.post("/api/me/password", headers=user,
                    json={"current": PASSWORD, "new": "a new password"})
    assert r.status_code == 200


@pytest.fixture
def received(monkeypatch):
    """How many bytes of uploaded files the server has taken in."""
    import starlette.formparsers as fp
    seen = {"bytes": 0}
    real = fp.MultiPartParser.on_part_data

    def counting(self, data, start, end):
        seen["bytes"] += end - start
        return real(self, data, start, end)
    monkeypatch.setattr(fp.MultiPartParser, "on_part_data", counting)
    return seen


def test_an_upload_is_not_taken_in_from_someone_not_signed_in(client, received):
    """The body used to be read first and the sender checked afterwards, so
    anyone could have the server swallow a gigabyte before being refused."""
    files = [("files", ("Hearing Calendar.xlsx", b"x" * 200_000, "application/x"))]
    r = client.post("/api/weeks/2026-W35/uploads", files=files)
    assert r.status_code == 401 and r.json()["detail"] == "Sign in to continue."
    assert received["bytes"] == 0


def test_an_upload_is_not_taken_in_from_a_viewer(client, user, admin, received):
    files = [("files", ("Hearing Calendar.xlsx", b"x" * 200_000, "application/x"))]
    r = client.post("/api/weeks/2026-W35/uploads", headers=user, files=files)
    assert r.status_code == 403 and received["bytes"] == 0
    assert [e.target for e in log("admin.denied")] == [
        "POST /api/weeks/2026-W35/uploads"]
    r = client.post("/api/weeks/2026-W35/uploads", headers=admin, files=files)
    assert r.status_code == 200 and received["bytes"] == 200_000


def test_nothing_but_an_upload_may_be_large(client):
    """A megabyte is far more than any form here sends."""
    r = client.post("/api/auth/login", content=b"x" * (1024 * 1024 + 1),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert login(client, "nobody@appedology.com", "whatever1").status_code == 401


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
                    files=[("files", ("Hearing Calendar.xlsx", big, "application/x"))])
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
    weaker = auth.ITERATIONS // 2
    old = "pbkdf2_sha256${}${}${}".format(
        weaker, auth._b64(salt),
        auth._b64(hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), salt, weaker)))
    with session() as s:
        s.execute(select(User).where(User.email == USER)).scalar_one().password_hash = old
    assert login(client, USER, PASSWORD).status_code == 200
    with session() as s:
        now = s.execute(select(User).where(User.email == USER)).scalar_one().password_hash
    assert now.split("$")[1] == str(auth.ITERATIONS)
    assert auth.verify_password(PASSWORD, now)


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
