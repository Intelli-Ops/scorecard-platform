"""The sheets and columns each input must have, and a check of an uploaded file against them."""
from __future__ import annotations
from pathlib import Path

import fastexcel
import polars as pl

from . import REPORTS, load_rules

CSV = ""                          # the sheet name a CSV's one table goes by
# Raw Data columns the builds work out themselves rather than read from the Owner Case AR.
DERIVED = {"Group", "Closing Order", "Case_Validity", "FileStatus", "FileStatus2"}

# The two Case ARs share most columns. These are what tell them apart: the Owner one
# has OWNER NAME, the Custom one has the status columns, and neither has the other's.
OWNER_ONLY = ["OWNER NAME"]
CUSTOM_ONLY = ["Closing Order", "Case_Validity", "FileStatus"]
LOOKS_LIKE = {"owner_case_ar": (CUSTOM_ONLY, "the Combined Custom Case AR"),
              "custom_case_ar": (OWNER_ONLY, "the Combined Owner Case AR")}


def _add(need: dict, sheet: str, columns) -> None:
    cols = need.setdefault(sheet, [])
    cols.extend(c for c in columns if c not in cols)


def _for_report(source_key: str, report_key: str, rules: dict) -> dict[str, list[str]]:
    """{sheet: columns} that one report's build reads from `source_key`."""
    need: dict[str, list[str]] = {}
    ca, delta = rules.get("case_ar") or {}, rules.get("delta") or {}
    if source_key == "owner_case_ar":
        _add(need, "Sheet1", ["CASEID", "BUSINESSREGID", "CASETYPE", *OWNER_ONLY]
             + [c for c in ca.get("raw_data_group_by", []) if c not in DERIVED]
             + ca.get("raw_data_measures", []))
    elif source_key == "custom_case_ar":
        _add(need, "Sheet1", ["CASEID", *CUSTOM_ONLY]
             + (["Lien Filed"] if report_key == "gfs" else []))   # see gfs/readers.py
    elif source_key.startswith("delta_") and source_key.endswith("_comments"):
        book = source_key[len("delta_"):-len("_comments")]
        cc = delta.get("comments") or {}
        for b, sheet in (cc.get("sheets") or {}).values():
            if b == book:
                _add(need, sheet, [cc["key"], *cc["columns"]])
    elif source_key.startswith("delta_"):
        for spec in delta.get("sources", []):
            if f"delta_{spec['workbook']}" == source_key:
                _add(need, spec["sheet"], spec["columns"].values())
    elif source_key == "payment_detail":
        _add(need, rules["collections"]["sheet"],
             ["BUSINESSREGID", "CASEID", "CASETYPE", "PAYMENT_TYPE", "PAYMENT",
              "PAYMENTDATE"])
    elif source_key == "hearing_calendar":
        _add(need, "NOI, CP Settlements", ["Hearing Date", "Outstanding",
                                           "Settlement Amount"])
    elif source_key == "document_log":
        _add(need, CSV, rules["kpi"]["sql_doc_columns"].values())
    elif source_key == "kpi_numbers":
        _add(need, (rules["kpi"].get("scorecard") or {}).get("sheet", "Sheet1"), [])
    return need


def requirements(source_key: str, report_key: str | None = None) -> dict[str, list[str]]:
    """{sheet: columns} the builds read from `source_key`: one report's when the file
    is that report's own copy, otherwise every report's that uses it."""
    need: dict[str, list[str]] = {}
    for key, report in REPORTS.items():
        if report_key not in (None, key) or source_key not in {s.key for s in report.sources}:
            continue
        for sheet, cols in _for_report(source_key, key, load_rules(key)).items():
            _add(need, sheet, cols)
    return need


def _book(source_key: str) -> str | None:
    """The Delta workbook a Delta input is a copy of: wc or mlcr."""
    if not source_key.startswith("delta_"):
        return None
    return source_key[len("delta_"):].removesuffix("_comments")


