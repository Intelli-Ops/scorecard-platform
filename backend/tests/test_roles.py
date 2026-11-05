"""Tests for roles, report access and working days."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import session as db_session
from tests.accounts import account, confirm_email, make_account, sign_in


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
def root(client):
    return account(client, "root@appedology.com", "APD-0001", role="system_admin")


@pytest.fixture
def admin(client):
    return account(client, "admin@appedology.com", "APD-0002", role="admin")


def _run(week="2026-W38", report="gfs", status="approved"):
    from app.db.models import Run, RunFigure
    from app.db.session import session
    with session() as s:
        run = Run(report_key=report, week=week, status=status, seconds=1.0,
                  approved_by="admin@appedology.com")
        s.add(run)
        s.flush()
        s.add(RunFigure(run_id=run.id, name="kpi", data=[{"a": 1}]))
        return run.id


def login_ok(client, email, password="a good long password"):
    return client.post("/api/auth/login", json={"email": email,
                                               "password": password}).status_code == 200


def _id(client, headers, email):
    return next(u["id"] for u in client.get("/api/admin/users", headers=headers).json()
                if u["email"] == email)


def test_a_viewer_sees_only_the_reports_it_was_given(client):
    gfs = _run(report="gfs")
    ap = _run(report="all_providers")
    viewer = account(client, "v@appedology.com", "APD-0100", reports="gfs")

    cards = client.get("/api/scorecards/current", headers=viewer).json()
    assert [c["key"] for c in cards] == ["gfs"]
    assert client.get(f"/api/runs/{gfs}", headers=viewer).status_code == 200
    assert client.get(f"/api/runs/{gfs}/figures/kpi", headers=viewer).status_code == 200
    assert client.get(f"/api/runs/{ap}", headers=viewer).status_code == 404
    assert client.get(f"/api/runs/{ap}/figures/kpi", headers=viewer).status_code == 404


def test_a_viewer_never_sees_a_run_before_it_is_approved(client):
    draft = _run(status="review")
    viewer = account(client, "v@appedology.com", "APD-0100", reports="gfs")
    assert client.get(f"/api/runs/{draft}", headers=viewer).status_code == 404


def test_a_viewer_gets_the_scorecard_without_the_review_working(client, admin):
    run_id = _run()
    viewer = account(client, "v@appedology.com", "APD-0100", reports="gfs")
    body = client.get(f"/api/runs/{run_id}", headers=viewer).json()
    assert "inputs" not in body and "notes" not in body
    assert "inputs" in client.get(f"/api/runs/{run_id}", headers=admin).json()


@pytest.mark.parametrize("method,path", [
    ("get", "/api/weeks"), ("get", "/api/runs"), ("get", "/api/reports"),
    ("get", "/api/weeks/2026-W38"), ("post", "/api/runs?report=gfs&week=2026-W38"),
    ("post", "/api/runs/1/approve"), ("post", "/api/runs/1/unapprove"),
    ("delete", "/api/runs/1"), ("get", "/api/weeks/2026-W38/month"),
])
def test_the_workspace_is_for_admins(client, method, path):
    viewer = account(client, "v@appedology.com", "APD-0100", reports="gfs,all_providers")
    assert getattr(client, method)(path, headers=viewer).status_code == 403


def test_a_viewer_cannot_upload(client):
    viewer = account(client, "v@appedology.com", "APD-0100", reports="gfs")
    r = client.post("/api/weeks/2026-W38/uploads", headers=viewer,
                    files=[("files", ("Hearing Calendar.xlsx", b"x", "application/x"))])
    assert r.status_code == 403


def test_an_admin_grants_a_viewer_access(client, admin):
    make_account("v@appedology.com", "APD-0100")
    vid = _id(client, admin, "v@appedology.com")
    r = client.post(f"/api/admin/users/{vid}/access", headers=admin,
                    json={"reports": ["all_providers", "gfs"]})
    assert r.json()["reports"] == ["gfs", "all_providers"]
    viewer = sign_in(client, "v@appedology.com")
    assert len(client.get("/api/scorecards/current", headers=viewer).json()) == 2
    r = client.post(f"/api/admin/users/{vid}/access", headers=admin,
                    json={"reports": ["nonsense"]})
    assert r.status_code == 409


def test_approving_a_sign_up_can_grant_access_at_once(client, admin):
    client.post("/api/auth/signup", json={"email": "new@appedology.com",
                                          "apd_id": "APD-0300",
                                          "password": "a good long password"})
    confirm_email(client, "new@appedology.com")
    nid = _id(client, admin, "new@appedology.com")
    r = client.post(f"/api/admin/users/{nid}/approve", headers=admin,
                    json={"reports": ["gfs"]})
    assert r.json()["role"] == "viewer" and r.json()["reports"] == ["gfs"]


def test_only_a_system_admin_makes_admins(client, root, admin):
    make_account("v@appedology.com", "APD-0100")
    vid = _id(client, root, "v@appedology.com")
    assert client.post(f"/api/admin/users/{vid}/role", headers=admin,
                       json={"role": "admin"}).status_code == 403
    assert client.post(f"/api/admin/users/{vid}/role", headers=root,
                       json={"role": "admin"}).status_code == 200


def test_an_admin_cannot_manage_another_admin(client, root, admin):
    make_account("other@appedology.com", "APD-0200", role="admin")
    oid = _id(client, admin, "other@appedology.com")
    for method, path, body in [("post", "active", {"active": False}),
                               ("post", "reset-password", None),
                               ("post", "unlock", None)]:
        r = getattr(client, method)(f"/api/admin/users/{oid}/{path}",
                                    headers=admin, json=body)
        assert r.status_code == 403, path
    assert client.delete(f"/api/admin/users/{oid}", headers=admin).status_code == 403
    assert client.delete(f"/api/admin/users/{oid}", headers=root).status_code == 200


def test_nobody_demotes_or_removes_another_system_admin(client, root):
    make_account("root2@appedology.com", "APD-0002", role="system_admin")
    rid = _id(client, root, "root2@appedology.com")
    assert client.delete(f"/api/admin/users/{rid}", headers=root).status_code == 403
    assert client.post(f"/api/admin/users/{rid}/role", headers=root,
                       json={"role": "viewer"}).status_code == 403


def test_a_system_admin_can_stop_another_in_an_emergency(client, root):
    """A stolen laptop, a leaked password: another system admin can sign them
    out, disable them, re-enable them and reset their password."""
    make_account("root2@appedology.com", "APD-0002", role="system_admin")
    theirs = sign_in(client, "root2@appedology.com")
    rid = _id(client, root, "root2@appedology.com")

    assert client.post(f"/api/admin/users/{rid}/sign-out",
                       headers=root).json()["ended"] == 1
    assert client.get("/api/auth/me", headers=theirs).status_code == 401

    theirs = sign_in(client, "root2@appedology.com")
    assert client.post(f"/api/admin/users/{rid}/active", headers=root,
                       json={"active": False}).status_code == 200
    assert client.get("/api/auth/me", headers=theirs).status_code == 401
    assert client.post(f"/api/admin/users/{rid}/active", headers=root,
                       json={"active": True}).status_code == 200

    r = client.post(f"/api/admin/users/{rid}/reset-password", headers=root)
    assert r.status_code == 200
    assert r.json()["notified"] == "root2@appedology.com"
    assert login_ok(client, "root2@appedology.com") is False   # old one is dead


def test_an_admin_cannot_stop_a_system_admin(client, root, admin):
    rid = _id(client, admin, "root@appedology.com")
    for path, body in [("active", {"active": False}), ("reset-password", None),
                       ("sign-out", None), ("unlock", None)]:
        r = client.post(f"/api/admin/users/{rid}/{path}", headers=admin, json=body)
        assert r.status_code == 403, path
    assert client.get("/api/auth/me", headers=root).status_code == 200


def test_the_last_active_system_admin_is_never_disabled(client, root):
    """Two system admins disabling each other at once leave one active."""
    from app.db.models import User
    from app.db.session import session
    from app.service import auth
    make_account("root2@appedology.com", "APD-0002", role="system_admin")
    with session() as s:
        one = s.query(User).filter_by(email="root@appedology.com").one()
        two = s.query(User).filter_by(email="root2@appedology.com").one()
        auth.set_active(s, one, two, False)           # the first one wins
    with session() as s:
        one = s.query(User).filter_by(email="root@appedology.com").one()
        two = s.query(User).filter_by(email="root2@appedology.com").one()
        with pytest.raises(auth.Forbidden, match="only active system admin"):
            auth.set_active(s, two, one, False)       # and leaves one standing


def test_the_server_command_will_not_demote_the_last_system_admin(client, root):
    from app import manage
    with pytest.raises(SystemExit, match="only active system admin"):
        manage.main(["set-role", "root@appedology.com", "admin"])
    make_account("root2@appedology.com", "APD-0002", role="system_admin")
    manage.main(["set-role", "root@appedology.com", "admin"])      # now it may


def test_the_installer_makes_the_default_admin_once(client, monkeypatch):
    import io
    from app import manage
    args = ["create-admin", "boss@appedology.com", "APD-0009",
            "--password-stdin", "--if-missing"]
    monkeypatch.setattr("sys.stdin", io.StringIO("Default@2026\n"))
    manage.main(args)
    assert sign_in(client, "boss@appedology.com", "Default@2026")

    monkeypatch.setattr("sys.stdin", io.StringIO("Another@2026\n"))
    manage.main(args)                       # an update: left as it is
    assert sign_in(client, "boss@appedology.com", "Default@2026")


def test_a_system_admin_may_leave_only_if_another_remains(client, root):
    me = _id(client, root, "root@appedology.com")
    r = client.delete(f"/api/admin/users/{me}", headers=root)
    assert r.status_code == 403 and "only system admin" in r.json()["detail"]

    make_account("root2@appedology.com", "APD-0002", role="system_admin")
    assert client.delete(f"/api/admin/users/{me}", headers=root).status_code == 200
    assert client.get("/api/auth/me", headers=root).status_code == 401


def test_an_admin_cannot_delete_their_own_account(client, admin):
    me = _id(client, admin, "admin@appedology.com")
    assert client.delete(f"/api/admin/users/{me}", headers=admin).status_code == 403


def test_the_users_screen_offers_only_what_will_work(client, root, admin):
    make_account("v@appedology.com", "APD-0100")
    rows = {u["email"]: u["can"] for u in
            client.get("/api/admin/users", headers=admin).json()}
    assert rows["v@appedology.com"]["delete"] and rows["v@appedology.com"]["access"]
    assert rows["v@appedology.com"]["roles"] == []          # admins cannot promote
    assert not any(rows["root@appedology.com"].values())
    assert not rows["admin@appedology.com"]["delete"]       # yourself, as an admin

    rows = {u["email"]: u["can"] for u in
            client.get("/api/admin/users", headers=root).json()}
    assert rows["admin@appedology.com"]["roles"] == ["viewer", "admin", "system_admin"]
    assert rows["admin@appedology.com"]["delete"]
    assert not rows["root@appedology.com"]["delete"]        # the only system admin

    make_account("root2@appedology.com", "APD-0003", role="system_admin")
    other = {u["email"]: u["can"] for u in
             client.get("/api/admin/users", headers=root).json()}["root2@appedology.com"]
    assert other["disable"] and other["reset_password"] and other["sign_out"]
    assert not other["delete"] and other["roles"] == [] and not other["access"]


def test_an_account_is_approved_only_once_its_email_is_confirmed(client, admin):
    client.post("/api/auth/signup", json={"email": "new@appedology.com",
                                          "apd_id": "APD-0300",
                                          "password": "a good long password"})
    row = next(u for u in client.get("/api/admin/users", headers=admin).json()
               if u["email"] == "new@appedology.com")
    assert row["status"] == "unverified" and not row["can"]["approve"]
    r = client.post(f"/api/admin/users/{row['id']}/approve", headers=admin)
    assert r.status_code == 409 and "not confirmed" in r.json()["detail"]

    confirm_email(client, "new@appedology.com")
    row = next(u for u in client.get("/api/admin/users", headers=admin).json()
               if u["email"] == "new@appedology.com")
    assert row["status"] == "pending" and row["can"]["approve"]


def test_deleting_an_account_keeps_its_history(client, admin):
    make_account("v@appedology.com", "APD-0100")
    sign_in(client, "v@appedology.com")
    vid = _id(client, admin, "v@appedology.com")
    client.delete(f"/api/admin/users/{vid}", headers=admin)
    events = client.get("/api/admin/activity?email=v@appedology.com",
                        headers=admin).json()["items"]
    assert {e["action"] for e in events} >= {"auth.login"}


def test_working_days_default_to_the_calendar_and_can_be_set(client, admin):
    info = client.get("/api/weeks/2026-W38/month", headers=admin).json()
    assert info["month"] == "2026-09" and not info["entered"]
    assert info["working_days"] == info["calendar_days"]

    r = client.put("/api/weeks/2026-W38/month", headers=admin, json={"working_days": 20})
    assert r.json()["working_days"] == 20 and r.json()["entered"]
    assert client.get("/api/weeks/2026-W37/month",
                      headers=admin).json()["working_days"] == 20
    r = client.put("/api/weeks/2026-W38/month", headers=admin, json={"working_days": None})
    assert not r.json()["entered"]


def test_the_days_passed_by_the_end_of_the_week(client, admin):
    """2026-W39 ends Fri 25 Sep: 1-25 September holds 19 weekdays, less Labour
    Day (7 Sep) in the rules' holidays."""
    info = client.get("/api/weeks/2026-W39/month", headers=admin).json()
    assert info["week_of_month"] == 4
    assert info["days_passed"] == 18 and info["passed_through"] == "2026-09-25"
    client.put("/api/weeks/2026-W39/month", headers=admin, json={"working_days": 15})
    assert client.get("/api/weeks/2026-W39/month",
                      headers=admin).json()["days_passed"] == 15


