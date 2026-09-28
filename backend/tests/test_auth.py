"""Accounts: the company rules, and that they hold at the API and not only in
the browser form.

The two rules are the point of this file. An email outside @appedology.com and
an APD id that is not APD-#### must both be refused by the API itself, because
a form can be bypassed by anyone who opens the developer console.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import session as db_session
from tests.accounts import account, make_account, sign_in

GOOD = {"email": "ali.asghar@appedology.com", "apd_id": "APD-1234",
        "password": "correct horse battery"}


@pytest.fixture
def client(tmp_path):
    settings.use(tmp_path / "data")
    db_session.reset()
    from app.db.session import create_all
    create_all()
    from app.main import app
    with TestClient(app) as c:
        yield c


def signup(client, **over):
    return client.post("/api/auth/signup", json={**GOOD, **over})


def approve_all():
    """What an admin does on the Users screen, done directly."""
    from sqlalchemy import update
    from app.db.models import User
    from app.db.session import session
    with session() as s:
        s.execute(update(User).values(pending=False, is_active=True))


def auth(client, **over):
    body = {**GOOD, **over}
    assert signup(client, **over).status_code == 200
    approve_all()
    return sign_in(client, body["email"], body["password"])


# ------------------------------------------------------------------ the rules

@pytest.mark.parametrize("email", [
    "someone@gmail.com",
    "someone@appedology.co",
    "someone@notappedology.com",
    "someone@appedology.com.attacker.net",
    "no-at-sign",
    "",
])
def test_only_appedology_emails_are_accepted(client, email):
    r = signup(client, email=email)
    assert r.status_code == 400
    assert "appedology.com" in r.json()["detail"].lower() or "email" in r.json()["detail"].lower()


@pytest.mark.parametrize("email", [
    "ali.asghar@appedology.com",
    "ALI.ASGHAR@APPEDOLOGY.COM",       # case does not matter
    "first+tag@appedology.com",
])
def test_appedology_emails_in_any_case_are_accepted(client, email):
    assert signup(client, email=email).status_code == 200


@pytest.mark.parametrize("apd", [
    "APD-123",      # three digits
    "APD-12345",    # five
    "APD1234",      # no dash
    "XYZ-1234",     # wrong prefix
    "APD-12a4",     # not digits
    "",
])
def test_apd_id_must_be_four_digits(client, apd):
    r = signup(client, apd_id=apd)
    assert r.status_code == 400
    assert "APD-1234" in r.json()["detail"]


@pytest.mark.parametrize("typed,stored", [
    ("APD-1234", "APD-1234"),
    ("apd-1234", "APD-1234"),      # lower case is fine
    ("1234", "APD-1234"),          # a bare badge number is completed
    (" APD-1234 ", "APD-1234"),
])
def test_apd_id_is_tidied_rather_than_rejected(client, typed, stored):
    r = signup(client, apd_id=typed)
    assert r.status_code == 200
    assert r.json()["user"]["apd_id"] == stored


def test_short_passwords_are_refused(client):
    r = signup(client, password="short")
    assert r.status_code == 400 and "8 characters" in r.json()["detail"]


def test_email_is_stored_lower_case(client):
    r = signup(client, email="Ali.Asghar@Appedology.com")
    assert r.json()["user"]["email"] == "ali.asghar@appedology.com"


# ------------------------------------------------------------------ accounts

def test_signing_up_waits_for_an_admin(client):
    """Anyone can TYPE an @appedology.com address. Until an admin approves the
    account, it cannot sign in - and no token comes back from signing up."""
    body = signup(client).json()
    assert body["pending"] is True and "token" not in body
    r = client.post("/api/auth/login",
                    json={"email": GOOD["email"], "password": GOOD["password"]})
    assert r.status_code == 401 and "approve" in r.json()["detail"]

    approve_all()
    headers = sign_in(client, GOOD["email"], GOOD["password"])
    assert client.get("/api/auth/me", headers=headers).json()["apd_id"] == "APD-1234"


def test_waiting_for_approval_is_only_said_to_the_right_password(client):
    """Saying "pending" to a wrong password would confirm the address exists."""
    signup(client)
    r = client.post("/api/auth/login",
                    json={"email": GOOD["email"], "password": "not the password"})
    assert r.json()["detail"] == "That email and password do not match."


def test_an_email_cannot_be_used_twice(client):
    signup(client)
    r = signup(client, apd_id="APD-9999")
    assert r.status_code == 400 and "already has an account" in r.json()["detail"]


def test_an_apd_id_cannot_be_used_twice(client):
    signup(client)
    r = signup(client, email="other@appedology.com")
    assert r.status_code == 400 and "already registered" in r.json()["detail"]


def test_login_and_logout(client):
    signup(client)
    approve_all()
    r = client.post("/api/auth/login",
                    json={"email": GOOD["email"], "password": GOOD["password"]})
    assert r.status_code == 200
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/auth/me", headers=headers).status_code == 200
    client.post("/api/auth/logout", headers=headers)
    # Signing out revokes the token, which is why sessions are rows rather than
    # self-contained tokens.
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_login_says_the_same_thing_for_a_wrong_email_and_a_wrong_password(client):
    signup(client)
    wrong_pw = client.post("/api/auth/login",
                           json={"email": GOOD["email"], "password": "not it at all"})
    no_user = client.post("/api/auth/login",
                          json={"email": "ghost@appedology.com", "password": "whatever!"})
    assert wrong_pw.status_code == no_user.status_code == 401
    # Different messages would tell someone guessing which addresses exist.
    assert wrong_pw.json()["detail"] == no_user.json()["detail"]


def test_the_password_itself_is_never_stored(client):
    signup(client)
    from sqlalchemy import select
    from app.db.models import User
    from app.db.session import session
    with session() as s:
        stored = s.execute(select(User.password_hash)).scalar_one()
    assert GOOD["password"] not in stored
    assert stored.startswith("pbkdf2_sha256$")


def test_two_accounts_with_the_same_password_hash_differently(client):
    signup(client)
    signup(client, email="second@appedology.com", apd_id="APD-5678")
    from sqlalchemy import select
    from app.db.models import User
    from app.db.session import session
    with session() as s:
        hashes = s.execute(select(User.password_hash)).scalars().all()
    assert len(set(hashes)) == 2      # per-user salt


# ------------------------------------------------------------------ the gate

@pytest.mark.parametrize("method,path", [
    ("get", "/api/weeks"),
    ("get", "/api/runs"),
    ("get", "/api/reports"),
    ("get", "/api/runs/1"),
    ("post", "/api/runs?report=gfs&week=2026-W36"),
    ("get", "/api/runs/1/tables/raw_data"),
    ("get", "/api/runs/1/tables/raw_data/csv"),
])
def test_everything_else_needs_an_account(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_health_is_open_so_monitoring_can_reach_it(client):
    """A health check that needs credentials is not a health check."""
    assert client.get("/api/health").json()["ok"] is True


def test_a_made_up_token_is_refused(client):
    assert client.get("/api/weeks",
                      headers={"Authorization": "Bearer not-a-real-token"}
                      ).status_code == 401


def test_signed_in_you_can_reach_the_app(client):
    """A new account is a viewer: it reaches the scorecards, not the workspace."""
    headers = auth(client)
    assert client.get("/api/scorecards/current", headers=headers).status_code == 200
    assert client.get("/api/weeks", headers=headers).status_code == 403
