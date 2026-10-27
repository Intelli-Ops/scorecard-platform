"""Migration 0004: the holiday table, seeded with the list rules.yml had.

Revision ID: 0004
Revises: 0003"""
from __future__ import annotations
import datetime as dt

from alembic import op
import sqlalchemy as sa

from app.db.models import UtcDateTime

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

STARTING = [
    (dt.date(2026, 1, 1), "New Year"),
    (dt.date(2026, 2, 16), "Presidents' Day (U.S.)"),
    (dt.date(2026, 3, 20), "Eid ul-Fitr (Pakistan)"),
    (dt.date(2026, 5, 25), "Memorial Day (U.S.)"),
    (dt.date(2026, 5, 27), "Eid ul-Azha"),
    (dt.date(2026, 7, 3), "Independence Day (observed U.S.)"),
    (dt.date(2026, 9, 7), "Labour Day"),
    (dt.date(2026, 11, 26), "Thanksgiving Day (U.S.)"),
    (dt.date(2026, 12, 25), "Christmas Day"),
]


def upgrade() -> None:
    holiday = op.create_table(
        "holiday",
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("set_by", sa.String(320)),
        sa.Column("set_at", UtcDateTime(), nullable=False),
    )
    now = dt.datetime.now(dt.timezone.utc)
    op.bulk_insert(holiday, [{"day": d, "name": n, "set_by": None, "set_at": now}
                             for d, n in STARTING])


def downgrade() -> None:
    op.drop_table("holiday")
