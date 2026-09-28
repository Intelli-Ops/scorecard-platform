"""Accounts for tests.

Signing up in the app leaves an account waiting for an admin, so a test that
needs someone signed in makes the account directly - approved, with the role
it asks for - and then signs in through the API like the browser would.
"""
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


def sign_in(client, email: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def account(client, email: str, apd_id: str, *, role: str = "viewer",
            reports: str = "") -> dict:
    """Make an account and return the headers of a session for it."""
    make_account(email, apd_id, role=role, reports=reports)
    return sign_in(client, email)
