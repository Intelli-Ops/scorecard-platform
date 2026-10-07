"""The build queue, the build lock and the sign-in rate limits move into the
database, so none of them depends on there being exactly one server process.

  run.active_key     unique while a run is pending or running: the database,
                     not a lock in one process, refuses a second build
  run.heartbeat_at   how a build whose process died is told from one that is
                     still being worked on
  rate_hit           the rate limiter's counts, which used to be a dict in
                     the server's memory

Revision ID: 0002
Revises: 0001
"""
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

    # A build still waiting or under way was queued by the old code, in the
    # memory of a process that has now stopped, and without a record of the
    # files it was to read - so the new worker has nothing to run it from.
    # Closed off, exactly as the old start-up did on every restart.
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
