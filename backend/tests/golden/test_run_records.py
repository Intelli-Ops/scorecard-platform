"""A run must record what it actually read.

Written after a real bug. The delta workbooks are read once per SHEET - three
sheets out of two files - and the run recorded reads by sheet key while the
uploads were keyed by workbook. The lookup never matched, so the audit trail
showed the two biggest delta files as contributing zero rows.

The numbers in the report were unaffected, which is exactly why it was easy to
miss: everything matched the golden master while the record of where those
numbers came from was quietly wrong. That is the failure this file exists to
catch.
"""
from __future__ import annotations
import datetime as dt
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.service import runner
from app.service.ingest import ingest
from app.storage.files import FileStore

LEGACY = Path(os.environ.get(
    "GFS_LEGACY_ROOT",
    r"C:\Users\ali.asghar\OneDrive - MSFT\Desktop\gfs-automation"))
WEEK = os.environ.get("GFS_GOLDEN_WEEK", "2026-W35")


@pytest.fixture(scope="module")
def executed(tmp_path_factory):
    week_dir = LEGACY / "inputs" / WEEK
    if not week_dir.exists():
        pytest.skip(f"no legacy inputs at {week_dir}")

    tmp = tmp_path_factory.mktemp("run")
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    store, results = FileStore(tmp / "objects"), FileStore(tmp / "results")

    with sessionmaker(bind=engine, future=True, expire_on_commit=False)() as s:
        ingest(s, store, WEEK,
               sorted(p for p in week_dir.iterdir() if p.is_file()),
               for_report="gfs", uploaded_by="test")
        run = runner.execute(s, store, "gfs", WEEK,
                             as_of=dt.date(2026, 9, 3), results=results)
        yield s, run


def test_every_file_read_is_recorded_against_its_upload(executed):
    _, run = executed
    assert len(run.inputs) == 9
    silent = [ri.upload.filename for ri in run.inputs if not ri.rows_read]
    assert not silent, f"recorded as contributing no rows: {silent}"


def test_delta_workbooks_report_all_their_sheets(executed):
    """MLCR carries two sheets - Med-Legal and IMR - and both must be counted."""
    _, run = executed
    rows = {ri.upload.source_key: ri.rows_read for ri in run.inputs}
    assert rows["delta_wc"] == 96_941
    assert rows["delta_mlcr"] == 40_203 + 20_376


def test_notes_are_stored_with_their_code_and_numbers(executed):
    _, run = executed
    by_code = {n.code: n for n in run.notes}
    dropped = by_code["ar_rows_dropped_no_group"]
    assert dropped.severity == "warning"
    assert dropped.detail["rows"] == 112_960
    assert by_code["kpi_block_without_source"].severity == "action"
    assert by_code["kpi_block_without_source"].detail["blocks"] == ["10635 (DDEL)"]


def test_a_run_waits_for_a_person(executed):
    """Finishing is not approving - the STEP 4 look is a required step."""
    s, run = executed
    assert run.status == "review"
    runner.approve(s, run, by="tester")
    assert run.status == "approved" and run.approved_by == "tester"