def test_working_days_must_fit_the_month(client, admin):
    for bad in (0, 31):                    # September has 30 days
        r = client.put("/api/weeks/2026-W38/month", headers=admin,
                       json={"working_days": bad})
        assert r.status_code == 400


def test_the_pace_uses_the_entered_working_days():
    """The sheet's =sum(...)/elapsed*days, with the month's days as entered."""
    from app.reports.period import reporting_period
    from app.reports.pacing import pace_grid
    calendar = reporting_period("2026-W38", [])
    entered = reporting_period("2026-W38", [], {"2026-09": 20})
    assert calendar.business_days == 22 and entered.business_days == 20
    amounts = {("A", "W1"): 1000.0, ("A", "W2"): 1000.0, ("A", "W3"): 1000.0}
    weeks = ["W1", "W2", "W3"]
    by_calendar = pace_grid(amounts, weeks, calendar)[("A", "W3")]
    by_entered = pace_grid(amounts, weeks, entered)[("A", "W3")]
    assert by_entered == pytest.approx(by_calendar * 20 / 22)


def test_a_build_records_the_working_days_it_paced_on(client, admin):
    from app.db.models import MonthSetting, Run
    from app.db.session import session
    from app.service import runner
    client.put("/api/weeks/2026-W38/month", headers=admin, json={"working_days": 19})
    with session() as s:
        run = Run(report_key="gfs", week="2026-W38", status="running")
        s.add(run)
        s.flush()
        rules = {"holidays": []}
        runner._fix_working_days(s, run, rules)
        assert run.working_days == 19 and run.working_days_source == "entered"
        assert rules["working_days"] == {"2026-09": 19}
        assert s.get(MonthSetting, "2026-09").set_by == "admin@appedology.com"


