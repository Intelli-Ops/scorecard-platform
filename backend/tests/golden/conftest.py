"""The golden master needs real client data, which is never committed.

When that data is not on the machine these tests used to SKIP - and a skipped
test is green. The check that the calculations still produce the approved
numbers could quietly not run, on a developer's machine or on the way to a
release, and nothing said so.

Now a missing reference FAILS, saying what is missing and how to make it.
Someone who really has no client data on their machine says so out loud:

    $env:GFS_GOLDEN_OPTIONAL = "1"

and gets the old skip. deploy/make_package.py never sets it, so a release
cannot be made without the golden master having run.
"""
from __future__ import annotations
import os

import pytest


def _require(present, why: str) -> None:
    if present:
        return
    if os.environ.get("GFS_GOLDEN_OPTIONAL") == "1":
        pytest.skip(why)
    pytest.fail(
        f"golden master cannot run: {why}\n"
        f"Build that report for a week in the app, review and approve it, "
        f"then run `python -m app.manage save-golden RUN_ID` from backend/ "
        f"(see README, 'The golden-master tests'). Or set "
        f"GFS_GOLDEN_OPTIONAL=1 to skip these on a machine without client "
        f"data.", pytrace=False)


@pytest.fixture(scope="session")
def require():
    """require(condition, why) - fail (or, if opted out, skip) unless the
    reference the golden master compares against is there."""
    return _require
