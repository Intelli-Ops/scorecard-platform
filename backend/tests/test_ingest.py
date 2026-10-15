"""Tests for file storage and upload classification."""
from __future__ import annotations
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Upload
from app.reports import get
from app.service.ingest import ingest, latest_uploads, week_status, classify
from app.storage.files import FileStore

WEEK = "2026-W36"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True, expire_on_commit=False)() as s:
        yield s


@pytest.fixture
def store(tmp_path):
    return FileStore(tmp_path / "objects")


def make(dirpath: Path, name: str, body: bytes = b"x") -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / name
    p.write_bytes(body)
    return p


def test_classifies_the_nine_by_filename(tmp_path):
    """The .bat pipeline's matching, unchanged: fragments, any case, dates fine."""
    cases = {
        "Combined Owner Case AR.xlsb": "owner_case_ar",
        "Combined Custom  Case AR.xlsb": "custom_case_ar",
        "Master Settlement & Collection Delta WC 08.31.2026.xlsb": "delta_wc",
        "Master Settlement & Collection Delta MLCR 08.31.26.xlsb": "delta_mlcr",
        "Payment Detail Report for 01st to 28th August - 2026.xlsx": "payment_detail",
        "Supporting File.xlsx": "supporting",
        "Hearing Calendar (Jan 2024 - 28th August 2026) - Updated.xlsx": "hearing_calendar",
        "sqllab_document_log_query_20260901T060517.csv": "document_log",
        "KPI-numbers.xlsx": "kpi_numbers",
    }
    for name, expected in cases.items():
        spec = classify(make(tmp_path, name))
        assert spec is not None and spec.key == expected, name


def test_ignores_files_that_are_not_inputs(tmp_path):
    """Delivered workbooks live alongside the inputs and must not be read."""
    assert classify(make(tmp_path, "GFS - Weekly Scorecard (Week -35) 2026.xlsx")) is None
    assert classify(make(tmp_path, "GFS Formate.xlsx")) is None


def test_case_ar_is_refused_without_a_report(db, store, tmp_path):
    """Guessing would attach Thursday's case activity to Tuesday's report."""
    res = ingest(db, store, WEEK, [make(tmp_path, "Combined Owner Case AR.xlsb")])
    assert not res.accepted
    assert "differs per report" in res.rejected[0][1]


def test_tuesday_and_thursday_case_ars_stay_apart(db, store, tmp_path):
    """The whole point of the per-report column."""
    tue = make(tmp_path / "tue", "Combined Owner Case AR.xlsb", b"tuesday copy")
    thu = make(tmp_path / "thu", "Combined Owner Case AR.xlsb", b"thursday copy")
    ingest(db, store, WEEK, [tue], for_report="gfs")
    ingest(db, store, WEEK, [thu], for_report="all_providers")

    gfs = latest_uploads(db, get("gfs"), WEEK)["owner_case_ar"]
    ap = latest_uploads(db, get("all_providers"), WEEK)["owner_case_ar"]

    assert gfs.sha256 != ap.sha256
    assert store.path(gfs.sha256, ".xlsb").read_bytes() == b"tuesday copy"
    assert store.path(ap.sha256, ".xlsb").read_bytes() == b"thursday copy"


def test_shared_files_serve_both_reports(db, store, tmp_path):
    """Seven files are uploaded once, not once per report."""
    ingest(db, store, WEEK, [make(tmp_path, "Supporting File.xlsx", b"shared")])
    for key in ("gfs", "all_providers"):
        got = latest_uploads(db, get(key), WEEK)
        assert "supporting" in got
        assert got["supporting"].report_key is None


def test_identical_bytes_are_stored_once(db, store, tmp_path):
    """Thursday's shared files are usually byte-identical to Tuesday's."""
    a = make(tmp_path / "a", "Supporting File.xlsx", b"same bytes")
    b = make(tmp_path / "b", "Supporting File.xlsx", b"same bytes")
    first = ingest(db, store, WEEK, [a]).accepted[0]
    second = ingest(db, store, WEEK, [b]).accepted[0]

    assert first.sha256 == second.sha256
    assert second.deduplicated is True
    assert len(list(store.root.rglob("*.xlsx"))) == 1


