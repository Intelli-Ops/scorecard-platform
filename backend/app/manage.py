"""Server-side commands, for the person running the app rather than using it.

Run from backend/, with the same SCORECARD_DB the server uses:

    python -m app.manage check                   can it reach the database?
    python -m app.manage upgrade                 apply the migrations this
                                                 database has not had
    python -m app.manage clean-files             list stored files no row
                                                 names (--delete removes them)
    python -m app.manage create-admin EMAIL APD  a new SYSTEM admin account
                                                 (asks for a password)
    python -m app.manage promote EMAIL           make an existing account a
                                                 system admin
    python -m app.manage set-role EMAIL ROLE     viewer, admin or system_admin
    python -m app.manage reset-password EMAIL    a temporary password, for when
                                                 the only admin is locked out
    python -m app.manage protect-log             add the trigger that stops
                                                 activity log rows being edited (run
                                                 with the database ADMIN's
                                                 address - see below)
    python -m app.manage copy-db FROM_URL        copy everything from another
                                                 database into this one

The first system admin has to come from here: accounts that sign up in the
app wait for an admin to approve them, and only a system admin can make
admins, so with none at all there is nobody to.
"""
from __future__ import annotations
import argparse
import getpass
import sys

from sqlalchemy import create_engine, func, inspect, select, text

from .config import database_url, settings
from .db import migrate
from .db.models import Base, User
from .db.session import create_all, engine, session
from .service import auth


def _say(msg: str) -> None:
    print(msg, flush=True)


def _where() -> str:
    """The database address with the password blanked, for messages."""
    return engine().url.render_as_string(hide_password=True)


def cmd_check(_):
    with engine().connect() as c:
        version = c.execute(text(
            "SELECT sqlite_version()" if engine().dialect.name == "sqlite"
            else "SELECT VERSION()")).scalar()
    _say(f"connected: {_where()} ({engine().dialect.name} {version})")


def cmd_upgrade(a):
    """Apply the migrations. The app's own database account can add tables,
    columns and indexes but, on purpose, cannot DROP anything (that would let
    it empty the activity log) - so a migration that removes or rebuilds a
    table has to be run once as the database admin: pass its address with
    --as, exactly as for protect-log."""
    if a.as_url:
        e = create_engine(database_url(a.as_url))
        migrate.upgrade(e)
        _say(f"tables up to date: {e.url.render_as_string(hide_password=True)}")
        return
    create_all()
    _say(f"tables up to date: {_where()}")


def _user(s, email: str) -> User:
    user = s.execute(select(User).where(User.email == email.strip().lower())
                     ).scalar_one_or_none()
    if user is None:
        sys.exit(f"no account for {email}")
    return user


def cmd_create_admin(a):
    create_all()
    password = getpass.getpass("Password for the new admin: ")
    if password != getpass.getpass("Same again: "):
        sys.exit("the two passwords differ")
    with session() as s:
        try:
            user = auth.sign_up(s, a.email, a.apd_id, password, pending=False)
        except auth.AuthError as e:
            sys.exit(str(e))
        user.role = "system_admin"
    _say(f"{a.email} is a system admin and can sign in.")


def cmd_promote(a):
    a.role = "system_admin"
    cmd_set_role(a)


def cmd_set_role(a):
    from .db.models import ROLES
    if a.role not in ROLES:
        sys.exit(f"role must be one of: {', '.join(ROLES)}")
    create_all()
    with session() as s:
        user = _user(s, a.email)
        user.role = a.role
        user.pending = False
        user.is_active = True
    _say(f"{a.email} is now {a.role}.")


def cmd_reset_password(a):
    with session() as s:
        temporary = auth.reset_password(s, _user(s, a.email))
    _say(f"temporary password for {a.email}: {temporary}")
    _say("It must be changed at the next sign-in.")


def cmd_protect_log(a):
    """Create the triggers. Needs a database account allowed to - on MySQL
    with binary logging on, that means the admin (root) account, which the app
    itself should never hold. Pass its address with --as."""
    e = create_engine(database_url(a.as_url)) if a.as_url else engine()
    if migrate.protect_activity_log(e):
        _say("activity_log rows cannot be edited.")
    else:
        sys.exit("could not add the triggers - see the warning above. On MySQL, "
                 "run this with --as mysql://root:...@host/scorecard")


