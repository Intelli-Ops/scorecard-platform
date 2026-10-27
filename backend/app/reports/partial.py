"""Partial builds: a section of the scorecard whose files are not in yet comes
out empty, with a note saying what it is waiting for."""
from __future__ import annotations

import polars as pl

from . import SHARED_SOURCES, CASE_AR_SOURCES
from .notes import Note, warning

_LABELS = {s.key: s.label for s in SHARED_SOURCES + CASE_AR_SOURCES}


def empty(schema: dict) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def waiting(section: str, keys: list[str]) -> Note:
    """`section` is empty because the files `keys` were not uploaded."""
    files = [_LABELS.get(k, k) for k in keys]
    return warning("section_waiting",
                   f"No {section} in this build - waiting for: {', '.join(files)}",
                   block=section, files=files)


def absent(**tables) -> list[str]:
    """The source keys whose table is None."""
    return [k for k, v in tables.items() if v is None or (isinstance(v, dict) and not v)]


def missing_books(rules: dict, sheets: dict) -> list[str]:
    """The Delta workbooks none of whose sheets were read."""
    return list(dict.fromkeys(f"delta_{s['workbook']}" for s in rules["delta"]["sources"]
                              if s["sheet"] not in sheets))
