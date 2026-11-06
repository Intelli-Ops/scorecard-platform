"""Security alerts worked out from the activity log."""
from __future__ import annotations
import datetime as dt
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from ..config import settings
from ..db.models import ActivityLog
from ..reports.notes import ACTION, INFO, SEVERITY_ORDER, WARNING

GUESSING_FAILURES = 5          # wrong passwords for one account
SPRAY_ACCOUNTS = 3             # accounts one address failed against
EXPORTS_PER_HOUR = 10          # whole-table exports by one person in an hour
NEW_ADDRESS_LOOKBACK = dt.timedelta(days=90)
DELETIONS = ("run.delete", "week.delete", "admin.activity_delete")


def _alert(code, severity, title, text, rows, **extra) -> dict:
    return {"code": code, "severity": severity, "title": title, "text": text,
            "count": len(rows),
            "first": min(r.at for r in rows), "last": max(r.at for r in rows),
            "event_ids": [r.id for r in rows][:50], **extra}


def alerts(s: Session, since: dt.datetime) -> list[dict]:
    rows = s.execute(select(ActivityLog).where(ActivityLog.at >= since)
                     .options(defer(ActivityLog.detail), defer(ActivityLog.user_agent))
                     .order_by(ActivityLog.id)).scalars().all()
    out: list[dict] = []
    out += _password_guessing(rows)
    out += _spraying(rows)
    out += _locked(rows)
    out += _new_address(s, rows)
    out += _out_of_hours(rows)
    out += _bulk_export(rows)
    out += _denied(rows)
    out += _deletions(rows)
    return sorted(out, key=lambda a: (SEVERITY_ORDER[a["severity"]], -a["last"].timestamp()))


def _failed_logins(rows):
    return [r for r in rows if r.action == "auth.login" and r.outcome == "failure"]


def _password_guessing(rows) -> list[dict]:
    by_email = defaultdict(list)
    for r in _failed_logins(rows):
        by_email[r.email or "(blank)"].append(r)
    out = []
    for email, fails in by_email.items():
        if len(fails) < GUESSING_FAILURES:
            continue
        known = any(r.user_id for r in fails)
        ips = sorted({r.ip for r in fails if r.ip})
        out.append(_alert(
            "password_guessing", ACTION if len(fails) >= 2 * GUESSING_FAILURES
            else WARNING,
            f"{len(fails)} wrong passwords for {email}",
            ("An existing account" if known else "An address with no account")
            + f", from {len(ips)} address{'es' if len(ips) != 1 else ''}"
            + (f": {', '.join(ips[:5])}" if ips else "") + ".",
            fails, email=email, ips=ips))
    return out


def _spraying(rows) -> list[dict]:
    by_ip = defaultdict(list)
    for r in _failed_logins(rows):
        if r.ip:
            by_ip[r.ip].append(r)
    out = []
    for ip, fails in by_ip.items():
        accounts = sorted({r.email or "(blank)" for r in fails})
        if len(accounts) < SPRAY_ACCOUNTS:
            continue
        out.append(_alert(
            "spraying", ACTION,
            f"{ip} failed to sign in to {len(accounts)} different accounts",
            "One address trying several accounts is someone working down a "
            f"list: {', '.join(accounts[:6])}"
            + ("…" if len(accounts) > 6 else "") + ".",
            fails, ip=ip, emails=accounts))
    return out


def _locked(rows) -> list[dict]:
    return [_alert("locked", WARNING, f"{r.email} was locked out",
                   "Too many wrong passwords in a row. It unlocks by itself, or "
                   "an admin can unlock it on the Users screen.",
                   [r], email=r.email, ip=r.ip)
            for r in rows if r.action == "auth.locked"]


def _new_address(s: Session, rows) -> list[dict]:
    """A good sign-in from an address this account has not signed in from in
    the last 90 days."""
    logins = [r for r in rows if r.action == "auth.login"
              and r.outcome == "success" and r.ip and r.user_id is not None]
    if not logins:
        return []
    history = defaultdict(list)          # user_id -> [(id, at, ip)], oldest first
    for h in s.execute(select(ActivityLog.id, ActivityLog.at, ActivityLog.user_id,
                              ActivityLog.ip).where(
            ActivityLog.user_id.in_({r.user_id for r in logins}),
            ActivityLog.action == "auth.login", ActivityLog.outcome == "success",
            ActivityLog.at >= min(r.at for r in logins) - NEW_ADDRESS_LOOKBACK,
            ActivityLog.id < max(r.id for r in logins))
            .order_by(ActivityLog.id)):
        history[h.user_id].append(h)

    out = []
    for r in logins:
        before = {h.ip for h in history[r.user_id]
                  if h.id < r.id and h.at >= r.at - NEW_ADDRESS_LOOKBACK}
        if before and r.ip not in before:
            out.append(_alert("new_address", INFO,
                              f"{r.email} signed in from a new address",
                              f"{r.ip} - not seen for this account in the "
                              f"previous 90 days.", [r], email=r.email, ip=r.ip))
    return out


def _out_of_hours(rows) -> list[dict]:
    zone = settings.zone()
    start, end = settings.work_hours
    by_email = defaultdict(list)
    for r in rows:
        if r.action == "auth.login" and r.outcome == "success":
            hour = r.at.astimezone(zone).hour
            if not (start <= hour < end):
                by_email[r.email].append(r)
    return [_alert("out_of_hours", INFO,
                   f"{email} signed in outside working hours",
                   f"{len(hits)} sign-in{'s' if len(hits) != 1 else ''} outside "
                   f"{start:02d}:00-{end:02d}:00.", hits, email=email)
            for email, hits in by_email.items()]


def _bulk_export(rows) -> list[dict]:
    """EXPORTS_PER_HOUR or more in any sixty-minute stretch, per person."""
    by_email = defaultdict(list)
    for r in rows:
        if r.action == "table.export" and r.outcome == "success":
            by_email[r.email].append(r)
    out = []
    hour = dt.timedelta(hours=1)
    for email, xs in by_email.items():
        xs.sort(key=lambda r: r.at)
        best, lo = [], 0
        for hi in range(len(xs)):
            while xs[hi].at - xs[lo].at > hour:
                lo += 1
            if hi - lo + 1 > len(best):
                best = xs[lo:hi + 1]
        if len(best) >= EXPORTS_PER_HOUR:
            out.append(_alert("bulk_export", WARNING,
                              f"{email} exported {len(best)} tables within an hour",
                              f"{len(xs)} exports in the period in all.",
                              best, email=email))
    return out


def _denied(rows) -> list[dict]:
    by_email = defaultdict(list)
    for r in rows:
        if r.outcome == "denied":
            by_email[r.email].append(r)
    return [_alert("denied", WARNING,
                   f"{email} tried admin actions without being an admin",
                   f"{len(hits)} refused request{'s' if len(hits) != 1 else ''}.",
                   hits, email=email)
            for email, hits in by_email.items()]


def _deletions(rows) -> list[dict]:
    gone = [r for r in rows if r.action in DELETIONS and r.outcome == "success"]
    if not gone:
        return []
    who = sorted({r.email for r in gone if r.email})
    return [_alert("deletions", INFO,
                   f"{len(gone)} deletion{'s' if len(gone) != 1 else ''}",
                   f"Runs, weeks or activity deleted, by {', '.join(who)}. Deleting "
                   "cannot be undone.", gone)]
