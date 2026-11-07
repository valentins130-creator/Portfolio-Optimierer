"""Gemeinsame Bausteine der Oberfläche: Farben, aufklappbare Abschnitte, Meldungen."""

from __future__ import annotations

import streamlit as st

from portfolio_optimizer import charts

# Dezente Akzente: Kennzahl-Kacheln und Abschnittsköpfe leicht eingefärbt, Überschriften in Blau
ACCENTS = {
    False: {"accent": "#2a78d6", "strong": "#1c5cab", "tint": "#eef4fc", "line": "#cfe0f6", "head": "#f3f7fd"},
    True: {"accent": "#5598e7", "strong": "#9ec5f4", "tint": "#1d2735", "line": "#2f4560", "head": "#202b3a"},
}


def theme() -> charts.Theme:
    try:
        dark = st.context.theme.type == "dark"
    except AttributeError:
        dark = False
    return charts.get_theme(dark)


def inject_style(th: charts.Theme) -> None:
    c = ACCENTS[th.dark]
    st.html(f"""<style>
    [data-testid="stMetric"] {{
        background: {c["tint"]}; border-left: 4px solid {c["accent"]};
        border-radius: 8px; padding: 0.55rem 0.9rem;
    }}
    [data-testid="stExpander"] details {{ border: 1px solid {c["line"]}; border-radius: 10px; }}
    [data-testid="stExpander"] summary {{ background: {c["head"]}; border-radius: 10px; }}
    [data-testid="stExpander"] summary p {{ font-weight: 600; font-size: 1.05rem; color: {c["strong"]}; }}
    [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {{ color: {c["accent"]}; }}
    h1, h2, h3, h4 {{ color: {c["strong"]}; }}
    [data-testid="stMainBlockContainer"] {{ padding-top: 4.5rem; }}
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
        st.toast(text, icon="✅" if kind == "success" else "⚠️")
