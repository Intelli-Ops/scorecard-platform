"""Test helpers for making accounts and signing in."""
from __future__ import annotations

PASSWORD = "a good long password"


def make_account(email: str, apd_id: str, *, role: str = "viewer",
                 reports: str = "",
                 password: str = PASSWORD) -> int:
    from app.db.session import session
    from app.service import auth
    with session() as s:
        user = auth.sign_up(s, email, apd_id, password, pending=False)
        user.role = role
        user.report_access = reports
        return user.id


def last_mail(to: str):
    """The newest mail to `to`."""
    from app.service import mail
    return next(m for m in reversed(mail.outbox) if m["To"] == to)


def mailed_code(to: str) -> str:
    """The 6-digit code in the newest mail to `to` - it leads the subject."""
    return last_mail(to)["Subject"].split()[0]


def age_codes(**ago) -> None:
    """Move every one-time code back in time by `ago`."""
    import datetime as dt
    from sqlalchemy import select
    from app.db.models import OneTimeCode
    from app.db.session import session
    shift = dt.timedelta(**ago)
    with session() as s:
        for row in s.execute(select(OneTimeCode)).scalars():
            row.created_at -= shift
            row.expires_at -= shift


def confirm_email(client, email: str) -> None:
    """What entering the code from the sign-up mail does."""
    r = client.post("/api/auth/verify-email",
                    json={"email": email, "code": mailed_code(email)})
    assert r.status_code == 200, r.text


def token_of(response) -> str:
    """The session a sign-in opened."""
    from app.api.deps import COOKIE
    assert "token" not in response.json()
    return response.cookies[COOKIE]


def sign_in(client, email: str, password: str = PASSWORD) -> dict:
    """Headers for a session of `email`."""
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {token_of(r)}"}


def account(client, email: str, apd_id: str, *, role: str = "viewer",
            reports: str = "") -> dict:
    """Make an account and return the headers of a session for it."""
    make_account(email, apd_id, role=role, reports=reports)
    return sign_in(client, email)
