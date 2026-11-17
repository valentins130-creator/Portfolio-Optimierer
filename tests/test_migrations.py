"""Migrationen der Konten-Datenbank: Stand, Sicherung, Rückrollen bei Fehlern."""

import sqlite3

import pytest

from portfolio_optimizer import migrations
from portfolio_optimizer.accounts import AccountStore
from portfolio_optimizer.migrations import BACKUP_DIR, MIGRATIONS, Migration, migrate

LATEST = MIGRATIONS[-1].version


def _version(path):
    with sqlite3.connect(path) as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def _tables(path):
    with sqlite3.connect(path) as db:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_new_database_gets_all_migrations_without_backup(tmp_path):
    path = tmp_path / "konten.sqlite"
    result = migrate(path)
    assert (result.before, result.after, result.backup) == (0, LATEST, None)
    assert {"users", "sessions", "failures", "resets"} <= _tables(path)
    assert _version(path) == LATEST
    assert not (tmp_path / BACKUP_DIR).exists()


def test_second_run_changes_nothing(tmp_path):
    path = tmp_path / "konten.sqlite"
    migrate(path)
    result = migrate(path)
    assert (result.before, result.after, result.backup) == (LATEST, LATEST, None)


def test_database_from_before_migrations_keeps_its_accounts_and_is_backed_up(tmp_path):
    """Stand vor diesem Mechanismus: Tabellen da, user_version 0 (so liegt die Datei auf Railway)."""
    path = tmp_path / "konten.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
                   "password TEXT NOT NULL, created TEXT NOT NULL)")
        db.execute("INSERT INTO users VALUES ('a1', 'anna@beispiel.de', 'scrypt$x', '2026-11-01')")
    result = migrate(path)
    assert (result.before, result.after) == (0, LATEST)
    assert result.backup and result.backup.parent == tmp_path / BACKUP_DIR
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT email FROM users").fetchall() == [("anna@beispiel.de",)]
    with sqlite3.connect(result.backup) as db:  # die Sicherung zeigt den alten Stand
        assert db.execute("SELECT email FROM users").fetchall() == [("anna@beispiel.de",)]
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0


def test_new_migration_runs_once_on_top_of_existing_data(tmp_path):
    path = tmp_path / "konten.sqlite"
    store = AccountStore(path)
    store.register("anna@beispiel.de", "sehr-geheim-123")

    def add_column(db, root):
        db.execute("ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT ''")

    steps = MIGRATIONS + (Migration(LATEST + 1, "Name", add_column),)
    assert migrate(path, steps).after == LATEST + 1
    assert migrate(path, steps).backup is None  # zweiter Lauf: nichts zu tun
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT email, name FROM users").fetchall() == [("anna@beispiel.de", "")]


def test_failing_migration_rolls_back_completely(tmp_path):
    path = tmp_path / "konten.sqlite"
    migrate(path)

    def half_done(db, root):
        db.execute("CREATE TABLE neu (x)")
        raise RuntimeError("kaputt")

    with pytest.raises(RuntimeError, match="kaputt"):
        migrate(path, MIGRATIONS + (Migration(LATEST + 1, "kaputt", half_done),))
    assert _version(path) == LATEST
    assert "neu" not in _tables(path)


def test_database_newer_than_code_is_left_alone(tmp_path):
    path = tmp_path / "konten.sqlite"
    migrate(path)
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version = {LATEST + 5}")
    result = migrate(path)
    assert result.newer_than_code and result.after == LATEST + 5


def test_only_the_latest_backups_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(migrations, "KEEP_BACKUPS", 3)
    path = tmp_path / "konten.sqlite"
    migrate(path)
    steps = MIGRATIONS
    for n in range(5):
        steps = steps + (Migration(len(steps) + 1, f"Schritt {n}", lambda db, root: None),)
        migrate(path, steps)
    assert len(list((tmp_path / BACKUP_DIR).glob("konten-*.sqlite"))) == 3


def test_numbering_must_have_no_gaps(tmp_path):
    with pytest.raises(ValueError, match="lückenlos"):
        migrate(tmp_path / "konten.sqlite", (Migration(2, "falsch", lambda db, root: None),))


def test_cli_uses_the_storage_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PORTFOLIO_DIR", str(tmp_path))
    assert migrations.main() == 0
    assert _version(tmp_path / "konten.sqlite") == LATEST
    assert f"v0 -> v{LATEST}" in capsys.readouterr().out
