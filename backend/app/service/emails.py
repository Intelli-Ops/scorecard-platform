"""Email content, as plain text and HTML."""
from __future__ import annotations
from dataclasses import dataclass
from html import escape

TEAL = "#0E3B35"
GREEN = "#21B47E"
GREEN_SOFT = "#E3F5EC"
TEXT = "#12211F"
TEXT_2 = "#5C6B68"
TEXT_3 = "#94A3A0"
BG = "#EFF3F4"
LINE = "#E4EAE8"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


@dataclass
class Email:
    subject: str
    text: str
    html: str


def _page(preheader: str, title: str, body: str) -> str:
    """The frame every email shares: a band with the name, a white card, a footer."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:{BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BG};">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
    <tr><td style="background:{TEAL};border-radius:12px 12px 0 0;padding:20px 28px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="background:{GREEN};border-radius:8px;width:32px;height:32px;text-align:center;
                   font:700 17px/32px {FONT};color:#FFFFFF;">S</td>
        <td style="padding-left:12px;font:600 17px/1.2 {FONT};color:#FFFFFF;">Scorecard
          <div style="font:400 12px/1.5 {FONT};color:#BFE6D4;">GFS &amp; All Providers &middot; Appedology</div></td>
      </tr></table>
    </td></tr>
    <tr><td style="background:#FFFFFF;border-radius:0 0 12px 12px;padding:32px 28px;
                   font:400 15px/1.6 {FONT};color:{TEXT};">
      <h1 style="margin:0 0 16px;font:600 22px/1.3 {FONT};color:{TEXT};">{escape(title)}</h1>
      {body}
    </td></tr>
    <tr><td style="padding:20px 28px;font:400 12px/1.6 {FONT};color:{TEXT_3};text-align:center;">
      An automatic message from the Appedology Scorecard. Replies are not read.
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


def _code_box(code: str, minutes: int) -> str:
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;">
<tr><td align="center" style="background:{GREEN_SOFT};border:1px solid #BFE6D4;border-radius:10px;padding:22px 12px;">
  <div style="font:600 12px/1.4 {FONT};color:{TEXT_2};letter-spacing:1px;text-transform:uppercase;">Your code</div>
  <div style="font:700 36px/1.3 'SFMono-Regular',Consolas,'Courier New',monospace;color:{TEAL};
              letter-spacing:10px;padding:6px 0 4px 10px;">{escape(code)}</div>
  <div style="font:400 13px/1.4 {FONT};color:{TEXT_2};">Expires in <b>{minutes} minutes</b></div>
</td></tr></table>"""


def _p(text: str, muted: bool = False) -> str:
    colour = TEXT_2 if muted else TEXT
    size = "13px" if muted else "15px"
    return f'<p style="margin:0 0 14px;font:400 {size}/1.6 {FONT};color:{colour};">{text}</p>'


def _button(url: str, label: str) -> str:
    """A link drawn as a button - a padded table cell, which Outlook draws
    where it would ignore the padding of the link itself."""
    return f"""<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:22px 0 6px;">
<tr><td style="background:{TEAL};border-radius:8px;">
  <a href="{escape(url, quote=True)}" style="display:inline-block;padding:12px 22px;
     font:600 14px/1 {FONT};color:#FFFFFF;text-decoration:none;">{escape(label)}</a>
</td></tr></table>"""


def _warning(text: str) -> str:
    return (f'<div style="margin-top:22px;padding-top:18px;border-top:1px solid {LINE};'
            f'font:400 13px/1.6 {FONT};color:{TEXT_2};">{text}</div>')


def verify_email(email: str, code: str, minutes: int) -> Email:
    who = escape(email)
    return Email(
        subject=f"{code} is your Scorecard confirmation code",
        text=(f"Your Scorecard confirmation code is {code}.\n\n"
              f"Enter it on the sign-up screen to confirm that {email} is "
              f"yours. It expires in {minutes} minutes.\n\n"
              f"Never share this code. Appedology staff will never ask you "
              f"for it.\n\nIf you did not create a Scorecard account, ignore "
              f"this email: without the code the account can never be used.\n"),
        html=_page(
            f"Your confirmation code is {code}. It expires in {minutes} minutes.",
            "Confirm your email",
            _p(f"Enter this code on the sign-up screen to confirm that "
               f"<b>{who}</b> is yours.")
            + _code_box(code, minutes)
            + _p("Once it is confirmed, an admin approves your account and "
                 "you can sign in.", muted=True)
            + _warning("<b>Never share this code.</b> Appedology staff will "
                       "never ask you for it. If you did not create a "
                       "Scorecard account, ignore this email: without the "
                       "code the account can never be used.")))


def reset_code(email: str, code: str, minutes: int) -> Email:
    who = escape(email)
    return Email(
        subject=f"{code} is your Scorecard password reset code",
        text=(f"Your Scorecard password reset code is {code}.\n\n"
              f"Someone asked to reset the password of {email}. Enter the "
              f"code on the reset screen to choose a new one. It expires in "
              f"{minutes} minutes.\n\nNever share this code. Appedology staff "
              f"will never ask you for it.\n\nIf you did not ask for this, "
              f"ignore this email. Your password has not changed.\n"),
        html=_page(
            f"Your password reset code is {code}. It expires in {minutes} minutes.",
            "Reset your password",
            _p(f"Someone asked to reset the password of <b>{who}</b>. Enter "
               f"this code on the reset screen to choose a new one.")
            + _code_box(code, minutes)
            + _warning("<b>Never share this code.</b> Appedology staff will "
                       "never ask you for it. If you did not ask for this, "
                       "ignore this email. Your password has not changed.")))


def password_changed(email: str, url: str) -> Email:
    who = escape(email)
    return Email(
        subject="Your Scorecard password was changed",
        text=(f"The password of your Scorecard account, {email}, was just "
              f"changed, and every place it was signed in was signed out.\n\n"
              f"If this was you, there is nothing to do.\n\nIf it was not, "
              f"use \"Forgot password?\" on the sign-in screen at once, and "
              f"tell an admin:\n\n{url}\n"),
        html=_page(
            "Your Scorecard password was just changed.",
            "Your password was changed",
            _p(f"The password of <b>{who}</b> was just changed, and every "
               f"place it was signed in was signed out.")
            + _p("If this was you, there is nothing to do.")
            + _button(url, "Open Scorecard")
            + _warning("<b>Not you?</b> Use <b>Forgot password?</b> on the "
                       "sign-in screen at once, and tell an admin.")))


def forced_reset(email: str, url: str) -> Email:
    who = escape(email)
    return Email(
        subject="Choose a new Scorecard password",
        text=(f"An admin has reset the password of your Scorecard account, "
              f"{email}, and signed it out everywhere. Your old password no "
              f"longer works.\n\nTo choose a new one, open the Scorecard, "
              f"press \"Forgot password?\" on the sign-in screen, and follow "
              f"the steps:\n\n{url}\n"),
        html=_page(
            "An admin reset your password. Use Forgot password? to choose a new one.",
            "Choose a new password",
            _p(f"An admin has reset the password of <b>{who}</b> and signed "
               f"it out everywhere. Your old password no longer works.")
            + _p("To choose a new one, open the Scorecard, press <b>Forgot "
                 "password?</b> on the sign-in screen, and follow the steps.")
            + _button(url, "Open Scorecard")
            + _warning("This is usually done to keep an account safe - after "
                       "a lost laptop, say. If you were not expecting it, "
                       "ask an admin why.")))
