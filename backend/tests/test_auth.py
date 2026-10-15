"""Sign-up rules, email confirmation codes and sign-in."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import session as db_session
from app.service import codes as codes_service
from tests.accounts import (age_codes, confirm_email, last_mail, mailed_code,
                            sign_in, token_of)

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
    """Following the mailed link and an admin's approval, done directly."""
    import datetime as dt
    from sqlalchemy import update
    from app.db.models import User
    from app.db.session import session
    with session() as s:
        s.execute(update(User).values(
            pending=False, is_active=True,
            email_verified_at=dt.datetime.now(dt.timezone.utc)))


def auth(client, **over):
    body = {**GOOD, **over}
    assert signup(client, **over).status_code == 200
    approve_all()
    return sign_in(client, body["email"], body["password"])


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


def test_signing_up_waits_for_the_email_and_then_an_admin(client):
    """Anyone can type an @appedology.com address."""
    body = signup(client).json()
    assert body["pending"] is True and "token" not in body
    login = lambda: client.post("/api/auth/login", json={
        "email": GOOD["email"], "password": GOOD["password"]})

    r = login()
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "email_unverified"

    confirm_email(client, GOOD["email"])
    r = login()
    assert r.status_code == 401 and "approve" in r.json()["detail"]

    approve_all()
    headers = sign_in(client, GOOD["email"], GOOD["password"])
    assert client.get("/api/auth/me", headers=headers).json()["apd_id"] == "APD-1234"


def verify(client, code, email=GOOD["email"]):
    return client.post("/api/auth/verify-email", json={"email": email, "code": code})


def test_a_confirmation_code_works_once(client):
    signup(client)
    code = mailed_code(GOOD["email"])
    assert len(code) == 6 and code.isdigit()
    assert verify(client, code).status_code == 200
    r = verify(client, code)
    assert r.status_code == 400 and r.json()["detail"] == codes_service.WRONG_CODE


def test_a_code_is_accepted_however_it_is_typed(client):
    signup(client)
    code = mailed_code(GOOD["email"])
    assert verify(client, f" {code[:3]} {code[3:]} ").status_code == 200


def test_a_confirmation_code_expires_after_five_minutes(client):
    signup(client)
    code = mailed_code(GOOD["email"])
    age_codes(minutes=5, seconds=1)
    assert verify(client, code).status_code == 400


def test_five_wrong_guesses_spend_a_code(client):
    signup(client)
    code = mailed_code(GOOD["email"])
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(codes_service.CODE_TRIES):
        assert verify(client, wrong).status_code == 400
    assert verify(client, code).status_code == 400


def test_a_wrong_email_and_a_wrong_code_get_the_same_answer(client):
    signup(client)
    code = mailed_code(GOOD["email"])
    nobody = verify(client, code, email="nobody@appedology.com")
    wrong = verify(client, "999999" if code != "999999" else "888888")
    assert nobody.status_code == wrong.status_code == 400
    assert nobody.json() == wrong.json()


def test_the_code_itself_is_never_stored(client):
    from sqlalchemy import select
    from app.db.models import OneTimeCode
    from app.db.session import session
    signup(client)
    code = mailed_code(GOOD["email"])
    with session() as s:
        stored = s.execute(select(OneTimeCode.secret)).scalar_one()
    assert code not in stored and stored.startswith("pbkdf2_sha256$")


def test_the_confirmation_code_is_sent_again_only_with_the_password(client):
    from app.service import mail
    signup(client)
    age_codes(seconds=61)
    before = len(mail.outbox)
    wrong = client.post("/api/auth/verify-email/resend",
                        json={"email": GOOD["email"], "password": "not it"})
    nobody = client.post("/api/auth/verify-email/resend",
                         json={"email": "nobody@appedology.com", "password": "x"})
    right = client.post("/api/auth/verify-email/resend",
                        json={"email": GOOD["email"], "password": GOOD["password"]})
    assert wrong.json() == nobody.json() == right.json()
    assert len(mail.outbox) == before + 1


def test_a_new_code_waits_a_minute_after_the_last(client):
    signup(client)
    r = client.post("/api/auth/verify-email/resend",
                    json={"email": GOOD["email"], "password": GOOD["password"]})
    assert r.status_code == 429 and "seconds" in r.json()["detail"]
    old = mailed_code(GOOD["email"])
    age_codes(seconds=61)
    client.post("/api/auth/verify-email/resend",
                json={"email": GOOD["email"], "password": GOOD["password"]})
    new = mailed_code(GOOD["email"])
    if new != old:
        assert verify(client, old).status_code == 400
    assert verify(client, new).status_code == 200


def test_the_email_is_html_with_a_plain_text_copy(client):
    signup(client)
    msg = last_mail(GOOD["email"])
    code = msg["Subject"].split()[0]
    html = msg.get_body(("html",)).get_content()
    text = msg.get_body(("plain",)).get_content()
    assert code in html and code in text
    assert "5 minutes" in html and "5 minutes" in text


def test_what_a_person_typed_is_escaped_in_the_html():
    from app.service import emails
    html = emails.verify_email("<script>x</script>@appedology.com", "123456", 5).html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_if_the_mail_cannot_go_no_account_is_made(client, monkeypatch):
    from app.service import mail

    def broken(*_):
        raise mail.MailUnavailable("The email could not be sent just now.")
    monkeypatch.setattr(mail, "send", broken)
    r = signup(client)
    assert r.status_code == 503
    monkeypatch.undo()
    assert signup(client).status_code == 200      # not "already has an account"


def test_a_server_without_mail_set_up_does_not_pretend_to_send(monkeypatch):
    from app.service import mail
    monkeypatch.setattr(settings, "require_https", True)
    monkeypatch.setattr(settings, "smtp_host", "")
    with pytest.raises(mail.MailUnavailable, match="cannot send email"):
        mail.send("a@appedology.com", "subject", "body")


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
    assert set(r.json()) == {"user"}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    headers = {"Authorization": f"Bearer {token_of(r)}"}

    assert client.get("/api/auth/me", headers=headers).status_code == 200
    client.post("/api/auth/logout", headers=headers)
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_login_says_the_same_thing_for_a_wrong_email_and_a_wrong_password(client):
    signup(client)
    wrong_pw = client.post("/api/auth/login",
                           json={"email": GOOD["email"], "password": "not it at all"})
    no_user = client.post("/api/auth/login",
                          json={"email": "ghost@appedology.com", "password": "whatever!"})
    assert wrong_pw.status_code == no_user.status_code == 401
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
