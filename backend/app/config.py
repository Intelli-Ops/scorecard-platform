"""Where things live. Every path in the project comes from here.

The .bat pipeline hard-coded a folder layout: inputs/, staging/, marts/,
outputs/, one subfolder per week, relative to the project root. That is what
made it a single-machine program.
"""
from __future__ import annotations
from pathlib import Path
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

        # The out-of-hours alert: sign-ins outside these hours, in this zone,
        # are flagged on the Activity screen. An IANA name ("Asia/Karachi");
        # empty means the server's own clock.
        self.timezone = os.environ.get("SCORECARD_TIMEZONE", "")
        start, _, end = os.environ.get("SCORECARD_WORK_HOURS", "7-21").partition("-")
        self.work_hours = (int(start), int(end or 24))

        # /docs lists every endpoint. Useful on a laptop; on a server it is a
        # map of the API handed to anyone who can reach it.
        self.api_docs = os.environ.get("SCORECARD_API_DOCS", "1") == "1"

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
