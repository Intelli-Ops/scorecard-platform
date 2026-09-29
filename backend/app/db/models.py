"""What replaces the week folders.

The .bat pipeline recorded a week by making four directories named after it.
That is a real audit trail - inputs/2026-W35/ still holds the exact files that
produced Week 35 - but it can only be read by someone sitting at that laptop,
and it records nothing about WHO ran it, WHEN, or what the run reported.

These tables keep the same guarantee and add the missing half. A week is rows,
not directories; the files themselves stay in the object store, addressed by
the hash of their own bytes.
"""
from __future__ import annotations
import datetime as dt

from sqlalchemy import (BigInteger, String, Integer, Float, DateTime, ForeignKey,
                        Text, UniqueConstraint, Index, JSON, Boolean, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """A moment in time, stored as UTC and always handed back as UTC.

    Neither SQLite nor MySQL keeps a time zone: both give back a bare
    2026-09-28 09:14, and a bare time sent to the browser is read as the
    BROWSER's local time - so a sign-in at 09:14 UTC would be shown as 09:14
    local, hours out. Stored naive in UTC and returned aware, the zone
    survives the round trip on every database alike.
    """
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        # MySQL's DATETIME drops fractions of a second unless asked, and two
        # events in the same second must still sort in the order they happened.
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


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# An auto-numbered 64-bit id. SQLite only auto-numbers a column declared
# INTEGER, so it keeps that there; MySQL gets BIGINT, because the activity log
# is kept forever and a 32-bit id runs out at 2.1 billion rows.
BigId = BigInteger().with_variant(Integer, "sqlite")

# viewer        reads the approved scorecards it has been given, nothing else
# admin         the workspace - uploads, builds, approvals - and viewers' accounts
# system_admin  everything an admin does, plus making and removing admins
ROLES = ("viewer", "admin", "system_admin")
ROLE_LABELS = {"viewer": "Viewer", "admin": "Admin", "system_admin": "System admin"}


class User(Base):
    """An Appedology account.

    Two rules, both enforced here and in the API rather than only in the browser,
    because a form can be bypassed and an API cannot:

      * the email must end @appedology.com - this is an internal tool
      * the APD id is the company's internal identifier, APD- followed by
        exactly four digits

    The password is never stored. What is stored is a PBKDF2-SHA256 hash with a
    per-user random salt, so two people with the same password still have
    different hashes and the stored value cannot be reversed.
    """
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    apd_id: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(),
                                                    default=_now)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Every column below has a server default, so adding it to a database that
    # already holds accounts (see migrate.py) gives those accounts a sensible
    # value rather than a NULL the code does not expect.

    # What the person may do - see ROLES.
    role: Mapped[str] = mapped_column(String(16), default="viewer",
                                      server_default="viewer")
    # Which scorecards a VIEWER may read, as report keys: "gfs,all_providers".
    # Admins read everything, whatever this says.
    report_access: Mapped[str] = mapped_column(String(200), default="",
                                               server_default="")
    # A new sign-up waits here, unable to sign in, until an admin approves it.
    # Anyone can TYPE an @appedology.com address; only an admin can vouch that
    # the person behind it is who it says.
    pending: Mapped[bool] = mapped_column(Boolean, default=False,
                                          server_default=text("0"))
    # What to call them. Optional; the email's local part stands in without it.
    display_name: Mapped[str | None] = mapped_column(String(120))

    password_changed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    # Set when an admin resets the password: the temporary one they were
    # handed is good for one thing only, choosing their own.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"))

    # Wrong passwords in a row, and the lock they lead to. Cleared by a good
    # sign-in or by an admin.
    failed_logins: Mapped[int] = mapped_column(Integer, default=0,
                                               server_default=text("0"))
    locked_until: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    @property
    def name(self) -> str:
        """What to call them: their chosen name, or the part before the @."""
        return self.display_name or self.email.split("@")[0]

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
    def status(self) -> str:
        """One word for the Users screen."""
        if self.pending:
            return "pending"
        if not self.is_active:
            return "disabled"
        if self.locked_until and self.locked_until > _now():
            return "locked"
        return "active"


class Session(Base):
    """A signed-in browser.

    Opaque random tokens in a table, rather than a self-contained token: signing
    out has to actually revoke access, and a token that carries its own validity
    cannot be taken back before it expires.

    `token` holds the SHA-256 of the token, never the token itself. Someone who
    reads this table - a backup, a leaked dump - gets hashes, which cannot be
    presented to the API as a sign-in.
    """
    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(),
                                                    default=_now)
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime())
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Where it was opened from, so the profile screen can list "where you are
    # signed in" and a session nobody recognises can be spotted and ended.
    ip: Mapped[str | None] = mapped_column(String(45))          # fits IPv6
    user_agent: Mapped[str | None] = mapped_column(String(400))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    user: Mapped[User] = relationship()


class Upload(Base):
    """One source file, as received.

    report_key is NULL for the seven shared files and set for the two Case AR
    files, which differ per report: GFS is mailed Tuesday and uses Tuesday's
    Case ARs, All Providers is mailed Thursday and uses Thursday's. The
    filenames are identical, so without this column one silently overwrites
    the other and the two reports disagree with nothing to explain why.

    Rows are never replaced. A corrected re-upload is a NEW row; the run that
    already used the old one still points at the old bytes.
    """
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
                                                     default=_now)
    uploaded_by: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        Index("ix_upload_lookup", "week", "report_key", "source_key",
              "uploaded_at"),
    )

    @property
    def is_shared(self) -> bool:
        return self.report_key is None


