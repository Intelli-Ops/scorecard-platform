"""A sheet is found even when the client's file names it with stray spaces or capitals."""
from __future__ import annotations
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.reports.reading import find_sheet, load_sheet
from app.service.ingest import ingest
from app.storage.files import FileStore

WEEK = "2026-W41"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def workbook(path: Path, sheets: dict[str, list[list]]) -> Path:
    """The smallest .xlsx that holds `sheets` ({name: rows}), for a test."""
    def cell(v) -> str:
        if isinstance(v, (int, float)):
            return f"<c><v>{v}</v></c>"
        return f'<c t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'

    names = list(sheets)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType='
                             '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(names) + 1))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PKG}">'
                   f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
                   + "".join(f'<sheet name={quoteattr(n)} sheetId="{i}" r:id="rId{i}"/>'
                             for i, n in enumerate(names, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PKG}">'
                   + "".join(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" '
                             f'Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(names) + 1))
                   + "</Relationships>")
        for i, n in enumerate(names, 1):
            rows = "".join("<row>" + "".join(cell(v) for v in r) + "</row>"
                           for r in sheets[n])
            z.writestr(f"xl/worksheets/sheet{i}.xml",
                       f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}">'
                       f"<sheetData>{rows}</sheetData></worksheet>")
    return path


PAYMENTS = [["BUSINESSREGID", "CASEID", "CASETYPE", "PAYMENT_TYPE", "PAYMENT", "PAYMENTDATE"],
            [233, 1, "WC", "BILLING", 100.5, "2026-10-01"]]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True, expire_on_commit=False)() as s:
        yield s


def test_the_exact_name_wins_then_one_differing_only_in_spaces_or_case():
    assert find_sheet(["KPI High-Level", "KPI High-Level "], "KPI High-Level ") == "KPI High-Level "
    assert find_sheet(["Case AR", "KPI High-Level "], "KPI High-Level") == "KPI High-Level "
    assert find_sheet(["  detail  payment report "], "Detail Payment Report") == "  detail  payment report "
    assert find_sheet(["Sheet1"], "Sheet2") is None
    assert find_sheet(["Sheet1"], 0) == 0                       # a position, not a name


@pytest.mark.parametrize("named", ["Detail Payment Report ", "  Detail Payment Report",
                                   "Detail Payment Report", "DETAIL PAYMENT REPORT"])
def test_a_payment_report_is_taken_however_its_sheet_name_is_spaced(db, tmp_path, named):
    f = workbook(tmp_path / "payments.xlsx", {named: PAYMENTS})
    r = ingest(db, FileStore(tmp_path / "objects"), WEEK, [f], as_source="payment_detail")
    assert [a.source_key for a in r.accepted] == ["payment_detail"], r.rejected


def test_a_payment_report_without_the_sheet_is_still_refused(db, tmp_path):
    f = workbook(tmp_path / "payments.xlsx", {"Summary": PAYMENTS})
    r = ingest(db, FileStore(tmp_path / "objects"), WEEK, [f], as_source="payment_detail")
    (_, why), = r.rejected
    assert "no sheet named 'Detail Payment Report'" in why and "'Summary'" in why


def test_the_build_reads_a_sheet_whose_name_ends_in_a_space(tmp_path):
    f = workbook(tmp_path / "payments.xlsx", {"Other": [["x"], [1]],
                                             "Detail Payment Report ": PAYMENTS})
    df = load_sheet(f, "Detail Payment Report", header_row=0)
    assert df.columns == PAYMENTS[0] and df.height == 1


SPACED = [[" BUSINESSREGID", "CASEID ", "CASETYPE", "PAYMENT_TYPE", " PAYMENT ", "PAYMENTDATE"],
          [233, 1, "WC", "BILLING", 100.5, "2026-10-01"]]


def test_a_payment_report_with_spaces_round_its_headings_is_taken(db, tmp_path):
    f = workbook(tmp_path / "payments.xlsx", {"Detail Payment Report": SPACED})
    r = ingest(db, FileStore(tmp_path / "objects"), WEEK, [f], as_source="payment_detail")
    assert [a.source_key for a in r.accepted] == ["payment_detail"], r.rejected


def test_the_build_reads_spaced_headings_under_their_plain_names(tmp_path):
    from app.reports.reading import tidy_columns
    f = workbook(tmp_path / "payments.xlsx", {"Detail Payment Report": SPACED})
    df = load_sheet(f, "Detail Payment Report", header_row=0)
    assert df.columns == [column.strip() for column in SPACED[0]]
    picked = load_sheet(f, "Detail Payment Report", header_row=0,
                        use_columns=["PAYMENT", "CASEID"])
    assert picked.columns == ["CASEID", "PAYMENT"] and picked["PAYMENT"][0] == 100.5
    import polars as pl
    clash = tidy_columns(pl.DataFrame({"PAYMENT": [1], " PAYMENT ": [2]}))
    assert clash.columns == ["PAYMENT", " PAYMENT "]               # left alone, not lost