def test_admins_keep_the_holidays_and_pacing_follows_them(client, admin, root):
    """September 2026 has 22 weekdays; the starting list takes Labour Day (7 Sep)
    off. 2026-W39 runs to Fri 25 Sep."""
    days = [h["day"] for h in client.get("/api/admin/holidays", headers=root).json()]
    assert "2026-09-07" in days and len(days) == 9

    def sep():
        return client.get("/api/weeks/2026-W39/month", headers=admin).json()
    assert (sep()["working_days"], sep()["days_passed"]) == (21, 18)

    assert client.delete("/api/admin/holidays/2026-09-07", headers=admin).status_code == 200
    assert (sep()["working_days"], sep()["days_passed"]) == (22, 19)

    r = client.post("/api/admin/holidays", headers=admin,
                    json={"day": "2026-09-14", "name": "Office closed"})
    assert r.status_code == 200 and r.json()["set_by"] == "admin@appedology.com"
    assert (sep()["working_days"], sep()["days_passed"]) == (21, 18)

    assert client.post("/api/admin/holidays", headers=admin,
                       json={"day": "2026-09-14", "name": "Again"}).status_code == 409
    assert client.post("/api/admin/holidays", headers=admin,
                       json={"day": "2026-09-12", "name": "A Saturday"}).status_code == 400
    assert client.post("/api/admin/holidays", headers=admin,
                       json={"day": "2026-09-15", "name": "  "}).status_code == 400


