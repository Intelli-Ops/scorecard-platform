"""All Providers builds record the client's row order, so the screens can follow the workbook."""
from __future__ import annotations

from app.reports import load_rules
from app.reports.all_providers.core.kpi import kpi_layout
from app.reports.all_providers.pipeline import sheet_layout
from app.service.figures import layout_records


def test_the_layout_follows_the_week_41_workbook():
    rules = load_rules("all_providers")
    layout = sheet_layout(rules, kpi_layout(rules))
    assert layout["kpi"] == ["SBR", "PMR", "DOR", "Med Legal", "Enforcement Of Agreement",
                             "DDE", "Medical Index", "10635 (DDEL)", "NTP"]
    assert layout["kpi/Med Legal"] == ["NOI (COST)", "NOI for Payment", "Cost Petition",
                                       "Cost Petition (DOR)"]
    assert layout["In House"][:3] == ["Med-Legal", "Medvantage", "Artheon"]
    assert layout["collections"][:3] == ["Russman", "Medvantage", "Advance Care"]
    assert layout["delta"][0] == "365 Medical" and layout["delta"][-1] == "Dr Dorian"
    assert layout["cp"] == ["Med-Legal"]


def test_layout_records_keep_each_rows_place():
    assert layout_records({"Board": ["B", "A"], "cp": ["Med-Legal"]}) == [
        {"section": "Board", "row": "B", "order": 0},
        {"section": "Board", "row": "A", "order": 1},
        {"section": "cp", "row": "Med-Legal", "order": 0},
    ]
