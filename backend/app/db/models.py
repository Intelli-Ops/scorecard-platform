"""Database tables."""
from __future__ import annotations
import datetime as dt
import re

from sqlalchemy import (BigInteger, String, Integer, Float, Date, DateTime, ForeignKey,
                        Text, UniqueConstraint, Index, JSON, Boolean, event, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator
from ..clock import utcnow


class UtcDateTime(TypeDecorator):
    """A moment in time, stored as UTC and always handed back as UTC."""
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            from sqlalchemy.dialects.mysql import DATETIME
            return dialect.type_descriptor(DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=dt.timezone.utc)


class Base(DeclarativeBase):
    pass


BigId = BigInteger().with_variant(Integer, "sqlite")

ROLES = ("viewer", "admin", "system_admin")
ROLE_LABELS = {"viewer": "Viewer", "admin": "Admin", "system_admin": "System admin"}


def name_from_email(email: str | None) -> str:
    """A person's name from their work email: ali.asghar@appedology.com -> Ali Asghar."""
    local = (email or "").split("@")[0]
    words = re.split(r"[._\-+\s]+", local)
    return " ".join(w[:1].upper() + w[1:].lower() for w in words if w) or local


class User(Base):
    """An Appedology account."""
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    apd_id: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(),
                                                    default=utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    role: Mapped[str] = mapped_column(String(16), default="viewer",
                                      server_default="viewer")
    report_access: Mapped[str] = mapped_column(String(200), default="",
                                               server_default="")
    pending: Mapped[bool] = mapped_column(Boolean, default=False,
                                          server_default=text("0"))
    display_name: Mapped[str | None] = mapped_column(String(120))

    password_changed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"))

    failed_logins: Mapped[int] = mapped_column(Integer, default=0,
                                               server_default=text("0"))
    locked_until: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    email_verified_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    # The inputs an admin may upload, comma separated; None for every one.
    upload_access: Mapped[str | None] = mapped_column(String(400))

    @property
    def name(self) -> str:
        """What to call them: their chosen name, or one made from their email."""
        return self.display_name or name_from_email(self.email)

    @property
    def is_admin(self) -> bool:
        """Admin or above: the workspace, and the Users and Activity screens."""
        return self.role in ("admin", "system_admin")

    @property
    def is_system_admin(self) -> bool:
        return self.role == "system_admin"

    @property
    def reports(self) -> list[str]:
        """The report keys this account may read."""
        if self.is_admin:
            from ..reports import REPORTS
            return list(REPORTS)
        return [k for k in (self.report_access or "").split(",") if k]

    @property
    def uploads_all(self) -> bool:
        """May upload every input: a system admin, or an admin no one has narrowed."""
        return self.is_system_admin or (self.is_admin and self.upload_access is None)

    @property
    def uploads(self) -> list[str]:
        """The input keys this account may upload and take back."""
        if not self.is_admin:
            return []
        from ..reports import input_keys
        if self.uploads_all:
            return input_keys()
        return [k for k in self.upload_access.split(",") if k]

    @property
    def status(self) -> str:
        """One word for the Users screen."""
        if self.pending:
            return "pending" if self.email_verified_at else "unverified"
        if not self.is_active:
            return "disabled"
        if self.locked_until and self.locked_until > utcnow():
            return "locked"
        return "active"


class Session(Base):
    """A signed-in browser."""
    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(),
                                                    default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime())
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    ip: Mapped[str | None] = mapped_column(String(45))          # fits IPv6
    user_agent: Mapped[str | None] = mapped_column(String(400))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    user: Mapped[User] = relationship()


class OneTimeCode(Base):
    """A one-time code for an account - see service/auth.py, "One-time codes"."""
    __tablename__ = "one_time_code"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"))
    purpose: Mapped[str] = mapped_column(String(16))
    secret: Mapped[str] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime())
    used_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    user: Mapped[User] = relationship()

    __table_args__ = (Index("ix_one_time_code_user_purpose", "user_id", "purpose"),)


class Upload(Base):
    """One source file, as received."""
    __tablename__ = "upload"

    id: Mapped[int] = mapped_column(primary_key=True)
    week: Mapped[str] = mapped_column(String(9), index=True)      # 2026-W35
    report_key: Mapped[str | None] = mapped_column(String(32))    # NULL = shared
    source_key: Mapped[str] = mapped_column(String(32))           # owner_case_ar
    filename: Mapped[str] = mapped_column(String(400))
    suffix: Mapped[str] = mapped_column(String(8))                # .xlsb, .csv
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(),
                                                     default=utcnow)
    uploaded_by: Mapped[str | None] = mapped_column(String(200))
    # Deleted from its week after a build read it: hidden from the upload screen and
    # from the next build, kept only for the builds that record reading it.
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    withdrawn_by: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        Index("ix_upload_lookup", "week", "report_key", "source_key",
              "uploaded_at"),
    )


