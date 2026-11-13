"""Konten: Registrierung, Anmeldung, Sperre nach Fehlversuchen und Sitzungen."""

import sqlite3

import pytest

from portfolio_optimizer.accounts import (
    LOCK_SECONDS,
    MAX_FAILURES,
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
