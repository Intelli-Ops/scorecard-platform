"""Content-addressed storage for uploaded source files.

A file is stored under the SHA-256 of its own bytes. Three things follow:

  IT IS THE UPLOAD CHECK. The browser sends a big file in chunks; the store
  hashes what it actually received. Same hash, same bytes - not "probably
  fine", identical. A mismatch is rejected before anything reads it.

  IDENTICAL FILES ARE STORED ONCE. The seven shared files are used by both
  reports, and Thursday's Case AR is often unchanged from Tuesday's. Storing
  by content means a re-upload of the same bytes costs nothing.

  A FILE CANNOT BE QUIETLY REPLACED. Change one byte and it lands at a new
  address; the old one stays for as long as a run names it. That is what lets
  a run in December still point at the exact bytes it read.

The extension is kept on the stored name because the Excel reader chooses its
parser from it - an .xlsb and an .xlsx are not read the same way.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import tempfile

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
        """Store a file under the hash of its bytes.

        One pass: the bytes are hashed as they are copied into a private
        temporary file, which is then renamed onto its address. Hashing,
        copying and re-hashing read a 240 MB workbook three times. A write
        cut short by a full disk raises, and the half-written file is removed
        rather than renamed.
        """
        source = Path(source)
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.root, suffix=".part")
        tmp = Path(tmp_name)
        h, size = hashlib.sha256(), 0
        try:
            with open(source, "rb") as src, os.fdopen(fd, "wb") as out:
                while chunk := src.read(CHUNK):
                    h.update(chunk)
                    out.write(chunk)
                    size += len(chunk)
            sha = h.hexdigest()
            dest = self._path_for(sha, source.suffix)
            if dest.exists():
                tmp.unlink()
                return StoredFile(sha, size, dest, deduplicated=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.replace(dest)
            return StoredFile(sha, size, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def path(self, sha: str, suffix: str) -> Path:
        p = self._path_for(sha, suffix)
        if not p.exists():
            raise FileNotFoundError(f"no stored file {sha[:12]}...{suffix}")
        return p

    def has(self, sha: str, suffix: str) -> bool:
        return self._path_for(sha, suffix).exists()

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
        only after the last run sharing them has gone - and only once that
        deletion has COMMITTED (see service/blobs.py), since a file cannot be
        rolled back.
        """
        p = self._path_for(sha, suffix)
        if not p.exists():
            return False
        p.unlink()
        return True
