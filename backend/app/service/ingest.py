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

from ..config import settings
from ..db.session import after_commit
from ..reports import CASE_AR_KEYS, REPORTS, ReportType, SourceFile
from ..reports.locate import _matches
from ..storage.files import FileStore
from ..db.models import RunInput, Upload
from . import blobs


# The longest file name taken, in bytes. A name is first written to disk as
# it is, and Linux allows 255 bytes for one - well inside the 400 characters
# the Upload.filename column holds. Real names run to about 60.
MAX_NAME = 240


def too_long(name: str) -> str | None:
    """Why this name is refused, or None if it is fine."""
    if len(name.encode("utf-8")) > MAX_NAME:
        return f"the file name is longer than {MAX_NAME} characters - shorten it"
    return None


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

        if too_long(path.name):
            result.rejected.append((path.name[:60] + "...", too_long(path.name)))
            continue

        if spec.key in CASE_AR_KEYS and for_report is None:
            result.rejected.append(
                (path.name, f"{spec.label} differs per report - say which report "
                            f"this copy is for"))
            continue

        report_key = for_report if spec.key in CASE_AR_KEYS else None
        stored = store.put(path)
        # The file is on disk before its row is saved. If the row never is,
        # the file is taken back out rather than left with nothing naming it.
        blobs.discard_on_rollback(session, store, stored, path.suffix,
                                  Upload.sha256)

        new = Upload(week=week, report_key=report_key, source_key=spec.key,
                     filename=path.name, suffix=path.suffix.lower(),
                     sha256=stored.sha256, size_bytes=stored.size,
                     uploaded_by=uploaded_by)
        session.add(new)
        session.flush()
        # A newer copy REPLACES the one before it. The old one used to be
        # kept - so the disk only ever grew, and removing a wrong file put
        # the file it had replaced back in its place. It goes now, unless a
        # build has read it: that build's record of what it was made from
        # must stay true, so that copy stays for as long as the build does.
        earlier = session.execute(select(Upload.id).where(
            Upload.week == week, Upload.source_key == spec.key,
            Upload.report_key.is_(None) if report_key is None
            else Upload.report_key == report_key,
            Upload.id != new.id)).scalars().all()
        retire_uploads(session, earlier, store)

        result.accepted.append(Accepted(
            source_key=spec.key, label=spec.label, filename=path.name,
            report_key=report_key, sha256=stored.sha256,
            size_bytes=stored.size, deduplicated=stored.deduplicated))

    session.flush()
    return result


def retire_uploads(session: Session, upload_ids, objects: FileStore) -> tuple[int, int]:
    """Remove uploads nothing reads any more, and the bytes behind them.

    Two levels of reference counting, because both are shared on purpose:

      * the ROW goes only once no RunInput names it. An upload belongs to the
        week, not to one run - the seven shared files feed both reports and
        every rebuild reads them again.
      * the BLOB goes only once no Upload row names its hash. Identical files
        are stored once, and Thursday's Case AR is often byte-for-byte
        Tuesday's, so one stored file can back two rows - and two weeks.

    The rows go now, inside the caller's transaction. The bytes go only once
    that transaction has COMMITTED: a row can be rolled back and a deleted
    file cannot, and done the other way round a commit that failed would put
    back rows pointing at files that no longer exist. The file's parsed copy
    in the week's cache goes with it.

    Returns (rows removed, blobs that will be unlinked).
    """
    rows_gone, blobs_gone = 0, 0
    for upload_id in upload_ids:
        still_read = session.execute(
            select(RunInput.id).where(RunInput.upload_id == upload_id).limit(1)
        ).scalar_one_or_none()
        if still_read is not None:
            continue                      # a run still reads this file
        upload = session.get(Upload, upload_id)
        if upload is None:
            continue
        sha, suffix, week = upload.sha256, upload.suffix, upload.week
        session.delete(upload)
        session.flush()
        rows_gone += 1
        shared = session.execute(
            select(Upload.id).where(Upload.sha256 == sha).limit(1)
        ).scalar_one_or_none()
        if shared is None and blobs.remove_after_commit(
                session, objects, sha, suffix, Upload.sha256):
            blobs_gone += 1
            after_commit(session, _forget_parsed(week, sha))
    return rows_gone, blobs_gone


def _forget_parsed(week: str, sha: str):
    """Drop a stored file's parsed copy from its week's cache (named after
    the stored file - see ParquetCache.key_for)."""
    cache = settings.data_dir / "cache" / week

    def forget() -> None:
        for path in cache.rglob(f"*-{sha[:16]}-*.parquet"):
            path.unlink(missing_ok=True)
    return forget


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


def week_status(session: Session, week: str) -> dict:
    """What the upload screen shows: which files are in, which are still needed."""
    # Every row held for the week, not just the latest per source. A copy that
    # was replaced after a build had read it is kept for that build, so this
    # can be larger than what `have` lists - and it is the number deleting
    # the week would remove.
    rows = _week_uploads(session, week)
    # An upload a build has read cannot be removed on its own - see
    # runner.remove_upload - so the screen is told which those are.
    read = set(session.execute(
        select(RunInput.upload_id).where(
            RunInput.upload_id.in_([u.id for u in rows]))).scalars()) if rows else set()
    out = {"week": week, "files": len(rows), "reports": {}}
    for key, report in REPORTS.items():
        uploads = latest_uploads(session, report, week, rows)
        out["reports"][key] = {
            "label": report.label,
            "send_day": report.send_day,
            "have": [{"id": u.id, "source_key": k, "filename": u.filename,
                      "uploaded_at": u.uploaded_at, "size_bytes": u.size_bytes,
                      "sha256": u.sha256, "read_by_a_build": u.id in read}
                     for k, u in uploads.items()],
            "missing": [s.label for s in report.sources
                        if s.key not in uploads and s.required],
            "ready": all(s.key in uploads for s in report.sources if s.required),
        }
    return out
