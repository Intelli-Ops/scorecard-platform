"""Accounts: signing up, signing in, and staying signed in.

The two company rules live here, not in the browser. A form can be bypassed by
anyone who opens the developer console; the API cannot.

  * the email must end @appedology.com
  * the APD id is APD- followed by exactly four digits

Passwords are never stored. What is stored is a PBKDF2-HMAC-SHA256 hash with a
fresh 16-byte random salt per user, at 600,000 iterations (OWASP's figure for
PBKDF2-SHA256) - deliberately slow,
so that guessing at scale costs real time. Standard library only; no dependency
to keep patched.
"""
from __future__ import annotations
from dataclasses import dataclass
import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db.models import ROLE_LABELS, ROLES, Session, User

EMAIL_DOMAIN = "@appedology.com"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@appedology\.com$", re.IGNORECASE)
APD_RE = re.compile(r"^APD-\d{4}$")

MIN_PASSWORD = 8
ITERATIONS = 600_000
SESSION_DAYS = 14

# Five wrong passwords in a row locks the account for fifteen minutes. Enough
# for a person who mistypes; far too slow for a program guessing - at most 480
# guesses a day against one account, each of which is logged.
LOCK_AFTER = 5
LOCK_MINUTES = 15

# A session's "last seen" is written at most this often. Writing it on every
# request would turn every page load into a database write.
SEEN_EVERY = dt.timedelta(minutes=5)

WRONG = "That email and password do not match."


class AuthError(Exception):
    """Something the person can fix, with wording safe to show them."""


class LoginRefused(AuthError):
    """A sign-in that did not work, carrying what the activity log needs to
    know about it - which account, if any, and whether it just got locked."""

    def __init__(self, message: str, *, email: str, user: User | None = None,
                 reason: str = "wrong_password", locked_now: bool = False):
        super().__init__(message)
        self.email, self.user = email, user
        self.reason, self.locked_now = reason, locked_now


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass(frozen=True)
class Credentials:
    email: str
    apd_id: str
    password: str


# ------------------------------------------------------------------ validation

def clean_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not email:
        raise AuthError("Enter your work email address.")
    if not EMAIL_RE.match(email):
        raise AuthError(f"Use your Appedology email - it must end {EMAIL_DOMAIN}.")
    return email


def clean_apd(raw: str) -> str:
    """APD-1234. Upper-cased, and a bare 1234 is accepted and completed.

    People type what is on their badge, and half of them will leave the prefix
    off. Rejecting that teaches nothing; completing it is unambiguous, because
    four digits can only mean one thing here.
    """
    apd = (raw or "").strip().upper().replace(" ", "")
    if re.fullmatch(r"\d{4}", apd):
        apd = f"APD-{apd}"
    if not APD_RE.match(apd):
        raise AuthError("The APD ID looks like APD-1234 - four digits.")
    return apd


def check_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > 256:
        # PBKDF2 hashes the whole thing on every sign-in; an unbounded password
        # is a way to make the server burn CPU.
        raise AuthError("Use a password of at most 256 characters.")
    return password


def clean_name(raw: str | None) -> str | None:
    name = " ".join((raw or "").split())
    if len(name) > 120:
        raise AuthError("Keep the name to 120 characters.")
    return name or None


# ------------------------------------------------------------------ hashing

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 _unb64(salt_b64), int(iterations))
        expected = _unb64(hash_b64)
    except (ValueError, TypeError):      # binascii.Error is a ValueError
        return False
    # Constant-time: a comparison that returns early leaks how much matched.
    return hmac.compare_digest(dk, expected)


def needs_rehash(stored: str) -> bool:
    """True for a hash made with fewer iterations than ITERATIONS - one
    stored before the count was raised."""
    try:
        return int(stored.split("$")[1]) < ITERATIONS
    except (IndexError, ValueError):
        return True


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


_dummy: str | None = None


def _burn_time(password: str) -> None:
    """Spend as long as checking a real password takes.

    Without this, a sign-in for an address with no account answers at once and
    one for a real account takes a quarter of a second - and the difference
    tells someone guessing which addresses exist, whatever the message says.
    """
    global _dummy
    if _dummy is None:
        _dummy = hash_password(secrets.token_hex(8))
    verify_password(password, _dummy)


# ------------------------------------------------------------------ accounts

