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
        "Hearing Calendar.xlsx": "hearing_calendar",
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
    ingest(db, store, WEEK, [make(tmp_path, "Hearing Calendar.xlsx", b"shared")])
    for key in ("gfs", "all_providers"):
        got = latest_uploads(db, get(key), WEEK)
        assert "hearing_calendar" in got
        assert got["hearing_calendar"].report_key is None


def test_identical_bytes_are_stored_once(db, store, tmp_path):
    """Thursday's shared files are usually byte-identical to Tuesday's."""
    a = make(tmp_path / "a", "Hearing Calendar.xlsx", b"same bytes")
    b = make(tmp_path / "b", "Hearing Calendar.xlsx", b"same bytes")
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
    ingest(db, store, WEEK, [make(tmp_path, "Hearing Calendar.xlsx")])
    st = week_status(db, WEEK)["reports"]["gfs"]
    assert st["ready"] is True and st["complete"] is False
    assert "Combined Owner Case AR" in st["missing"]
    assert "Hearing Calendar" not in st["missing"]


def test_stored_bytes_can_be_proved_unchanged(store, tmp_path):
    """The hash is the upload check: same address means the same bytes."""
    stored = store.put(make(tmp_path, "Hearing Calendar.xlsx", b"payload"))
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


def test_the_comments_copies_feed_gfs_only(db, store, tmp_path):
    names = ["Delta WC 09.28.2026.xlsb", "Delta WC 09.28.2026 - comments.xlsb"]
    ingest(db, store, WEEK, [make(tmp_path, n, n.encode()) for n in names])
    gfs = latest_uploads(db, get("gfs"), WEEK)
    ap = latest_uploads(db, get("all_providers"), WEEK)
    assert gfs["delta_wc"].filename == names[0]
    assert gfs["delta_wc_comments"].filename == names[1]
    assert ap["delta_wc"].filename == names[0] and "delta_wc_comments" not in ap
    st = week_status(db, WEEK)["reports"]["gfs"]
    assert not any("WC - comments" in m for m in st["missing"])
    assert any("MLCR - comments" in m for m in st["missing"])


def test_a_build_made_without_some_files_names_them(db, store, tmp_path):
    from app.service import runner
    ingest(db, store, WEEK, [make(tmp_path, "Hearing Calendar.xlsx")])
    run = runner.queue(db, "gfs", WEEK)
    missing = runner.missing_inputs(run)
    assert "Combined Owner Case AR" in missing and "Hearing Calendar" not in missing
    assert any(m.startswith("KPI numbers") for m in missing)


# Uploading a file as one input, whatever it is called.

SQL_HEADER = b"ProviderID,Type,DocumentMonth,DocumentType,#ofcases\n"


def test_a_file_of_any_name_is_taken_as_the_input_it_was_sent_as(db, store, tmp_path):
    f = make(tmp_path / "in", "export from superset.csv", SQL_HEADER + b"233,GFS,2026-10,BillingDocs,4\n")
    assert classify(f) is None                      # its name alone says nothing
    r = ingest(db, store, WEEK, [f], as_source="document_log")
    assert [a.source_key for a in r.accepted] == ["document_log"]
    assert latest_uploads(db, get("gfs"), WEEK)["document_log"].filename == f.name


def test_a_file_missing_the_columns_the_build_reads_is_refused_and_says_which(db, store, tmp_path):
    f = make(tmp_path / "in", "export.csv", b"ProviderID,type,DocumentMonth\n1,GFS,2026-10\n")
    r = ingest(db, store, WEEK, [f], as_source="document_log")
    assert not r.accepted
    (_, why), = r.rejected
    assert "'DocumentType'" in why and "'#ofcases'" in why
    assert "'Type' (the file has 'type')" in why
    assert not db.query(Upload).count()


def test_the_wrong_kind_of_file_is_refused_before_it_is_opened(db, store, tmp_path):
    f = make(tmp_path / "in", "hearings.csv", SQL_HEADER)
    (_, why), = ingest(db, store, WEEK, [f], as_source="hearing_calendar").rejected
    assert "must be a .xlsx or .xlsb file" in why


def test_a_damaged_workbook_is_refused(db, store, tmp_path):
    f = make(tmp_path / "in", "hearings.xlsx", b"not a workbook")
    (_, why), = ingest(db, store, WEEK, [f], as_source="hearing_calendar").rejected
    assert "could not be opened as a spreadsheet" in why


def test_every_input_has_sheets_to_check():
    from app.reports import REPORTS, templates
    for report in REPORTS.values():
        for spec in report.sources:
            assert templates.requirements(spec.key, report.key), spec.key
    assert "Lien Filed" in templates.requirements("custom_case_ar", "gfs")["Sheet1"]
    assert "Lien Filed" not in templates.requirements("custom_case_ar", "all_providers")["Sheet1"]


def test_the_upload_screen_names_each_missing_input_by_key(db):
    missing = week_status(db, WEEK)["reports"]["gfs"]["missing_files"]
    keys = {m["key"] for m in missing}
    assert {"document_log", "owner_case_ar", "delta_wc_comments"} <= keys
    assert next(m for m in missing if m["key"] == "owner_case_ar")["per_report"]


def test_the_owner_case_ar_needs_its_owner_column_for_either_report():
    from app.reports import templates
    for report in ("gfs", "all_providers"):
        assert "OWNER NAME" in templates.requirements("owner_case_ar", report)["Sheet1"]
    banned, providers = templates._delta_checks("delta_wc", None)
    assert "Med-Legal Delta" in banned
    assert providers["WC Delta"][2] == {300, 309, 239}
    _, providers = templates._delta_checks("delta_mlcr", None)
    assert providers["Med-Legal Delta"][1] == {300, 309}
