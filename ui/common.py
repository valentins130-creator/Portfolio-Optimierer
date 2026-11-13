"""Gemeinsame Bausteine der Oberfläche: Farbwelt, Abschnittswahl, Karten, Meldungen.

Gestaltung: schlicht wie Apple, ruhig wie eine Finanz-App. Viel Weißraum auf hellem Grau, Karten in
Weiß, eine einzige Akzentfarbe (Blau) für alles, was man anklicken kann, große Zahlen in Inter.
Grün und Rot nur für Gewinne und Verluste, Orange nur für überschrittene Grenzen.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from portfolio_optimizer import charts

# Jede Farbe gilt für hell und dunkel: Streamlit setzt das Farbschema (color-scheme) der App,
# light-dark() wählt daraus den passenden Wert. Daten tragen die geprüfte Diagrammpalette
# (charts.py), Texte nie Datenfarben.
TOKENS = {
    "bg": ("#f5f5f7", "#0a0b0d"),
    "card": ("#ffffff", "#16181c"),
    "sunken": ("#f0f0f3", "#1d2026"),
    "line": ("rgb(0 0 0 / 0.08)", "rgb(255 255 255 / 0.09)"),
    "line-strong": ("rgb(0 0 0 / 0.16)", "rgb(255 255 255 / 0.18)"),
    "ink": ("#1d1d1f", "#f5f5f7"),
    "ink2": ("#424245", "#c7c7cc"),
    "muted": ("#6e6e73", "#98989d"),
    "primary": ("#0066cc", "#2997ff"),  # Links, aktive Symbole
    "primary-fill": ("#0071e3", "#0071e3"),  # Flächen mit weißer Schrift
    "accent": ("#d97000", "#d67600"),  # überschrittene Grenze (Fläche)
    "accent-text": ("#b25000", "#ff9f0a"),
    "up": ("#067a46", "#30d158"),
    "down": ("#d70015", "#ff453a"),
    "shadow": ("rgb(0 0 0 / 0.07)", "rgb(0 0 0 / 0.45)"),
    "edge": ("transparent", "rgb(255 255 255 / 0.04)"),
    # Balken (Palette mit dem dataviz-Validator geprüft)
    "chart-ok": ("#0071e3", "#0a84ff"),
    "chart-warn": ("#d97000", "#d67600"),
    "chart-track": ("#e8e8ed", "#2c2f36"),
    "chart-muted": ("#a1a1a6", "#636366"),
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

    /* Kopfzeile: durchscheinend wie bei Apple, mit fester Kante; ohne Unschärfe-Unterstützung deckend */
    header[data-testid="stHeader"] {{
        background: color-mix(in srgb, var(--po-bg) 78%, transparent);
        -webkit-backdrop-filter: saturate(180%) blur(20px); backdrop-filter: saturate(180%) blur(20px);
        border-bottom: 1px solid var(--po-line);
    }}
    @supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {{
        header[data-testid="stHeader"] {{ background: var(--po-bg); }}
    }}
    /* Bildmarke als Bild, Name als echter Text (lesbar auch im dunklen Design) */
    :has(> img[data-testid="stHeaderLogo"]) {{
        display: flex; align-items: center; gap: 0.75rem; width: auto !important; max-width: none !important;
    }}
    :has(> img[data-testid="stHeaderLogo"])::after {{
        content: "Portfolio-Optimierer"; color: var(--po-ink); font-weight: 600; font-size: 1.05rem;
        letter-spacing: -0.01em; white-space: nowrap;
    }}
    @media (max-width: 767.98px) {{ :has(> img[data-testid="stHeaderLogo"])::after {{ display: none; }} }}
    [data-testid="stTopNavLink"] p {{ font-weight: 500; }}
    [data-testid="stMainBlockContainer"] {{ padding-top: 5rem; padding-bottom: 5rem; max-width: 1180px; }}

    h1, h2, h3, h4 {{ color: var(--po-ink); letter-spacing: -0.02em; text-wrap: balance; }}
    /* unsichtbare Rahmen: setzen nur das Cookie bzw. Sprache und Browserfarbe */
    .st-key-po_cookie, .st-key-po_meta {{ position: absolute; width: 0; height: 0; overflow: hidden; }}
    /* Fokus per Tastatur nicht unter der festen Kopfzeile verstecken */
    [data-testid="stMain"] {{ scroll-padding-top: 5rem; }}
    /* Tippen auf dem Handy: keine Doppeltipp-Verzögerung, kein grauer Blitz (Buttons geben eigenes Feedback) */
    button, a, [role="tab"], [data-baseweb="select"] {{ touch-action: manipulation;
                                                       -webkit-tap-highlight-color: transparent; }}
    /* Dialoge und Menüs scrollen für sich, ohne die Seite dahinter mitzuziehen */
    [role="dialog"], [data-testid="stPopoverBody"] {{ overscroll-behavior: contain; }}
    /* Lange Namen (Depots, Wertpapiere, E-Mail-Adressen) umbrechen statt überzulaufen */
    .po-page-head .po-eyebrow, .po-xray-title, .po-xray-sub, .po-hint-name, .st-key-account_email p,
    [role="dialog"] strong {{ overflow-wrap: anywhere; }}
    .po-card-title {{ margin: 0; padding: 0; color: var(--po-ink); font-size: 1.375rem; font-weight: 600;
                      line-height: 1.2; letter-spacing: -0.02em; }}

    /* Buttons: leichter Druck beim Klicken */
    [data-testid^="stBaseButton"] {{ transition: transform 100ms ease, background-color 150ms ease,
                                     border-color 150ms ease, color 150ms ease; }}
    [data-testid^="stBaseButton"]:active {{ transform: scale(0.98); }}
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] p,
    [data-testid="stBaseButton-primaryFormSubmit"], [data-testid="stBaseButton-primaryFormSubmit"] p {{
        color: #ffffff; }}

    /* Segment-Schalter wie bei Apple: Schiene in Grau, gewählter Abschnitt als weiße Fläche */
    [data-testid="stButtonGroup"] > div:has(> button[data-variant="segmented_control"]) {{
        gap: 0.25rem; padding: 0.25rem; border-radius: 999px; background: var(--po-sunken);
        border: 1px solid var(--po-line); width: fit-content; max-width: 100%; flex-wrap: wrap;
    }}
    button[data-variant="segmented_control"] {{
        min-height: 2.75rem; padding: 0 1.1rem; border: 0 !important; border-radius: 999px !important;
        background: transparent !important; color: var(--po-ink2) !important; box-shadow: none;
        transition: background-color 150ms ease, color 150ms ease;
    }}
    button[data-variant="segmented_control"] p {{ font-weight: 500; }}
    @media (hover: hover) {{
        button[data-variant="segmented_control"]:not([aria-checked="true"]):hover {{
            color: var(--po-ink) !important; background: color-mix(in srgb, var(--po-card) 60%, transparent) !important; }}
    }}
    button[data-variant="segmented_control"][aria-checked="true"] {{
        background: var(--po-card) !important; color: var(--po-ink) !important;
        box-shadow: 0 1px 3px var(--po-shadow), 0 0 0 1px var(--po-line), inset 0 1px 0 var(--po-edge);
    }}
    button[data-variant="segmented_control"]:focus-visible {{ outline: 2px solid var(--po-primary); outline-offset: 2px; }}
    /* Handy: gleich breite Felder im Raster statt einer umbrechenden Pille */
    @media (max-width: 767.98px) {{
        .stElementContainer:has(> [data-testid="stButtonGroup"] button[data-variant="segmented_control"]),
        [data-testid="stButtonGroup"]:has(> div > button[data-variant="segmented_control"]) {{ width: 100% !important; }}
        [data-testid="stButtonGroup"] > div:has(> button[data-variant="segmented_control"]) {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(7.5rem, 1fr)); width: 100%;
            border-radius: 26px; }}
        button[data-variant="segmented_control"] {{ padding: 0 0.75rem; }}
    }}

    /* Karten: Streamlit-Container mit Schlüssel „card_…“ und HTML-Karten (.po-card).
       Sie reagieren auf die Maus: heben sich leicht an, die Kante wird kräftiger, ein weicher Schatten
       blendet ein (nur transform und opacity bewegen sich). */
    [class*="st-key-card_"], .po-card, [data-testid="stMetric"], [data-testid="stExpander"] details {{
        position: relative; background: var(--po-card); border: 1px solid var(--po-line); border-radius: 18px;
        box-shadow: inset 0 1px 0 var(--po-edge);
        transition: transform 200ms cubic-bezier(0.16, 1, 0.3, 1), border-color 150ms ease;
    }}
    [class*="st-key-card_"] {{ padding: 1.5rem; }}
    [class*="st-key-card_"]::after, .po-card::after, [data-testid="stMetric"]::after {{
        content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
        box-shadow: 0 12px 32px var(--po-shadow); opacity: 0; transition: opacity 200ms ease;
    }}
    @media (hover: hover) {{
        [class*="st-key-card_"]:hover, .po-card:hover, [data-testid="stMetric"]:hover {{
            transform: translateY(-2px); border-color: var(--po-line-strong); }}
        [class*="st-key-card_"]:hover::after, .po-card:hover::after, [data-testid="stMetric"]:hover::after {{
            opacity: 1; }}
    }}
    [data-testid="stExpander"] details {{ border-radius: 14px; }}
    [data-testid="stExpander"] summary p {{ font-weight: 600; color: var(--po-ink); }}
    [data-testid="stExpanderIcon"] {{ color: var(--po-primary); }}

    /* Kennzahlen: ruhige Beschriftung, große Zahl */
    [data-testid="stMetric"] {{ padding: 1rem 1.25rem; }}
    [data-testid="stMetricLabel"] p {{ color: var(--po-muted); font-size: 0.875rem; }}
    [data-testid="stMetricValue"] > div {{ font-weight: 600; letter-spacing: -0.02em;
                                           font-variant-numeric: tabular-nums; }}

    /* Tabellen in einer ruhigen Fläche */
    [data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; }}

    /* Depotwert */
    .po-hero {{ margin: 0 0 0.5rem; }}
    .po-hero .po-label {{ color: var(--po-muted); font-size: 0.875rem; font-weight: 500; }}
    .po-hero .po-value {{ color: var(--po-ink); font-size: 3.2rem; font-weight: 600; line-height: 1.05;
                         letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }}
    /* Teile umbrechen als Ganzes; der Trennpunkt sitzt in der Lücke und fällt am Zeilenanfang weg
       (er liegt dort links außerhalb und wird abgeschnitten) */
    .po-hero .po-sub {{ display: flex; flex-wrap: wrap; column-gap: 1.1rem; overflow: hidden; color: var(--po-ink2);
                       font-size: 0.9375rem; line-height: 1.5; margin-top: 0.5rem; }}
    .po-hero .po-sub > span {{ position: relative; white-space: nowrap; }}
    .po-hero .po-sub > span + span::before {{ content: "·"; position: absolute; left: -0.72rem; color: var(--po-muted); }}
    .po-up {{ color: var(--po-up); font-weight: 600; }}
    .po-down {{ color: var(--po-down); font-weight: 600; }}

    /* Seitenkopf: kleine Zeile darüber, große Überschrift */
    .po-page-head {{ margin: 0 0 1.5rem; }}
    .po-page-head .po-eyebrow {{ margin: 0 0 0.25rem; color: var(--po-muted); font-size: 0.875rem; font-weight: 500; }}
    .po-page-head h1 {{ margin: 0; padding: 0; font-size: 2.5rem; font-weight: 600; line-height: 1.1;
                       letter-spacing: -0.03em; color: var(--po-ink); }}
    .po-page-head p.po-intro {{ margin: 0.75rem 0 0; max-width: 60ch; color: var(--po-ink2); font-size: 1.0625rem;
                               line-height: 1.5; }}
    .po-sub-head {{ margin: 2.5rem 0 0.5rem; }}
    .po-sub-head h2 {{ margin: 0; padding: 0; font-size: 1.5rem; font-weight: 600; line-height: 1.2;
                      letter-spacing: -0.02em; color: var(--po-ink); }}
    .po-sub-head p.po-intro {{ margin: 0.5rem 0 0; max-width: 65ch; color: var(--po-ink2); font-size: 0.9375rem;
                              line-height: 1.5; }}
    @media (max-width: 767.98px) {{ .po-page-head h1 {{ font-size: 2rem; }} .po-hero .po-value {{ font-size: 2.5rem; }} }}

    @media (prefers-reduced-motion: reduce) {{
        [class*="st-key-card_"], .po-card, [data-testid="stMetric"], [data-testid^="stBaseButton"] {{ transition: none; }}
        [class*="st-key-card_"]:hover, .po-card:hover, [data-testid="stMetric"]:hover,
        [data-testid^="stBaseButton"]:active {{ transform: none; }}
    }}
    </style>""")


