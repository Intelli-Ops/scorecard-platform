"""The HTTP surface, exercised end to end on stand-in files.

No real spreadsheets here - these check the behaviour around a build: what the
upload endpoint accepts and refuses, that a week which is not ready cannot be
built, and that approving is a separate act from finishing. The arithmetic is
covered by the golden master.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import session as db_session


@pytest.fixture
def client(tmp_path):
    """A signed-in client.

    Every data route requires an account now, so the fixture signs one up and
    attaches the token - the same thing the browser does after sign-in.
    """
    settings.use(tmp_path / "data")
    db_session.reset()
    from app.db.session import create_all
    create_all()
    from app.main import app
    with TestClient(app) as c:
        token = c.post("/api/auth/signup", json={
            "email": "tester@appedology.com", "apd_id": "APD-0001",
            "password": "a good long password"}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def upload(client, week, name, body=b"stand-in", for_report=None):
    data = {"for_report": for_report} if for_report else {}
    return client.post(f"/api/weeks/{week}/uploads",
                       files=[("files", (name, body,
                                         "application/octet-stream"))],
                       data=data)


def test_uploads_are_recorded_against_the_signed_in_account(client):
    """Who uploaded comes from the account, not from a field the caller sets."""
    upload(client, "2026-W36", "Supporting File.xlsx")
    from sqlalchemy import select
    from app.db.models import Upload
    from app.db.session import session
    with session() as s:
        assert s.execute(select(Upload.uploaded_by)).scalar_one() == "tester@appedology.com"


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_reports_lists_both_and_marks_the_per_report_files(client):
    reports = client.get("/api/reports").json()
    by_key = {r["key"]: r for r in reports}
    assert set(by_key) == {"gfs", "all_providers"}
    assert by_key["gfs"]["send_day"] == "Tuesday"
    assert by_key["all_providers"]["send_day"] == "Thursday"

    per_report = {s["key"] for s in by_key["gfs"]["sources"] if s["per_report"]}
    assert per_report == {"owner_case_ar", "custom_case_ar"}


def test_upload_accepts_a_source_and_reports_what_it_ignored(client):
    r = upload(client, "2026-W36", "Supporting File.xlsx")
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"][0]["source_key"] == "supporting"
    assert body["accepted"][0]["scope"] == "shared"

    r = upload(client, "2026-W36", "GFS - Weekly Scorecard (Week -36) 2026.xlsx")
    assert r.json()["rejected"][0]["reason"] == "not one of the report inputs"


def test_upload_refuses_a_case_ar_without_a_report(client):
    r = upload(client, "2026-W36", "Combined Owner Case AR.xlsb")
    assert "differs per report" in r.json()["rejected"][0]["reason"]


def test_case_ars_are_kept_apart_per_report(client):
    upload(client, "2026-W36", "Combined Owner Case AR.xlsb", b"tuesday",
           for_report="gfs")
    upload(client, "2026-W36", "Combined Owner Case AR.xlsb", b"thursday",
           for_report="all_providers")

    week = client.get("/api/weeks/2026-W36").json()["reports"]
    gfs = next(h for h in week["gfs"]["have"] if h["source_key"] == "owner_case_ar")
    ap = next(h for h in week["all_providers"]["have"]
              if h["source_key"] == "owner_case_ar")
    assert gfs["sha256"] != ap["sha256"]


def test_a_week_that_is_not_ready_cannot_be_built(client):
    upload(client, "2026-W36", "Supporting File.xlsx")
    r = client.post("/api/runs", params={"report": "gfs", "week": "2026-W36"})
    assert r.status_code == 409
    assert "Combined Owner Case AR" in str(r.json()["detail"]["missing"])


def test_unknown_report_is_refused(client):
    r = client.post("/api/runs", params={"report": "nope", "week": "2026-W36"})
    assert r.status_code == 404


def test_weeks_lists_what_has_been_uploaded(client):
    upload(client, "2026-W35", "Supporting File.xlsx")
    upload(client, "2026-W36", "Supporting File.xlsx")
    weeks = [w["week"] for w in client.get("/api/weeks").json()]
    assert weeks == ["2026-W36", "2026-W35"]


def test_missing_run_is_a_404(client):
    assert client.get("/api/runs/999").status_code == 404
    assert client.post("/api/runs/999/approve").status_code == 404
    assert client.get("/api/runs/999/tables/raw_data/csv").status_code == 404
