"""Gemeinsame Bausteine der Oberfläche: Farbwelt, aufklappbare Abschnitte, Meldungen."""

from __future__ import annotations

import streamlit as st

from portfolio_optimizer import charts

# Farbwelt: warmes Off-White, Karten eine Stufe heller, Tiefblau für Aktionen, dezentes Orange für
# Hinweise und Abschnittssymbole. Jede Farbe gilt für hell und dunkel: Streamlit setzt das
# Farbschema (color-scheme) der App, light-dark() wählt daraus den passenden Wert. Daten tragen die
# geprüfte Diagrammpalette (charts.py), Texte nie Datenfarben.
TOKENS = {
    "bg": ("#f8f5ef", "#0c1222"),
    "card": ("#fffdf9", "#141c30"),
    "sunken": ("#f1ece3", "#10172a"),
    "line": ("rgb(19 32 61 / 0.10)", "rgb(237 240 246 / 0.12)"),
    "line-strong": ("rgb(19 32 61 / 0.20)", "rgb(237 240 246 / 0.22)"),
    "ink": ("#13203d", "#edf0f6"),
    "ink2": ("#46516a", "#b6bece"),
    "muted": ("#5f687c", "#949eb2"),
    "primary": ("#1e3f8f", "#a3b8ff"),
    "on-primary": ("#ffffff", "#0c1222"),
    "accent": ("#c8601f", "#d6762f"),
    "accent-text": ("#a84a12", "#f5ab70"),
    "up": ("#1f7a4f", "#6fd3a0"),
    "down": ("#b3261e", "#ff8a80"),
    "shadow": ("rgb(19 32 61 / 0.05)", "transparent"),
    "edge": ("transparent", "rgb(255 255 255 / 0.05)"),
    # Balken der Startseite (Palette mit dem dataviz-Validator geprüft)
    "chart-ok": ("#2f5bc4", "#6f8ff0"),
    "chart-warn": ("#c8601f", "#d6762f"),
    "chart-track": ("#e3e8f2", "#26324f"),
    "chart-muted": ("#8f8a80", "#707a90"),
}


def is_dark() -> bool:
    return st.context.theme.type == "dark"


def theme() -> charts.Theme:
    """Diagrammfarben passend zum hellen oder dunklen Design der App."""
    return charts.get_theme(is_dark())


def css_tokens() -> str:
    return " ".join(f"--po-{name}: light-dark({light}, {dark});" for name, (light, dark) in TOKENS.items())


def inject_style() -> None:
    st.html(f"""<style>
    .stApp {{ {css_tokens()} }}
    header[data-testid="stHeader"] {{
        background: color-mix(in srgb, var(--po-bg) 94%, transparent); border-bottom: 1px solid var(--po-line);
    }}
    /* Bildmarke als Bild, Name als echter Text: so bleibt er im dunklen Design lesbar */
    /* Auf der Startseite steckt das Logo in einem div, auf den Ebenen in einem Button zur Startseite */
    :has(> img[data-testid="stHeaderLogo"]) {{
        display: flex; align-items: center; gap: 0.75rem; width: auto !important; max-width: none !important;
    }}
    :has(> img[data-testid="stHeaderLogo"])::after {{
        content: "Portfolio-Optimierer"; color: var(--po-ink); font-weight: 600; font-size: 1.05rem;
        white-space: nowrap;
    }}
    @media (max-width: 767.98px) {{  /* schmal: nur die Bildmarke, damit das Menü oben rechts sichtbar bleibt */
        :has(> img[data-testid="stHeaderLogo"])::after {{ display: none; }}
    }}
    [data-testid="stTopNavLink"] p {{ font-weight: 500; }}
    /* Schrift auf dem Hauptbutton: weiß auf Tiefblau, im dunklen Design dunkel auf Hellblau */
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] p {{ color: var(--po-on-primary); }}
    [data-testid="stMainBlockContainer"] {{ padding-top: 4.5rem; padding-bottom: 4rem; max-width: 1240px; }}

    /* Abschnitte als ruhige Karten */
    [data-testid="stExpander"] details {{
        background: var(--po-card); border: 1px solid var(--po-line); border-radius: 12px;
        box-shadow: 0 1px 2px var(--po-shadow), inset 0 1px 0 var(--po-edge);
    }}
    [data-testid="stExpander"] summary {{ padding-top: 0.85rem; padding-bottom: 0.85rem; }}
    [data-testid="stExpander"] summary p {{ font-weight: 600; font-size: 1rem; color: var(--po-ink); }}
    [data-testid="stExpander"] summary:hover p {{ color: var(--po-primary); }}
    [data-testid="stExpanderIcon"] {{ color: var(--po-accent); }}

    /* Kennzahlen: Karte, ruhige Beschriftung, kräftige Zahl */
    [data-testid="stMetric"] {{
        background: var(--po-card); border: 1px solid var(--po-line); border-radius: 12px;
        padding: 0.75rem 1rem; box-shadow: inset 0 1px 0 var(--po-edge);
    }}
    [data-testid="stMetricLabel"] p {{ color: var(--po-ink2); font-size: 0.875rem; }}
    [data-testid="stMetricValue"] > div {{ font-weight: 600; letter-spacing: -0.01em; }}

    /* Depotwert oben auf der Portfolio-Seite */
    .po-hero {{ margin: 0.25rem 0 0.5rem; }}
    .po-hero .po-label {{ color: var(--po-ink2); font-size: 0.875rem; }}
    .po-hero .po-value {{ color: var(--po-ink); font-size: 2.986rem; font-weight: 600; line-height: 1.1;
                         letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }}
    .po-hero .po-sub {{ color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; margin-top: 0.25rem; }}
    .po-hero .po-sub span + span::before {{ content: "·"; color: var(--po-muted); margin: 0 0.5rem; }}
    .po-up {{ color: var(--po-up); font-weight: 600; }}
    .po-down {{ color: var(--po-down); font-weight: 600; }}

    h1, h2, h3, h4 {{ color: var(--po-ink); letter-spacing: -0.01em; text-wrap: balance; }}
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
