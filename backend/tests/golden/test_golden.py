"""Golden master: the code must still produce the numbers that were approved.

For each report, the reference is one build a person reviewed and approved,
saved with `python -m app.manage save-golden RUN_ID` (see
app/service/golden.py): the exact files it read, and everything it produced.
This reads those same files again with today's code and compares.

Nothing here looks at this week's uploads. The inputs are frozen copies, so
new data and corrected data cannot make it fail - only a change to the code
or to rules.yml can. When it fails after a change that was MEANT to move the
numbers, read what moved, approve a build made with the new code, and save it
as the reference again.

HOW EQUALITY IS DEFINED, AND WHY IT IS NOT `frame.equals`
---------------------------------------------------------
Two deliberate tolerances, neither of which hides a wrong number:

1. ROW ORDER IS NOT COMPARED. Polars group-bys and joins are multi-threaded
   and do not promise a stable row order between runs. The tables are
   compared as sets of rows. A missing, extra or altered row still fails.

2. MONEY IS COMPARED TO THE CENT. Summing the same 278,930 values in a
   different order gives answers that differ in the last bit of a double:
   the largest observed gap is 0.0000008 on a total of 299,693,534.89, a
   relative error of 3e-15. Rounding to 2dp is the same precision the client
   reads off the sheet. A real discrepancy of one cent still fails.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path

import polars as pl
import pytest

from app.config import settings
from app.reports import REPORTS
from app.reports.cache import ParquetCache
from app.service import golden, runner
from app.service.figures import all_figures

MONEY_COLUMNS = 2  # decimal places the client reads


def _canonical(df: pl.DataFrame) -> pl.DataFrame:
    """Column order, float precision and row order all made comparable."""
    df = df.select(sorted(df.columns))
    df = df.with_columns(
        [pl.col(c).round(MONEY_COLUMNS) for c, t in zip(df.columns, df.dtypes)
         if t in (pl.Float32, pl.Float64)])
    return df.sort(by=df.columns, nulls_last=True)


@pytest.fixture(scope="module", params=sorted(REPORTS))
def build(request, require):
    """(the saved reference, what was read, what was calculated) for one
    report - calculated once, and looked at by every test below."""
    key = request.param
    ref = golden.load(key)
    require(ref is not None,
            f"no reference saved for {REPORTS[key].label} in {settings.golden_dir}")
    cache = ParquetCache(Path(os.environ.get("GFS_CACHE_DIR", ".golden-cache"))
                         / ref.meta["week"] / key)
    src, result = runner.compute(ref.plan(), cache)
    return ref, src, result


def test_every_table_matches_the_approved_build(build):
    ref, _, result = build
    assert sorted(result.tables) == sorted(ref.tables), "the set of tables changed"

    problems = []
    for name, path in ref.tables.items():
        new, old = result.tables[name], pl.read_parquet(path)
        if new.shape != old.shape:
            problems.append(f"{name}: {new.shape} rows/cols, approved {old.shape}")
        elif sorted(new.columns) != sorted(old.columns):
            problems.append(
                f"{name}: columns differ - "
                f"only now {sorted(set(new.columns) - set(old.columns))}, "
                f"only approved {sorted(set(old.columns) - set(new.columns))}")
        else:
            a, b = _canonical(new), _canonical(old)
            if not a.equals(b):
                for c in b.columns:
                    ne = (a[c] != b[c]).fill_null(True).sum()
                    if ne:
                        problems.append(f"{name}.{c}: {ne} of {b.height} rows differ")
    assert not problems, ("differs from the approved build\n  "
                          + "\n  ".join(problems))


def _same(a, b) -> bool:
    """Equal, with numbers compared to well under a cent and lists compared
    without regard to order - the same two tolerances as the tables."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(
            _same(x, y) for x, y in zip(sorted(a, key=_order), sorted(b, key=_order)))
    return a == b


def _order(value) -> str:
    def rounded(v):
        if isinstance(v, float):
            return round(v, 4)
        if isinstance(v, dict):
            return {k: rounded(x) for k, x in v.items()}
        if isinstance(v, list):
            return [rounded(x) for x in v]
        return v
    return json.dumps(rounded(value), sort_keys=True, default=str)


def test_the_dashboard_figures_match_the_approved_build(build):
    """Settlement grids, KPI blocks, pace - what the dashboard draws, which
    never pass through a table and so are not covered by the test above."""
    ref, _, result = build
    # Through JSON, as the approved ones went through the database.
    now = json.loads(json.dumps(all_figures(result), default=str))
    was = ref.meta["figures"]
    assert sorted(now) == sorted(was), "the set of figures changed"
    differ = [name for name in was if not _same(now[name], was[name])]
    assert not differ, f"figures differ from the approved build: {differ}"


def test_the_build_raises_the_same_checks(build):
    """A check that appears or disappears with no change to the data is a
    change in the logic, even if every total happens to agree."""
    ref, _, result = build
    now = sorted([n.code, n.severity] for n in result.notes)
    assert now == ref.meta["notes"]


def test_every_file_is_read_as_it_was(build):
    """The same rows out of each file. Several reads can come from one file -
    the delta workbooks give three sheets from two files - so they are added
    up per file, as the run's own record of what it read is."""
    ref, src, _ = build
    rows: dict[str, int] = {}
    for r in src.reads:
        rows[r.source_key] = rows.get(r.source_key, 0) + r.rows
    was = {i["source_key"]: i["rows_read"] for i in ref.meta["inputs"]}
    assert {k: rows.get(k) for k in was} == was
