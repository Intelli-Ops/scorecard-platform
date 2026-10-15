"""Tests for the Ongoing DOR columns looked up from the comments files."""
from __future__ import annotations

import polars as pl

from app.reports import load_rules
from app.reports.gfs.core.delta import DeltaReport, attach_comments

COLS = ["Ongoing DOR Status", "Ongoing DOR Details"]


def _delta():
    return pl.DataFrame({
        "Case_ID": [1, 2, 3, 1, 9],
        "_source_sheet": ["WC Delta", "WC Delta", "Med-Legal Delta",
                          "Med-Legal Delta", "IMR Delta"],
        "Settlement_Amount": [10.0, 20.0, 30.0, 40.0, 50.0],
    })


def _sheet(ids, statuses):
    return pl.DataFrame({"Case Id": [float(i) for i in ids],     # Excel's 1.0
                         COLS[0]: statuses,
                         COLS[1]: [f"detail {s}" for s in statuses]})


def test_each_row_takes_the_comment_from_its_own_sheet():
    rep = DeltaReport()
    out = attach_comments(_delta(), {
        "WC Delta": _sheet([1, 2, 2], ["wc-1", "wc-2 first", "wc-2 second"]),
        "Med-Legal Delta": _sheet([1], ["ml-1"]),
    }, load_rules("gfs"), rep)

    assert out.height == 5
    assert out["Settlement_Amount"].to_list() == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert out[COLS[0]].to_list() == ["wc-1", "wc-2 first", None, "ml-1", None]
    assert out[COLS[1]][0] == "detail wc-1"
    assert rep.comments_found == {"WC Delta": (2, 2), "Med-Legal Delta": (1, 2),
                                  "IMR Delta": (0, 1)}
    assert rep.comment_rows == {"WC Delta": 2, "Med-Legal Delta": 1}
    assert "_commented" not in out.columns


def test_without_the_files_the_columns_are_there_and_blank():
    rep = DeltaReport()
    out = attach_comments(_delta(), {}, load_rules("gfs"), rep)
    assert all(out[c].null_count() == out.height for c in COLS)
    assert rep.comments_found == {}


def test_the_review_says_what_matched_and_what_is_missing():
    from app.reports.gfs.pipeline import comment_notes
    rep = DeltaReport()
    attach_comments(_delta(), {"WC Delta": _sheet([1, 2], ["a", "b"])},
                    load_rules("gfs"), rep)
    notes = {(n.code, n.detail["block"]): n for n in comment_notes(rep, load_rules("gfs"))}
    assert notes[("delta_comments_matched", "WC Delta")].severity == "info"
    assert notes[("delta_comments_missing", "Med-Legal Delta")].severity == "warning"
