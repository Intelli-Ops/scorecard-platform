"""Accounts: passwords, sessions, and what admins may do to whom."""
from __future__ import annotations
import base64
import datetime as dt
import functools
import hashlib
import hmac
import re
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..clock import utcnow
from ..config import settings
from ..db.models import ROLE_LABELS, ROLES, OneTimeCode, Session, User
from . import emails, mail, ratelimit

# Any organisation's email - the group's companies each have their own domain. What
# keeps strangers out is the code sent to the address and an admin's approval;
# temporary inboxes are refused at sign-up (disposable_domains.txt).
EMAIL_RE = re.compile(
    r"^[a-z0-9._%+'-]+@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
EMAIL_MAX = 254
APD_RE = re.compile(r"^APD-\d{4}$")

MIN_PASSWORD = 8
ITERATIONS = 600_000

SESSION_IDLE = dt.timedelta(hours=1)
SESSION_MAX = dt.timedelta(hours=12)

TEMPORARY_TTL = dt.timedelta(hours=24)

LOCK_AFTER = 5
LOCK_MINUTES = 15
LOCK = (LOCK_AFTER, LOCK_MINUTES * 60)


def _lock_key(user: User, ip: str | None) -> str:
    return f"lock:{user.id}:{ip or '?'}"

SEEN_EVERY = dt.timedelta(minutes=1)

WRONG = "That email and password do not match."


class AuthError(Exception):
    """Something the person can fix, with wording safe to show them."""


class WrongPassword(AuthError):
    """The current password given to change_password was not right - the one
    refusal there that is a guess at a password, and is counted as one."""


class LoginRefused(AuthError):
    """A sign-in that did not work, carrying what the activity log needs to
    know about it - which account, if any, and whether it just got locked."""

    def __init__(self, message: str, *, email: str, user: User | None = None,
                 reason: str = "wrong_password", locked_now: bool = False):
        super().__init__(message)
        self.email, self.user = email, user
        self.reason, self.locked_now = reason, locked_now


@functools.lru_cache(maxsize=1)
def _disposable() -> frozenset[str]:
    """The temporary-email domains, read once."""
    path = Path(__file__).with_name("disposable_domains.txt")
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(d.strip().lower() for d in lines if d.strip() and not d.startswith("#"))


def is_disposable(email: str) -> bool:
    """Whether the address is at a temporary-email provider, or a subdomain of one."""
    domain = email.rpartition("@")[2].lower()
    blocked = _disposable() | settings.blocked_email_domains
    labels = domain.split(".")
    return any(".".join(labels[i:]) in blocked for i in range(len(labels) - 1))


def clean_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not email:
        raise AuthError("Enter your work email address.")
    if len(email) > EMAIL_MAX or not EMAIL_RE.match(email):
        raise AuthError("That does not look like an email address - check it for typos.")
    if is_disposable(email):
        raise AuthError("Temporary email addresses cannot be used. Sign up with your "
                        "work email.")
    return email


def clean_apd(raw: str) -> str:
    """APD-1234."""
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
        raise AuthError("Use a password of at most 256 characters.")
    return password


def clean_name(raw: str | None) -> str | None:
    name = " ".join((raw or "").split())
    if len(name) > 120:
        raise AuthError("Keep the name to 120 characters.")
    return name or None


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
    return hmac.compare_digest(dk, expected)


def needs_rehash(stored: str) -> bool:
    """True for a hash made with fewer iterations than iterations - one stored
    before the count was raised."""
    try:
        return int(stored.split("$")[1]) < ITERATIONS
    except (IndexError, ValueError):
        return True


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


_dummy: str | None = None


def burn_time(password: str) -> None:
    """Spend as long as checking a real password takes."""
    global _dummy
    if _dummy is None:
        _dummy = hash_password(secrets.token_hex(8))
    verify_password(password, _dummy)


def sign_up(db: DbSession, email: str, apd_id: str, password: str,
            pending: bool = True) -> User:
    """Create an account - waiting, by default, for two things."""
    email = clean_email(email)
    apd_id = clean_apd(apd_id)
    check_password(password)

    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise AuthError("That email already has an account. Sign in instead.")
    if db.execute(select(User).where(User.apd_id == apd_id)).scalar_one_or_none():
        raise AuthError(f"{apd_id} is already registered to another account.")

    user = User(email=email, apd_id=apd_id, password_hash=hash_password(password),
                password_changed_at=utcnow(), pending=pending,
                is_active=not pending, role="viewer",
                email_verified_at=None if pending else utcnow())
    db.add(user)
    db.flush()
    return user


def sign_in(db: DbSession, email: str, password: str, *,
            ip: str | None = None, user_agent: str | None = None
            ) -> tuple[User, str]:
    """Returns the user and a session token, or raises LoginRefused."""
    lookup = (email or "").strip().lower()
    user = db.execute(select(User).where(User.email == lookup)).scalar_one_or_none()
    now = utcnow()

    if user is None:
        burn_time(password or "")
        raise LoginRefused(WRONG, email=lookup, reason="no_account")

    lock = _lock_key(user, ip)
    wait = ratelimit.blocked(lock, LOCK)
    if wait:
        minutes = max(1, round(wait / 60))
        raise LoginRefused(
            f"Sign-in to this account from here is locked after too many wrong "
            f"passwords. Try again in {minutes} minute{'s' if minutes != 1 else ''}"
            f", or ask an admin to unlock it.",
            email=lookup, user=user, reason="locked")

    if not verify_password(password or "", user.password_hash):
        ratelimit.hit(lock, LOCK)
        if ratelimit.blocked(lock, LOCK):
            user.locked_until = now + dt.timedelta(minutes=LOCK_MINUTES)
            db.flush()
            raise LoginRefused(
                f"Too many wrong passwords. Sign-in to this account from here "
                f"is locked for {LOCK_MINUTES} minutes.", email=lookup, user=user,
                locked_now=True)
        raise LoginRefused(WRONG, email=lookup, user=user)

    if user.pending and not user.email_verified_at:
        raise LoginRefused(f"Confirm your email address first: open the link "
                           f"we sent to {user.email}.",
                           email=lookup, user=user, reason="unverified")
    if user.pending:
        raise LoginRefused("Your account is waiting for an admin to approve it.",
                           email=lookup, user=user, reason="pending")
    if not user.is_active:
        raise LoginRefused("This account has been disabled.",
                           email=lookup, user=user, reason="disabled")
    if temporary_expired(user, now):
        raise LoginRefused("This temporary password has expired. Ask an admin "
                           "to reset your password again.",
                           email=lookup, user=user, reason="temporary_expired")

    ratelimit.clear(lock)       # the right password: this address starts afresh
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user, start_session(db, user, ip=ip, user_agent=user_agent)


def update_profile(db: DbSession, user: User, display_name: str | None) -> User:
    user.display_name = clean_name(display_name)
    db.flush()
    return user


def change_password(db: DbSession, user: User, current: str, new: str,
                    keep_session: int | None = None) -> int:
    """Change your own password."""
    if not verify_password(current or "", user.password_hash):
        raise WrongPassword("Your current password is not right.")
    check_password(new)
    if new == current:
        raise AuthError("Choose a password different from the current one.")
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    db.flush()
    return revoke_sessions(db, user.id, keep=keep_session)


def temporary_expired(user: User, now: dt.datetime | None = None) -> bool:
    """A temporary password more than TEMPORARY_TTL old."""
    return bool(user.must_change_password and user.password_changed_at
                and user.password_changed_at + TEMPORARY_TTL < (now or utcnow()))


UNUSABLE = "!reset"


def digest(token: str) -> str:
    """What is stored for a token."""
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: DbSession, user: User, *, ip: str | None = None,
                  user_agent: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(Session(token=digest(token), user_id=user.id, ip=ip,
                   user_agent=(user_agent or "")[:400] or None,
                   created_at=now, last_seen_at=now,
                   expires_at=now + SESSION_IDLE))
    db.flush()
    return token


def session_for_token(db: DbSession, token: str | None) -> Session | None:
    """The live session a token opens, or None."""
    if not token:
        return None
    row = db.execute(select(Session).where(Session.token == digest(token))
                     ).scalar_one_or_none()
    if row is None or row.revoked or row.expires_at < utcnow():
        return None
    user = row.user
    if user is None or not user.is_active or user.pending:
        return None
    return row


def touch(db: DbSession, row: Session, ip: str | None) -> None:
    """Note that the session is still in use - now and then, not every time -
    and give it another hour, up to SESSION_MAX from when it was opened."""
    now = utcnow()
    if row.last_seen_at is None or now - row.last_seen_at > SEEN_EVERY:
        row.last_seen_at = now
        row.expires_at = min(now + SESSION_IDLE, row.created_at + SESSION_MAX)
        if ip:
            row.ip = ip
        db.flush()


def sign_out(db: DbSession, token: str | None) -> User | None:
    """End the session this token opens."""
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
                              Session.expires_at > utcnow())
        .order_by(Session.last_seen_at.desc(), Session.id.desc())).scalars())


