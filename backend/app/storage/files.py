"""File storage addressed by each file's SHA-256 hash."""
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
        return self.root / sha[:2] / f"{sha}{suffix.lower()}"

    def put(self, source: Path) -> StoredFile:
        """Store a file under the hash of its bytes."""
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
        """Delete one stored blob."""
        p = self._path_for(sha, suffix)
        if not p.exists():
            return False
        p.unlink()
        return True
