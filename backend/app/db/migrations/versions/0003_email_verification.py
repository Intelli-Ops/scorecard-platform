"""Migration 0003: email verification and one-time codes.

Revision ID: 0003
Revises: 0002"""
from __future__ import annotations
import datetime as dt

from alembic import op
import sqlalchemy as sa

from app.db.models import UtcDateTime

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_account", sa.Column("email_verified_at", UtcDateTime()))
    user = sa.table("user_account", sa.column("pending", sa.Boolean),
                    sa.column("email_verified_at", UtcDateTime()))
    op.execute(user.update().where(user.c.pending.is_(False))
               .values(email_verified_at=dt.datetime.now(dt.timezone.utc)))

    op.create_table(
        "one_time_code",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user_account.id"),
                  nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("secret", sa.String(255), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("expires_at", UtcDateTime(), nullable=False),
        sa.Column("used_at", UtcDateTime()),
    )
    op.create_index("ix_one_time_code_user_purpose", "one_time_code",
                    ["user_id", "purpose"])


def downgrade() -> None:
    op.drop_index("ix_one_time_code_user_purpose", table_name="one_time_code")
    op.drop_table("one_time_code")
    op.drop_column("user_account", "email_verified_at")
