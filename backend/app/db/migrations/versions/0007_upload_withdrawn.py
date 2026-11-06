"""Migration 0007: a file deleted after a build read it is withdrawn, not removed,
so the builds that read it keep a true account of their inputs.

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