def test_a_build_paces_on_the_holidays_when_it_is_queued(client, admin):
    from app.db.session import session
    from app.service import runner
    client.post("/api/admin/holidays", headers=admin,
                json={"day": "2026-09-14", "name": "Office closed"})
    with session() as s:
        run = runner.queue(s, "gfs", "2026-W39")
        assert run.working_days == 20 and run.working_days_source == "calendar"
        s.rollback()


def test_a_viewer_cannot_see_or_change_the_holidays(client):
    viewer = account(client, "v@appedology.com", "APD-0100", reports="gfs")
    assert client.get("/api/admin/holidays", headers=viewer).status_code == 403
    assert client.post("/api/admin/holidays", headers=viewer,
                       json={"day": "2026-09-14", "name": "x"}).status_code == 403
    assert client.delete("/api/admin/holidays/2026-09-07", headers=viewer).status_code == 403


def test_admins_keep_the_provider_list(client, admin):
    rows = client.get("/api/admin/providers", headers=admin).json()
    assert len(rows) == 59
    assert next(p for p in rows if p["regid"] == 245)["provider_group"] == "A Miles"

    new = {"regid": 381, "provider_id": "New Clinic", "name": "New Clinic LLC",
           "status": "Active", "provider_group": "New Clinic"}
    r = client.post("/api/admin/providers", headers=admin, json=new)
    assert r.status_code == 200 and r.json()["set_by"] == "admin@appedology.com"
    assert client.post("/api/admin/providers", headers=admin, json=new).status_code == 409

    r = client.put("/api/admin/providers/381", headers=admin,
                   json=new | {"regid": 382, "provider_group": "A Miles"})
    assert r.json()["regid"] == 382 and r.json()["provider_group"] == "A Miles"
    assert client.put("/api/admin/providers/382", headers=admin,
                      json=new | {"regid": 218}).status_code == 409
    assert client.put("/api/admin/providers/382", headers=admin,
                      json=new | {"provider_group": " "}).status_code == 400

    assert client.delete("/api/admin/providers/382", headers=admin).status_code == 200
    assert len(client.get("/api/admin/providers", headers=admin).json()) == 59

    from app.db.models import ActivityLog
    from app.db.session import session
    from sqlalchemy import select
    with session() as s:
        acts = [e.action for e in s.scalars(select(ActivityLog)) if e.action.startswith("provider.")]
    assert acts == ["provider.add", "provider.edit", "provider.delete"]