def page_meta() -> None:
    """Sprache, Browserfarbe und E-Mail-Felder der Seite einstellen; Streamlit bietet dafür keine Option.

    ``lang="de"``: Screenreader lesen deutsch vor, der Browser bietet keine Übersetzung an. ``theme-color``
    färbt die Browserleiste auf dem Handy wie den Hintergrund. E-Mail-Felder bekommen die E-Mail-Tastatur,
    ohne automatische Großschreibung, Autokorrektur und Rechtschreibprüfung.
    """
    bg = TOKENS["bg"][1 if is_dark() else 0]
    with st.container(key="po_meta"):
        components.html(f"""<script>
        const doc = window.parent.document;
        doc.documentElement.lang = "de";
        let meta = doc.querySelector('meta[name="theme-color"]');
        if (!meta) {{ meta = doc.createElement("meta"); meta.name = "theme-color"; doc.head.appendChild(meta); }}
        meta.content = "{bg}";
        const fix = () => doc.querySelectorAll('input[autocomplete="email"]:not([inputmode])').forEach(el => {{
            el.name = "email"; el.inputMode = "email"; el.spellcheck = false;
            el.setAttribute("autocapitalize", "none"); el.setAttribute("autocorrect", "off");
        }});
        fix();
        new MutationObserver(fix).observe(doc.body, {{ childList: true, subtree: true }});
        </script>""", height=0)


