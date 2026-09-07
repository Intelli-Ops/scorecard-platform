"""Golden master for All Providers.

Same contract as the GFS golden master, against the All-Providers .bat
pipeline's own marts/<week>/*.parquet. See test_gfs_golden.py for why row order
is not compared and money is compared to the cent.

Settlement is checked too, which GFS's golden master cannot do: the
All-Providers pipeline writes its grids out as settlement.parquet, so the
figures the dashboard serves can be compared against the .bat pipeline's rather
than only trusted.
"""
from __future__ import annotations
import datetime as dt
import os
from pathlib import Path

import polars as pl
import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.reports import get
from app.reports.cache import ParquetCache
from app.reports.locate import locate_dirs
from app.reports.all_providers.readers import read_all_providers
from app.reports.all_providers.pipeline import run
from app.service.figures import settlement_records

LEGACY = Path(os.environ.get(
    "GFS_LEGACY_ROOT",
    r"C:\Users\ali.asghar\OneDrive - MSFT\Desktop\gfs-automation"))
AP = LEGACY / "all-providers-automation"
WEEK = os.environ.get("GFS_GOLDEN_WEEK", "2026-W35")


def _canonical(df: pl.DataFrame) -> pl.DataFrame:
    df = df.select(sorted(df.columns))
    df = df.with_columns([pl.col(c).round(2) for c, t in zip(df.columns, df.dtypes)
                          if t in (pl.Float32, pl.Float64)])
    return df.sort(by=df.columns, nulls_last=True)


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    """All Providers reads from BOTH projects' week folders - the seven shared
    files sit in the GFS folder and its own Case ARs in its own. That is how the
    .bat pipeline works, and the reason the platform stores the shared files
    once and the Case ARs per report."""
    shared = LEGACY / "inputs" / WEEK
    own = AP / "inputs" / WEEK
    if not shared.exists() or not own.exists():
        pytest.skip("legacy inputs not present")

    report = get("all_providers")
    rules = yaml.safe_load(report.rules_path.read_text())

    # Its own folder FIRST: both folders hold a "Combined Custom Case AR.xlsb"
    # and they are different files - Thursday's and Tuesday's.
    sources = locate_dirs(report, [own, shared])
    if not sources.ok:
        pytest.skip(f"cannot assemble inputs: {sources.problems()}")

    cache = ParquetCache(tmp_path_factory.mktemp("cache"))
    src = read_all_providers(sources, rules, cache)
    return run(src, rules, as_of=dt.date(2026, 9, 3), week=WEEK)


@pytest.fixture(scope="module")
def golden():
    d = AP / "marts" / WEEK
    if not d.exists():
        pytest.skip(f"no legacy marts at {d}")
    return {p.stem: pl.read_parquet(p) for p in d.glob("*.parquet")}


@pytest.mark.parametrize("table", ["raw_data", "case_ar",
                                   "delta_comparison", "collections"])
def test_matches_bat_pipeline(result, golden, table):
    if table not in golden:
        pytest.skip(f"{table}.parquet not produced by the legacy run")
    new, old = result.tables[table], golden[table]

    assert new.shape == old.shape, (
        f"{table}: {new.shape} vs the .bat pipeline's {old.shape}")
    assert sorted(new.columns) == sorted(old.columns), (
        f"{table}: only in new {sorted(set(new.columns) - set(old.columns))}, "
        f"only in golden {sorted(set(old.columns) - set(new.columns))}")

    a, b = _canonical(new), _canonical(old)
    if not a.equals(b):
        detail = [f"{c}: {(a[c] != b[c]).fill_null(True).sum()} of {b.height} differ"
                  for c in b.columns if (a[c] != b[c]).fill_null(True).sum()]
        pytest.fail(f"{table} differs\n  " + "\n  ".join(detail))


def test_settlement_grids_match(result, golden):
    """The dashboard's settlement figures, against the .bat pipeline's own.

    The legacy table is {Location, Group, Bucket, Amount}; the platform flattens
    the same grids to records. Comparing them checks the flattening as well as
    the arithmetic.
    """
    if "settlement" not in golden:
        pytest.skip("no settlement.parquet in the legacy marts")

    mine = pl.DataFrame(
        [{"Location": r["block"], "Group": r["group"],
          "Bucket": r["bucket"], "Amount": r["amount"]}
         for r in settlement_records(result.settlement_grids)],
        schema={"Location": pl.Utf8, "Group": pl.Utf8,
                "Bucket": pl.Utf8, "Amount": pl.Float64})

    assert mine.shape == golden["settlement"].shape
    assert _canonical(mine).equals(_canonical(golden["settlement"]))


def test_current_month_agrees(result, golden):
    if "period" not in golden:
        pytest.skip("no period.parquet")
    assert result.current_month == golden["period"]["month"][0]