def revoke_sessions(db: DbSession, user_id: int, keep: int | None = None) -> int:
    """End every live session of one account, except `keep`."""
    n = 0
    for row in active_sessions(db, user_id):
        if row.id != keep:
            row.revoked = True
            n += 1
    db.flush()
    return n


def revoke_session(db: DbSession, user_id: int, session_id: int) -> bool:
    """End one of your own sessions."""
    row = db.get(Session, session_id)
    if row is None or row.user_id != user_id or row.revoked:
        return False
    row.revoked = True
    db.flush()
    return True


def purge_expired_sessions(db: DbSession, older_than_days: int = 30) -> int:
    """Delete sessions long past use."""
    cutoff = utcnow() - dt.timedelta(days=older_than_days)
    rows = db.execute(select(Session).where(Session.expires_at < cutoff)).scalars().all()
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)


def retire_unhashed_sessions(db: DbSession) -> int:
    """Close sessions made before tokens were stored hashed."""
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


class AdminError(AuthError):
    """An admin action refused because of what it would do."""


class Forbidden(AdminError):
    """An admin action this admin is not allowed to take."""


def manages(actor: User, target: User) -> bool:
    """Every action: role, access, approval, deletion and the emergency ones."""
    if actor.id == target.id or target.is_system_admin:
        return False
    if target.role == "admin":
        return actor.is_system_admin
    return actor.is_admin


