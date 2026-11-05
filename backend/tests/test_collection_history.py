"""The collections history under the Collections tab: January to September 2026 as
migration 0008 loads them, then each finished month from its own last build."""
from __future__ import annotations

import polars as pl
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import session as db_session
from tests.accounts import account


@pytest.fixture
def client(tmp_path):
    settings.use(tmp_path / "data")
    db_session.reset()
    from app.db.session import create_all
    create_all()
    from app.main import app
    with TestClient(app) as c:
        c.headers.update(account(c, "tester@appedology.com", "APD-0001", role="admin"))
        yield c


def run(report_key, week, status="approved"):
    from app.db.models import Run
    from app.db.session import session
    with session() as s:
        r = Run(report_key=report_key, week=week, status=status)
        s.add(r)
        s.flush()
        return r.id


def test_the_migration_loads_january_to_september():
    import importlib
    m = importlib.import_module("app.db.migrations.versions.0008_collection_history")
    assert {r[0] for r in m.ROWS} == set(range(1, 10))
    assert round(sum(r[3] for r in m.ROWS), 2) == 27866480.19        # the file's Grand Total
    assert len({(r[0], r[1]) for r in m.ROWS}) == len(m.ROWS)        # one row per provider


def test_all_providers_shows_every_group_and_october_from_its_build(client, tmp_path,
                                                                     monkeypatch):
    october = run("all_providers", "2026-W42")
    run("all_providers", "2026-W43", status="failed")
    parquet = tmp_path / "oct.parquet"
    pl.DataFrame({"Group": ["Russman", "Russman", "Medvantage"], "Week": [1, 2, 2],
                  "PT": ["BILLING", "SETTLEMENT", "APPEAL"],
                  "Payment": [100.0, 20.0, 7.0]}).write_parquet(parquet)
    from app.service import collection_history
    monkeypatch.setattr(collection_history.runner, "table_path", lambda r, name: parquet)

    nov = run("all_providers", "2026-W45", status="review")
    h = client.get(f"/api/runs/{nov}/collections-history").json()
    assert [(m["month"], m["source"]) for m in h["months"]] == [
        *[(m, "file") for m in range(1, 10)], (10, "build")]
    assert h["months"][-1]["run_id"] == october
    totals = {(t["group"], t["month"]): t["amount"] for t in h["totals"]}
    assert totals[("Russman", 1)] == pytest.approx(1312779.88)   # FMR + DIMG
    assert totals[("Bayco", 1)] == pytest.approx(11230)
    assert totals[("Russman", 10)] == 120
    assert {(w["week"], w["pt"]) for w in h["weeks"] if w["group"] == "Russman"} == {
        (1, "BILLING"), (2, "SETTLEMENT")}
    assert h["order"][0] == "Russman"


def test_gfs_shows_only_the_groups_its_collections_list(client):
    nov = run("gfs", "2026-W45", status="review")
    h = client.get(f"/api/runs/{nov}/collections-history").json()
    groups = {t["group"] for t in h["totals"]}
    assert "Russman" not in groups and {"Medvantage", "Bayco", "Med-Legal"} <= groups
    assert h["order"][:2] == ["Med-Legal", "Medvantage"]
    assert [m["source"] for m in h["months"]] == ["file"] * 9    # no October build


def test_the_history_stops_before_the_month_being_reported(client):
    feb = run("all_providers", "2026-W07", status="review")
    h = client.get(f"/api/runs/{feb}/collections-history").json()
    assert [m["month"] for m in h["months"]] == [1]