def _delta_checks(source_key: str, report_key: str | None):
    """(sheets the file must not have, {sheet: (ProviderID column, only, never)})."""
    book, banned, providers = _book(source_key), [], {}
    if book is None:
        return banned, providers
    for key, report in REPORTS.items():
        if report_key not in (None, key) or source_key not in {s.key for s in report.sources}:
            continue
        delta = load_rules(key).get("delta") or {}
        uc = delta.get("upload_check") or {}
        banned += [s for s in (uc.get("not_sheets") or {}).get(book, []) if s not in banned]
        if source_key.endswith("_comments"):
            continue                       # the comments copies carry no ProviderID to read
        for spec in delta.get("sources", []):
            rule = (uc.get("providers") or {}).get(spec["sheet"])
            if spec["workbook"] == book and rule:
                providers[spec["sheet"]] = (spec["columns"]["Provider_ID"],
                                            set(rule["only"]) if "only" in rule else None,
                                            set(rule.get("never") or ()))
    return banned, providers


def _provider_ids(book, sheet: str, column: str) -> set[int]:
    values = (book.load_sheet(sheet, header_row=0, use_columns=[column],
                              dtypes={column: "string"}).to_polars()[column])
    out = set()
    for v in values.drop_nulls().unique().to_list():
        try:
            out.add(int(float(v)))
        except ValueError:
            pass
    return out


def _near(name: str, names) -> str | None:
    """`name` as the file has it, if only the case or spaces differ."""
    k = " ".join(str(name).split()).lower()
    return next((n for n in names if " ".join(str(n).split()).lower() == k), None)


def _open(path: Path, sheets):
    """(the workbook or None for a CSV, its sheet names, the header row of each of
    `sheets` it has)."""
    if path.suffix.lower() == ".csv":
        return None, [CSV], {CSV: pl.read_csv(path, n_rows=1, infer_schema=False).columns}
    book = fastexcel.read_excel(str(path))
    names = list(book.sheet_names)
    return book, names, {s: list(book.load_sheet(s, header_row=0, n_rows=1)
                                 .to_polars().columns)
                         for s in sheets if s in names}


def check(source_key: str, path: Path, report_key: str | None = None) -> list[str]:
    """What is wrong with `path` as `source_key`, one sentence each; empty if nothing."""
    need = requirements(source_key, report_key)
    try:
        book, names, headers = _open(path, need)
    except Exception as e:                    # not a workbook, or a damaged one
        return [f"the file could not be opened as a spreadsheet ({type(e).__name__})"]
    banned, providers = _delta_checks(source_key, report_key)
    extra = [s for s in banned if s in names]
    if extra:
        return [f"it has the sheet(s) {', '.join(repr(s) for s in extra)}, so it looks like "
                f"the MLCR workbook, not the WC one"]
    if source_key in LOOKS_LIKE and "Sheet1" in headers:
        cols, other = LOOKS_LIKE[source_key]
        if all(c in headers["Sheet1"] for c in cols):
            return [f"it has {', '.join(repr(c) for c in cols)}, so it looks like {other}"]
    problems = []
    for sheet, cols in need.items():
        if sheet not in headers:
            near = _near(sheet, names)
            problems.append(
                f"no sheet named '{sheet}'"
                + (f" (there is '{near}' - rename it exactly)" if near else
                   f" (the file has: {', '.join(repr(n) for n in names[:8])})"))
            continue
        have = headers[sheet]
        missing = [c for c in cols if c not in have]
        if missing:
            hints = [f"'{c}'" + (f" (the file has '{n}')" if (n := _near(c, have)) else "")
                     for c in missing]
            where = "the file" if sheet == CSV else f"sheet '{sheet}'"
            problems.append(f"{where} is missing column(s): {', '.join(hints)}")
    if problems:
        return problems
    for sheet, (column, only, never) in providers.items():
        try:
            ids = _provider_ids(book, sheet, column)
        except Exception as e:
            problems.append(f"the {column} column of '{sheet}' could not be read "
                            f"({type(e).__name__})")
            continue
        stray = sorted(ids - only if only is not None else ids & never)
        if stray:
            shown = ", ".join(map(str, stray[:8])) + (" ..." if len(stray) > 8 else "")
            problems.append(
                f"'{sheet}' holds provider(s) {shown}, which do not belong on it"
                + (f" - it should hold only {', '.join(map(str, sorted(only)))}"
                   if only is not None else " - they belong on another sheet"))
    return problems
