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


# ------------------------------------------------------------ no rewriting the log

# Rows of the activity log can be DELETED - by a system admin, from the
# Activity screen, and every deletion is itself logged (see audit.delete) -
# but never EDITED. A row either says what happened or is gone, and its going
# is on record; nobody can make one say something else.
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

# The guard that used to refuse deletes too. Dropped wherever it is found.
_RETIRED = "activity_log_no_delete"


def protect_activity_log(engine: Engine) -> bool:
    """Make the database itself refuse any UPDATE on activity_log, and let
    DELETE through (the app allows it to system admins only, and logs it).

    Returns True when the guard is in place. On MySQL, creating or dropping a
    trigger needs the TRIGGER privilege, and with binary logging on (the
    default) it needs more still - so the deployment's setup script does it as
    the database admin, and the app only checks. If something is off, the app
    keeps running but says so loudly on every start: a server that refuses to
    come up is worse than one that tells you what it is missing.
    """
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
