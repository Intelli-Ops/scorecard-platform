"""The schema as it was when versioned migrations started. Do not edit."""
from __future__ import annotations

from sqlalchemy import (JSON, Boolean, Column, Date, Float, ForeignKey, Index,
                        Integer, MetaData, String, Table, Text,
                        UniqueConstraint, text)

from .models import BigId, UtcDateTime

metadata = MetaData()

Table(
    "user_account", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(320), nullable=False, unique=True, index=True),
    Column("apd_id", String(8), nullable=False, unique=True, index=True),
    Column("password_hash", String(255), nullable=False),
    Column("created_at", UtcDateTime(), nullable=False),
    Column("last_login_at", UtcDateTime()),
    Column("is_active", Boolean, nullable=False),
    Column("role", String(16), nullable=False, server_default="viewer"),
    Column("report_access", String(200), nullable=False, server_default=""),
    Column("pending", Boolean, nullable=False, server_default=text("0")),
    Column("display_name", String(120)),
    Column("password_changed_at", UtcDateTime()),
    Column("must_change_password", Boolean, nullable=False,
           server_default=text("0")),
    Column("failed_logins", Integer, nullable=False, server_default=text("0")),
    Column("locked_until", UtcDateTime()),
)

Table(
    "user_session", metadata,
    Column("id", Integer, primary_key=True),
    Column("token", String(64), nullable=False, unique=True, index=True),
    Column("user_id", ForeignKey("user_account.id"), nullable=False, index=True),
    Column("created_at", UtcDateTime(), nullable=False),
    Column("expires_at", UtcDateTime(), nullable=False),
    Column("revoked", Boolean, nullable=False),
    Column("ip", String(45)),
    Column("user_agent", String(400)),
    Column("last_seen_at", UtcDateTime()),
)

Table(
    "upload", metadata,
    Column("id", Integer, primary_key=True),
    Column("week", String(9), nullable=False, index=True),
    Column("report_key", String(32)),
    Column("source_key", String(32), nullable=False),
    Column("filename", String(400), nullable=False),
    Column("suffix", String(8), nullable=False),
    Column("sha256", String(64), nullable=False, index=True),
    Column("size_bytes", Integer, nullable=False),
    Column("uploaded_at", UtcDateTime(), nullable=False),
    Column("uploaded_by", String(200)),
    Index("ix_upload_lookup", "week", "report_key", "source_key", "uploaded_at"),
)

Table(
    "run", metadata,
    Column("id", Integer, primary_key=True),
    Column("report_key", String(32), nullable=False, index=True),
    Column("week", String(9), nullable=False, index=True),
    Column("status", String(16), nullable=False),
    Column("as_of", Date),
    Column("started_at", UtcDateTime(), nullable=False),
    Column("finished_at", UtcDateTime()),
    Column("seconds", Float),
    Column("error", Text),
    Column("approved_at", UtcDateTime()),
    Column("approved_by", String(200)),
    Column("working_days", Integer),
    Column("working_days_source", String(16)),
)

Table(
    "run_input", metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", ForeignKey("run.id"), nullable=False, index=True),
    Column("upload_id", ForeignKey("upload.id"), nullable=False),
    Column("rows_read", Integer),
    Column("seconds", Float),
    UniqueConstraint("run_id", "upload_id"),
)

Table(
    "run_note", metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", ForeignKey("run.id"), nullable=False, index=True),
    Column("seq", Integer, nullable=False),
    Column("code", String(64), nullable=False, index=True),
    Column("severity", String(16), nullable=False),
    Column("text", Text, nullable=False),
    Column("detail", JSON, nullable=False),
)

Table(
    "run_figure", metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", ForeignKey("run.id"), nullable=False, index=True),
    Column("name", String(32), nullable=False),
    Column("data", JSON, nullable=False),
    UniqueConstraint("run_id", "name"),
)

Table(
    "run_table", metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", ForeignKey("run.id"), nullable=False, index=True),
    Column("name", String(64), nullable=False),
    Column("rows", Integer, nullable=False),
    Column("columns", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("bytes", Integer, nullable=False),
    UniqueConstraint("run_id", "name"),
)

Table(
    "activity_log", metadata,
    Column("id", BigId, primary_key=True, autoincrement=True),
    Column("at", UtcDateTime(), nullable=False),
    Column("user_id", Integer),
    Column("email", String(320)),
    Column("action", String(48), nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("target", String(200)),
    Column("detail", JSON, nullable=False),
    Column("ip", String(45)),
    Column("user_agent", String(400)),
    Index("ix_activity_at", "at"),
    Index("ix_activity_user_at", "user_id", "at"),
    Index("ix_activity_email_at", "email", "at"),
    Index("ix_activity_action_at", "action", "at"),
    Index("ix_activity_ip_at", "ip", "at"),
)

Table(
    "month_setting", metadata,
    Column("month", String(7), primary_key=True),
    Column("working_days", Integer, nullable=False),
    Column("set_by", String(320)),
    Column("set_at", UtcDateTime(), nullable=False),
)
