"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Platform email: verification and password reset.

Distinct from app/channels/email.py, which carries *customer* conversations in
and out of an organization's own support inbox. This module speaks only as the
platform, always from the platform's own SMTP account, and never touches an
organization's channel credentials — a tenant must not be able to make the
platform send a password-reset mail through their mail server, or read one.
"""

import asyncio
import html
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional
from urllib.parse import quote

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

SMTP_TIMEOUT_SECONDS = 20.0

# Shipped defaults from .env.example. Sending with these configured means
# talking to smtp.gmail.com as "your-email@gmail.com", which fails auth every
# time — so treat them as "not configured" rather than as credentials.
_PLACEHOLDER_VALUES = {
    "your-email@gmail.com",
    "your-password",
    "",
}


def is_configured() -> bool:
    """True when real SMTP credentials are present.

    Callers use this to decide whether an email-dependent flow can be offered
    at all, rather than accepting a signup and silently never sending the mail.
    """
    return (
        bool(settings.SMTP_SERVER)
        and settings.SMTP_USERNAME not in _PLACEHOLDER_VALUES
        and settings.SMTP_PASSWORD not in _PLACEHOLDER_VALUES
    )


def _send_blocking(to_email: str, subject: str, text_body: str, html_body: str) -> None:
    """Synchronous SMTP send. Always called via a worker thread."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.FROM_NAME, settings.FROM_EMAIL))
    message["To"] = to_email
    # Bounces and vacation responders must not reply into a mailbox nobody
    # reads, and this header suppresses most auto-replies outright.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    port = int(settings.SMTP_PORT)
    if port == 465:
        smtp = smtplib.SMTP_SSL(settings.SMTP_SERVER, port, timeout=SMTP_TIMEOUT_SECONDS)
    else:
        smtp = smtplib.SMTP(settings.SMTP_SERVER, port, timeout=SMTP_TIMEOUT_SECONDS)
    try:
        if port != 465:
            try:
                smtp.starttls()
            except smtplib.SMTPNotSupportedError:
                # Refuse rather than downgrade. The channel adapter tolerates
                # plaintext for a tenant's own legacy mail server; a password
                # reset token is a live credential and does not travel in clear.
                raise RuntimeError(
                    "SMTP server does not support STARTTLS; refusing to send "
                    "an authentication email unencrypted"
                )
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


async def send_email(to_email: str, subject: str, text_body: str, html_body: str) -> bool:
    """Send one message. Returns success rather than raising.

    smtplib blocks, and these handlers are async, so the send runs in a worker
    thread — a slow or black-holed SMTP host would otherwise stall the event
    loop for every other request for up to the full timeout.

    Failures are logged and swallowed by design. The callers are auth flows
    whose responses are deliberately identical whether or not an address
    exists; letting an SMTP error turn into a 500 would leak that difference
    and hand an attacker an account-enumeration oracle.
    """
    if not is_configured():
        logger.error(
            "Email not sent to %s (%r): SMTP is not configured. Set SMTP_SERVER, "
            "SMTP_USERNAME, SMTP_PASSWORD and FROM_EMAIL.", to_email, subject
        )
        return False
    try:
        await asyncio.to_thread(_send_blocking, to_email, subject, text_body, html_body)
        logger.info("Sent %r to %s", subject, to_email)
        return True
    except Exception as e:
        logger.error("Failed to send %r to %s: %s", subject, to_email, e)
        return False


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def _shell(heading: str, intro: str, body_html: str, footer: str) -> str:
    """Wrap content in the platform's email chrome.

    Table-based, inline-styled and single-column on purpose: Outlook ignores
    most external CSS and flexbox, so anything cleverer than this degrades to
    unstyled text in a meaningful share of inboxes.
    """
    product = html.escape(settings.PLATFORM_NAME)
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#0b0d10;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#0b0d10;padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="max-width:520px;background:#14171c;border:1px solid #232830;
                  border-radius:16px;padding:36px 32px;
                  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
      <tr><td style="color:#c8ff4d;font-size:15px;font-weight:700;padding-bottom:22px;">
        {product}
      </td></tr>
      <tr><td style="color:#f4f6f8;font-size:23px;font-weight:700;padding-bottom:12px;">
        {heading}
      </td></tr>
      <tr><td style="color:#9aa4b2;font-size:15px;line-height:1.6;padding-bottom:26px;">
        {intro}
      </td></tr>
      <tr><td>{body_html}</td></tr>
      <tr><td style="color:#6b7484;font-size:12.5px;line-height:1.6;
                     padding-top:26px;border-top:1px solid #232830;">
        {footer}
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _button(url: str, label: str) -> str:
    return (
        f'<a href="{html.escape(url, quote=True)}" '
        'style="display:inline-block;background:#c8ff4d;color:#0b0d10;'
        'text-decoration:none;font-weight:600;font-size:15px;'
        'padding:13px 26px;border-radius:10px;">'
        f'{html.escape(label)}</a>'
    )


async def send_verification_email(to_email: str, full_name: str, raw_token: str) -> bool:
    product = settings.PLATFORM_NAME
    # quote() the token even though token_urlsafe() output is URL-safe: the
    # guarantee belongs at the boundary that builds the URL, not in the caller.
    link = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email?token={quote(raw_token)}"
    name = (full_name or "").strip().split(" ")[0] or "there"

    text = (
        f"Hi {name},\n\n"
        f"Confirm your email address to finish setting up your {product} workspace:\n\n"
        f"{link}\n\n"
        "This link works for 48 hours. If you didn't create an account, ignore "
        "this email and nothing will happen.\n"
    )
    body = (
        _button(link, "Verify email address")
        + '<p style="color:#6b7484;font-size:12.5px;line-height:1.6;margin:22px 0 0;">'
        'Button not working? Paste this into your browser:<br>'
        f'<span style="color:#9aa4b2;word-break:break-all;">{html.escape(link)}</span></p>'
    )
    return await send_email(
        to_email,
        f"Verify your email for {product}",
        text,
        _shell(
            "Confirm your email",
            f"Hi {html.escape(name)}, you're one click from finishing your workspace setup.",
            body,
            "This link works for 48 hours. If you didn't create an account, "
            "you can safely ignore this email.",
        ),
    )


async def send_password_reset_email(to_email: str, full_name: str, code: str) -> bool:
    product = settings.PLATFORM_NAME
    name = (full_name or "").strip().split(" ")[0] or "there"

    text = (
        f"Hi {name},\n\n"
        f"Your {product} password reset code is: {code}\n\n"
        "It expires in 15 minutes. If you didn't ask to reset your password, "
        "ignore this email — your password has not changed.\n"
    )
    body = (
        '<div style="background:#0b0d10;border:1px solid #232830;border-radius:12px;'
        'padding:20px;text-align:center;">'
        '<div style="color:#6b7484;font-size:12px;letter-spacing:0.08em;'
        'text-transform:uppercase;padding-bottom:10px;">Your reset code</div>'
        '<div style="color:#c8ff4d;font-size:34px;font-weight:700;'
        f'letter-spacing:0.18em;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{html.escape(code)}</div>'
        '</div>'
    )
    return await send_email(
        to_email,
        f"Your {product} password reset code",
        text,
        _shell(
            "Reset your password",
            f"Hi {html.escape(name)}, enter this code to choose a new password.",
            body,
            "This code expires in 15 minutes. If you didn't request it, ignore "
            "this email — your password has not changed.",
        ),
    )
