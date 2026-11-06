"""Makes CSV cells safe to open in Excel (no formulas)."""
from __future__ import annotations
import re

import polars as pl

_RISKY = ("=", "+", "-", "@", "\t", "\r")
_STARTS_RISKY = "^[" + "".join(re.escape(c) for c in _RISKY) + "]"
_NUMBER = re.compile(r"^-\d[\d,]*(\.\d+)?$")


def cell(value):
    """One value, defused if it is text a spreadsheet would run."""
    if isinstance(value, str) and value.startswith(_RISKY) \
            and not _NUMBER.match(value):
        return "'" + value
    return value


def frame(df: pl.DataFrame) -> pl.DataFrame:
    """Every text column of a table, defused the same way."""
    text = [c for c, t in df.schema.items() if t == pl.Utf8]
    if not text:
        return df
    return df.with_columns(
        pl.when(pl.col(c).str.contains(_STARTS_RISKY)
                & ~pl.col(c).str.contains(_NUMBER.pattern))
        .then(pl.lit("'") + pl.col(c))
        .otherwise(pl.col(c))
        .alias(c)
        for c in text)