def test_a_corrected_reupload_replaces_the_one_before_it(db, store, tmp_path):
    """The old copy is not kept to pile up - or to come back when the new one
    is removed."""
    ingest(db, store, WEEK,
           [make(tmp_path / "1", "Payment Detail Report.xlsx", b"first")])
    ingest(db, store, WEEK,
           [make(tmp_path / "2", "Payment Detail Report.xlsx", b"corrected")])

    latest = latest_uploads(db, get("gfs"), WEEK)["payment_detail"]
    assert store.path(latest.sha256, ".xlsx").read_bytes() == b"corrected"
    assert db.query(Upload).filter_by(source_key="payment_detail").count() == 1


def test_a_replaced_file_a_build_has_read_is_kept_for_that_build(db, store, tmp_path):
    """A run that already used the old file must still point at the old bytes."""
    from app.db.models import Run, RunInput
    ingest(db, store, WEEK,
           [make(tmp_path / "1", "Payment Detail Report.xlsx", b"first")])
    old = db.query(Upload).one()
    run = Run(report_key="gfs", week=WEEK, status="review")
    db.add(run)
    db.flush()
    db.add(RunInput(run_id=run.id, upload_id=old.id))
    db.flush()

    ingest(db, store, WEEK,
           [make(tmp_path / "2", "Payment Detail Report.xlsx", b"corrected")])
    assert db.query(Upload).filter_by(source_key="payment_detail").count() == 2
    assert store.path(old.sha256, ".xlsx").read_bytes() == b"first"
    latest = latest_uploads(db, get("gfs"), WEEK)["payment_detail"]
    assert store.path(latest.sha256, ".xlsx").read_bytes() == b"corrected"


def test_replacing_a_case_ar_leaves_the_other_reports_copy_alone(db, store, tmp_path):
    name = "Combined Owner Case AR.xlsb"
    ingest(db, store, WEEK, [make(tmp_path / "t", name, b"tuesday")], for_report="gfs")
    ingest(db, store, WEEK, [make(tmp_path / "h", name, b"thursday")],
           for_report="all_providers")
    ingest(db, store, WEEK, [make(tmp_path / "t2", name, b"tuesday, fixed")],
           for_report="gfs")
    assert {u.report_key for u in db.query(Upload)} == {"gfs", "all_providers"}
    assert db.query(Upload).count() == 2


def test_week_status_reports_what_is_still_needed(db, store, tmp_path):
    ingest(db, store, WEEK, [make(tmp_path, "Supporting File.xlsx")])
    st = week_status(db, WEEK)["reports"]["gfs"]
    assert st["ready"] is False
    assert "Combined Owner Case AR" in st["missing"]
    assert "Supporting File" not in st["missing"]


def test_stored_bytes_can_be_proved_unchanged(store, tmp_path):
    """The hash is the upload check: same address means the same bytes."""
    stored = store.put(make(tmp_path, "Supporting File.xlsx", b"payload"))
    assert store.verify(stored.sha256, ".xlsx")


def test_the_tuesday_comments_copies_are_not_taken_for_the_delta_data(tmp_path):
    """"Delta WC 09.28.2026 - comments.xlsb" holds every fragment of the Delta
    WC match."""
    cases = {
        "Master Settlement & Collection Delta WC 09.28.2026.xlsb": "delta_wc",
        "Master Settlement & Collection Delta WC 09.28.2026 - comments.xlsb":
            "delta_wc_comments",
        "Master Settlement & Collection Delta MLCR 09.28.2026.xlsb": "delta_mlcr",
        "Master Settlement & Collection Delta MLCR 09.28.2026 - Comments.xlsb":
            "delta_mlcr_comments",
    }
    for name, expected in cases.items():
        assert classify(make(tmp_path, name)).key == expected, name


def test_the_comments_copies_feed_gfs_only_and_are_optional(db, store, tmp_path):
    names = ["Delta WC 09.28.2026.xlsb", "Delta WC 09.28.2026 - comments.xlsb"]
    ingest(db, store, WEEK, [make(tmp_path, n, n.encode()) for n in names])
    gfs = latest_uploads(db, get("gfs"), WEEK)
    ap = latest_uploads(db, get("all_providers"), WEEK)
    assert gfs["delta_wc"].filename == names[0]
    assert gfs["delta_wc_comments"].filename == names[1]
    assert ap["delta_wc"].filename == names[0] and "delta_wc_comments" not in ap
    st = week_status(db, WEEK)["reports"]["gfs"]
    assert not any("comments" in m for m in st["missing"])
