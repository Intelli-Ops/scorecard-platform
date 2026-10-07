"""The golden master: one approved build per report, kept as the reference.

The question it answers is "does the code still produce, from the same files,
the numbers a person checked and approved?" - the only test of the figures
themselves, and the one that catches a change which moved a total nobody
meant to move.

The reference used to be the old .bat pipeline's output, which tied the test
to a folder of that pipeline's files on one laptop. It is now this app's own
work: build a week, review it, approve it, and save THAT run -

    python -m app.manage save-golden RUN_ID

- which copies, into settings.golden_dir:

    objects/<sha256>.<ext>      the exact files the run read (stored once,
                                though both reports read seven of them)
    <report>/<table>.parquet    the tables it produced
    <report>/golden.json        its week, date, working days, figures and
                                notes, and which file fed which source

Nothing in there changes when new weeks are uploaded or old data is
corrected: the inputs are copies, frozen. Only a change to the CODE (or to
rules.yml) can make the comparison fail. When such a change is intended, look
at what moved, approve a build made with the new code, and save it again.

Real client data: the folder is in .gitignore and never committed.
"""
from __future__ import annotations
import datetime as dt
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..db.models import Run
from ..reports import get as get_report
from ..reports.locate import SourceSet
from ..storage.files import FileStore
from . import runner

META = "golden.json"


@dataclass
class Golden:
    """A saved reference, read back."""
    meta: dict
    directory: Path                   # <golden_dir>/<report>
    objects: FileStore

    @property
    def tables(self) -> dict[str, Path]:
        return {p.stem: p for p in sorted(self.directory.glob("*.parquet"))}

    def plan(self) -> runner.Plan:
        """What to hand runner.compute() to make the same build again."""
        m = self.meta
        report = get_report(m["report_key"])
        found = {i["source_key"]: self.objects.path(i["sha256"], i["suffix"])
                 for i in m["inputs"]}
        return runner.Plan(
            report_key=m["report_key"], week=m["week"],
            as_of=dt.date.fromisoformat(m["as_of"]),
            rules=runner.rules_for(m["report_key"], m["week"], m["working_days"],
                                   m["working_days_source"]),
            sources=SourceSet(report=report, found=found, missing=tuple(
                s for s in report.sources if s.key not in found)),
            upload_ids={})


def load(report_key: str, directory: Path | None = None) -> Golden | None:
    """The reference saved for a report, or None if there is none."""
    root = Path(directory or settings.golden_dir)
    meta = root / report_key / META
    if not meta.is_file():
        return None
    return Golden(meta=json.loads(meta.read_text(encoding="utf-8")),
                  directory=root / report_key,
                  objects=FileStore(root / "objects"))


def save(run: Run, directory: Path | None = None,
         objects: FileStore | None = None,
         results: FileStore | None = None) -> dict:
    """Make `run` the reference for its report, replacing the one before.

    Only an APPROVED run: the whole worth of the reference is that a person
    looked at these numbers and signed them off.
    """
    if run.status != "approved":
        raise ValueError(f"run {run.id} is {run.status}, not approved - the "
                         f"reference has to be a build someone signed off")
    if run.as_of is None:
        raise ValueError(f"run {run.id} was built before the date a build is "
                         f"made as of was recorded - build the week again")
    root = Path(directory or settings.golden_dir)
    objects = objects or FileStore(settings.object_dir)
    results = results or FileStore(settings.results_dir)
    kept = FileStore(root / "objects")

    inputs = []
    for ri in sorted(run.inputs, key=lambda ri: ri.upload.source_key):
        u = ri.upload
        kept.put(objects.path(u.sha256, u.suffix))
        inputs.append({"source_key": u.source_key, "filename": u.filename,
                       "sha256": u.sha256, "suffix": u.suffix,
                       "rows_read": ri.rows_read})

    target = root / run.report_key
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for t in run.tables:
        shutil.copyfile(results.path(t.sha256, ".parquet"),
                        target / f"{t.name}.parquet")

    meta = {
        "report_key": run.report_key, "week": run.week,
        "as_of": run.as_of.isoformat(),
        "working_days": run.working_days,
        "working_days_source": run.working_days_source,
        "run_id": run.id, "approved_by": run.approved_by,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "inputs": inputs,
        "tables": {t.name: t.rows for t in run.tables},
        "figures": {f.name: f.data for f in run.figures},
        # What the build said about itself. Notes added afterwards - an
        # approval taken back - are about the run's life, not its numbers.
        "notes": sorted([n.code, n.severity] for n in run.notes
                        if not n.code.startswith("approval.")),
    }
    (target / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    _prune(root)
    return {"report_key": run.report_key, "week": run.week, "run_id": run.id,
            "inputs": len(inputs), "tables": len(meta["tables"]),
            "directory": str(target)}


def _prune(root: Path) -> None:
    """Drop kept input files no saved reference names any more - the ones
    the reference just replaced had to itself."""
    named = set()
    for meta in root.glob(f"*/{META}"):
        named |= {i["sha256"] for i in
                  json.loads(meta.read_text(encoding="utf-8"))["inputs"]}
    for path in (root / "objects").rglob("*"):
        if path.is_file() and path.stem not in named:
            path.unlink()
