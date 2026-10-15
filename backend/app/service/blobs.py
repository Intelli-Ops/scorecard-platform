"""Keeps stored files in step with the database rows that point to them."""
from __future__ import annotations

from sqlalchemy import select

from ..db.session import after_commit, after_rollback, session
from ..storage.files import FileStore, StoredFile


def _drop_if_unreferenced(store: FileStore, sha: str, suffix: str, column) -> None:
    """Remove a stored file unless a saved row names its hash in `column`."""
    with session() as s:
        named = s.execute(select(column).where(column == sha).limit(1)).first()
    if named is None:
        store.remove(sha, suffix)


def remove_after_commit(s, store: FileStore, sha: str, suffix: str, column) -> bool:
    """Remove a stored file once `s` commits."""
    going = s.info.setdefault("blobs_going", set())
    blob = (str(store.root), sha, suffix)
    if blob in going or not store.has(sha, suffix):
        return False
    going.add(blob)
    after_commit(s, lambda: _drop_if_unreferenced(store, sha, suffix, column))
    return True


def discard_on_rollback(s, store: FileStore, stored: StoredFile, suffix: str,
                        column) -> None:
    """Take a file just written back out of the store if `s` is rolled back."""
    if not stored.deduplicated:
        after_rollback(s, lambda: _drop_if_unreferenced(
            store, stored.sha256, suffix, column))