def test_a_build_reads_the_provider_list_as_it_stands(client, admin):
    from app.db.session import session
    from app.reports.reading import provider_list
    from app.service import runner
    client.delete("/api/admin/providers/218", headers=admin)
    with session() as s:
        rules = runner.rules_for(s, "gfs", "2026-W39", None, None)
    df = provider_list(rules)
    assert df.height == 58 and 218.0 not in df["BUSINESSREGID"].to_list()
    assert df.columns == ["BUSINESSREGID", "PROVIDER ID", "PROVIDER NAME",
                          "Provider Status", "Provider Group"]


def test_a_supporting_file_is_turned_away_with_the_reason(client, admin):
    r = client.post("/api/weeks/2026-W38/uploads", headers=admin,
                    files=[("files", ("Supporting File.xlsx", b"x", "application/x"))])
    assert "Providers page" in r.json()["rejected"][0]["reason"]


def test_a_viewer_cannot_change_the_provider_list(client):
    viewer = account(client, "v@appedology.com", "APD-0100", reports="gfs")
    assert client.get("/api/admin/providers", headers=viewer).status_code == 403
    assert client.delete("/api/admin/providers/218", headers=viewer).status_code == 403


# Which files each admin may upload.

def _upload(client, headers, name, body=b"stand-in", **form):
    return client.post("/api/weeks/2026-W38/uploads", headers=headers,
                       files=[("files", (name, body, "application/octet-stream"))],
                       data=form)


