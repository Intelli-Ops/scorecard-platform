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


# --------------------------------------------------- unapprove, and deleting

def _finished_run(week="2026-W35", report="gfs", status="review"):
    """A run recorded straight into the database.

    The endpoints under test are about a run's LIFE after it was built - being
    approved, un-approved and deleted - and none of that needs real
    spreadsheets to have been read.
    """
    from app.db.models import Run, RunFigure, RunNote, RunTable
    from app.db.session import session
    with session() as s:
        run = Run(report_key=report, week=week, status=status, seconds=2.0)
        s.add(run)
        s.flush()
        s.add(RunNote(run_id=run.id, seq=0, code="x", severity="info", text="hi",
                      detail={}))
        s.add(RunFigure(run_id=run.id, name="kpi", data=[{"a": 1}]))
        s.add(RunTable(run_id=run.id, name="raw_data", rows=10, columns=3,
                       sha256="a" * 64, bytes=99))
        s.commit()
        return run.id


def test_approving_can_be_taken_back(client):
    run_id = _finished_run()
    assert client.post(f"/api/runs/{run_id}/approve").status_code == 200
    assert client.get(f"/api/runs/{run_id}").json()["run"]["status"] == "approved"

    r = client.post(f"/api/runs/{run_id}/unapprove")
    assert r.status_code == 200
    assert r.json()["status"] == "review"

    run = client.get(f"/api/runs/{run_id}").json()["run"]
    assert run["status"] == "review"
    assert run["approved_by"] is None and run["approved_at"] is None


def test_withdrawing_an_approval_is_recorded(client):
    """Who un-approved, and who had approved it. Otherwise a run that was
    signed off on Tuesday and is unsigned on Wednesday has no explanation."""
    run_id = _finished_run()
    client.post(f"/api/runs/{run_id}/approve")
    client.post(f"/api/runs/{run_id}/unapprove")

    notes = client.get(f"/api/runs/{run_id}").json()["notes"]
    withdrawn = [n for n in notes if n["code"] == "approval.withdrawn"]
    assert len(withdrawn) == 1
    assert "tester@appedology.com" in withdrawn[0]["text"]


def test_a_run_that_is_not_approved_cannot_be_unapproved(client):
    run_id = _finished_run()
    r = client.post(f"/api/runs/{run_id}/unapprove")
    assert r.status_code == 409 and "not approved" in r.json()["detail"]


def test_it_can_be_approved_again_afterwards(client):
    run_id = _finished_run()
    client.post(f"/api/runs/{run_id}/approve")
    client.post(f"/api/runs/{run_id}/unapprove")
    assert client.post(f"/api/runs/{run_id}/approve").status_code == 200


def test_deleting_a_run_removes_it_and_everything_it_recorded(client):
    from sqlalchemy import select
    from app.db.models import RunFigure, RunNote, RunTable
    from app.db.session import session

    run_id = _finished_run()
    r = client.delete(f"/api/runs/{run_id}")
    assert r.status_code == 200
    assert r.json()["deleted_by"] == "tester@appedology.com"

    assert client.get(f"/api/runs/{run_id}").status_code == 404
    with session() as s:
        for model in (RunNote, RunFigure, RunTable):
            assert s.execute(select(model).where(model.run_id == run_id)
                             ).scalars().all() == []


def test_deleting_a_run_leaves_the_uploaded_files_alone(client):
    """The files belong to the week and to the other report as well. Deleting
    a build must never cost you the inputs."""
    from sqlalchemy import select
    from app.db.models import Upload
    from app.db.session import session

    upload(client, "2026-W35", "Supporting File.xlsx")
    client.delete(f"/api/runs/{_finished_run()}")
    with session() as s:
        assert len(s.execute(select(Upload)).scalars().all()) == 1


def test_a_running_build_cannot_be_deleted(client):
    run_id = _finished_run(status="running")
    r = client.delete(f"/api/runs/{run_id}")
    assert r.status_code == 409 and "still running" in r.json()["detail"]


def test_deleting_a_run_that_is_not_there_is_a_404(client):
    assert client.delete("/api/runs/9999").status_code == 404


def test_deleting_keeps_a_result_another_run_still_points_at(client):
    """Results are addressed by the hash of their bytes, so two identical
    builds share one file. Removing the blob with the first run would leave
    the second one pointing at nothing."""
    from app.config import settings
    from app.storage.files import FileStore

    first, second = _finished_run(), _finished_run(week="2026-W36")
    store = FileStore(settings.results_dir)
    path = store.root / "aa" / ("a" * 64 + ".parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"pretend parquet")

    assert client.delete(f"/api/runs/{first}").json()["files_removed"] == 0
    assert path.exists()                    # the second run still needs it
    assert client.delete(f"/api/runs/{second}").json()["files_removed"] == 1
    assert not path.exists()


def test_deleting_and_unapproving_need_an_account(client):
    bare = TestClient(client.app)
    assert bare.delete("/api/runs/1").status_code == 401
    assert bare.post("/api/runs/1/unapprove").status_code == 401


def test_run_history_carries_the_report_and_is_bounded_by_weeks(client):
    _finished_run(week="2026-W35", report="gfs")
    _finished_run(week="2026-W35", report="all_providers")
    rows = client.get("/api/runs").json()
    assert {r["report_key"] for r in rows} == {"gfs", "all_providers"}
    assert all(r["report"] for r in rows)
    assert client.get("/api/runs?weeks=1").status_code == 200
    assert client.get("/api/runs?weeks=0").status_code == 422
