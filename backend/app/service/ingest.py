"""Taking uploaded files in: classify, store, record.

Replaces "drop the files into inputs/2026-W36/". The classifying is the same
filename matching the .bat pipeline did, so nobody has to rename anything, but
it happens at upload time rather than at run time - a missing or duplicated
file is reported while the person is still there to fix it.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..reports import CASE_AR_KEYS, REPORTS, ReportType, SourceFile
from ..reports.locate import SourceSet, _matches
from ..storage.files import FileStore
from ..db.models import Upload


@dataclass
class Accepted:
    source_key: str
    label: str
    filename: str
    report_key: str | None
    sha256: str
    size_bytes: int
    deduplicated: bool


@dataclass
class IngestResult:
    accepted: list[Accepted] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)   # (file, why)


def _all_sources() -> tuple[SourceFile, ...]:
    """Every input any report declares, deduplicated.

    Built from the registry rather than from the shared + Case AR lists, so a
    file only one report needs - All Providers reads its KPI layout out of last
    week's workbook - is still recognised. Hard-coding the two lists here meant
    that file was silently rejected as "not one of the nine inputs".
    """
    seen: dict[str, SourceFile] = {}
    for report in REPORTS.values():
        for spec in report.sources:
            seen.setdefault(spec.key, spec)
    return tuple(seen.values())


def classify(path: Path) -> SourceFile | None:
    """Which input is this file? None if it is not one of them."""
    for spec in _all_sources():
        if _matches(spec, path):
            return spec
    return None


def ingest(session: Session, store: FileStore, week: str, paths: list[Path],
           for_report: str | None = None,
           uploaded_by: str | None = None) -> IngestResult:
    """Store and record a batch of uploaded files.

    for_report is required only for the two Case AR files, because those are
    the ones that differ between GFS (Tuesday) and All Providers (Thursday).
    Rejecting them rather than guessing is deliberate: guessing wrong attaches
    Thursday's case activity to Tuesday's report, and nothing in the file would
    ever reveal it.
    """
    result = IngestResult()

    for path in paths:
        path = Path(path)
        spec = classify(path)
        if spec is None:
            result.rejected.append((path.name, "not one of the report inputs"))
            continue

        if spec.key in CASE_AR_KEYS and for_report is None:
            result.rejected.append(
                (path.name, f"{spec.label} differs per report - say which report "
                            f"this copy is for"))
            continue

        report_key = for_report if spec.key in CASE_AR_KEYS else None
        stored = store.put(path)

        session.add(Upload(week=week, report_key=report_key, source_key=spec.key,
                           filename=path.name, suffix=path.suffix.lower(),
                           sha256=stored.sha256, size_bytes=stored.size,
                           uploaded_by=uploaded_by))
        result.accepted.append(Accepted(
            source_key=spec.key, label=spec.label, filename=path.name,
            report_key=report_key, sha256=stored.sha256,
            size_bytes=stored.size, deduplicated=stored.deduplicated))

    session.flush()
    return result


def _week_uploads(session: Session, week: str) -> list[Upload]:
    """Every upload held for a week, newest first - one query, which each
    report then picks its own files out of."""
    return list(session.execute(
        select(Upload).where(Upload.week == week)
        .order_by(Upload.uploaded_at.desc(), Upload.id.desc())).scalars())


def latest_uploads(session: Session, report: ReportType, week: str,
                   rows: list[Upload] | None = None) -> dict[str, Upload]:
    """The upload each source_key currently resolves to for this report.

    Shared files match on report_key IS NULL; the two Case AR files must match
    this report specifically - falling back to another report's copy would
    silently mix Tuesday's and Thursday's data.

    `rows` is the week's uploads, newest first, when the caller already has
    them; otherwise they are fetched.
    """
    wanted = {s.key for s in report.sources}
    out: dict[str, Upload] = {}
    for row in (_week_uploads(session, week) if rows is None else rows):
        if row.source_key not in wanted or row.source_key in out:
            continue
        scope = report.key if row.source_key in CASE_AR_KEYS else None
        if row.report_key == scope:
            out[row.source_key] = row
    return out


def source_set(session: Session, store: FileStore, report: ReportType,
               week: str) -> tuple[SourceSet, dict[str, Upload]]:
    """Build what the reader expects, out of the database and object store."""
    uploads = latest_uploads(session, report, week)
    found = {key: store.path(u.sha256, u.suffix) for key, u in uploads.items()}
    missing = tuple(s for s in report.sources if s.key not in found)
    return SourceSet(report=report, found=found, missing=missing), uploads


def week_status(session: Session, week: str) -> dict:
    """What the upload screen shows: which files are in, which are still needed."""
    # Every row held for the week, not just the latest per source. A corrected
    # re-upload is a new row and the old one is kept, so this is larger than
    # what `have` lists - and it is the number deleting the week would remove.
    rows = _week_uploads(session, week)
    out = {"week": week, "files": len(rows), "reports": {}}
    for key, report in REPORTS.items():
        uploads = latest_uploads(session, report, week, rows)
        out["reports"][key] = {
            "label": report.label,
            "send_day": report.send_day,
            "have": [{"source_key": k, "filename": u.filename,
                      "uploaded_at": u.uploaded_at, "size_bytes": u.size_bytes,
                      "sha256": u.sha256}
                     for k, u in uploads.items()],
            "missing": [s.label for s in report.sources
                        if s.key not in uploads and s.required],
            "ready": all(s.key in uploads for s in report.sources if s.required),
        }
    return out
