"""Tests for the review screen data."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Run, RunNote, RunTable
from app.reports.notes import ACTION, WARNING, INFO, info, warning, action, sort_notes
from app.service.review import review, previous_run, history


@pytest.fixture
def db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True, expire_on_commit=False)() as s:
        yield s


def add_run(db, week, notes=(), tables=(), status="approved", report="gfs"):
    run = Run(report_key=report, week=week, status=status, seconds=1.0)
    db.add(run)
    db.flush()
    for i, n in enumerate(notes):
        db.add(RunNote(run_id=run.id, seq=i, code=n.code, severity=n.severity,
                       text=n.message, detail=n.detail))
    for name, rows in tables:
        db.add(RunTable(run_id=run.id, name=name, rows=rows, columns=12,
                        sha256="0" * 64, bytes=100))
    db.flush()
    db.refresh(run)
    return run


def test_severity_sorts_the_serious_to_the_top():
    notes = [info("a", "a"), action("b", "b"), warning("c", "c")]
    assert [n.severity for n in sort_notes(notes)] == [ACTION, WARNING, INFO]


def test_a_note_still_reads_as_its_sentence():
    """The .bat pipeline's wording is preserved - str() is the message."""
    n = warning("ar_rows_dropped_no_group", "112,960 AR rows dropped", rows=112960)
    assert str(n) == "112,960 AR rows dropped"
    assert n.detail["rows"] == 112960


def test_first_run_has_nothing_to_compare_against(db):
    run = add_run(db, "2026-W35", [warning("x", "something", rows=5)])
    out = review(db, run)
    assert out["compared_with"] is None
    assert out["notes"][0]["change"] == "no previous run"


def test_previous_run_is_the_earlier_week_not_the_earlier_row(db):
    add_run(db, "2026-W36")           # inserted first, but a LATER week
    older = add_run(db, "2026-W34")
    this = add_run(db, "2026-W35")
    assert previous_run(db, this).id == older.id


def test_failed_runs_are_not_used_as_the_comparison(db):
    good = add_run(db, "2026-W33")
    add_run(db, "2026-W34", status="failed")
    this = add_run(db, "2026-W35")
    assert previous_run(db, this).id == good.id


def test_new_changed_resolved_and_unchanged_are_distinguished(db):
    add_run(db, "2026-W34", [
        warning("dropped", "900 rows dropped", rows=900),
        warning("steady", "same every week", rows=7),
        warning("goes_away", "will not recur", rows=1),
    ])
    this = add_run(db, "2026-W35", [
        warning("dropped", "112,960 rows dropped", rows=112960),
        warning("steady", "same every week", rows=7),
        action("brand_new", "a KPI block has no source", blocks=["10635 (DDEL)"]),
    ])

    by_code = {n["code"]: n for n in review(db, this)["notes"]}
    assert by_code["dropped"]["change"] == "changed"
    assert by_code["dropped"]["moved"]["rows"] == {"was": 900, "now": 112960}
    assert by_code["steady"]["change"] == "same as last week"
    assert by_code["brand_new"]["change"] == "new this week"
    assert by_code["goes_away"]["change"] == "resolved since last week"


def test_needs_attention_flags_an_action_note(db):
    run = add_run(db, "2026-W35", [action("kpi", "a figure is missing")])
    assert review(db, run)["needs_attention"] is True


def test_needs_attention_is_false_when_nothing_is_new_or_serious(db):
    add_run(db, "2026-W34", [warning("steady", "same", rows=7)])
    this = add_run(db, "2026-W35", [warning("steady", "same", rows=7)])
    assert review(db, this)["needs_attention"] is False


def test_table_row_counts_are_compared_with_last_week(db):
    add_run(db, "2026-W34", tables=[("raw_data", 278_000)])
    this = add_run(db, "2026-W35", tables=[("raw_data", 278_930)])
    t = review(db, this)["tables"][0]
    assert t["rows_last_week"] == 278_000
    assert t["change"] == 930



def test_history_lists_runs_newest_first_with_their_counts(db):
    add_run(db, "2026-W34", [warning("w", "w")])
    add_run(db, "2026-W35", [action("a", "a"), warning("w", "w")])
    rows = history(db, "gfs")
    assert [r["week"] for r in rows] == ["2026-W35", "2026-W34"]
    assert rows[0]["actions"] == 1 and rows[0]["warnings"] == 1


def test_history_says_which_scorecard_each_row_is(db):
    """Both reports share one list, so a row that does not name itself is a row
    you cannot tell from the other report's run of the same week."""
    add_run(db, "2026-W35", report="gfs")
    row = history(db, "gfs")[0]
    assert row["report_key"] == "gfs"
    assert row["report"]                    # the human label, not the key


def test_history_is_bounded_by_weeks_and_not_by_rows(db):
    """A rebuilt week must not push an older week off the list."""
    for n in range(21, 36):
        add_run(db, f"2026-W{n}")
    for _ in range(3):
        add_run(db, "2026-W35")             # rebuilt three more times

    rows = history(db, "gfs", weeks=12)
    weeks = sorted({r["week"] for r in rows}, reverse=True)
    assert len(weeks) == 12
    assert weeks[0] == "2026-W35" and weeks[-1] == "2026-W24"
    assert sum(1 for r in rows if r["week"] == "2026-W35") == 4


def test_routine_row_drops_are_not_on_the_review(db):
    """Runs stored before the review was trimmed still carry them; they stay hidden."""
    run = add_run(db, "2026-W35", [
        warning("ar_rows_dropped_no_group", "112,960 AR rows dropped", rows=112960),
        info("delta_partial_paid_rewritten", "3 Partial Paid rows", count=3),
        warning("delta_duplicate_case_ids", "1 duplicate case id(s)", count=1)])
    out = review(db, run)
    assert [n["code"] for n in out["notes"]] == ["delta_duplicate_case_ids"]
    assert out["notes"][0]["section"] == "duplicates"
    assert out["note_counts"][WARNING] == 1


def test_each_new_provider_is_compared_on_its_own(db):
    """Two new providers share a code; last week's one is not 'new' again."""
    add_run(db, "2026-W37", [action("kpi_new_provider", "A", block="DOR", provider="A",
                                    value=1)])
    this = add_run(db, "2026-W38", [
        action("kpi_new_provider", "A", block="DOR", provider="A", value=1),
        action("kpi_new_provider", "B", block="DOR", provider="B", value=2)])
    change = {n["detail"].get("provider"): n["change"] for n in review(db, this)["notes"]}
    assert change == {"A": "same as last week", "B": "new this week"}
