"""Report-type registry.

Two weekly scorecards: GFS and All Providers.

WHICH FILES EACH ONE NEEDS
--------------------------
Seven of the nine weekly files are the same for both reports - upload once,
both reports use them.

The two Case AR files are NOT shared. Case ARs are regenerated every day,
and the two reports go out on different days:

    GFS            mailed Tuesday   -> Tuesday's Case ARs
    All Providers  mailed Thursday  -> Thursday's Case ARs

The filenames are identical, so nothing in the file itself says which day it
came from. That is why a week stores them separately, tagged by report. The
same case can legitimately show different numbers in the two reports, and
this is the record that explains why.

WHY THE MATHS IS NOT SHARED
---------------------------
Each report keeps its own core/ package and rules.yml. Diffing the two shows
50-90% of lines differing - they are different calculations, not copies.
Everything AROUND the maths (upload, storage, jobs, database, API, UI) is
shared.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import copy

import yaml


@dataclass(frozen=True)
class SourceFile:
    """One expected weekly input, found by fragments of its filename.

    Matching is carried over from the .bat pipelines: case-insensitive, and
    every fragment must appear somewhere in the name. So a trailing date is
    fine and nobody has to rename files by hand. `excludes` are fragments the
    name must NOT hold - how "Delta WC 09.28.2026.xlsb" is told apart from
    "Delta WC 09.28.2026 - comments.xlsb".
    """
    key: str
    fragments: tuple[str, ...]
    exts: tuple[str, ...] = (".xlsx", ".xlsb")
    label: str = ""
    required: bool = True
    excludes: tuple[str, ...] = ()


# The litigation team's copies of the two Delta workbooks are named like the
# originals with "- comments" on the end. They are NOT the Delta data - see
# COMMENT_SOURCES - so the plain Delta match refuses any name holding this.
COMMENTS = "comment"

# Uploaded once per week. Both reports read these same files.
SHARED_SOURCES: tuple[SourceFile, ...] = (
    SourceFile("delta_wc", ("delta wc",), excludes=(COMMENTS,),
               label="Master Settlement & Collection Delta WC"),
    SourceFile("delta_mlcr", ("delta mlcr",), excludes=(COMMENTS,),
               label="Master Settlement & Collection Delta MLCR"),
    SourceFile("payment_detail", ("payment detail",),
               label="Payment Detail Report"),
    SourceFile("supporting", ("supporting file",),
               label="Supporting File"),
    SourceFile("hearing_calendar", ("hearing calendar",),
               label="Hearing Calendar"),
    SourceFile("document_log", ("document_log",), exts=(".csv",),
               label="SQL document log (SBR / DDE)"),
    SourceFile("kpi_numbers", ("kpi", "number"),
               label="KPI numbers", required=False),
)

# All Providers needs a tenth file that GFS does not.
#
# Its KPI blocks are not declared in rules.yml - they are READ OUT of last
# week's delivered workbook, because that sheet's shape changes: the provider
# list runs to 33 rows and grows when a provider is taken on, and the grids
# gain a week column every week of the month. Any row map typed into config
# would be wrong within a fortnight, and wrong quietly.
#
# Matched on "provider" + "score" so it can never pick up the GFS workbook by
# accident. Nothing opens Excel to read it - an .xlsx is a zip of XML.
TEMPLATE_SOURCE = SourceFile(
    "template", ("provider", "score"), exts=(".xlsx",),
    label="Last week's All Providers workbook (for the KPI layout)")


# GFS only, and only on Tuesday: the "- comments" copies of the two Delta
# workbooks, whose last two columns - Ongoing DOR Status and Ongoing DOR
# Details - are looked up onto the Delta Comparison rows by Case ID (see
# delta.comments in gfs/rules.yml). Optional: without them the two columns
# are left blank and the review says so.
COMMENT_SOURCES: tuple[SourceFile, ...] = (
    SourceFile("delta_wc_comments", ("delta wc", COMMENTS), required=False,
               label="Delta WC - comments (Ongoing DOR)"),
    SourceFile("delta_mlcr_comments", ("delta mlcr", COMMENTS), required=False,
               label="Delta MLCR - comments (Ongoing DOR)"),
)


# Uploaded once PER REPORT, because each report uses its own day's copy.
CASE_AR_SOURCES: tuple[SourceFile, ...] = (
    SourceFile("owner_case_ar", ("combined owner case ar",),
               label="Combined Owner Case AR"),
    SourceFile("custom_case_ar", ("combined custom", "case ar"),
               label="Combined Custom Case AR"),
)
CASE_AR_KEYS: frozenset[str] = frozenset(s.key for s in CASE_AR_SOURCES)


@dataclass(frozen=True)
class ReportType:
    key: str
    label: str
    short: str               # for table columns, where the full label is noise
    send_day: str            # the day this report is mailed to the client
    rules_path: Path
    sheets: tuple[str, ...] = ()
    extra_sources: tuple[SourceFile, ...] = ()

    @property
    def sources(self) -> tuple[SourceFile, ...]:
        """Every file this report needs: the shared seven, its own two Case ARs,
        and anything only it requires."""
        return SHARED_SOURCES + CASE_AR_SOURCES + self.extra_sources


HERE = Path(__file__).parent

REPORTS: dict[str, ReportType] = {
    "gfs": ReportType(
        key="gfs",
        label="GFS Weekly Scorecard",
        short="GFS",
        send_day="Tuesday",
        rules_path=HERE / "gfs" / "rules.yml",
        sheets=("Settlement High-Level", "Collection High-Level",
                "Delta Comparison", "KPI High-Level", "Case AR", "Raw Data"),
        extra_sources=COMMENT_SOURCES,
    ),
    "all_providers": ReportType(
        key="all_providers",
        label="All Providers Weekly Scorecard",
        short="All Providers",
        send_day="Thursday",
        rules_path=HERE / "all_providers" / "rules.yml",
        extra_sources=(TEMPLATE_SOURCE,),
    ),
}


def get(key: str) -> ReportType:
    if key not in REPORTS:
        raise KeyError(f"unknown report type {key!r}; "
                       f"known: {', '.join(sorted(REPORTS))}")
    return REPORTS[key]


@lru_cache(maxsize=None)
def _parsed_rules(path: Path, mtime_ns: int) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def load_rules(key: str) -> dict:
    """A report's rules.yml, parsed once and reused until the file changes.

    A fresh copy every call: a build writes the month's working days into the
    dict it is given, and that must not leak into the next build or request.
    """
    path = get(key).rules_path
    return copy.deepcopy(_parsed_rules(path, path.stat().st_mtime_ns))
