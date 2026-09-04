"""Where things live. Every path in the project comes from here.

The .bat pipeline hard-coded a folder layout: inputs/, staging/, marts/,
outputs/, one subfolder per week, relative to the project root. That is what
made it a single-machine program.
"""
from __future__ import annotations
from pathlib import Path
import os


class Settings:
    def __init__(self) -> None:
        root = os.environ.get("SCORECARD_DATA", str(Path.cwd() / "data"))
        self.data_dir = Path(root)
        self.object_dir = self.data_dir / "objects"     # uploaded source files
        self.results_dir = self.data_dir / "results"    # parquet the runs produce
        self.database_url = os.environ.get(
            "SCORECARD_DB", f"sqlite:///{(self.data_dir / 'scorecard.db').as_posix()}")

    def ensure(self) -> None:
        for d in (self.data_dir, self.object_dir, self.results_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
