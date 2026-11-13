"""Konten in der Oberfläche: Anmelden, Konto erstellen, angemeldet bleiben, Abmelden, Konto löschen.

Eingeschaltet über die Umgebungsvariable ``ACCOUNTS=on`` (im Dockerfile gesetzt, also auf Railway an).
Lokal ohne die Variable startet die App wie bisher ohne Anmeldung, mit den Depots im Ordner
``portfolios``. Mit Konten liegen die Depots je Nutzer getrennt (``nutzer/<id>`` im Speicherordner).

„Angemeldet bleiben“: Der Browser bekommt ein zufälliges Token als Cookie; die Datenbank kennt nur
dessen Hash. Abmelden oder Konto löschen macht das Token sofort ungültig.
"""

from __future__ import annotations

import os
import shutil

import streamlit as st
import streamlit.components.v1 as components

from portfolio_optimizer.accounts import SESSION_DAYS, Account, AccountError, AccountStore
from ui.state import _root, user_root

COOKIE = "po_session"


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
        components.html(f"<script>document.cookie = '{COOKIE}={token}; Max-Age={age}; Path=/; "
                        f"SameSite=Lax{secure}';</script>", height=0)


def _https() -> bool:
    headers = st.context.headers
    proto = (headers.get("X-Forwarded-Proto") or "").lower() if headers else ""
    origin = (headers.get("Origin") or "") if headers else ""
    return proto == "https" or origin.startswith("https://")


# ---------------------------------------------------------------------------
# Anmelden und Konto erstellen
# ---------------------------------------------------------------------------


def panel() -> None:
    """Karte mit „Anmelden“ und „Konto erstellen“ (Startseite für Abgemeldete)."""
    st.html("""<style>
    .st-key-card_auth .po-auth-title { margin: 0; color: var(--po-ink); font-size: 1.5rem; font-weight: 600;
                                      line-height: 1.2; letter-spacing: -0.02em; }
    .st-key-card_auth .po-auth-text { margin: 0.5rem 0 0; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.5; }
    .st-key-card_auth [data-testid="stFormSubmitButton"] button { min-height: 48px; }
    </style>""")
    with st.container(key="card_auth"):
        mode = st.segmented_control("Konto", ["Anmelden", "Konto erstellen"], default="Anmelden", key="auth_mode",
                                    required=True, label_visibility="collapsed") or "Anmelden"
        if mode == "Anmelden":
            st.html('<p class="po-auth-title">Willkommen zurück</p>'
                    '<p class="po-auth-text">Melde dich an, um deine Depots zu öffnen.</p>')
            _login_form()
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
        st.markdown(f"Angemeldet als  \n**{account.email}**")
        if st.button("Abmelden", icon=":material/logout:", width="stretch", key="sign_out"):
            sign_out()
            st.rerun()
        st.divider()
        if st.button("Konto löschen …", type="tertiary", key="delete_account"):
            st.session_state["confirm_delete"] = True
    if st.session_state.get("confirm_delete"):  # bleibt offen, bis bestätigt oder abgebrochen
        _confirm_delete(account)
