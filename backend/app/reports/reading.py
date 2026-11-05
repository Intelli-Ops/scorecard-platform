"""Reads one source sheet and records how long it took."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import time

import fastexcel
import polars as pl

from .cache import Cache, NoCache, ParquetCache


def name_key(name) -> str:
    """A sheet or column name with case, doubled spaces and the spaces at
    either end ignored: 'KPI High-Level ' and 'kpi  high-level' are the same."""
    return " ".join(str(name).split()).lower()


def find_sheet(names, wanted):
    """The sheet in `names` that `wanted` means. The exact name first, then one
    that differs only in case or spaces; None if there is neither. A number is
    a sheet's position and is returned as it is."""
    if isinstance(wanted, int):
        return wanted
    names = list(names)
    if wanted in names:
        return wanted
    k = name_key(wanted)
    return next((n for n in names if name_key(n) == k), None)


def column_key(name) -> str:
    """A column heading with its spaces tidied: ' PAYMENT ' is 'PAYMENT'. Unlike a
    sheet name, its capitals still count."""
    return " ".join(str(name).split())


def tidy_columns(df: pl.DataFrame) -> pl.DataFrame:
    """`df` with the spaces round its headings taken off, so a file's ' PAYMENT '
    reads as PAYMENT. A heading that would then clash with another is left alone."""
    taken = set(df.columns)
    rename: dict[str, str] = {}
    for c in df.columns:
        k = column_key(c)
        if k != c and k not in taken:
            rename[c] = k
            taken.add(k)
    return df.rename(rename) if rename else df


def load_sheet(path: Path, sheet, **kwargs) -> pl.DataFrame:
    """One sheet of a workbook as a table, found by `find_sheet`, its headings tidied
    by `tidy_columns`. Client files sometimes put spaces round a sheet name or a
    column heading, so neither need match exactly; `use_columns` names are matched
    the same way."""
    book = fastexcel.read_excel(str(path))
    found = find_sheet(book.sheet_names, sheet)
    wanted = kwargs.get("use_columns")
    if isinstance(wanted, (list, tuple)) and all(isinstance(c, str) for c in wanted):
        keys = {column_key(c) for c in wanted}
        kwargs["use_columns"] = lambda col: column_key(col.name) in keys
    return tidy_columns(
        book.load_sheet(sheet if found is None else found, **kwargs).to_polars())


@dataclass
class FileRead:
    """What one read produced."""
    key: str
    source_key: str
    label: str
    filename: str
    rows: int
    seconds: float
    from_cache: bool = False


def timed_reader(cache: Cache | None, reads: list[FileRead]):
    """A read function that goes through `cache` and appends a FileRead to
    `reads` for every sheet it loads."""
    cache = cache or NoCache()

    def timed(key: str, label: str, path: Path | None,
              load: Callable[[], pl.DataFrame],
              source_key: str | None = None) -> pl.DataFrame | None:
        """Read one sheet and time it; None if the file was not uploaded."""
        if path is None:
            return None
        t = time.perf_counter()
        ck = (ParquetCache.key_for(key, path)
              if isinstance(cache, ParquetCache) else key)
        df = tidy_columns(cache.get_or_read(ck, load))     # cached before tidying, too
        elapsed = time.perf_counter() - t
        reads.append(FileRead(key=key, source_key=source_key or key, label=label,
                              filename=path.name, rows=df.height,
                              seconds=elapsed, from_cache=elapsed < 0.25))
        return df

    return timed


PROVIDER_COLUMNS = {"regid": "BUSINESSREGID", "provider_id": "PROVIDER ID",
                    "name": "PROVIDER NAME", "status": "Provider Status",
                    "provider_group": "Provider Group"}


def provider_list(rules: dict) -> pl.DataFrame:
    """The provider list, shaped like the old Supporting File sheet."""
    rows = rules.get("providers") or []
    return pl.DataFrame(
        {col: [r.get(key) for r in rows] for key, col in PROVIDER_COLUMNS.items()},
        schema={"BUSINESSREGID": pl.Float64, "PROVIDER ID": pl.Utf8,
                "PROVIDER NAME": pl.Utf8, "Provider Status": pl.Utf8,
                "Provider Group": pl.Utf8})