class Run(Base):
    """One attempt at building one report for one week."""
    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_key: Mapped[str] = mapped_column(String(32), index=True)
    week: Mapped[str] = mapped_column(String(9), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    as_of: Mapped[dt.date | None] = mapped_column()
    started_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(),
                                                    default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    seconds: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    approved_by: Mapped[str | None] = mapped_column(String(200))
    working_days: Mapped[int | None] = mapped_column(Integer)
    working_days_source: Mapped[str | None] = mapped_column(String(16))
    active_key: Mapped[str | None] = mapped_column(String(48), unique=True,
                                                   index=True)
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    inputs: Mapped[list["RunInput"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")
    notes: Mapped[list["RunNote"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunNote.seq")
    tables: Mapped[list["RunTable"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")
    figures: Mapped[list["RunFigure"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")


STATUSES = ("pending", "running", "review", "approved", "failed")
ACTIVE = ("pending", "running")


@event.listens_for(Run, "before_insert")
@event.listens_for(Run, "before_update")
def _keep_active_key(_mapper, _connection, run: Run) -> None:
    """Keep active_key in step with status, so a finished week can be built again."""
    run.active_key = (f"{run.report_key}:{run.week}"
                      if run.status in ACTIVE else None)


class RunInput(Base):
    """Exactly which upload each run consumed."""
    __tablename__ = "run_input"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("upload.id"))
    rows_read: Mapped[int | None] = mapped_column(Integer)
    seconds: Mapped[float | None] = mapped_column(Float)

    run: Mapped[Run] = relationship(back_populates="inputs")
    upload: Mapped[Upload] = relationship()

    __table_args__ = (UniqueConstraint("run_id", "upload_id"),)


class RunNote(Base):
    """The STEP 4 warnings, kept instead of scrolling past in a console."""
    __tablename__ = "run_note"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(64), default="", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    text: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="notes")


class RunFigure(Base):
    """The sheet-shaped results, as flat records."""
    __tablename__ = "run_figure"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    name: Mapped[str] = mapped_column(String(32))     # settlement, kpi, ...
    data: Mapped[list] = mapped_column(JSON, default=list)

    run: Mapped[Run] = relationship(back_populates="figures")

    __table_args__ = (UniqueConstraint("run_id", "name"),)


class RunTable(Base):
    """A table a run produced, held as parquet in the object store."""
    __tablename__ = "run_table"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))       # raw_data, case_ar, ...
    rows: Mapped[int] = mapped_column(Integer)
    columns: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(Integer)

    run: Mapped[Run] = relationship(back_populates="tables")

    __table_args__ = (UniqueConstraint("run_id", "name"),)


class ActivityLog(Base):
    """Who did what, when, and from where."""
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    user_id: Mapped[int | None] = mapped_column(Integer)
    email: Mapped[str | None] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(48))          # auth.login, run.approve
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    target: Mapped[str | None] = mapped_column(String(200))  # "run 12", "2026-W38"
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(400))

    __table_args__ = (
        Index("ix_activity_at", "at"),
        Index("ix_activity_user_at", "user_id", "at"),
        Index("ix_activity_email_at", "email", "at"),
        Index("ix_activity_action_at", "action", "at"),
        Index("ix_activity_ip_at", "ip", "at"),
    )

OUTCOMES = ("success", "failure", "denied")


class RateHit(Base):
    """One counted attempt - a wrong sign-in, a sign-up - against a key such as
    "login:203.0.113.9"."""
    __tablename__ = "rate_hit"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(80))
    at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)

    __table_args__ = (Index("ix_rate_hit_key_at", "key", "at"),)


class MonthSetting(Base):
    """Working days in a month, as entered on the upload screen."""
    __tablename__ = "month_setting"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)   # 2026-09
    working_days: Mapped[int] = mapped_column(Integer)
    set_by: Mapped[str | None] = mapped_column(String(320))
    set_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Holiday(Base):
    """A day off, left out of pacing."""
    __tablename__ = "holiday"

    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    set_by: Mapped[str | None] = mapped_column(String(320))
    set_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)


class CollectionHistory(Base):
    """One provider's collections for one month before the app kept collections
    itself: January to September 2026, loaded by migration 0008."""
    __tablename__ = "collection_history"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    month: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    regid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    provider: Mapped[str | None] = mapped_column(String(255))     # as the file named it
    amount: Mapped[float] = mapped_column(Float)


class Provider(Base):
    """A provider and the group its cases count under."""
    __tablename__ = "provider"

    regid: Mapped[int] = mapped_column(Integer, primary_key=True)     # BUSINESSREGID
    provider_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(32))
    provider_group: Mapped[str] = mapped_column(String(200))
    set_by: Mapped[str | None] = mapped_column(String(320))
    set_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
