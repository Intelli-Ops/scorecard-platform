"""The two reports, the files each needs, and their rules."""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import copy

import yaml


@dataclass(frozen=True)
class SourceFile:
    """One expected weekly input, found by fragments of its filename."""
    key: str
    fragments: tuple[str, ...]
    exts: tuple[str, ...] = (".xlsx", ".xlsb")
    label: str = ""
    required: bool = True
    excludes: tuple[str, ...] = ()


COMMENTS = "comment"

SHARED_SOURCES: tuple[SourceFile, ...] = (
    SourceFile("delta_wc", ("delta wc",), excludes=(COMMENTS,),
               label="Master Settlement & Collection Delta WC"),
    SourceFile("delta_mlcr", ("delta mlcr",), excludes=(COMMENTS,),
               label="Master Settlement & Collection Delta MLCR"),
    SourceFile("payment_detail", ("payment detail",),
               label="Payment Detail Report"),
    SourceFile("hearing_calendar", ("hearing calendar",),
               label="Hearing Calendar"),
    SourceFile("document_log", ("document_log",), exts=(".csv",),
               label="SQL document log (SBR / DDE)"),
    SourceFile("kpi_numbers", ("kpi", "number"),
               label="KPI numbers (usually Tuesday)"),
)

COMMENT_SOURCES: tuple[SourceFile, ...] = (
    SourceFile("delta_wc_comments", ("delta wc", COMMENTS),
               label="Delta WC - comments (usually Tuesday)"),
    SourceFile("delta_mlcr_comments", ("delta mlcr", COMMENTS),
               label="Delta MLCR - comments (usually Tuesday)"),
)


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
        """Every file this report needs: the shared six, its own two Case
        ARs, and anything only it requires."""
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
    """A report's rules.yml, parsed once and reused until the file changes."""
    path = get(key).rules_path
    return copy.deepcopy(_parsed_rules(path, path.stat().st_mtime_ns))
