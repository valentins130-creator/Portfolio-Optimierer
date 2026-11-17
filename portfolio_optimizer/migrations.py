"""Versionierte Migrationen für den Datenspeicher: Konten-Datenbank und Dateien im Speicherordner.

Den erreichten Stand merkt sich die Konten-Datenbank (``PRAGMA user_version``). Im Container läuft
``python -m portfolio_optimizer.migrations`` vor dem Start der App (siehe ``Dockerfile``):

1. Stehen Migrationen aus, wird die Datenbank vorher nach ``backups/`` im Speicherordner gesichert;
   die letzten ``KEEP_BACKUPS`` Sicherungen bleiben liegen.
2. Alle ausstehenden Schritte laufen in einer Transaktion. Schlägt einer fehl, bleibt der alte Stand
   erhalten und der Start bricht ab, sodass Railway das Deployment als fehlgeschlagen meldet.
3. Ist die Datenbank neuer als der Code (Rollback auf ein älteres Deployment), bleibt sie unverändert.

Neue Migration: Funktion ``_v<n>`` schreiben und hinten an ``MIGRATIONS`` anhängen. Bestehende
Migrationen nie ändern, sie sind auf dem Server schon gelaufen. Die Schritte bekommen die Verbindung
und den Speicherordner, können also auch Depot-Dateien (``nutzer/<id>/*.json``) umbauen.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

DB_NAME = "konten.sqlite"
BACKUP_DIR = "backups"
KEEP_BACKUPS = 10


def data_dir() -> Path:
    """Speicherordner: ``PORTFOLIO_DIR``, sonst das Railway-Volume, sonst ``portfolios`` neben der App."""
    folder = os.environ.get("PORTFOLIO_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    return Path(folder) if folder else Path(__file__).resolve().parents[1] / "portfolios"


@dataclass(frozen=True)
class Migration:
    version: int
    title: str
    apply: Callable[[sqlite3.Connection, Path], None]


@dataclass(frozen=True)
class Result:
    before: int
    after: int
    backup: Path | None = None
    newer_than_code: bool = False


# -- Migrationen ------------------------------------------------------------
# Kein executescript: es schließt die laufende Transaktion ab, ein Fehler ließe sich nicht zurückrollen.


def _v1(db: sqlite3.Connection, root: Path) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        created TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        expires REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS failures (
        email TEXT NOT NULL,
        at REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS failures_email ON failures (email)")


def _v2(db: sqlite3.Connection, root: Path) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS resets (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created REAL NOT NULL,
        expires REAL NOT NULL)""")


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "Konten, Sitzungen und Fehlversuche", _v1),
    Migration(2, "Links für ein neues Passwort", _v2),
)


# -- Ablauf -----------------------------------------------------------------


def _version(db: sqlite3.Connection) -> int:
    return db.execute("PRAGMA user_version").fetchone()[0]


def _has_tables(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0


def _backup(db: sqlite3.Connection, folder: Path, version: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target = folder / f"konten-{stamp}-v{version}.sqlite"
    copy = sqlite3.connect(target)
    try:
        db.backup(copy)  # Backup-API: konsistent, auch wenn die App gerade liest
    finally:
        copy.close()
    for old in sorted(folder.glob("konten-*.sqlite"))[:-KEEP_BACKUPS]:
        old.unlink()
    return target


def migrate(db_path: Path, migrations: tuple[Migration, ...] = MIGRATIONS) -> Result:
    """Bringt die Datenbank unter ``db_path`` auf den neuesten Stand und gibt alten und neuen Stand zurück."""
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise ValueError(f"Migrationen müssen lückenlos ab 1 nummeriert sein, gefunden: {versions}")
    latest = versions[-1] if versions else 0
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path, timeout=30, isolation_level=None)  # Transaktionen von Hand
    try:
        current = _version(db)
        if current >= latest:
            return Result(current, current, newer_than_code=current > latest)
        # vor der Sperre sichern: innerhalb der eigenen Schreibsperre würde die Backup-API blockieren
        backup = _backup(db, db_path.parent / BACKUP_DIR, current) if _has_tables(db) else None
        db.execute("BEGIN IMMEDIATE")
        try:
            current = _version(db)  # ein zweiter Prozess kann inzwischen migriert haben
            for step in migrations:
                if step.version > current:
                    step.apply(db, db_path.parent)
            db.execute(f"PRAGMA user_version = {max(current, latest)}")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return Result(current, max(current, latest), backup)
    finally:
        db.close()


def main() -> int:
    path = data_dir() / DB_NAME
    latest = MIGRATIONS[-1].version
    result = migrate(path)
    if result.newer_than_code:
        print(f"Migration: Datenstand v{result.before} ist neuer als der Code (v{latest}), nichts geändert.")
    elif result.before == result.after:
        print(f"Migration: Datenstand v{result.after} ist aktuell ({path}).")
    else:
        saved = f", Sicherung {result.backup}" if result.backup else ""
        print(f"Migration: v{result.before} -> v{result.after} ({path}{saved}).")  # ASCII: jede Konsole
    return 0


if __name__ == "__main__":
    sys.exit(main())
