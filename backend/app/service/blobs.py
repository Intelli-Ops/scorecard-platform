"""Keeping the files on disk in step with the rows that name them.

A file and a database row cannot be saved or removed in one transaction: the
database can take a change back, the disk cannot. So the two are ordered such
that whatever fails, no row is ever left pointing at a file that is not there:

  * REMOVING a file waits until the transaction that dropped its last row
    has committed. If the commit fails, the rows come back and the file was
    never touched.
  * WRITING a file comes before its row, and is taken back if the row is then
    never saved.

Either way the worst outcome is a stored file nothing names - wasted space,
which `python -m app.manage clean-files` finds and removes - and never a
scorecard whose data has gone.
"""
from __future__ import annotations

from sqlalchemy import select

from ..db.session import after_commit, after_rollback, session
from ..storage.files import FileStore, StoredFile


def _drop_if_unreferenced(store: FileStore, sha: str, suffix: str, column) -> None:
    """Remove a stored file unless a saved row names its hash in `column`.

    Asked again here, in a transaction of its own, rather than trusted from
    the caller: between the caller's check and its commit, someone else may
    have uploaded the very same bytes and saved a row that needs them.
    """
    with session() as s:
        named = s.execute(select(column).where(column == sha).limit(1)).first()
    if named is None:
        store.remove(sha, suffix)


def remove_after_commit(s, store: FileStore, sha: str, suffix: str, column) -> bool:
    """Remove a stored file once `s` commits. True if there is one to remove
    that this transaction was not already going to."""
    going = s.info.setdefault("blobs_going", set())
    blob = (str(store.root), sha, suffix)
    if blob in going or not store.has(sha, suffix):
        return False
    going.add(blob)
    after_commit(s, lambda: _drop_if_unreferenced(store, sha, suffix, column))
    return True


def discard_on_rollback(s, store: FileStore, stored: StoredFile, suffix: str,
                        column) -> None:
    """Take a file just written back out of the store if `s` is rolled back.

    Only a file this call created: one that was already there (deduplicated)
    belongs to whichever row named it first.
    """
    if not stored.deduplicated:
        after_rollback(s, lambda: _drop_if_unreferenced(
            store, stored.sha256, suffix, column))
