"""All Providers: reads the uploaded source files into tables."""
from __future__ import annotations

from ..cache import Cache
from ..locate import SourceSet
from ..notes import info
from ..reading import Sources, read_sources


def read_all_providers(sources: SourceSet, rules: dict,
                       cache: Cache | None = None) -> Sources:
    src, _timed = read_sources(
        sources, rules, cache,
        custom_columns=["CASEID", "Closing Order", "Case_Validity", "FileStatus"])
    if src.scorecard is None:
        src.notes.append(info("kpi_numbers_not_supplied",
                              "KPI / litigation numbers file not supplied"))
    return src
