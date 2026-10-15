"""Applying migrations, and the trigger that stops activity log rows being edited."""
from __future__ import annotations
import logging
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import Column

log = logging.getLogger("scorecard.db")

BASELINE = "0001"


def _config(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location",
                        str(Path(__file__).resolve().parent / "migrations"))
    cfg.attributes["engine"] = engine
    return cfg


def upgrade(engine: Engine) -> None:
    """Apply every migration this database has not had."""
    from . import baseline
    cfg = _config(engine)
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and tables & set(baseline.metadata.tables):
        baseline.metadata.create_all(engine)
        add_missing_columns(engine, baseline.metadata)
        upgrade_roles(engine)
        command.stamp(cfg, BASELINE)
        log.warning("database from before versioned migrations - brought to "
                    "revision %s", BASELINE)
    command.upgrade(cfg, "head")


def revision(engine: Engine) -> str | None:
    """The migration this database is at, or None if it has had none."""
    from alembic.runtime.migration import MigrationContext
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


@lru_cache(maxsize=None)
def head() -> str:
    """The newest migration this code knows."""
    from alembic.script import ScriptDirectory
    return ScriptDirectory(str(Path(__file__).resolve().parent
                               / "migrations")).get_current_head()


def _default_sql(column: Column) -> str | None:
    d = column.server_default
    if d is None:
        return None
    arg = d.arg
    if hasattr(arg, "text"):                  # text("0")
        return arg.text
    return "'" + str(arg).replace("'", "''") + "'"


def add_missing_columns(engine: Engine, metadata: MetaData) -> list[str]:
    """ALTER table ..."""
    have = inspect(engine)
    added: list[str] = []
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if not have.has_table(table.name):
                continue
            existing = {c["name"] for c in have.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                prep = engine.dialect.identifier_preparer
                ddl = (f"ALTER TABLE {prep.format_table(table)} "
                       f"ADD COLUMN {prep.format_column(column)} "
                       f"{column.type.compile(dialect=engine.dialect)}")
                default = _default_sql(column)
                if default is not None:
                    ddl += f" DEFAULT {default}"
                if not column.nullable and default is not None:
                    ddl += " NOT NULL"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
        if "user_account.role" in added:
            conn.execute(text("UPDATE user_account SET role = 'user'"))
    if added:
        log.warning("database upgraded - added %s", ", ".join(added))
    return added


def upgrade_roles(engine: Engine) -> int:
    """Accounts from before there were viewers."""
    from ..reports import REPORTS
    with engine.begin() as conn:
        if not inspect(engine).has_table("user_account"):
            return 0
        n = conn.execute(text(
            "UPDATE user_account SET role = 'viewer', report_access = :all "
            "WHERE role = 'user' OR role IS NULL"),
            {"all": ",".join(REPORTS)}).rowcount
    if n:
        log.warning("%d account(s) moved from 'user' to 'viewer'", n)
    return n


_MESSAGE = "activity_log rows cannot be changed"

_SQLITE = [
    f"""CREATE TRIGGER IF NOT EXISTS activity_log_no_update
        BEFORE UPDATE ON activity_log
        BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END""",
]

_MYSQL = {
    "activity_log_no_update": f"""CREATE TRIGGER activity_log_no_update
        BEFORE UPDATE ON activity_log FOR EACH ROW
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '{_MESSAGE}'""",
}

_RETIRED = "activity_log_no_delete"


def protect_activity_log(engine: Engine) -> bool:
    """Make the database itself refuse any UPDATE on activity_log, and let
    DELETE through (the app allows it to system admins only, and logs it)."""
    name = engine.dialect.name
    with engine.begin() as conn:
        if name == "sqlite":
            conn.execute(text(f"DROP TRIGGER IF EXISTS {_RETIRED}"))
            for sql in _SQLITE:
                conn.execute(text(sql))
            return True
        if name != "mysql":
            log.warning("activity_log is NOT protected: no triggers for %s", name)
            return False

        present = {r[0] for r in conn.execute(text(
            "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
            "WHERE TRIGGER_SCHEMA = DATABASE() "
            "AND EVENT_OBJECT_TABLE = 'activity_log'"))}
    todo = ([f"DROP TRIGGER IF EXISTS {_RETIRED}"] if _RETIRED in present else [])
    todo += [sql for n, sql in _MYSQL.items() if n not in present]
    for sql in todo:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as exc:                 # no privilege - see docstring
            log.warning("activity_log triggers are not as they should be: could "
                        "not run %r (%s). Run `python -m app.manage protect-log` "
                        "as the database admin.", sql.split(" ON ")[0],
                        exc.__class__.__name__)
            return False
    return True
