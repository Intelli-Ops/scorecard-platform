"""Read the big spreadsheets once, then reuse.

Combined Custom Case AR is 240 MB and takes over a minute to parse. The .bat
pipeline wrote a parquet copy into staging/<week>/ so a re-run took 0.1s, and
that mattered because a failed run had to be retried.

It matters more here. A run is a background job that can be retried, and the
review step may send someone back to fix a rule and run again. Re-parsing a
quarter of a gigabyte each time would make that unusable.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable, Protocol

import polars as pl


class Cache(Protocol):
    def get_or_read(self, key: str, read: Callable[[], pl.DataFrame]) -> pl.DataFrame: ...


class NoCache:
    """Always re-reads. Used when correctness matters more than speed."""

    def get_or_read(self, key: str, read: Callable[[], pl.DataFrame]) -> pl.DataFrame:
        return read()


class ParquetCache:
    """One parquet file per source, per week.

    Keyed by content, not by filename: the cache key includes the stored
    file's name - in the object store, the SHA-256 of its bytes - as well as
    its size and modified time, so replacing an upload with a corrected copy
    re-reads it instead of quietly serving the old numbers. Size and time
    alone could not tell apart two corrections of equal size stored within
    the same second.
    """

    def __init__(self, directory: Path):
        self.dir = Path(directory)

    @staticmethod
    def key_for(name: str, source: Path) -> str:
        st = source.stat()
        return f"{name}-{source.stem[:16]}-{st.st_size}-{int(st.st_mtime)}"

    def get_or_read(self, key: str, read: Callable[[], pl.DataFrame]) -> pl.DataFrame:
        path = self.dir / f"{key}.parquet"
        if path.exists():
            return pl.read_parquet(path)
        df = read()
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        df.write_parquet(tmp)
        tmp.replace(path)          # never leave a half-written cache behind
        return df
