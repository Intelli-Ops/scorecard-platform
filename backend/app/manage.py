"""Server commands: create admins, reset passwords, apply migrations, copy data."""
from __future__ import annotations
import argparse
import getpass
import sys

from sqlalchemy import create_engine, func, inspect, select, text

from .clock import utcnow
from .config import database_url, settings
from .db import migrate
from .db.models import Base, User
from .db.session import create_all, engine, session
from .service import auth, codes


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
    have, want = migrate.revision(engine()), migrate.head()
    _say(f"schema: at migration {have or 'none'}, this code needs {want}"
         + ("" if have == want else " - run: scorecard-manage upgrade"))


def cmd_upgrade(a):
    """Apply migrations, as the migration account when one is set."""
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
    if a.if_missing:
        with session() as s:
            if s.execute(select(User).where(User.email == a.email.strip().lower())
                         ).scalar_one_or_none():
                _say(f"{a.email} already has an account - left as it is.")
                return
    if a.password_stdin:                # install.sh, with the default admin
        password = sys.stdin.readline().rstrip("\r\n")
    else:
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
        if a.role != "system_admin":
            try:
                auth.keep_a_system_admin(s, user, "changing their role")
            except auth.AuthError as e:
                sys.exit(str(e))
        user.role = a.role
        user.pending = False
        user.is_active = True
        user.email_verified_at = user.email_verified_at or utcnow()
    _say(f"{a.email} is now {a.role}.")


def cmd_reset_password(a):
    """A password reset code, shown here rather than mailed - for when mail is
    not working, or the only admin is locked out and cannot get it."""
    with session() as s:
        code = codes.emergency_reset_code(s, _user(s, a.email))
    minutes = codes.ttl_minutes(codes.CODE_TTL)
    _say(f"Reset code for {a.email}: {code}")
    _say(f"It works once, within {minutes} minutes, and replaces any code "
         f"already mailed. They type it into the code boxes - the screen "
         f"they reach with Forgot password? -> {a.email} -> Send code - "
         f"then choose a new password.")


def cmd_protect_log(a):
    """Create the triggers."""
    e = create_engine(database_url(a.as_url)) if a.as_url else engine()
    if migrate.protect_activity_log(e):
        _say("activity_log rows cannot be edited.")
    else:
        sys.exit("could not add the triggers - see the warning above. On MySQL, "
                 "run this with --as mysql://root:...@host/scorecard")


# Tables a new database is made with rows in - the source's rows replace them.
SEEDED = {"holiday", "provider", "collection_history"}


def cmd_copy_db(a):
    """Copy every row from FROM_URL into this database."""
    source = create_engine(database_url(a.from_url))
    create_all()
    target = engine()
    with target.connect() as c:
        existing = {t.name: c.execute(select(func.count()).select_from(t)).scalar()
                    for t in Base.metadata.sorted_tables if t.name not in SEEDED}
    if any(existing.values()):
        busy = ", ".join(f"{k}={v}" for k, v in existing.items() if v)
        sys.exit(f"the target is not empty ({busy}) - copy into a fresh database")

    migrate.add_missing_columns(source, Base.metadata)
    present = set(inspect(source).get_table_names())
    with source.connect() as src, target.begin() as dst:
        for table in Base.metadata.sorted_tables:
            if table.name not in present:
                _say(f"  {table.name}: not in the source, skipped")
                continue
            rows = [dict(r._mapping) for r in src.execute(select(table))]
            if table.name in SEEDED:
                dst.execute(table.delete())
            for i in range(0, len(rows), 500):
                dst.execute(table.insert(), rows[i:i + 500])
            _say(f"  {table.name}: {len(rows)} rows")
    migrate.upgrade_roles(target)
    _say(f"copied into {_where()}")
    _say("Now copy the data folder's objects/ and results/ directories too - "
         "the database points at files in them.")


def cmd_clean_files(a):
    """List - and with --delete, remove - stored files no row names."""
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
    c.add_argument("--password-stdin", action="store_true",
                   help="read the password from the first line of stdin")
    c.add_argument("--if-missing", action="store_true",
                   help="do nothing if the email already has an account")
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
