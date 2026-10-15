"""Sends email over SMTP."""
from __future__ import annotations
import logging
import smtplib
import threading
from email.message import EmailMessage

from ..config import settings

log = logging.getLogger("scorecard.mail")

outbox: list[EmailMessage] = []
OUTBOX_KEEP = 20


class MailUnavailable(Exception):
    """The mail could not be sent."""


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = f"Scorecard <{settings.mail_from}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if not settings.smtp_host:
        if settings.require_https:
            raise MailUnavailable(
                "This server cannot send email yet, so it cannot send the "
                "code. Ask the person who runs it to set up mail (DEPLOY.md, "
                "'Email').")
        log.warning("no SMTP host - mail to %s not sent:\n%s\n\n%s",
                    to, subject, text)
        outbox.append(msg)
        del outbox[:-OUTBOX_KEEP]
        return

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        log.error("mail to %s failed: %s", to, e)
        raise MailUnavailable("The email could not be sent just now. Try "
                              "again in a few minutes.") from e


def send_later(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Send without making the request wait for it - and without letting how
    long it took say anything."""
    def go():
        try:
            send(to, subject, text, html)
        except MailUnavailable:
            pass                        # logged by send()
    if not settings.smtp_host:
        go()
    else:
        threading.Thread(target=go, name="mail", daemon=True).start()
