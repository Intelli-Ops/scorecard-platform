"""Tests for the filtered Case AR pivot."""
import polars as pl
import pytest
import yaml

from app.reports import get as get_report
from app.service.case_ar_view import case_ar


@pytest.fixture
def rules():
    return yaml.safe_load(get_report("gfs").rules_path.read_text())


def raw():
    rows = [
        (1, 10, "Artheon", "CIC Pending", "Valid", "ACTIVE", "Open", 100.25, 10.10),
        (2, 10, "Artheon", "CIC Pending", "Invalid", "Closed", "Closed", 50.50, 0.0),
        (3, 20, "Med-Legal", "CIC Pending", "Valid", "ACTIVE", "Open", 20.01, 5.05),
    ]
    return pl.DataFrame(
        [(*r[:7], r[7], r[8], 0.0, 0.0, r[7] - r[8]) for r in rows],
        schema=["CASEID", "BUSINESSREGID", "Group", "Closing Order", "Case_Validity",
                "FileStatus", "FileStatus2", "BILLED", "PAID", "WRITEOFF", "ADVANCE",
                "OUTSTANDING"], orient="row")


def test_unfiltered_ends_in_an_exact_grand_total(rules):
    out = case_ar(raw(), rules, "gfs", {})
    total = out["rows"][-1]
    assert total["Case_Validity"] == "Grand Total"
    assert total["# Of Cases"] == 3
    assert total["BILLED"] == pytest.approx(170.76)       # to the cent, not rounded
    assert {f["key"] for f in out["filters"]} == {"group", "file_status", "validity"}


def test_each_filter_narrows_the_pivot(rules):
    out = case_ar(raw(), rules, "gfs", {"group": "Artheon", "validity": "Valid"})
    assert out["matched"] == 1 and out["of"] == 3
    assert out["rows"][-1]["BILLED"] == pytest.approx(100.25)
    out = case_ar(raw(), rules, "gfs", {"file_status": "Closed"})
    assert out["rows"][-1]["# Of Cases"] == 1


def test_a_filter_with_several_values_keeps_rows_matching_any(rules):
    out = case_ar(raw(), rules, "gfs", {"group": ["Artheon", "Med-Legal"]})
    assert out["matched"] == 3
    out = case_ar(raw(), rules, "gfs", {"group": ["Artheon", "Med-Legal"],
                                        "validity": ["Valid"]})
    assert out["matched"] == 2
    assert out["rows"][-1]["BILLED"] == pytest.approx(120.26)
    assert case_ar(raw(), rules, "gfs", {"group": []})["matched"] == 3


def test_gfs_file_status_is_open_or_closed(rules):
    """GFS's File status filter is FileStatus2, not the raw FileStatus."""
    out = case_ar(raw(), rules, "gfs", {})
    status = next(f for f in out["filters"] if f["key"] == "file_status")
    assert status["values"] == ["Closed", "Open"]
    out = case_ar(raw(), rules, "gfs", {"file_status": "Open"})
    assert out["rows"][-1]["# Of Cases"] == 2


def test_all_providers_filters_on_group_and_validity_only():
    ap_rules = yaml.safe_load(get_report("all_providers").rules_path.read_text())
    headers = ap_rules["case_ar"]["raw_data_headers"]
    row = [1, "Dr A", 10, "Artheon", "WC", "CIC Pending", "Valid", "ACTIVE",
           100.25, 10.0, 0.0, 0.0, 90.25]
    ap_raw = pl.DataFrame([row], schema=headers, orient="row")
    out = case_ar(ap_raw, ap_rules, "all_providers", {})
    assert [f["key"] for f in out["filters"]] == ["group", "validity"]
    assert out["rows"][-1]["File Status"] == "Grand Total"


def test_all_providers_case_ar_has_the_sheets_headings_highest_outstanding_first():
    ap_rules = yaml.safe_load(get_report("all_providers").rules_path.read_text())
    headers = ap_rules["case_ar"]["raw_data_headers"]
    rows = [[1, "Dr A", 10, "Artheon", "WC", "x", "Valid", "Closed", 50.0, 49.0, 0.0, 0.0, 1.0],
            [2, "Dr A", 10, "Artheon", "WC", "x", "Valid", "Verified", 90.0, 0.0, 0.0, 0.0, 90.0],
            [3, "Dr A", 10, "Artheon", "WC", "x", "Valid", "Open", 20.0, 0.0, 0.0, 0.0, 20.0]]
    out = case_ar(pl.DataFrame(rows, schema=headers, orient="row"), ap_rules,
                  "all_providers", {})
    assert out["columns"] == ["File Status", "Count of Cases", "BILLED", "Paid",
                              "Write Off", "Advance", "Outstanding"]
    assert [r["File Status"] for r in out["rows"]] == ["Verified", "Open", "Closed",
                                                       "Grand Total"]
    assert out["rows"][-1]["Outstanding"] == 111.0


def test_nothing_matching_is_an_empty_table(rules):
    out = case_ar(raw(), rules, "gfs", {"group": "Nobody"})
    assert out["rows"] == [] and out["matched"] == 0


def test_gfs_owner_case_ar_step_takes_bayco_with_gfs_gfs_spv_and_med_legal():
    """PHASE 1: the owners whose cases make up the GFS case list (Bayco since November 2026)."""
    from app.reports import load_rules
    from app.reports.gfs.core.case_ar import gfs_case_ids
    gfs_rules = load_rules("gfs")
    owners = ["GFS", "GFS-SPV", "Med Legal", "Bayco", "Javlin", "Russman"]
    owner_ar = pl.DataFrame({"CASEID": list(range(1, 7)), "OWNER NAME": owners,
                             "CASETYPE": ["Workers Compensation"] * 6})
    assert sorted(gfs_case_ids(owner_ar, gfs_rules)["CASEID"].to_list()) == [1, 2, 3, 4]