def cmd_copy_db(a):
    """Copy every row from FROM_URL into this database.

    For moving the laptop's SQLite file onto the server's MySQL. The target
    must be empty - copying into a database that already has rows would
    collide on ids. Tables go in dependency order (accounts before sessions,
    runs before their notes), so foreign keys are satisfied as they land.
    """
    source = create_engine(database_url(a.from_url))
    create_all()
    target = engine()
    with target.connect() as c:
        existing = {t.name: c.execute(select(func.count()).select_from(t)).scalar()
                    for t in Base.metadata.sorted_tables}
    if any(existing.values()):
        busy = ", ".join(f"{k}={v}" for k, v in existing.items() if v)
        sys.exit(f"the target is not empty ({busy}) - copy into a fresh database")

    # Old rows gain the columns added since; the models' defaults fill them.
    # A table the source never had (a database from before the activity log)
    # is simply skipped - there is nothing in it to copy.
    migrate.add_missing_columns(source, Base.metadata)
    present = set(inspect(source).get_table_names())
    with source.connect() as src, target.begin() as dst:
        for table in Base.metadata.sorted_tables:
            if table.name not in present:
                _say(f"  {table.name}: not in the source, skipped")
                continue
            rows = [dict(r._mapping) for r in src.execute(select(table))]
            for i in range(0, len(rows), 500):
                dst.execute(table.insert(), rows[i:i + 500])
            _say(f"  {table.name}: {len(rows)} rows")
    # Rows copied from before there were viewers carry the old "user" role.
    migrate.upgrade_roles(target)
    _say(f"copied into {_where()}")
    _say("Now copy the data folder's objects/ and results/ directories too - "
         "the database points at files in them.")


def cmd_clean_files(a):
    """List - and with --delete, remove - stored files no row names.

    The app keeps files and rows in step (service/blobs.py), but a process
    killed between writing a file and saving its row leaves the file behind,
    and nothing in the database knows to look for it. Files under an hour
    old are left alone: one may be an upload whose row is about to be saved.
    """
    import time
    from .db.models import RunTable, Upload
    from .storage.files import FileStore
    with session() as s:
        named = {
            settings.object_dir: set(s.execute(select(Upload.sha256)).scalars()),
            settings.results_dir: set(s.execute(select(RunTable.sha256)).scalars()),
        }
    cutoff = time.time() - 3600
    found = 0
    for root, hashes in named.items():
        for path in FileStore(root).root.rglob("*"):
            if (not path.is_file() or path.stat().st_mtime > cutoff
                    or path.stem in hashes):
                continue
            found += 1
            _say(f"  {path}  ({path.stat().st_size:,} bytes)")
            if a.delete:
                path.unlink()
    _say(f"{found} file(s) no row names" + (", removed." if a.delete else
         ". Run again with --delete to remove them." if found else "."))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.manage",
                                description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    c = sub.add_parser("upgrade")
    c.add_argument("--as", dest="as_url", default=None,
                   help="database address to run the migrations as")
    c.set_defaults(fn=cmd_upgrade)
    c = sub.add_parser("create-admin")
    c.add_argument("email"); c.add_argument("apd_id")
    c.set_defaults(fn=cmd_create_admin)
    c = sub.add_parser("promote"); c.add_argument("email")
    c.set_defaults(fn=cmd_promote)
    c = sub.add_parser("set-role"); c.add_argument("email"); c.add_argument("role")
    c.set_defaults(fn=cmd_set_role)
    c = sub.add_parser("reset-password"); c.add_argument("email")
    c.set_defaults(fn=cmd_reset_password)
    c = sub.add_parser("protect-log")
    c.add_argument("--as", dest="as_url", default=None,
                   help="database address to create the triggers as")
    c.set_defaults(fn=cmd_protect_log)
    c = sub.add_parser("copy-db"); c.add_argument("from_url")
    c.set_defaults(fn=cmd_copy_db)
    c = sub.add_parser("clean-files")
    c.add_argument("--delete", action="store_true",
                   help="remove the files, rather than only listing them")
    c.set_defaults(fn=cmd_clean_files)
    a = p.parse_args(argv)
    settings.ensure()
    a.fn(a)


if __name__ == "__main__":
    main()
