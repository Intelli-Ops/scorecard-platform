"""Where things live. Every path in the project comes from here.

The .bat pipeline hard-coded a folder layout: inputs/, staging/, marts/,
outputs/, one subfolder per week, relative to the project root. That is what
made it a single-machine program.
"""
from __future__ import annotations
from pathlib import Path
from zoneinfo import ZoneInfo
import datetime as dt
import os


# The project root: .../scorecard-platform, two levels above this file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def database_url(url: str) -> str:
    """Tidy a database address into the form SQLAlchemy needs.

    A MySQL address may be written plainly - mysql://user:pass@host/scorecard,
    the way a DBA would hand it over. It is given the PyMySQL driver, and the
    utf8mb4 character set: MySQL's older "utf8" holds only three bytes per
    character and fails on an emoji or some names pasted from elsewhere.
    """
    if url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://"):]
    if url.startswith("mysql") and "charset=" not in url:
        url += ("&" if "?" in url else "?") + "charset=utf8mb4"
    return url


class Settings:
    def __init__(self) -> None:
        # Anchored to the project, NOT to the shell's working directory.
        # Defaulting to cwd meant starting the server from backend/ and running
        # a script from the project root used two different databases, each
        # looking empty to the other - a silent, confusing kind of wrong.
        root = os.environ.get("SCORECARD_DATA", str(PROJECT_ROOT / "data"))
        self.data_dir = Path(root)
        self.object_dir = self.data_dir / "objects"     # uploaded source files
        self.results_dir = self.data_dir / "results"    # parquet the runs produce
        self.database_url = database_url(os.environ.get(
            "SCORECARD_DB", f"sqlite:///{(self.data_dir / 'scorecard.db').as_posix()}"))

        # The zone the business works in, as an IANA name. Two things use it:
        # which DATE a build is made as of (see today()), and the out-of-hours
        # alert - sign-ins outside the hours below are flagged on the Activity
        # screen. Karachi unless told otherwise, wherever the server is.
        self.timezone = os.environ.get("SCORECARD_TIMEZONE") or "Asia/Karachi"
        start, _, end = os.environ.get("SCORECARD_WORK_HOURS", "7-21").partition("-")
        self.work_hours = (int(start), int(end or 24))

        # /docs lists every endpoint. Useful on a laptop; on a server it is a
        # map of the API handed to anyone who can reach it.
        self.api_docs = os.environ.get("SCORECARD_API_DOCS", "1") == "1"

        # Browser origins allowed to call the API directly, comma-separated.
        # The Vite dev server and nginx both serve the page and the API from
        # one origin, so on the server this can be left empty.
        self.cors_origins = [o.strip() for o in os.environ.get(
            "SCORECARD_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

        # The largest single uploaded file, in MB. The biggest real input is
        # about 240 MB; without a ceiling one request can fill the disk.
        self.max_upload_mb = int(os.environ.get("SCORECARD_MAX_UPLOAD_MB", "1024"))

        # 1 on a server: the API refuses anything that did not arrive over
        # HTTPS (see main.py), so a password or a session can never cross the
        # network in the clear because a certificate was not set up yet. Off
        # by default, for a laptop, where there is no certificate to have.
        self.require_https = os.environ.get("SCORECARD_REQUIRE_HTTPS", "0") == "1"

    def today(self) -> dt.date:
        """Today's date where the business is - not where the server is.

        A server in a data centre keeps UTC, five hours behind Karachi: a
        build started at 02:00 on Tuesday was dated Monday, and every "age in
        days" in it came out one short.
        """
        try:
            return dt.datetime.now(ZoneInfo(self.timezone)).date()
        except Exception:                     # unknown name, or no tz data
            return dt.date.today()

    def ensure(self) -> None:
        for d in (self.data_dir, self.object_dir, self.results_dir):
            d.mkdir(parents=True, exist_ok=True)

    def use(self, data_dir: Path) -> None:
        """Point everything at another directory.

        For tests, and for running two instances side by side. Callers must
        also reset the database session, since it caches its engine.
        """
        self.data_dir = Path(data_dir)
        self.object_dir = self.data_dir / "objects"
        self.results_dir = self.data_dir / "results"
        self.database_url = f"sqlite:///{(self.data_dir / 'scorecard.db').as_posix()}"
        self.ensure()


settings = Settings()
