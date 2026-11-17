"""E-Mails verschicken, etwa den Link für „Passwort vergessen“.

Eingestellt wird über Umgebungsvariablen (auf Railway unter Variables):

- ``MAIL_FROM``: Absender, z. B. ``Portfolio-Optimierer <noreply@deine-domain.de>``.
- ``RESEND_API_KEY``: Versand über die HTTP-API von Resend. Läuft über HTTPS und damit auch dort,
  wo ausgehendes SMTP gesperrt ist.
- oder ``SMTP_HOST`` mit ``SMTP_PORT`` (Standard 587, STARTTLS; 465 für SSL), ``SMTP_USER`` und
  ``SMTP_PASSWORD``: jeder SMTP-Server.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

RESEND_URL = "https://api.resend.com/emails"


class MailError(RuntimeError):
    """Versand nicht eingerichtet oder fehlgeschlagen."""


def configured() -> bool:
    return bool(os.environ.get("MAIL_FROM", "").strip()
                and (os.environ.get("RESEND_API_KEY") or os.environ.get("SMTP_HOST")))


def send(to: str, subject: str, text: str) -> None:
    """Eine Nachricht als reinen Text verschicken; Fehler als ``MailError``."""
    if not configured():
        raise MailError("E-Mail-Versand nicht eingerichtet: MAIL_FROM und RESEND_API_KEY oder SMTP_HOST fehlen.")
    sender = os.environ["MAIL_FROM"].strip()
    if os.environ.get("RESEND_API_KEY"):
        _send_resend(sender, to, subject, text)
    else:
        _send_smtp(sender, to, subject, text)


def _send_resend(sender: str, to: str, subject: str, text: str) -> None:
    body = json.dumps({"from": sender, "to": [to], "subject": subject, "text": text}).encode("utf-8")
    request = urllib.request.Request(RESEND_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
        "Content-Type": "application/json",
        "User-Agent": "portfolio-optimierer",
    })
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except urllib.error.HTTPError as exc:
        raise MailError(f"Resend lehnte den Versand ab (HTTP {exc.code}).") from None
    except OSError as exc:
        raise MailError(f"Resend nicht erreichbar ({exc}).") from None


def _send_smtp(sender: str, to: str, subject: str, text: str) -> None:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, to, subject
    message.set_content(text)
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT") or 587)
    user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD", "")
    context = ssl.create_default_context()
    try:
        server = (smtplib.SMTP_SSL(host, port, timeout=15, context=context) if port == 465
                  else smtplib.SMTP(host, port, timeout=15))
        with server:
            if port != 465:
                server.starttls(context=context)
            if user:
                server.login(user, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"SMTP-Versand fehlgeschlagen ({exc}).") from None
