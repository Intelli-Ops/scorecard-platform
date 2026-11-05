"""Migration 0006: which inputs each admin may upload.

Revision ID: 0006
Revises: 0005"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL - every input - so the admins there already keep what they had.
    op.add_column("user_account", sa.Column("upload_access", sa.String(400)))


def downgrade() -> None:
    op.drop_column("user_account", "upload_access")