def sign_up(db: DbSession, email: str, apd_id: str, password: str,
            pending: bool = True) -> User:
    """Create an account - waiting for an admin to approve it, by default.

    The email rule proves only that someone can TYPE an Appedology address,
    not that it is theirs: nothing is mailed to it. So a new account cannot
    sign in until an admin has looked at it and approved it. `pending=False`
    is for accounts an admin creates themselves (see app/manage.py).
    """
    email = clean_email(email)
    apd_id = clean_apd(apd_id)
    check_password(password)

    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise AuthError("That email already has an account. Sign in instead.")
    if db.execute(select(User).where(User.apd_id == apd_id)).scalar_one_or_none():
        raise AuthError(f"{apd_id} is already registered to another account.")

    user = User(email=email, apd_id=apd_id, password_hash=hash_password(password),
                password_changed_at=_now(), pending=pending,
                is_active=not pending, role="viewer")
    db.add(user)
    db.flush()
    return user


def sign_in(db: DbSession, email: str, password: str, *,
            ip: str | None = None, user_agent: str | None = None
            ) -> tuple[User, str]:
    """Returns the user and a session token, or raises LoginRefused.

    One message for a wrong email and a wrong password alike. Saying which was
    wrong tells someone who is guessing which addresses have accounts. Only
    once the password is RIGHT does it say anything specific about the account
    - pending, disabled - since by then the person has proved who they are.

    The caller must commit even when this raises: the count of wrong passwords
    and the lock are changes that have to stick.
    """
    lookup = (email or "").strip().lower()
    user = db.execute(select(User).where(User.email == lookup)).scalar_one_or_none()
    now = _now()

    if user is None:
        _burn_time(password or "")
        raise LoginRefused(WRONG, email=lookup, reason="no_account")

    if user.locked_until and user.locked_until > now:
        minutes = max(1, round((user.locked_until - now).total_seconds() / 60))
        raise LoginRefused(
            f"This account is locked after too many wrong passwords. Try again "
            f"in {minutes} minute{'s' if minutes != 1 else ''}, or ask an admin "
            f"to unlock it.", email=lookup, user=user, reason="locked")

    if not verify_password(password or "", user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= LOCK_AFTER:
            user.failed_logins = 0
            user.locked_until = now + dt.timedelta(minutes=LOCK_MINUTES)
            db.flush()
            raise LoginRefused(
                f"Too many wrong passwords. This account is locked for "
                f"{LOCK_MINUTES} minutes.", email=lookup, user=user,
                locked_now=True)
        db.flush()
        raise LoginRefused(WRONG, email=lookup, user=user)

    if user.pending:
        raise LoginRefused("Your account is waiting for an admin to approve it.",
                           email=lookup, user=user, reason="pending")
    if not user.is_active:
        raise LoginRefused("This account has been disabled.",
                           email=lookup, user=user, reason="disabled")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    # An older, weaker hash is replaced the next time its owner signs in -
    # the only moment the password itself is in hand.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user, start_session(db, user, ip=ip, user_agent=user_agent)


def update_profile(db: DbSession, user: User, display_name: str | None) -> User:
    user.display_name = clean_name(display_name)
    db.flush()
    return user


def change_password(db: DbSession, user: User, current: str, new: str,
                    keep_session: int | None = None) -> int:
    """Change your own password. Returns how many other sessions were ended.

    Every OTHER session is signed out: if the reason for changing it is that
    someone else knew it, their session must not outlive the old password.
    """
    if not verify_password(current or "", user.password_hash):
        raise AuthError("Your current password is not right.")
    check_password(new)
    if new == current:
        raise AuthError("Choose a password different from the current one.")
    user.password_hash = hash_password(new)
    user.password_changed_at = _now()
    user.must_change_password = False
    db.flush()
    return revoke_sessions(db, user.id, keep=keep_session)


# ------------------------------------------------------------------ sessions

def digest(token: str) -> str:
    """What is stored for a token. See Session in models.py."""
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: DbSession, user: User, *, ip: str | None = None,
                  user_agent: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    db.add(Session(token=digest(token), user_id=user.id, ip=ip,
                   user_agent=(user_agent or "")[:400] or None,
                   last_seen_at=now,
                   expires_at=now + dt.timedelta(days=SESSION_DAYS)))
    db.flush()
    return token


def session_for_token(db: DbSession, token: str | None) -> Session | None:
    """The live session a token opens, or None."""
    if not token:
        return None
    row = db.execute(select(Session).where(Session.token == digest(token))
                     ).scalar_one_or_none()
    if row is None or row.revoked or row.expires_at < _now():
        return None
    user = row.user
    if user is None or not user.is_active or user.pending:
        return None
    return row


def user_for_token(db: DbSession, token: str | None) -> User | None:
    row = session_for_token(db, token)
    return row.user if row else None


def touch(db: DbSession, row: Session, ip: str | None) -> None:
    """Note that the session is still in use - now and then, not every time."""
    now = _now()
    if row.last_seen_at is None or now - row.last_seen_at > SEEN_EVERY:
        row.last_seen_at = now
        if ip:
            row.ip = ip
        db.flush()


def sign_out(db: DbSession, token: str | None) -> User | None:
    """End the session this token opens. Returns whose it was."""
    if not token:
        return None
    row = db.execute(select(Session).where(Session.token == digest(token))
                     ).scalar_one_or_none()
    if row is None or row.revoked:
        return None
    row.revoked = True
    db.flush()
    return row.user


def active_sessions(db: DbSession, user_id: int) -> list[Session]:
    return list(db.execute(
        select(Session).where(Session.user_id == user_id,
                              Session.revoked.is_(False),
                              Session.expires_at > _now())
        .order_by(Session.last_seen_at.desc(), Session.id.desc())).scalars())


def revoke_sessions(db: DbSession, user_id: int, keep: int | None = None) -> int:
    """End every live session of one account, except `keep`. Returns how many."""
    n = 0
    for row in active_sessions(db, user_id):
        if row.id != keep:
            row.revoked = True
            n += 1
    db.flush()
    return n


def revoke_session(db: DbSession, user_id: int, session_id: int) -> bool:
    """End one of your OWN sessions. Someone else's id is treated as missing."""
    row = db.get(Session, session_id)
    if row is None or row.user_id != user_id or row.revoked:
        return False
    row.revoked = True
    db.flush()
    return True


def purge_expired_sessions(db: DbSession, older_than_days: int = 30) -> int:
    """Delete sessions long past use. The activity log keeps the sign-ins and
    sign-outs themselves; these rows are only the keys, and dead keys are
    clutter."""
    cutoff = _now() - dt.timedelta(days=older_than_days)
    rows = db.execute(select(Session).where(Session.expires_at < cutoff)).scalars().all()
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)


