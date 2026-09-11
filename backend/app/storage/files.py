"""Content-addressed storage for uploaded source files.

A file is stored under the SHA-256 of its own bytes. Three things follow:

  IT IS THE UPLOAD CHECK. The browser sends a big file in chunks; the store
  hashes what it actually received. Same hash, same bytes - not "probably
  fine", identical. A mismatch is rejected before anything reads it.

  IDENTICAL FILES ARE STORED ONCE. The seven shared files are used by both
  reports, and Thursday's Case AR is often unchanged from Tuesday's. Storing
  by content means a re-upload of the same bytes costs nothing.

  A FILE CANNOT BE QUIETLY REPLACED. Change one byte and it lands at a new
  address; the old one stays. That is what lets a run in December still point
  at the exact bytes it read.

The extension is kept on the stored name because the Excel reader chooses its
parser from it - an .xlsb and an .xlsx are not read the same way.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import shutil

CHUNK = 1024 * 1024      # 1 MB - big files are never held whole in memory


@dataclass(frozen=True)
class StoredFile:
    sha256: str
    size: int
    path: Path
    deduplicated: bool = False


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


class FileStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path_for(self, sha: str, suffix: str) -> Path:
        # Two-character prefix directory: a flat folder with tens of thousands
        # of files is slow to list on Windows.
        return self.root / sha[:2] / f"{sha}{suffix.lower()}"

    def put(self, source: Path) -> StoredFile:
        source = Path(source)
        sha = sha256_of(source)
        dest = self._path_for(sha, source.suffix)
        size = source.stat().st_size

        if dest.exists():
            return StoredFile(sha, size, dest, deduplicated=True)

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        shutil.copyfile(source, tmp)
        # Re-hash what actually landed. A copy that was truncated by a full
        # disk must not be recorded as a good upload.
        if sha256_of(tmp) != sha:
            tmp.unlink(missing_ok=True)
            raise IOError(f"{source.name}: content changed while being stored")
        tmp.replace(dest)
        return StoredFile(sha, size, dest)

    def path(self, sha: str, suffix: str) -> Path:
        p = self._path_for(sha, suffix)
        if not p.exists():
            raise FileNotFoundError(f"no stored file {sha[:12]}...{suffix}")
        return p

    def verify(self, sha: str, suffix: str) -> bool:
        """Re-read the bytes and check they still hash to their own address."""
        return sha256_of(self.path(sha, suffix)) == sha

    def remove(self, sha: str, suffix: str) -> bool:
        """Delete one stored blob. True if it was there.

        Only ever called once NOTHING IN THE DATABASE points at the hash any
        more - for a result, no RunTable row; for a source upload, no Upload
        row. That condition is the whole safety property: while a run still
        names these bytes they stay, so a run from December can still be asked
        exactly what it read. Deleting a run is what retires its files, and
        only after the last run sharing them has gone.
        """
        p = self._path_for(sha, suffix)
        if not p.exists():
            return False
        p.unlink()
        return True
