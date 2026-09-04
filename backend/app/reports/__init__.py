"""Report-type registry.

Two weekly scorecards are produced from the SAME nine source files: GFS and
All-Providers. Their calculation cores are genuinely different code - a diff
of the two shows 50-90% of lines differing - so they are NOT merged into one
generic engine. Each report owns its own `core/` package and `rules.yml`.

What is shared is everything around the maths: upload, storage, jobs, the
database, the API and the UI. A report type is just a declaration of which
files it needs and which pipeline turns them into tables.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SourceFile:
    """One expected weekly input, matched by fragments of its filename.

    Carried over verbatim from the .bat pipelines: matching is
    case-insensitive and every fragment must appear in the name, so a
    trailing date is fine and files are never renamed by hand.
    """
    key: str
    fragments: tuple[str, ...]
    exts: tuple[str, ...] = (".xlsx", ".xlsb")
    label: str = ""
    required: bool = True


# The nine files a week needs. Both reports consume this same set, which is
# why the upload screen is shared: one upload per week, two reports built.
WEEKLY_SOURCES: tuple[SourceFile, ...] = (
    SourceFile("owner_case_ar", ("combined owner case ar",),
               label="Combined Owner Case AR"),
    SourceFile("custom_case_ar", ("combined custom", "case ar"),
               label="Combined Custom Case AR"),
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


@dataclass(frozen=True)
class ReportType:
    key: str
    label: str
    rules_path: Path
    sources: tuple[SourceFile, ...] = WEEKLY_SOURCES
    sheets: tuple[str, ...] = ()


HERE = Path(__file__).parent

REPORTS: dict[str, ReportType] = {
    "gfs": ReportType(
        key="gfs",
        label="GFS Weekly Scorecard",
        rules_path=HERE / "gfs" / "rules.yml",
        sheets=("Settlement High-Level", "Collection High-Level",
                "Delta Comparison", "KPI High-Level", "Case AR", "Raw Data"),
    ),
    "all_providers": ReportType(
        key="all_providers",
        label="All Providers Weekly Scorecard",
        rules_path=HERE / "all_providers" / "rules.yml",
    ),
}


def get(key: str) -> ReportType:
    if key not in REPORTS:
        raise KeyError(f"unknown report type {key!r}; "
                       f"known: {', '.join(sorted(REPORTS))}")
    return REPORTS[key]