def retire_unhashed_sessions(db: DbSession) -> int:
    """Close sessions made before tokens were stored hashed.

    Their `token` column holds the raw token, which no longer matches anything
    presented to the API, so they can never be used - but they still counted
    as live and showed up as "Unknown device" on the profile screen. They are
    the only sessions without a last-seen time, since every session started
    since has one from the moment it opens.
    """
    rows = db.execute(select(Session).where(Session.last_seen_at.is_(None),
                                            Session.revoked.is_(False))).scalars().all()
    for row in rows:
        row.revoked = True
    db.flush()
    return len(rows)


def session_dict(row: Session, current_id: int | None = None) -> dict:
    return {"id": row.id, "created_at": row.created_at,
            "last_seen_at": row.last_seen_at, "expires_at": row.expires_at,
            "ip": row.ip, "user_agent": row.user_agent,
            "current": row.id == current_id}


# ------------------------------------------------------------------ admin

class AdminError(AuthError):
    """An admin action refused because of what it would do."""


class Forbidden(AdminError):
    """An admin action this admin is not allowed to take."""


# Who may manage whom. Three rules, and every account action below follows
# them:
#
#   * a viewer is managed by any admin
#   * an admin is managed only by a system admin
#   * a system admin is managed by nobody else - not even another system admin
#
# and nobody manages their own account from the Users screen (a slip of the
# mouse must not end your own access) - except that a system admin may delete
# their own account, as long as another system admin remains. Since nobody
# can touch a system admin but themselves, and the last one cannot leave,
# there is always one.

def manages(actor: User, target: User) -> bool:
    if actor.id == target.id or target.is_system_admin:
        return False
    if target.role == "admin":
        return actor.is_system_admin
    return actor.is_admin


def _other_system_admins(db: DbSession, user: User) -> int:
    return len(db.execute(select(User.id).where(
        User.role == "system_admin", User.is_active.is_(True),
        User.pending.is_(False), User.id != user.id)).all())


def can_delete(db: DbSession, actor: User, target: User) -> bool:
    if actor.id == target.id:
        return actor.is_system_admin and _other_system_admins(db, actor) > 0
    return manages(actor, target)


def permissions(db: DbSession, actor: User, target: User) -> dict:
    """What `actor` may do to `target` - sent with each row of the Users
    screen, so it offers exactly the buttons the server will accept."""
    m = manages(actor, target)
    locked = bool(target.locked_until and target.locked_until > _now())
    return {
        "approve": m and target.pending,
        "access": m and target.role == "viewer",
        "roles": list(ROLES) if m and actor.is_system_admin else [],
        "disable": m and target.is_active and not target.pending,
        "enable": m and not target.is_active and not target.pending,
        "unlock": m and locked,
        "reset_password": m and not target.pending,
        "sign_out": m and not target.pending,
        "delete": can_delete(db, actor, target),
    }


