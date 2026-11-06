"""Reads one source sheet and records how long it took."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
import time

import fastexcel
import polars as pl

from .cache import Cache, NoCache, ParquetCache
from .locate import SourceSet
from .notes import Note


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
        reads.append(FileRead(key=key, source_key=source_key or key, label=label,
                              filename=path.name, rows=df.height,
                              seconds=time.perf_counter() - t))
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


@dataclass
class Sources:
    """A build's uploaded files as tables. Each is None when its file was not
    uploaded - a partial build."""
    owner_ar: pl.DataFrame | None
    custom_ar: pl.DataFrame | None           # Closing Order / Validity / Status lookups
    providers: pl.DataFrame                  # provider -> group map
    delta_sheets: dict[str, pl.DataFrame]    # only the sheets uploaded
    payments: pl.DataFrame | None            # Collection High-Level
    hearing_noi: pl.DataFrame | None         # CP Settled Cases
    sql_doc: pl.DataFrame | None             # KPI: SBR and DDE
    scorecard: pl.DataFrame | None           # KPI numbers - may legitimately be absent
    gfs_cases: pl.DataFrame | None = None    # GFS only: which cases count as GFS
    delta_comments: dict[str, pl.DataFrame] = field(default_factory=dict)   # GFS only
    reads: list[FileRead] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


def read_sources(sources: SourceSet, rules: dict, cache: Cache | None,
                 custom_columns: list[str], hearing_columns: list[str] | None = None
                 ) -> tuple[Sources, Callable]:
    """Every input both reports read, and the read function for any the caller adds."""
    reads: list[FileRead] = []
    timed = timed_reader(cache, reads)

    def sheet(key: str, label: str, name, **kwargs) -> pl.DataFrame | None:
        path = sources.optional(key)
        return timed(key, label, path, lambda: load_sheet(path, name, **kwargs))

    books = {"wc": sources.optional("delta_wc"), "mlcr": sources.optional("delta_mlcr")}
    delta_sheets: dict[str, pl.DataFrame] = {}
    for spec in rules["delta"]["sources"]:
        book, name = books[spec["workbook"]], spec["sheet"]
        df = timed(f"delta_{name}", name, book,
                   lambda b=book, s=name, c=list(spec["columns"].values()):
                       load_sheet(b, s, header_row=0, use_columns=c),
                   source_key=f"delta_{spec['workbook']}")
        if df is not None:
            delta_sheets[name] = df

    sql_path = sources.optional("document_log")
    hearing = {"use_columns": hearing_columns} if hearing_columns else {}
    src = Sources(
        owner_ar=sheet("owner_case_ar", "Combined Owner Case AR", "Sheet1", header_row=0),
        custom_ar=sheet("custom_case_ar", "Combined Custom Case AR", "Sheet1", header_row=0,
                        use_columns=custom_columns),
        providers=provider_list(rules),
        delta_sheets=delta_sheets,
        payments=sheet("payment_detail", "Payment Detail Report",
                       rules["collections"]["sheet"], header_row=0),
        hearing_noi=sheet("hearing_calendar", "Hearing Calendar", "NOI, CP Settlements",
                          header_row=0, **hearing),
        sql_doc=timed("document_log", "SQL document log", sql_path,
                      lambda: pl.read_csv(sql_path)),
        scorecard=sheet("kpi_numbers", "KPI numbers",
                        (rules["kpi"].get("scorecard") or {}).get("sheet", 0), header_row=None),
        reads=reads)
    return src, timed
