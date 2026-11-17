"""Konten für den Betrieb als Website: Registrierung, Anmeldung, Sitzungen, Passwort vergessen.

Gespeichert wird in einer SQLite-Datei (auf Railway im Volume). Passwörter liegen nie im Klartext
vor, nur als scrypt-Hash mit zufälligem Salz. Für „Angemeldet bleiben“ bekommt der Browser ein
zufälliges Token; gespeichert wird davon nur der SHA-256-Wert. Nach mehreren Fehlversuchen wird
eine E-Mail-Adresse für eine Viertelstunde gesperrt. Links für ein neues Passwort gelten eine
Stunde und nur einmal; auch von ihnen liegt nur der Hash in der Datenbank.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from portfolio_optimizer.migrations import migrate

MIN_PASSWORD = 10
SESSION_DAYS = 30
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
RESET_MINUTES = 60  # so lange gilt ein Link für ein neues Passwort
RESET_PER_HOUR = 3  # höchstens so viele Links je Konto und Stunde
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

class AccountError(ValueError):
    """Fehler mit einer Meldung, die so in der Oberfläche erscheinen kann."""


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    created: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        salt_bytes, digest_bytes = base64.b64decode(salt), base64.b64decode(digest)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    calc = hashlib.scrypt(password.encode("utf-8"), salt=salt_bytes, n=int(n), r=int(r), p=int(p),
                          dklen=len(digest_bytes))
    return hmac.compare_digest(calc, digest_bytes)


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # gleiche Rechenzeit, wenn es die E-Mail nicht gibt


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountStore:
    """Konten und Sitzungen in einer SQLite-Datei."""

    def __init__(self, path: Path):
        self.path = Path(path)
        migrate(self.path)  # Tabellen anlegen oder auf den neuesten Stand bringen (portfolio_optimizer/migrations.py)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- Konten -------------------------------------------------------------

    def register(self, email: str, password: str) -> Account:
        email = normalize_email(email)
        if not _EMAIL.match(email):
            raise AccountError("Gib eine E-Mail-Adresse wie name@beispiel.de ein.")
        if len(password) < MIN_PASSWORD:
            raise AccountError(f"Wähle ein Passwort mit mindestens {MIN_PASSWORD} Zeichen.")
        account = Account(uuid.uuid4().hex, email, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        try:
            with self._db() as db:
                db.execute("INSERT INTO users (id, email, password, created) VALUES (?, ?, ?, ?)",
                           (account.id, account.email, hash_password(password), account.created))
        except sqlite3.IntegrityError:
            raise AccountError("Für diese E-Mail gibt es schon ein Konto. Melde dich damit an.") from None
        return account

    def authenticate(self, email: str, password: str, now: float | None = None) -> Account:
        email = normalize_email(email)
        now = time.time() if now is None else now
        with self._db() as db:  # Fehlversuch erst speichern, dann melden (sonst ginge er beim Abbruch verloren)
            # abgelaufene Fehlversuche aller Adressen löschen: sie zählen nicht mehr (Datenschutzerklärung)
            db.execute("DELETE FROM failures WHERE at <= ?", (now - LOCK_SECONDS,))
            db.execute("DELETE FROM resets WHERE expires < ?", (now,))  # abgelaufene Links (Datenschutzerklärung)
            failures = db.execute("SELECT COUNT(*) FROM failures WHERE email = ? AND at > ?",
                                  (email, now - LOCK_SECONDS)).fetchone()[0]
            locked = failures >= MAX_FAILURES
            row = None if locked else db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            ok = not locked and verify_password(password, row["password"] if row else _DUMMY_HASH) and row is not None
            if ok:
                db.execute("DELETE FROM failures WHERE email = ?", (email,))
            elif not locked:
                db.execute("INSERT INTO failures (email, at) VALUES (?, ?)", (email, now))
        if locked:
            raise AccountError("Zu viele Fehlversuche. Versuch es in 15 Minuten noch einmal.")
        if not ok:
            raise AccountError("E-Mail oder Passwort stimmen nicht. Prüf beides und versuch es noch einmal.")
        return Account(row["id"], row["email"], row["created"])

    def get(self, user_id: str) -> Account | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return Account(row["id"], row["email"], row["created"]) if row else None

    def delete(self, user_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM resets WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # -- Sitzungen für „Angemeldet bleiben“ -----------------------------------

    def create_session(self, user_id: str, days: int = SESSION_DAYS, now: float | None = None) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time() if now is None else now
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
            db.execute("INSERT INTO sessions (token_hash, user_id, expires) VALUES (?, ?, ?)",
                       (_token_hash(token), user_id, now + days * 86400))
        return token

    def session_user(self, token: str, now: float | None = None) -> Account | None:
        if not token:
            return None
        now = time.time() if now is None else now
        with self._db() as db:
            row = db.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires > ?",
                (_token_hash(token), now)).fetchone()
        return Account(row["id"], row["email"], row["created"]) if row else None

    def end_session(self, token: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    # -- Passwort vergessen ---------------------------------------------------

    def create_reset(self, email: str, now: float | None = None) -> tuple[Account, str] | None:
        """Einmal-Link für ein neues Passwort: (Konto, Token) oder None.

        None, wenn es zu der Adresse kein Konto gibt oder in der letzten Stunde schon
        ``RESET_PER_HOUR`` Links angefordert wurden. Die Oberfläche antwortet in beiden Fällen
        gleich, damit sich nicht herausfinden lässt, welche Adressen ein Konto haben.
        """
        email = normalize_email(email)
        now = time.time() if now is None else now
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM resets WHERE expires < ?", (now,))
            recent = db.execute("SELECT COUNT(*) FROM resets WHERE user_id = ? AND created > ?",
                                (row["id"], now - 3600)).fetchone()[0]
            if recent >= RESET_PER_HOUR:
                return None
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO resets (token_hash, user_id, created, expires) VALUES (?, ?, ?, ?)",
                       (_token_hash(token), row["id"], now, now + RESET_MINUTES * 60))
        return Account(row["id"], row["email"], row["created"]), token

    def reset_account(self, token: str, now: float | None = None) -> Account | None:
        """Konto zu einem Link, solange er gilt (nicht abgelaufen, noch nicht benutzt)."""
        if not token:
            return None
        now = time.time() if now is None else now
        with self._db() as db:
            row = db.execute(
                "SELECT u.* FROM resets r JOIN users u ON u.id = r.user_id WHERE r.token_hash = ? AND r.expires > ?",
                (_token_hash(token), now)).fetchone()
        return Account(row["id"], row["email"], row["created"]) if row else None

    def reset_password(self, token: str, password: str, now: float | None = None) -> Account:
        """Neues Passwort über den Link setzen.

        Danach gilt keiner der Links mehr, gemerkte Anmeldungen auf anderen Geräten enden und
        eine Sperre nach Fehlversuchen ist aufgehoben.
        """
        if len(password) < MIN_PASSWORD:
            raise AccountError(f"Wähle ein Passwort mit mindestens {MIN_PASSWORD} Zeichen.")
        account = self.reset_account(token, now)
        if account is None:
            raise AccountError("Der Link ist abgelaufen oder wurde schon benutzt. Fordere einen neuen an.")
        with self._db() as db:
            db.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(password), account.id))
            db.execute("DELETE FROM resets WHERE user_id = ?", (account.id,))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (account.id,))
            db.execute("DELETE FROM failures WHERE email = ?", (account.email,))
        return account