def intervenes(actor: User, target: User) -> bool:
    """The emergency actions only: disable, enable, unlock, reset, sign out."""
    if manages(actor, target):
        return True
    return (actor.id != target.id and actor.is_system_admin
            and target.is_system_admin)


def _other_system_admins(db: DbSession, user: User, lock: bool = False) -> int:
    """Active system admins other than `user`."""
    stmt = select(User.id).where(
        User.role == "system_admin", User.is_active.is_(True),
        User.pending.is_(False), User.id != user.id)
    if lock:
        stmt = stmt.with_for_update()
    return len(db.execute(stmt).all())


def keep_a_system_admin(db: DbSession, target: User, doing: str) -> None:
    """Refuse to leave no active system admin."""
    if (target.is_system_admin and target.is_active and not target.pending
            and _other_system_admins(db, target, lock=True) == 0):
        raise Forbidden(f"{target.email} is the only active system admin. "
                        f"Make someone else a system admin before {doing}.")


def can_delete(db: DbSession, actor: User, target: User) -> bool:
    if actor.id == target.id:
        return actor.is_system_admin and _other_system_admins(db, actor) > 0
    return manages(actor, target)


def permissions(db: DbSession, actor: User, target: User) -> dict:
    """What `actor` may do to `target` - sent with each row of the Users
    screen, so it offers exactly the buttons the server will accept."""
    m = manages(actor, target)
    i = intervenes(actor, target)
    locked = bool(target.locked_until and target.locked_until > utcnow())
    return {
        "approve": m and target.pending and bool(target.email_verified_at),
        "access": m and target.role == "viewer",
        "uploads": m and actor.is_system_admin and target.role == "admin",
        "roles": list(ROLES) if m and actor.is_system_admin else [],
        "disable": i and target.is_active and not target.pending,
        "enable": i and not target.is_active and not target.pending,
        "unlock": i and locked,
        "reset_password": i and not target.pending,
        "sign_out": i and not target.pending,
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
        raise Forbidden("Another system admin can disable, reset or sign out "
                        "a system admin, but not change their role or remove "
                        "them.")
    _require(manages(actor, target),
             "Only a system admin can change an admin's account.")


def _intervene(actor: User, target: User) -> None:
    """For the emergency actions - see `intervenes`."""
    if target.is_system_admin and actor.id != target.id:
        _require(actor.is_system_admin,
                 "Only another system admin can change a system admin's account.")
        return
    _manage(actor, target)


def clean_reports(keys) -> str:
    from ..reports import REPORTS
    keys = [k for k in dict.fromkeys(keys or [])]
    unknown = [k for k in keys if k not in REPORTS]
    if unknown:
        raise AdminError(f"Unknown report {unknown[0]!r}.")
    return ",".join(k for k in REPORTS if k in keys)        # registry order


def set_upload_access(db: DbSession, actor: User, target: User, inputs) -> User:
    """Which inputs an admin may upload; None for every one."""
    from ..reports import input_keys
    _manage(actor, target)
    _require(actor.is_system_admin,
             "Only a system admin chooses which files an admin may upload.")
    if target.role != "admin":
        raise AdminError("Upload access is set for admins: system admins upload "
                         "everything, and viewers upload nothing.")
    if inputs is None:
        target.upload_access = None
    else:
        known = input_keys()
        unknown = [k for k in inputs if k not in known]
        if unknown:
            raise AdminError(f"Unknown input {unknown[0]!r}.")
        target.upload_access = ",".join(k for k in known if k in inputs)
    db.flush()
    return target


def set_role(db: DbSession, actor: User, target: User, role: str) -> User:
    if role not in ROLES:
        raise AdminError(f"Unknown role {role!r}.")
    _manage(actor, target)
    _require(actor.is_system_admin, "Only a system admin can change roles.")
    if role != "system_admin":
        keep_a_system_admin(db, target, "changing their role")
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
    if not target.email_verified_at:
        raise AdminError(f"{target.email} has not confirmed their email address "
                         f"yet, so it is not known to be theirs.")
    target.pending = False
    target.is_active = True
    if reports is not None:
        target.report_access = clean_reports(reports)
    db.flush()
    return target


def set_active(db: DbSession, actor: User, target: User, active: bool) -> User:
    """Disable or re-enable."""
    _intervene(actor, target)
    if not active:
        keep_a_system_admin(db, target, "disabling them")
        revoke_sessions(db, target.id)
    target.is_active = active
    target.pending = False
    db.flush()
    return target


def unlock(db: DbSession, actor: User, target: User) -> User:
    """Lift the account's locks, from every address they were set for."""
    _intervene(actor, target)
    ratelimit.clear_prefix(f"lock:{target.id}:")    # before this session writes
    target.locked_until = None
    db.flush()
    return target


def force_reset(db: DbSession, actor: User, target: User) -> None:
    """Admin's emergency reset: kill the password, end every session, email the
    owner."""
    _intervene(actor, target)
    ratelimit.clear_prefix(f"lock:{target.id}:")    # before this session writes
    target.password_hash = UNUSABLE
    target.password_changed_at = utcnow()
    target.must_change_password = False
    target.locked_until = None
    for row in db.execute(select(OneTimeCode).where(
            OneTimeCode.user_id == target.id, OneTimeCode.used_at.is_(None))).scalars():
        row.used_at = utcnow()
    db.flush()
    revoke_sessions(db, target.id)
    m = emails.forced_reset(target.email, settings.public_url)
    mail.send_later(target.email, m.subject, m.text, m.html)


def sign_out_everywhere(db: DbSession, actor: User, target: User) -> int:
    _intervene(actor, target)
    return revoke_sessions(db, target.id)


def delete_user(db: DbSession, actor: User, target: User) -> dict:
    """Remove an account for good."""
    if actor.id == target.id:
        _require(actor.is_system_admin,
                 "Ask an admin to remove your account.")
        _require(_other_system_admins(db, actor, lock=True) > 0,
                 "You are the only system admin. Make someone else a system "
                 "admin before removing your own account.")
    else:
        _manage(actor, target)
    gone = {"email": target.email, "role": target.role}
    for model in (Session, OneTimeCode):
        for row in db.execute(select(model).where(model.user_id == target.id)).scalars():
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
            "uploads": user.uploads, "uploads_all": user.uploads_all,
            "status": user.status,
            "must_change_password": bool(user.must_change_password),
            "email_verified": bool(user.email_verified_at),
            "created_at": user.created_at, "last_login_at": user.last_login_at,
            "password_changed_at": user.password_changed_at,
            "locked_until": user.locked_until}
