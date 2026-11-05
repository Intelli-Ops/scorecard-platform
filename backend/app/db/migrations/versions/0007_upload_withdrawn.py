"""Migration 0007: an uploaded file can be deleted after a build has read it.

The file leaves the week - the upload screen and the next build no longer see it -
but its row stays while a build still records reading it, so finished scorecards
keep a true account of their inputs. Deleting those builds clears it for good.

Revision ID: 0007
Revises: 0006"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models import UtcDateTime

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL - still in its week - for every file already held.
    op.add_column("upload", sa.Column("withdrawn_at", UtcDateTime()))
    op.add_column("upload", sa.Column("withdrawn_by", sa.String(200)))


def downgrade() -> None:
    op.drop_column("upload", "withdrawn_by")
    op.drop_column("upload", "withdrawn_at")
