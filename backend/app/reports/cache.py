"""Caches parsed spreadsheets as parquet so a rebuild skips re-reading them."""
from __future__ import annotations
from pathlib import Path
from typing import Callable, Protocol

import polars as pl


class Cache(Protocol):
    def get_or_read(self, key: str, read: Callable[[], pl.DataFrame]) -> pl.DataFrame: ...


class NoCache:
    """Always re-reads."""

    def get_or_read(self, key: str, read: Callable[[], pl.DataFrame]) -> pl.DataFrame:
        return read()


class ParquetCache:
    """One parquet file per source, per week."""

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
