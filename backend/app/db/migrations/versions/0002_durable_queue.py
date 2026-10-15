"""Migration 0002: build queue, build lock and rate limits stored in the database.

Revision ID: 0002
Revises: 0001"""
from __future__ import annotations
import datetime as dt

from alembic import op
import sqlalchemy as sa

from app.db.models import BigId, UtcDateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("run", sa.Column("active_key", sa.String(48)))
    op.add_column("run", sa.Column("heartbeat_at", UtcDateTime()))
    op.create_index("ix_run_active_key", "run", ["active_key"], unique=True)

    run = sa.table("run", sa.column("status", sa.String), sa.column("error", sa.Text),
                   sa.column("finished_at", UtcDateTime()))
    op.execute(run.update().where(run.c.status.in_(("pending", "running"))).values(
        status="failed",
        error="Interrupted: the server was upgraded before this build "
              "finished. Build it again.",
        finished_at=dt.datetime.now(dt.timezone.utc)))

    op.create_table(
        "rate_hit",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("at", UtcDateTime(), nullable=False),
    )
    op.create_index("ix_rate_hit_key_at", "rate_hit", ["key", "at"])


def downgrade() -> None:
    op.drop_index("ix_rate_hit_key_at", table_name="rate_hit")
    op.drop_table("rate_hit")
    op.drop_index("ix_run_active_key", table_name="run")
    op.drop_column("run", "heartbeat_at")
    op.drop_column("run", "active_key")