def _require(allowed: bool, message: str) -> None:
    if not allowed:
        raise Forbidden(message)


def _manage(actor: User, target: User) -> None:
    if actor.id == target.id:
        raise Forbidden("You cannot change your own account here. Use your "
                        "profile, or ask another admin.")
    if target.is_system_admin:
        raise Forbidden("A system admin's account can only be changed by "
                        "that person.")
    _require(manages(actor, target),
             "Only a system admin can change an admin's account.")


def clean_reports(keys) -> str:
    from ..reports import REPORTS
    keys = [k for k in dict.fromkeys(keys or [])]
    unknown = [k for k in keys if k not in REPORTS]
    if unknown:
        raise AdminError(f"Unknown report {unknown[0]!r}.")
    return ",".join(k for k in REPORTS if k in keys)        # registry order


def set_role(db: DbSession, actor: User, target: User, role: str) -> User:
    if role not in ROLES:
        raise AdminError(f"Unknown role {role!r}.")
    _manage(actor, target)
    _require(actor.is_system_admin, "Only a system admin can change roles.")
    target.role = role
    db.flush()
    return target


def set_access(db: DbSession, actor: User, target: User, reports) -> User:
    """Which scorecards a viewer may read."""
    _manage(actor, target)
    if target.role != "viewer":
        raise AdminError("Admins see every scorecard; access is set for viewers.")
    target.report_access = clean_reports(reports)
    db.flush()
    return target


def approve(db: DbSession, actor: User, target: User, reports=None) -> User:
    _manage(actor, target)
    if not target.pending:
        raise AdminError(f"{target.email} is not waiting for approval.")
    target.pending = False
    target.is_active = True
    if reports is not None:
        target.report_access = clean_reports(reports)
    db.flush()
    return target


def set_active(db: DbSession, actor: User, target: User, active: bool) -> User:
    """Disable or re-enable. Disabling ends every session at once - a disabled
    account that stays signed in for two more weeks is not disabled."""
    _manage(actor, target)
    if not active:
        revoke_sessions(db, target.id)
    target.is_active = active
    target.pending = False
    db.flush()
    return target


def unlock(db: DbSession, actor: User, target: User) -> User:
    _manage(actor, target)
    target.locked_until = None
    target.failed_logins = 0
    db.flush()
    return target


def reset_password(db: DbSession, target: User, actor: User | None = None) -> str:
    """Give the account a temporary password, returned once and never stored.

    There is no email server to send a reset link through, so an admin hands
    this over in person or on Teams. It works for exactly one thing: the next
    sign-in asks for a new password before anything else. Every session is
    ended, and the lock is lifted - the usual reason for a reset is someone
    who locked themselves out.

    `actor` is None only from the server's command line (app/manage.py), which
    is how a locked-out system admin gets back in.
    """
    if actor is not None:
        _manage(actor, target)
    temporary = secrets.token_urlsafe(9)          # 12 characters
    target.password_hash = hash_password(temporary)
    target.password_changed_at = _now()
    target.must_change_password = True
    target.locked_until = None
    target.failed_logins = 0
    db.flush()
    revoke_sessions(db, target.id)
    return temporary


def sign_out_everywhere(db: DbSession, actor: User, target: User) -> int:
    _manage(actor, target)
    return revoke_sessions(db, target.id)


def delete_user(db: DbSession, actor: User, target: User) -> dict:
    """Remove an account for good. What it did stays in the activity log,
    which holds the email as it was and does not depend on this row."""
    if actor.id == target.id:
        _require(actor.is_system_admin,
                 "Ask an admin to remove your account.")
        _require(_other_system_admins(db, actor) > 0,
                 "You are the only system admin. Make someone else a system "
                 "admin before removing your own account.")
    else:
        _manage(actor, target)
    gone = {"email": target.email, "role": target.role}
    for row in db.execute(select(Session).where(Session.user_id == target.id)).scalars():
        db.delete(row)
    db.flush()
    db.delete(target)
    db.flush()
    return gone


def as_dict(user: User) -> dict:
    return {"id": user.id, "email": user.email, "apd_id": user.apd_id,
            "name": user.name, "display_name": user.display_name,
            "role": user.role, "role_label": ROLE_LABELS.get(user.role, user.role),
            "is_admin": user.is_admin, "is_system_admin": user.is_system_admin,
            "reports": user.reports,
            "status": user.status,
            "must_change_password": bool(user.must_change_password),
            "created_at": user.created_at, "last_login_at": user.last_login_at,
            "password_changed_at": user.password_changed_at,
            "locked_until": user.locked_until}
