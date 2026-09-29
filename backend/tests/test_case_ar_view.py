"""The filtered Case AR tab: the pivot rebuilt from Raw Data, with a Grand Total."""
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
        # CASEID, REGID, Group, Closing Order, Validity, FileStatus, FileStatus2, money
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


def test_nothing_matching_is_an_empty_table(rules):
    out = case_ar(raw(), rules, "gfs", {"group": "Nobody"})
    assert out["rows"] == [] and out["matched"] == 0
