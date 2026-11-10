"""Gemeinsame Bausteine der Oberfläche: Farbwelt, aufklappbare Abschnitte, Meldungen."""

from __future__ import annotations

import streamlit as st

from portfolio_optimizer import charts

# Farbwelt: warmes Papier, Karten in fast Weiß, Navy als Akzent, Gold nur für Bildmarke und
# Abschnittssymbole. Daten tragen die geprüfte Diagrammpalette (charts.py), Texte nie Datenfarben.
TOKENS = {
    "paper": "#f5f3ee", "card": "#fcfbf8", "line": "#e4dfd4", "ink": "#16191d", "ink2": "#52514e",
    "muted": "#898781", "navy": "#1f3a5f", "gold": "#b8892f", "up": "#006300", "down": "#c4312f",
}


def theme() -> charts.Theme:
    """Diagrammfarben; die App ist bewusst immer hell (siehe .streamlit/config.toml)."""
    return charts.get_theme(False)


def inject_style() -> None:
    t = TOKENS
    st.html(f"""<style>
    :root {{ --po-card: {t["card"]}; --po-line: {t["line"]}; --po-ink: {t["ink"]}; --po-ink2: {t["ink2"]};
             --po-muted: {t["muted"]}; --po-navy: {t["navy"]}; --po-gold: {t["gold"]}; --po-up: {t["up"]};
             --po-down: {t["down"]}; }}
    header[data-testid="stHeader"] {{ background: rgba(245, 243, 238, 0.94); border-bottom: 1px solid var(--po-line); }}
    [data-testid="stTopNavLink"] p {{ font-weight: 500; }}
    [data-testid="stMainBlockContainer"] {{ padding-top: 4.4rem; padding-bottom: 4rem; max-width: 1240px; }}

    /* Abschnitte als ruhige Karten */
    [data-testid="stExpander"] details {{
        background: var(--po-card); border: 1px solid var(--po-line); border-radius: 12px;
        box-shadow: 0 1px 2px rgba(22, 25, 29, 0.04);
    }}
    [data-testid="stExpander"] summary {{ padding-top: 0.85rem; padding-bottom: 0.85rem; }}
    [data-testid="stExpander"] summary p {{ font-weight: 600; font-size: 1.02rem; color: var(--po-ink); }}
    [data-testid="stExpander"] summary:hover p {{ color: var(--po-navy); }}
    [data-testid="stExpanderIcon"] {{ color: var(--po-gold); }}

    /* Kennzahlen: Karte, ruhige Beschriftung, kräftige Zahl */
    [data-testid="stMetric"] {{
        background: #ffffff; border: 1px solid var(--po-line); border-radius: 12px; padding: 0.8rem 1rem 0.7rem;
    }}
    [data-testid="stMetricLabel"] p {{ color: var(--po-ink2); font-size: 0.86rem; }}
    [data-testid="stMetricValue"] > div {{ font-weight: 600; letter-spacing: -0.01em; }}

    /* Depotwert oben auf der Portfolio-Seite */
    .po-hero {{ margin: 0.2rem 0 0.4rem; }}
    .po-hero .po-label {{ color: var(--po-ink2); font-size: 0.92rem; }}
    .po-hero .po-value {{ color: var(--po-ink); font-size: 3.2rem; font-weight: 600; line-height: 1.12;
                         letter-spacing: -0.02em; }}
    .po-hero .po-sub {{ color: var(--po-ink2); font-size: 0.95rem; margin-top: 0.3rem; }}
    .po-hero .po-sub span + span::before {{ content: "·"; color: var(--po-muted); margin: 0 0.55rem; }}
    .po-up {{ color: var(--po-up); font-weight: 600; }}
    .po-down {{ color: var(--po-down); font-weight: 600; }}

    h1, h2, h3, h4 {{ color: var(--po-ink); letter-spacing: -0.01em; }}
    </style>""")


# Eingaben der Seiten, die beim Wechsel zwischen Portfolio, Analysen und Lösungen erhalten bleiben
# (nicht das Anfangskapital der Simulation: es folgt dem Depotwert des gewählten Portfolios)
PERSISTENT_KEYS = ("sec_", "lim_", "mc_portfolio", "mc_method", "mc_contribution", "mc_years", "mc_paths",
                   "mc_target", "mc_seed", "sens_", "exp_", "frontier_", "rb_", "hedge_", "mix_", "pf_dim",
                   "corr_table", "cluster_table", "error_table", "tx_mode", "tx_kind", "tx_date", "tx_shares",
                   "tx_price", "tx_query")


def keep_page_state() -> None:
    """Zustand der Seiten-Widgets über Seitenwechsel hinweg behalten.

    Streamlit vergisst Widgets, die in einem Durchlauf nicht gezeichnet werden – beim Wechsel
    der Ebene also aufgeklappte Abschnitte und Eingaben der anderen Seiten. Zurückgeschrieben
    werden sie zu gewöhnlichen Sitzungswerten, die erhalten bleiben. Widgets mit datenabhängigen
    Optionen prüfen ihren Wert vor dem Zeichnen selbst.
    """
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith(PERSISTENT_KEYS):
            st.session_state[key] = st.session_state[key]


def delta(diff: float, text: str, inverse: bool = False, tol: float = 5e-4) -> dict:
    """Argumente für ``st.metric``: Abweichungen um null erscheinen grau, ohne Pfeil und mit ±."""
    if abs(diff) < tol:
        return {"delta": "±" + text.lstrip("+-−"), "delta_color": "off", "delta_arrow": "off"}
    return {"delta": text, "delta_color": "inverse" if inverse else "normal"}


def show_chart(fig) -> None:
    st.plotly_chart(fig, theme=None, config={"displaylogo": False})


def section(label: str, key: str, expanded: bool = False, icon: str | None = None):
    """Aufklappbarer Abschnitt; sein Inhalt wird nur gerechnet, solange er geöffnet ist."""
    box = st.expander(label, expanded=expanded, key=key, icon=icon, on_change="rerun")
    return box if box.open else None


def flash(message: str, kind: str = "success") -> None:
    """Meldung für den nächsten Durchlauf merken (Callbacks laufen vor dem Neuzeichnen)."""
    st.session_state["flash"] = (message, kind)


def show_flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        text, kind = message
        st.toast(text, icon=":material/check_circle:" if kind == "success" else ":material/error:")
