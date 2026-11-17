"""Konten in der Oberfläche: Anmelden, Konto erstellen, angemeldet bleiben, Abmelden, Konto löschen.

Eingeschaltet über die Umgebungsvariable ``ACCOUNTS=on`` (im Dockerfile gesetzt, also auf Railway an).
Lokal ohne die Variable startet die App wie bisher ohne Anmeldung, mit den Depots im Ordner
``portfolios``. Mit Konten liegen die Depots je Nutzer getrennt (``nutzer/<id>`` im Speicherordner).

„Angemeldet bleiben“: Der Browser bekommt ein zufälliges Token als Cookie; die Datenbank kennt nur
dessen Hash. Abmelden oder Konto löschen macht das Token sofort ungültig.

„Passwort vergessen“: Ein Einmal-Link per E-Mail (``portfolio_optimizer/mailer.py``) führt über
``?reset=…`` zum Formular für das neue Passwort. Ist kein Versand eingerichtet, steht der Link im
Server-Log, damit der Betreiber weiterhelfen kann.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from html import escape

import streamlit as st

from portfolio_optimizer import mailer
from portfolio_optimizer.accounts import RESET_MINUTES, SESSION_DAYS, Account, AccountError, AccountStore
from ui.state import _root, user_root

COOKIE = "po_session"
log = logging.getLogger(__name__)


def enabled() -> bool:
    return os.environ.get("ACCOUNTS", "").strip().lower() in ("1", "on", "true", "ja", "yes")


@st.cache_resource(show_spinner=False)
def _store(path: str) -> AccountStore:
    return AccountStore(path)


def store() -> AccountStore:
    return _store(str(_root() / "konten.sqlite"))


def current_user() -> Account | None:
    """Angemeldetes Konto der Sitzung; nach dem Neuladen über das Cookie wiederhergestellt."""
    user = st.session_state.get("user")
    if user is not None or not enabled():
        return user
    if not st.session_state.get("_cookie_checked"):
        st.session_state["_cookie_checked"] = True
        token = st.context.cookies.get(COOKIE)
        account = store().session_user(token) if isinstance(token, str) and token else None
        if account is not None:
            st.session_state["user"] = account
            st.session_state["_token"] = token
            return account
    return None


def _sign_in(account: Account, remember: bool) -> None:
    st.session_state["user"] = account
    if remember:
        token = store().create_session(account.id)
        st.session_state["_token"] = token
        st.session_state["_cookie"] = ("set", token)


def sign_out() -> None:
    token = st.session_state.get("_token")
    if token:
        store().end_session(token)
    st.session_state.clear()
    st.session_state["_cookie_checked"] = True  # das alte Cookie gilt nicht mehr
    st.session_state["_cookie"] = ("clear", "")


def sync_cookie() -> None:
    """Gemerktes Cookie setzen oder löschen. Läuft in einem unsichtbaren Rahmen derselben Seite."""
    pending = st.session_state.pop("_cookie", None)
    if not pending:
        return
    action, token = pending
    secure = "; Secure" if _https() else ""
    age = SESSION_DAYS * 86400 if action == "set" else 0
    with st.container(key="po_cookie"):
        st.iframe(f"<script>document.cookie = '{COOKIE}={token}; Max-Age={age}; Path=/; "
                  f"SameSite=Lax{secure}';</script>", width=1, height=1, tab_index=-1)


def _https() -> bool:
    headers = st.context.headers
    proto = (headers.get("X-Forwarded-Proto") or "").lower() if headers else ""
    origin = (headers.get("Origin") or "") if headers else ""
    return proto == "https" or origin.startswith("https://")


# ---------------------------------------------------------------------------
# Anmelden und Konto erstellen
# ---------------------------------------------------------------------------


def reset_token() -> str:
    """Token aus dem Link „Neues Passwort“ (``?reset=…``), sonst leer."""
    token = st.query_params.get("reset", "")
    return token if isinstance(token, str) else ""


def _set_forgot(value: bool) -> None:
    st.session_state["auth_forgot"] = value
    if value:  # die schon eingegebene Adresse übernehmen
        st.session_state["forgot_email"] = st.session_state.get("login_email", "")


def panel() -> None:
    """Karte mit „Anmelden“ und „Konto erstellen“ (Startseite für Abgemeldete).

    Über den Link aus der E-Mail zeigt sie stattdessen das Formular für ein neues Passwort, nach
    „Passwort vergessen?“ das Formular für den Link.
    """
    st.html("""<style>
    .st-key-card_auth .po-auth-title { margin: 0; color: var(--po-ink); font-size: 1.5rem; font-weight: 600;
                                      line-height: 1.2; letter-spacing: -0.02em; }
    .st-key-card_auth .po-auth-text { margin: 0.5rem 0 0; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.5;
                                      overflow-wrap: anywhere; }
    .st-key-card_auth [data-testid="stFormSubmitButton"] button { min-height: 48px; }
    </style>""")
    with st.container(key="card_auth"):
        if reset_token():
            _new_password_form(reset_token())
            return
        if st.session_state.get("auth_forgot"):
            _forgot_form()
            return
        mode = st.segmented_control("Konto", ["Anmelden", "Konto erstellen"], default="Anmelden", key="auth_mode",
                                    required=True, label_visibility="collapsed") or "Anmelden"
        if mode == "Anmelden":
            st.html('<p class="po-auth-title">Willkommen zurück</p>'
                    '<p class="po-auth-text">Melde dich an, um deine Depots zu öffnen.</p>')
            _login_form()
            st.button("Passwort vergessen?", type="tertiary", key="forgot_open", on_click=_set_forgot, args=(True,))
        else:
            st.html('<p class="po-auth-title">Konto erstellen</p>'
                    '<p class="po-auth-text">Kostenlos. Deine Depots sieht nur dein Konto.</p>')
            _register_form()


def _login_form() -> None:
    with st.form("login", border=False):
        email = st.text_input("E-Mail", key="login_email", autocomplete="email", placeholder="name@beispiel.de")
        password = st.text_input("Passwort", type="password", key="login_password", autocomplete="current-password")
        remember = st.checkbox("Angemeldet bleiben", value=True, key="login_remember",
                               help=f"Auf diesem Gerät {SESSION_DAYS} Tage lang, bis du dich abmeldest.")
        submitted = st.form_submit_button("Anmelden", type="primary", width="stretch")
    if submitted:
        if not email.strip() or not password:
            st.error("Gib E-Mail und Passwort ein.")
            return
        try:
            account = store().authenticate(email, password)
        except AccountError as exc:
            st.error(str(exc))
            return
        _sign_in(account, remember)
        st.rerun()


def _register_form() -> None:
    with st.form("register", border=False):
        email = st.text_input("E-Mail", key="register_email", autocomplete="email", placeholder="name@beispiel.de")
        password = st.text_input("Passwort", type="password", key="register_password", autocomplete="new-password",
                                 help="Mindestens 10 Zeichen. Ein Satz aus mehreren Wörtern ist sicher und gut zu merken.")
        remember = st.checkbox("Angemeldet bleiben", value=True, key="register_remember")
        st.caption("Mit dem Konto gilt die Datenschutzerklärung unten auf dieser Seite.")
        submitted = st.form_submit_button("Konto erstellen", type="primary", width="stretch")
    if submitted:
        try:
            account = store().register(email, password)
        except AccountError as exc:
            st.error(str(exc))
            return
        _sign_in(account, remember)
        st.session_state["flash"] = ("Konto erstellt. Lege jetzt dein erstes Depot an.", "success")
        st.rerun()


# ---------------------------------------------------------------------------
# Passwort vergessen
# ---------------------------------------------------------------------------


def _forgot_form() -> None:
    st.html('<p class="po-auth-title">Passwort vergessen</p>'
            '<p class="po-auth-text">Gib die E-Mail-Adresse deines Kontos ein. Du bekommst einen Link, mit dem du '
            f"ein neues Passwort festlegst. Er gilt {RESET_MINUTES} Minuten.</p>")
    with st.form("forgot", border=False):
        email = st.text_input("E-Mail", key="forgot_email", autocomplete="email", placeholder="name@beispiel.de")
        submitted = st.form_submit_button("Link senden", type="primary", width="stretch")
    if submitted:
        _request_reset(email.strip())
    st.button("Zurück zur Anmeldung", type="tertiary", key="forgot_close", on_click=_set_forgot, args=(False,))


def _request_reset(email: str) -> None:
    if not email:
        st.error("Gib die E-Mail-Adresse deines Kontos ein.")
        return
    result = store().create_reset(email)
    if result is not None:
        account, token = result
        # im Hintergrund: Die Antwort kommt gleich schnell, ob es das Konto gibt oder nicht
        _in_background(_deliver, account.email, _reset_link(token))
    if mailer.configured():
        st.success(f"Wenn es zu {email} ein Konto gibt, ist jetzt ein Link unterwegs. Schau auch im Spam-Ordner nach.")
    else:
        st.warning("Der E-Mail-Versand ist auf diesem Server noch nicht eingerichtet. Wende dich bitte an den "
                   "Betreiber, die Adresse steht im Impressum.")


def _in_background(task, *args) -> None:
    threading.Thread(target=task, args=args, daemon=True).start()


def _deliver(to: str, link: str) -> None:
    try:
        mailer.send(to, "Neues Passwort für den Portfolio-Optimierer", _reset_mail(link))
    except mailer.MailError as exc:  # der Betreiber findet den Link dann im Server-Log
        log.warning("Link für ein neues Passwort nicht verschickt (%s). Link für %s: %s", exc, to, link)


def _reset_link(token: str) -> str:
    """Adresse der Website aus ``APP_URL``, sonst aus der Anfrage (Host)."""
    base = os.environ.get("APP_URL", "").strip().rstrip("/")
    if not base:
        host = (st.context.headers.get("Host") if st.context.headers else None) or "localhost:8501"
        base = f"{'https' if _https() else 'http'}://{host}"
    return f"{base}/?reset={token}"


def _reset_mail(link: str) -> str:
    return ("Hallo,\n\n"
            "für dein Konto beim Portfolio-Optimierer wurde ein neues Passwort angefordert. "
            "Über diesen Link legst du es fest:\n\n"
            f"{link}\n\n"
            f"Der Link gilt {RESET_MINUTES} Minuten und nur einmal. Hast du nichts angefordert, ignoriere diese "
            "E-Mail; dein Passwort bleibt dann unverändert.\n")


def _new_password_form(token: str) -> None:
    account = store().reset_account(token)
    if account is None:
        st.html('<p class="po-auth-title">Link abgelaufen</p>'
                '<p class="po-auth-text">Dieser Link ist abgelaufen oder wurde schon benutzt. Fordere einfach '
                "einen neuen an.</p>")
        if st.button("Neuen Link anfordern", type="primary", width="stretch", key="reset_again"):
            st.query_params.clear()
            _set_forgot(True)
            st.rerun()
        return
    st.html('<p class="po-auth-title">Neues Passwort</p>'
            f'<p class="po-auth-text">Für {escape(account.email)}. Danach bist du angemeldet, gemerkte '
            "Anmeldungen auf anderen Geräten enden.</p>")
    with st.form("reset", border=False):
        password = st.text_input("Neues Passwort", type="password", key="reset_password", autocomplete="new-password",
                                 help="Mindestens 10 Zeichen. Ein Satz aus mehreren Wörtern ist sicher und gut zu merken.")
        remember = st.checkbox("Angemeldet bleiben", value=True, key="reset_remember")
        submitted = st.form_submit_button("Passwort speichern", type="primary", width="stretch")
    if submitted:
        try:
            account = store().reset_password(token, password)
        except AccountError as exc:
            st.error(str(exc))
            return
        st.query_params.clear()
        _sign_in(account, remember)
        st.session_state["flash"] = ("Neues Passwort gespeichert. Du bist angemeldet.", "success")
        st.rerun()


# ---------------------------------------------------------------------------
# Konto-Menü in der Kopfzeile
# ---------------------------------------------------------------------------


def _close_delete() -> None:
    st.session_state.pop("confirm_delete", None)


@st.dialog("Konto löschen", on_dismiss=_close_delete)
def _confirm_delete(account: Account) -> None:
    st.html("""<style>.st-key-delete_confirm button { background: var(--po-down) !important;
               border-color: var(--po-down) !important; }</style>""")
    st.markdown(f"**Konto {account.email} löschen?**")
    st.write("Alle Depots, Transaktionen und Einstellungen dieses Kontos werden endgültig gelöscht. "
             "Das lässt sich nicht rückgängig machen.")
    cancel, delete = st.columns(2)
    if cancel.button("Abbrechen", width="stretch", key="delete_cancel"):
        _close_delete()
        st.rerun()
    if delete.button("Konto löschen", type="primary", width="stretch", key="delete_confirm",
                     icon=":material/delete_forever:"):
        folder = user_root(account)
        store().delete(account.id)
        if folder.is_dir() and folder.parent.name == "nutzer":
            shutil.rmtree(folder)
        sign_out()
        st.session_state["flash"] = ("Dein Konto und alle Depots sind gelöscht.", "success")
        st.rerun()


def account_menu(account: Account) -> None:
    with st.popover("Konto", icon=":material/account_circle:"):
        with st.container(key="account_email"):
            st.markdown(f"Angemeldet als  \n**{account.email}**")
        if st.button("Abmelden", icon=":material/logout:", width="stretch", key="sign_out"):
            sign_out()
            st.rerun()
        st.divider()
        if st.button("Konto löschen …", type="tertiary", key="delete_account"):
            st.session_state["confirm_delete"] = True
    if st.session_state.get("confirm_delete"):  # bleibt offen, bis bestätigt oder abgebrochen
        _confirm_delete(account)
