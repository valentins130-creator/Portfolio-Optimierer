"""Konten: Registrierung, Anmeldung, Sperre nach Fehlversuchen und Sitzungen."""

import sqlite3

import pytest

from portfolio_optimizer.accounts import (
    LOCK_SECONDS,
    MAX_FAILURES,
    RESET_MINUTES,
    RESET_PER_HOUR,
    AccountError,
    AccountStore,
    hash_password,
    verify_password,
)


@pytest.fixture
def store(tmp_path):
    return AccountStore(tmp_path / "konten.sqlite")


def test_password_hash_is_salted_and_verifiable():
    a, b = hash_password("ein langes Passwort"), hash_password("ein langes Passwort")
    assert a != b and a.startswith("scrypt$")
    assert verify_password("ein langes Passwort", a)
    assert not verify_password("ein anderes Passwort", a)
    assert not verify_password("egal", "kaputt")


def test_register_and_authenticate(store, tmp_path):
    account = store.register(" Anna@Beispiel.de ", "sehr-geheim-123")
    assert account.email == "anna@beispiel.de"
    assert store.authenticate("ANNA@beispiel.de", "sehr-geheim-123").id == account.id
    # Nur der Hash liegt in der Datenbank, nie das Passwort
    with sqlite3.connect(tmp_path / "konten.sqlite") as db:
        stored = db.execute("SELECT password FROM users").fetchone()[0]
    assert "sehr-geheim-123" not in stored


def test_register_rejects_bad_input_with_helpful_messages(store):
    with pytest.raises(AccountError, match="name@beispiel.de"):
        store.register("keine-mail", "sehr-geheim-123")
    with pytest.raises(AccountError, match="mindestens 10 Zeichen"):
        store.register("anna@beispiel.de", "kurz")
    store.register("anna@beispiel.de", "sehr-geheim-123")
    with pytest.raises(AccountError, match="schon ein Konto"):
        store.register("Anna@Beispiel.de", "anderes-passwort")


def test_wrong_password_and_unknown_email_get_the_same_answer(store):
    store.register("anna@beispiel.de", "sehr-geheim-123")
    with pytest.raises(AccountError) as wrong:
        store.authenticate("anna@beispiel.de", "falsch-falsch")
    with pytest.raises(AccountError) as unknown:
        store.authenticate("bert@beispiel.de", "falsch-falsch")
    assert str(wrong.value) == str(unknown.value)


def test_too_many_failures_lock_the_email_for_a_while(store):
    store.register("anna@beispiel.de", "sehr-geheim-123")
    for _ in range(MAX_FAILURES):
        with pytest.raises(AccountError):
            store.authenticate("anna@beispiel.de", "falsch-falsch", now=1000.0)
    with pytest.raises(AccountError, match="Zu viele Fehlversuche"):
        store.authenticate("anna@beispiel.de", "sehr-geheim-123", now=1001.0)
    assert store.authenticate("anna@beispiel.de", "sehr-geheim-123", now=1001.0 + LOCK_SECONDS).email


def test_expired_failures_are_deleted(store, tmp_path):
    for _ in range(2):  # auch für Adressen ohne Konto, die sich nie erfolgreich anmelden
        with pytest.raises(AccountError):
            store.authenticate("niemand@beispiel.de", "falsch-falsch", now=1000.0)
    with pytest.raises(AccountError):
        store.authenticate("anna@beispiel.de", "falsch-falsch", now=1001.0 + LOCK_SECONDS)
    with sqlite3.connect(tmp_path / "konten.sqlite") as db:
        assert db.execute("SELECT email FROM failures").fetchall() == [("anna@beispiel.de",)]


def test_sessions_keep_users_signed_in_until_they_expire_or_end(store):
    account = store.register("anna@beispiel.de", "sehr-geheim-123")
    token = store.create_session(account.id, days=30, now=0.0)
    assert store.session_user(token, now=10.0).id == account.id
    assert store.session_user(token, now=31 * 86400) is None
    assert store.session_user("ausgedacht", now=10.0) is None
    store.end_session(token)
    assert store.session_user(token, now=10.0) is None


def test_deleting_an_account_removes_it_and_its_sessions(store):
    account = store.register("anna@beispiel.de", "sehr-geheim-123")
    token = store.create_session(account.id)
    store.delete(account.id)
    assert store.get(account.id) is None and store.session_user(token) is None
    with pytest.raises(AccountError):
        store.authenticate("anna@beispiel.de", "sehr-geheim-123")


def test_reset_link_sets_a_new_password_once(store):
    account = store.register("anna@beispiel.de", "sehr-geheim-123")
    session = store.create_session(account.id, now=0.0)
    result = store.create_reset(" Anna@Beispiel.de ", now=100.0)
    assert result is not None and result[0].id == account.id
    token = result[1]
    assert store.reset_account(token, now=200.0).id == account.id
    with pytest.raises(AccountError, match="mindestens 10 Zeichen"):
        store.reset_password(token, "kurz", now=200.0)
    store.reset_password(token, "ganz-neues-passwort", now=200.0)
    assert store.authenticate("anna@beispiel.de", "ganz-neues-passwort").id == account.id
    with pytest.raises(AccountError):
        store.authenticate("anna@beispiel.de", "sehr-geheim-123")
    # der Link gilt nur einmal, gemerkte Anmeldungen enden
    assert store.reset_account(token, now=300.0) is None
    with pytest.raises(AccountError, match="abgelaufen oder wurde schon benutzt"):
        store.reset_password(token, "noch-ein-passwort", now=300.0)
    assert store.session_user(session, now=300.0) is None


def test_reset_link_expires_and_is_limited_per_hour(store):
    store.register("anna@beispiel.de", "sehr-geheim-123")
    assert store.create_reset("bert@beispiel.de", now=0.0) is None  # kein Konto, keine Mail
    token = store.create_reset("anna@beispiel.de", now=0.0)[1]
    assert store.reset_account(token, now=RESET_MINUTES * 60 + 1) is None
    for i in range(RESET_PER_HOUR - 1):
        assert store.create_reset("anna@beispiel.de", now=10.0 + i) is not None
    assert store.create_reset("anna@beispiel.de", now=20.0) is None  # Grenze je Stunde erreicht
    assert store.create_reset("anna@beispiel.de", now=3700.0) is not None


def test_reset_lifts_the_lock_after_failed_logins(store):
    store.register("anna@beispiel.de", "sehr-geheim-123")
    for _ in range(MAX_FAILURES):
        with pytest.raises(AccountError):
            store.authenticate("anna@beispiel.de", "falsch-falsch", now=1000.0)
    token = store.create_reset("anna@beispiel.de", now=1000.0)[1]
    store.reset_password(token, "ganz-neues-passwort", now=1001.0)
    assert store.authenticate("anna@beispiel.de", "ganz-neues-passwort", now=1002.0).email
