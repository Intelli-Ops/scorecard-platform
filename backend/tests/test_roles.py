"""Roles and access: viewer, admin, system admin - and working days.

The rules, as agreed:

  * a viewer sees only the approved scorecards of the reports it was given
  * uploading, building, approving and deleting are for admins and above
  * admins manage viewers; only a system admin makes or manages admins
  * nobody touches a system admin's account but that person, and a system
    admin may remove their own account only while another one remains
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import session as db_session
from tests.accounts import account, make_account, sign_in


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
    from app.db.models import Run, RunFigure, RunTable
    from app.db.session import session
    with session() as s:
        run = Run(report_key=report, week=week, status=status, seconds=1.0,
                  approved_by="admin@appedology.com")
        s.add(run)
        s.flush()
        s.add(RunFigure(run_id=run.id, name="kpi", data=[{"a": 1}]))
        return run.id


def _id(client, headers, email):
    return next(u["id"] for u in client.get("/api/admin/users", headers=headers).json()
                if u["email"] == email)


# ------------------------------------------------------------ viewers

def test_a_viewer_sees_only_the_reports_it_was_given(client):
    gfs = _run(report="gfs")
    ap = _run(report="all_providers")
    viewer = account(client, "v@appedology.com", "APD-0100", reports="gfs")

    cards = client.get("/api/scorecards/current", headers=viewer).json()
    assert [c["key"] for c in cards] == ["gfs"]
    assert client.get(f"/api/runs/{gfs}", headers=viewer).status_code == 200
    assert client.get(f"/api/runs/{gfs}/figures/kpi", headers=viewer).status_code == 200
    # The other report does not exist, as far as this viewer can tell.
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
                    files=[("files", ("Supporting File.xlsx", b"x", "application/x"))])
    assert r.status_code == 403


# ------------------------------------------------------------ who manages whom

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
    # The system admin can.
    assert client.delete(f"/api/admin/users/{oid}", headers=root).status_code == 200


def test_nobody_touches_another_system_admin(client, root):
    make_account("root2@appedology.com", "APD-0002", role="system_admin")
    rid = _id(client, root, "root2@appedology.com")
    assert client.delete(f"/api/admin/users/{rid}", headers=root).status_code == 403
    assert client.post(f"/api/admin/users/{rid}/role", headers=root,
                       json={"role": "viewer"}).status_code == 403


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


def test_deleting_an_account_keeps_its_history(client, admin):
    make_account("v@appedology.com", "APD-0100")
    sign_in(client, "v@appedology.com")
    vid = _id(client, admin, "v@appedology.com")
    client.delete(f"/api/admin/users/{vid}", headers=admin)
    events = client.get("/api/admin/activity?email=v@appedology.com",
                        headers=admin).json()["items"]
    assert {e["action"] for e in events} >= {"auth.login"}


# ------------------------------------------------------------ working days

def test_working_days_default_to_the_calendar_and_can_be_set(client, admin):
    info = client.get("/api/weeks/2026-W38/month", headers=admin).json()
    assert info["month"] == "2026-09" and not info["entered"]
    assert info["working_days"] == info["calendar_days"]

    r = client.put("/api/weeks/2026-W38/month", headers=admin, json={"working_days": 20})
    assert r.json()["working_days"] == 20 and r.json()["entered"]
    # Every week of the month shares it.
    assert client.get("/api/weeks/2026-W37/month",
                      headers=admin).json()["working_days"] == 20
    # Back to the calendar.
    r = client.put("/api/weeks/2026-W38/month", headers=admin, json={"working_days": None})
    assert not r.json()["entered"]


def test_the_days_passed_by_the_end_of_the_week(client, admin):
    """2026-W39 ends Fri 25 Sep: 1-25 September holds 19 weekdays, less
    Labour Day (7 Sep) in the rules' holidays."""
    info = client.get("/api/weeks/2026-W39/month", headers=admin).json()
    assert info["week_of_month"] == 4
    assert info["days_passed"] == 18 and info["passed_through"] == "2026-09-25"
    # Never more than the month's working days, when fewer are entered.
    client.put("/api/weeks/2026-W39/month", headers=admin, json={"working_days": 15})
    assert client.get("/api/weeks/2026-W39/month",
                      headers=admin).json()["days_passed"] == 15


def test_working_days_must_fit_the_month(client, admin):
    for bad in (0, 31):                    # September has 30 days
        r = client.put("/api/weeks/2026-W38/month", headers=admin,
                       json={"working_days": bad})
        assert r.status_code == 400


def test_the_pace_uses_the_entered_working_days():
    """The sheet's =SUM(...)/elapsed*days, with the month's days as entered."""
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
        runner._apply_working_days(s, run, rules, "2026-W38")
        assert run.working_days == 19 and run.working_days_source == "entered"
        assert rules["working_days"] == {"2026-09": 19}
        assert s.get(MonthSetting, "2026-09").set_by == "admin@appedology.com"
