"""The schema as it stood when migrations became versioned.

Revision ID: 0001
Revises:
"""
from __future__ import annotations

from alembic import op

from app.db import baseline

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    baseline.metadata.create_all(op.get_bind())


def downgrade() -> None:
    baseline.metadata.drop_all(op.get_bind())