class Run(Base):
    """One attempt at building one report for one week."""
    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_key: Mapped[str] = mapped_column(String(32), index=True)
    week: Mapped[str] = mapped_column(String(9), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    as_of: Mapped[dt.date | None] = mapped_column()
    started_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(),
                                                    default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    seconds: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    approved_by: Mapped[str | None] = mapped_column(String(200))
    # The month's working days the pace was worked out on, and where that
    # number came from: typed in on the upload screen, or the calendar's.
    working_days: Mapped[int | None] = mapped_column(Integer)
    working_days_source: Mapped[str | None] = mapped_column(String(16))

    inputs: Mapped[list["RunInput"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")
    notes: Mapped[list["RunNote"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunNote.seq")
    tables: Mapped[list["RunTable"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")
    figures: Mapped[list["RunFigure"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")


# pending  -> queued, nothing read yet
# running  -> reading and calculating
# review   -> finished, waiting on the STEP 4 look
# approved -> signed off, safe to send the client
# failed   -> stopped with an error
STATUSES = ("pending", "running", "review", "approved", "failed")


class RunInput(Base):
    """Exactly which upload each run consumed.

    Not derivable after the fact: uploads accumulate, so "the latest Payment
    Detail for week 36" is not necessarily the one a run three days ago read.
    This is the row that answers "which file produced this number".
    """
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
    """The STEP 4 warnings, kept instead of scrolling past in a console.

    text is the .bat pipeline's exact wording. code, severity and detail are
    what make it usable: code is stable across weeks, so "this warning is new"
    and "this count doubled" are questions the screen can answer; severity
    decides what sorts to the top; detail holds the numbers behind the
    sentence, which a string cannot be charted from.
    """
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
    """The sheet-shaped results, as flat records.

    Settlement grids, CP Settled Cases and the KPI blocks were never tables -
    the .bat pipeline calculated them and wrote them straight into Excel cells,
    so they only ever existed inside the workbook. A dashboard has to read them
    back, and a chart needs one row per value rather than a grid keyed by
    (group, bucket), so they are stored flattened.

    Small enough for the database: a week is a few hundred records, not the
    278,930 of Raw Data.
    """
    __tablename__ = "run_figure"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    name: Mapped[str] = mapped_column(String(32))     # settlement, kpi, ...
    data: Mapped[list] = mapped_column(JSON, default=list)

    run: Mapped[Run] = relationship(back_populates="figures")

    __table_args__ = (UniqueConstraint("run_id", "name"),)


class RunTable(Base):
    """A table a run produced, held as parquet in the object store.

    Raw Data is 278,930 rows a week. Putting that in the database would add
    ~14 million rows a year for something only ever read whole or aggregated,
    so the numbers stay in parquet and the database holds the pointer, the
    shape and the hash.
    """
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
    """Who did what, when, and from where. Kept until a system admin deletes it.

    The security record. Every sign-in (and every failed one), every upload,
    build, approval, deletion and export, and every change an admin makes to an
    account is one row here.

    Never edited, enforced by the DATABASE rather than by this code: a trigger
    (see migrate.py) refuses any UPDATE on this table, so neither a bug nor
    someone holding the app's own credentials can make a row say something
    else. Rows can be deleted - only by a system admin, from the Activity
    screen - and every deletion writes a row of its own saying what went.

    No foreign key to the account on purpose. A failed sign-in may name no
    account at all, and the record of what someone did must never depend on
    their account row still existing. The email is copied in as it was at the
    time for the same reason.
    """
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=_now)
    user_id: Mapped[int | None] = mapped_column(Integer)
    email: Mapped[str | None] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(48))          # auth.login, run.approve
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    target: Mapped[str | None] = mapped_column(String(200))  # "run 12", "2026-W38"
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(400))

    # Shaped by the questions asked of it: everything in a period, one
    # person's history, one kind of event, one address.
    __table_args__ = (
        Index("ix_activity_at", "at"),
        Index("ix_activity_user_at", "user_id", "at"),
        Index("ix_activity_email_at", "email", "at"),
        Index("ix_activity_action_at", "action", "at"),
        Index("ix_activity_ip_at", "ip", "at"),
    )

# success -> it happened
# failure -> it was attempted and did not work (a wrong password)
# denied  -> it was refused because the person is not allowed (not an admin)
OUTCOMES = ("success", "failure", "denied")


class MonthSetting(Base):
    """Working days in a month, as entered on the upload screen.

    The calendar count (weekdays less the holidays in rules.yml) is right most
    months, but not when the office closes on a day nobody put in the rules,
    or opens on one it did. Whoever uploads the week can say how many working
    days the month really has; every build in that month paces on it. One row
    per month, replaced when changed - each change is in the activity log.
    """
    __tablename__ = "month_setting"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)   # 2026-09
    working_days: Mapped[int] = mapped_column(Integer)
    set_by: Mapped[str | None] = mapped_column(String(320))
    set_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=_now)
