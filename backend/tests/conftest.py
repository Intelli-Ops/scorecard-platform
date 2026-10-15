"""Test setup: no real email, fast hashing, an empty outbox per test."""
import os

import pytest

os.environ["SCORECARD_SMTP_HOST"] = ""


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    """Password and code hashing at a few thousand rounds rather than 600,000."""
    from app.service import auth
    monkeypatch.setattr(auth, "ITERATIONS", 2_000)


@pytest.fixture(autouse=True)
def empty_outbox():
    """Each test starts with no mail."""
    from app.service import mail
    mail.outbox.clear()
    yield
