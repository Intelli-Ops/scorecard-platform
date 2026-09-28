"""Bringing an existing database up to date, and keeping the log untouchable.

create_all() makes tables that are missing but never changes one that exists,
so a database created before a column was added never gets it. That is what
add_missing_columns is for: it compares each table with its model and adds
whatever is absent. It only ever ADDS - it never drops, renames or retypes
anything, so running it against a database holding real data is safe, and
running it twice does nothing the second time.

When a change needs more than an added column, this is the point to bring in
Alembic. Until then, one small function beats a migrations folder nobody runs.
"""
from __future__ import annotations
import logging

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import Column

log = logging.getLogger("scorecard.db")


def _default_sql(column: Column) -> str | None:
    d = column.server_default
    if d is None:
        return None
    arg = d.arg
    if hasattr(arg, "text"):                  # text("0")
        return arg.text
    return "'" + str(arg).replace("'", "''") + "'"


def add_missing_columns(engine: Engine, metadata: MetaData) -> list[str]:
    """ALTER TABLE ... ADD COLUMN for every column a model has and its table
    lacks. Returns what was added, as "table.column"."""
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
                # NOT NULL only with a default to fill the rows already there;
                # otherwise the ALTER fails on any table that is not empty.
                if not column.nullable and default is not None:
                    ddl += " NOT NULL"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
        # Accounts from before there were roles at all could do everything;
        # mark them as the old "user" so upgrade_roles treats them like one.
        if "user_account.role" in added:
            conn.execute(text("UPDATE user_account SET role = 'user'"))
    if added:
        log.warning("database upgraded - added %s", ", ".join(added))
    return added


def upgrade_roles(engine: Engine) -> int:
    """Accounts from before there were viewers.

    The old "user" could read every scorecard, so it becomes a viewer of every
    report - nobody loses what they could see. Uploading, building and
    approving now belong to admins, so it does lose those; an admin can make
    them an admin again. Returns how many accounts changed.
    """
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


# ------------------------------------------------------------ append-only log

_MESSAGE = "activity_log is append-only"

_SQLITE = [
    f"""CREATE TRIGGER IF NOT EXISTS activity_log_no_update
        BEFORE UPDATE ON activity_log
        BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS activity_log_no_delete
        BEFORE DELETE ON activity_log
        BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END""",
]

_MYSQL = {
    "activity_log_no_update": f"""CREATE TRIGGER activity_log_no_update
        BEFORE UPDATE ON activity_log FOR EACH ROW
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '{_MESSAGE}'""",
    "activity_log_no_delete": f"""CREATE TRIGGER activity_log_no_delete
        BEFORE DELETE ON activity_log FOR EACH ROW
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '{_MESSAGE}'""",
}


def mysql_trigger_sql() -> list[str]:
    """The MySQL triggers, for the setup script to run as the database admin."""
    return list(_MYSQL.values())


def protect_activity_log(engine: Engine) -> bool:
    """Make the database itself refuse any UPDATE or DELETE on activity_log.

    Returns True when the guard is in place. On MySQL, creating a trigger needs
    the TRIGGER privilege, and with binary logging on (the default) it needs
    more still - so the deployment's setup script creates them as the database
    admin, and the app only checks they are there. If they are missing, the app
    keeps running but says so loudly on every start: a server that refuses to
    come up is worse than one that tells you what it is missing.
    """
    name = engine.dialect.name
    with engine.begin() as conn:
        if name == "sqlite":
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
    missing = [n for n in _MYSQL if n not in present]
    for trigger in missing:
        try:
            with engine.begin() as conn:
                conn.execute(text(_MYSQL[trigger]))
        except Exception as exc:                 # no privilege - see docstring
            log.warning("activity_log is NOT protected: could not create %s "
                        "(%s). Run `python -m app.manage protect-log` as the "
                        "database admin.", trigger, exc.__class__.__name__)
            return False
    return True
