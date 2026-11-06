"""GFS: reads the uploaded source files into tables."""
from __future__ import annotations

from ..cache import Cache
from ..locate import SourceSet
from ..notes import warning
from ..reading import Sources, load_sheet, read_sources
from .core.case_ar import gfs_case_ids


def read_gfs(sources: SourceSet, rules: dict, cache: Cache | None = None) -> Sources:
    src, timed = read_sources(
        sources, rules, cache,
        custom_columns=["CASEID", "Closing Order", "Case_Validity", "FileStatus", "Lien Filed"],
        hearing_columns=["Hearing Date", "Outstanding", "Settlement Amount"])
    if src.owner_ar is not None:
        src.gfs_cases = gfs_case_ids(src.owner_ar, rules)

    ccfg = rules["delta"].get("comments") or {}
    for src_sheet, (book, in_sheet) in (ccfg.get("sheets") or {}).items():
        path = sources.optional(f"delta_{book}_comments")
        if path is not None:
            src.delta_comments[src_sheet] = timed(
                f"delta_{book}_comments", f"{in_sheet} (comments)", path,
                lambda p=path, s=in_sheet: load_sheet(
                    p, s, header_row=0, use_columns=[ccfg["key"], *ccfg["columns"]]))

    if src.scorecard is None:
        src.notes.append(warning(
            "kpi_numbers_not_supplied",
            "KPI numbers file not supplied - the blocks it feeds (DOR, PMR, NTP, "
            "Enforcement Of Agreement, Medical Index, Med Legal) will show no data "
            "this week"))
    return src