def _me(client, headers):
    return client.get("/api/me", headers=headers).json()


def test_admins_upload_every_file_until_a_system_admin_narrows_them(client, root, admin):
    aid = _id(client, root, "admin@appedology.com")
    assert _me(client, admin)["uploads_all"]
    r = client.post(f"/api/admin/users/{aid}/uploads", headers=root,
                    json={"inputs": ["delta_wc", "delta_mlcr"]})
    assert r.status_code == 200, r.text
    me = _me(client, admin)
    assert not me["uploads_all"] and me["uploads"] == ["delta_wc", "delta_mlcr"]

    r = _upload(client, admin, "Hearing Calendar.xlsx").json()
    assert not r["accepted"]
    assert "not been given this file" in r["rejected"][0]["reason"]
    assert _upload(client, admin, "Master Settlement & Collection Delta WC.xlsb"
                   ).json()["accepted"]
    assert _upload(client, admin, "x.xlsx", as_source="hearing_calendar").status_code == 403

    assert client.post(f"/api/admin/users/{aid}/uploads", headers=root,
                       json={"inputs": None}).status_code == 200
    assert _me(client, admin)["uploads_all"]


def test_an_admin_given_no_files_uploads_nothing(client, root, admin):
    aid = _id(client, root, "admin@appedology.com")
    assert client.post(f"/api/admin/users/{aid}/uploads", headers=root,
                       json={"inputs": []}).status_code == 200
    me = _me(client, admin)
    assert not me["uploads_all"] and me["uploads"] == []
    r = _upload(client, admin, "Master Settlement & Collection Delta WC.xlsb").json()
    assert not r["accepted"] and "not been given this file" in r["rejected"][0]["reason"]
    assert _upload(client, admin, "x.xlsb", as_source="delta_wc").status_code == 403


def test_a_narrowed_admin_cannot_take_back_or_wipe_other_admins_files(client, root, admin):
    hid = _upload(client, root, "Hearing Calendar.xlsx").json()["status"]
    hid = hid["reports"]["gfs"]["have"][0]["id"]
    aid = _id(client, root, "admin@appedology.com")
    client.post(f"/api/admin/users/{aid}/uploads", headers=root, json={"inputs": ["delta_wc"]})
    assert client.delete(f"/api/weeks/2026-W38/uploads/{hid}",
                         headers=admin).status_code == 403
    assert client.delete("/api/weeks/2026-W38", headers=admin).status_code == 403
    assert client.delete(f"/api/weeks/2026-W38/uploads/{hid}",
                         headers=root).status_code == 200


def test_only_a_system_admin_sets_upload_access_and_only_for_admins(client, root, admin):
    make_account("other@appedology.com", "APD-0200", role="admin")
    make_account("v@appedology.com", "APD-0100")
    oid = _id(client, root, "other@appedology.com")
    vid = _id(client, root, "v@appedology.com")
    rid = _id(client, admin, "root@appedology.com")
    assert client.post(f"/api/admin/users/{oid}/uploads", headers=admin,
                       json={"inputs": []}).status_code == 403
    assert client.post(f"/api/admin/users/{vid}/uploads", headers=root,
                       json={"inputs": []}).status_code == 409
    assert client.post(f"/api/admin/users/{oid}/uploads", headers=root,
                       json={"inputs": ["nonsense"]}).status_code == 409
    assert client.post(f"/api/admin/users/{rid}/uploads", headers=root,
                       json={"inputs": []}).status_code == 403     # their own account