def page_head(title: str, eyebrow: str = "", intro: str = "") -> None:
    """Großer Seitentitel im Apple-Stil, optional mit Zeile darüber und kurzer Einleitung."""
    top = f'<p class="po-eyebrow">{eyebrow}</p>' if eyebrow else ""
    text = f'<p class="po-intro">{intro}</p>' if intro else ""
    st.html(f'<div class="po-page-head">{top}<h1>{title}</h1>{text}</div>')


def sub_head(title: str, intro: str = "") -> None:
    """Zwischenüberschrift innerhalb eines Abschnitts."""
    text = f'<p class="po-intro">{intro}</p>' if intro else ""
    st.html(f'<div class="po-sub-head"><h2>{title}</h2>{text}</div>')


def choose(key: str, options: dict[str, str], default: str) -> str:
    """Abschnittswahl als Segment-Schalter. Gezeichnet und gerechnet wird nur der gewählte Abschnitt.

    ``options`` ordnet Schlüssel ihren Beschriftungen zu; zurück kommt der Schlüssel. Der Wert bleibt
    beim Wechsel der Seite erhalten (Schlüssel beginnen mit ``sec_``) und lässt sich von außen setzen,
    etwa von einem Knopf auf der Übersicht.
    """
    if st.session_state.get(key) not in options:
        st.session_state[key] = default
    return st.segmented_control("Abschnitt", list(options), format_func=options.get, key=key, required=True,
                                label_visibility="collapsed") or default


# Eingaben der Seiten, die beim Wechsel zwischen Übersicht, Depot und Analysen erhalten bleiben
# (nicht das Anfangskapital der Simulation: es folgt dem Depotwert des gewählten Portfolios)
PERSISTENT_KEYS = ("sec_", "lim_", "mc_portfolio", "mc_method", "mc_contribution", "mc_years", "mc_paths",
                   "mc_target", "mc_seed", "sens_", "exp_", "frontier_", "rb_", "hedge_", "mix_", "pf_dim",
                   "corr_table", "cluster_table", "error_table", "tx_mode", "tx_kind", "tx_date", "tx_shares",
                   "tx_price", "tx_query", "whatif_")


def keep_page_state() -> None:
    """Zustand der Seiten-Widgets über Seitenwechsel hinweg behalten.

    Streamlit vergisst Widgets, die in einem Durchlauf nicht gezeichnet werden – beim Wechsel
    der Seite also gewählte Abschnitte und Eingaben der anderen Seiten. Zurückgeschrieben
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
