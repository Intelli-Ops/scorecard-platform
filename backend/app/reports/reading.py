"""Reads one source sheet and records how long it took."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import time

import polars as pl

from .cache import Cache, NoCache, ParquetCache


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

    def timed(key: str, label: str, path: Path, load: Callable[[], pl.DataFrame],
              source_key: str | None = None) -> pl.DataFrame:
        """Read one sheet, recording how long it took and how much came back."""
        t = time.perf_counter()
        ck = (ParquetCache.key_for(key, path)
              if isinstance(cache, ParquetCache) else key)
        df = cache.get_or_read(ck, load)
        elapsed = time.perf_counter() - t
        reads.append(FileRead(key=key, source_key=source_key or key, label=label,
                              filename=path.name, rows=df.height,
                              seconds=elapsed, from_cache=elapsed < 0.25))
        return df

    return timed
