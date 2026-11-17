"""E-Mail-Versand über die Resend-API oder SMTP, ohne echtes Netz."""

import json

import pytest

from portfolio_optimizer import mailer


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("MAIL_FROM", "RESEND_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_without_settings_nothing_is_sent():
    assert not mailer.configured()
    with pytest.raises(mailer.MailError, match="nicht eingerichtet"):
        mailer.send("anna@beispiel.de", "Betreff", "Text")


def test_resend_api_gets_sender_recipient_and_key(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "Portfolio-Optimierer <noreply@beispiel.de>")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    sent = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        sent.update(url=request.full_url, auth=request.get_header("Authorization"),
                    body=json.loads(request.data.decode("utf-8")))
        return Response()

    monkeypatch.setattr(mailer.urllib.request, "urlopen", urlopen)
    mailer.send("anna@beispiel.de", "Neues Passwort", "Hallo")
    assert sent["url"] == mailer.RESEND_URL and sent["auth"] == "Bearer re_test"
    assert sent["body"] == {"from": "Portfolio-Optimierer <noreply@beispiel.de>", "to": ["anna@beispiel.de"],
                            "subject": "Neues Passwort", "text": "Hallo"}


def test_resend_errors_become_mail_errors(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "noreply@beispiel.de")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    def urlopen(request, timeout):
        raise mailer.urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr(mailer.urllib.request, "urlopen", urlopen)
    with pytest.raises(mailer.MailError, match="HTTP 403"):
        mailer.send("anna@beispiel.de", "Betreff", "Text")


def test_smtp_uses_starttls_and_login(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "noreply@beispiel.de")
    monkeypatch.setenv("SMTP_HOST", "smtp.beispiel.de")
    monkeypatch.setenv("SMTP_USER", "nutzer")
    monkeypatch.setenv("SMTP_PASSWORD", "geheim")
    calls = []

    class SMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, message):
            calls.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr(mailer.smtplib, "SMTP", SMTP)
    mailer.send("anna@beispiel.de", "Neues Passwort", "Hallo")
    assert calls == [("connect", "smtp.beispiel.de", 587), ("starttls",), ("login", "nutzer", "geheim"),
                     ("send", "anna@beispiel.de", "Neues Passwort")]
