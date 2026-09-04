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
from pathlib import Path


@dataclass(frozen=True)
class SourceFile:
    """One expected weekly input, found by fragments of its filename.

    Matching is carried over from the .bat pipelines: case-insensitive, and
    every fragment must appear somewhere in the name. So a trailing date is
    fine and nobody has to rename files by hand.
    """
    key: str
    fragments: tuple[str, ...]
    exts: tuple[str, ...] = (".xlsx", ".xlsb")
    label: str = ""
    required: bool = True


# Uploaded once per week. Both reports read these same files.
SHARED_SOURCES: tuple[SourceFile, ...] = (
    SourceFile("delta_wc", ("delta wc",),
               label="Master Settlement & Collection Delta WC"),
    SourceFile("delta_mlcr", ("delta mlcr",),
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

# Uploaded once PER REPORT, because each report uses its own day's copy.
CASE_AR_SOURCES: tuple[SourceFile, ...] = (
    SourceFile("owner_case_ar", ("combined owner case ar",),
               label="Combined Owner Case AR"),
    SourceFile("custom_case_ar", ("combined custom", "case ar"),
               label="Combined Custom Case AR"),
)


@dataclass(frozen=True)
class ReportType:
    key: str
    label: str
    send_day: str            # the day this report is mailed to the client
    rules_path: Path
    sheets: tuple[str, ...] = ()

    @property
    def sources(self) -> tuple[SourceFile, ...]:
        """Every file this report needs: the shared seven plus its own two."""
        return SHARED_SOURCES + CASE_AR_SOURCES


HERE = Path(__file__).parent

REPORTS: dict[str, ReportType] = {
    "gfs": ReportType(
        key="gfs",
        label="GFS Weekly Scorecard",
        send_day="Tuesday",
        rules_path=HERE / "gfs" / "rules.yml",
        sheets=("Settlement High-Level", "Collection High-Level",
                "Delta Comparison", "KPI High-Level", "Case AR", "Raw Data"),
    ),
    "all_providers": ReportType(
        key="all_providers",
        label="All Providers Weekly Scorecard",
        send_day="Thursday",
        rules_path=HERE / "all_providers" / "rules.yml",
    ),
}


def get(key: str) -> ReportType:
    if key not in REPORTS:
        raise KeyError(f"unknown report type {key!r}; "
                       f"known: {', '.join(sorted(REPORTS))}")
    return REPORTS[key]
