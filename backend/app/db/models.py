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

from sqlalchemy import (String, Integer, Float, DateTime, ForeignKey, Text,
                        UniqueConstraint, Index, JSON)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
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
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                    default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(200))

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
