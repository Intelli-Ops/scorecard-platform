"""Golden master: the new pipeline must reproduce the .bat pipeline's tables.

The .bat pipeline writes four parquet tables into marts/<week>/ on every run.
Those are the reference. This test reads the same inputs/<week>/ files, runs
this project's pipeline, and compares.

HOW EQUALITY IS DEFINED, AND WHY IT IS NOT `frame.equals`
---------------------------------------------------------
Two deliberate tolerances, neither of which hides a wrong number:

1. ROW ORDER IS NOT COMPARED. Polars group-bys and joins are multi-threaded
   and do not promise a stable row order between runs - the .bat pipeline's
   own order varies run to run too. The tables are compared as sets of rows.
   A missing, extra or altered row still fails.

2. MONEY IS COMPARED TO THE CENT. Summing the same 278,930 values in a
   different order gives answers that differ in the last bit of a double:
   the largest observed gap is 0.0000008 on a total of 299,693,534.89, a
   relative error of 3e-15. Rounding to 2dp is the same precision the client
   reads off the sheet. A real discrepancy of one cent still fails.

Set GFS_LEGACY_ROOT to the .bat project if it is not at the default path.
"""
from __future__ import annotations
import datetime as dt
import os
from pathlib import Path

import polars as pl
import pytest
import yaml

from app.reports import get
from app.reports.locate import locate_dir
from app.reports.cache import ParquetCache
from app.reports.gfs.readers import read_gfs
from app.reports.gfs.pipeline import run

LEGACY = Path(os.environ.get(
    "GFS_LEGACY_ROOT",
    r"C:\Users\ali.asghar\OneDrive - MSFT\Desktop\gfs-automation"))
WEEK = os.environ.get("GFS_GOLDEN_WEEK", "2026-W35")
AS_OF = dt.date.fromisoformat(os.environ.get("GFS_GOLDEN_AS_OF", "2026-09-03"))

MONEY_COLUMNS = 2  # decimal places the client reads


def _canonical(df: pl.DataFrame) -> pl.DataFrame:
    """Column order, float precision and row order all made comparable."""
    df = df.select(sorted(df.columns))
    df = df.with_columns(
        [pl.col(c).round(MONEY_COLUMNS) for c, t in zip(df.columns, df.dtypes)
         if t in (pl.Float32, pl.Float64)])
    return df.sort(by=df.columns, nulls_last=True)


@pytest.fixture(scope="module")
def result():
    week_dir = LEGACY / "inputs" / WEEK
    if not week_dir.exists():
        pytest.skip(f"no legacy inputs at {week_dir}")
    report = get("gfs")
    rules = yaml.safe_load(report.rules_path.read_text())
    cache = ParquetCache(Path(os.environ.get("GFS_CACHE_DIR", ".golden-cache")) / WEEK)
    sources = read_gfs(locate_dir(report, week_dir), rules, cache)
    return run(sources, rules, as_of=AS_OF)


@pytest.fixture(scope="module")
def golden():
    d = LEGACY / "marts" / WEEK
    if not d.exists():
        pytest.skip(f"no legacy marts at {d} - run the .bat pipeline for {WEEK} first")
    return {p.stem: pl.read_parquet(p) for p in d.glob("*.parquet")}


@pytest.mark.parametrize("table", ["raw_data", "case_ar",
                                   "delta_comparison", "collections"])
def test_matches_bat_pipeline(result, golden, table):
    if table not in golden:
        pytest.skip(f"{table}.parquet not produced by the legacy run")
    new, old = result.tables[table], golden[table]

    assert new.shape == old.shape, (
        f"{table}: {new.shape} rows/cols vs the .bat pipeline's {old.shape}")
    assert sorted(new.columns) == sorted(old.columns), (
        f"{table}: columns differ - "
        f"only in new {sorted(set(new.columns) - set(old.columns))}, "
        f"only in golden {sorted(set(old.columns) - set(new.columns))}")

    a, b = _canonical(new), _canonical(old)
    if not a.equals(b):
        detail = []
        for c in b.columns:
            ne = (a[c] != b[c]).fill_null(True).sum()
            if ne:
                detail.append(f"{c}: {ne} of {b.height} rows differ")
        pytest.fail(f"{table} differs from the .bat pipeline\n  " + "\n  ".join(detail))


def test_raw_data_row_count(result):
    """278,930 is the figure recorded as matching the hand-built sheet."""
    if WEEK != "2026-W35":
        pytest.skip("the recorded count is for 2026-W35")
    assert result.raw_data.height == 278_930


def test_no_unexpected_warnings(result):
    """Not a correctness check - it surfaces the notes so a reviewer sees them."""
    for note in result.notes:
        print("  note:", note)
