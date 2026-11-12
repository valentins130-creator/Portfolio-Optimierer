"""Passwortschutz für den Betrieb im Internet (z. B. auf Railway).

Ist die Umgebungsvariable ``APP_PASSWORD`` gesetzt, fragt die App vor allem anderen nach diesem
Passwort. Lokal ohne die Variable startet sie wie gewohnt ohne Anmeldung. Die Anmeldung gilt für
die Sitzung im Browser-Tab; nach dem Neuladen der Seite fragt die App erneut.
"""

from __future__ import annotations

import hmac
import os
import time

import streamlit as st

ENV = "APP_PASSWORD"


def allowed() -> bool:
    """True, wenn die App ohne Passwort läuft oder die Sitzung angemeldet ist; sonst Anmeldung zeigen."""
    password = os.environ.get(ENV, "")
    if not password or st.session_state.get("auth_ok"):
        return True
    _login(password)
    return False


def _login(password: str) -> None:
    st.html("""<style>
    .st-key-po_login { max-width: 26rem; margin: 4rem auto 0; padding: 2rem; background: var(--po-card);
                       border: 1px solid var(--po-line); border-radius: 12px;
                       box-shadow: 0 4px 12px var(--po-shadow), inset 0 1px 0 var(--po-edge); }
    .po-login-head .po-eyebrow { margin: 0 0 0.75rem; color: var(--po-accent-text); font-size: 0.875rem;
                                 font-weight: 500; line-height: 1.5; }
    .po-login-head h1 { margin: 0; padding: 0; color: var(--po-ink); font-size: 1.728rem; font-weight: 600;
                        line-height: 1.2; }
    .po-login-head p.po-login-text { margin: 0.75rem 0 0; color: var(--po-ink2); font-size: 1rem; line-height: 1.55; }
    .st-key-po_login [data-testid="stFormSubmitButton"] button { min-height: 48px; }
    @media (max-width: 767.98px) { .st-key-po_login { margin-top: 2rem; padding: 1.5rem; } }
    </style>""")
    with st.container(key="po_login"):
        st.html('<div class="po-login-head"><p class="po-eyebrow">Privater Zugang</p><h1>Anmelden</h1>'
                '<p class="po-login-text">Dieser Portfolio-Optimierer ist geschützt. Gib das Passwort ein, um deine '
                "Depots zu öffnen.</p></div>")
        with st.form("login", border=False):
            entered = st.text_input("Passwort", type="password", key="login_password",
                                    autocomplete="current-password")
            submitted = st.form_submit_button("Anmelden", type="primary", width="stretch")
        if submitted:
            if entered and hmac.compare_digest(entered.encode(), password.encode()):
                st.session_state["auth_ok"] = True
                st.rerun()
            time.sleep(1)  # bremst das Durchprobieren von Passwörtern
            st.error("Das Passwort passt nicht. Prüf die Schreibweise und versuch es noch einmal.")
