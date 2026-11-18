"""Übersicht: Depotwert mit Verlauf, Klumpenrisiko jetzt und nach Umschichtung, Hinweise, Schnellzugriff.

Ohne Depot führt sie mit drei Einstiegen zum ersten Depot: erfassen, importieren, Beispiel ansehen.
"""

from __future__ import annotations

import hashlib
from html import escape
from urllib.parse import quote

import pandas as pd
import streamlit as st

from portfolio_optimizer import concentration as conc
from portfolio_optimizer import performance
from ui import header, xray
from ui.common import page_head, show_flash
from ui.portfolio_view import _hero
from ui.state import PortfolioContext, RunState

PAGES = {"depot": "views/depot.py", "analysen": "views/analysen.py"}


def _go(page: str, **state) -> None:
    """Zur Seite wechseln und dort gleich den passenden Abschnitt zeigen."""
    for key, value in state.items():
        st.session_state[key] = value
    st.switch_page(PAGES[page])


def _try_demo() -> None:
    header.use_provider("demo")
    header.load_example("demo")


def render(run: RunState) -> None:
    show_flash()
    _style()
    ctx = run.ctx
    if not ctx.portfolio.positions:
        _onboarding(run)
        return
    page_head("Übersicht", eyebrow=ctx.portfolio.name)
    left, right = st.columns([3, 2], gap="medium")
    with left, st.container(key="card_value"):
        _hero(ctx)
        _trend(ctx)
    with right, st.container(key="card_actions"):
        st.html('<p class="po-kicker">Schnellzugriff</p>')
        if st.button("Transaktion erfassen", icon=":material/add:", width="stretch", key="go_add"):
            _go("depot", sec_add=True)
        if st.button("Depot prüfen", icon=":material/troubleshoot:", width="stretch", key="go_check"):
            _go("analysen", sec_analyse="cluster")
        if st.button("Gewichte ausprobieren", icon=":material/tune:", width="stretch", key="go_whatif",
                     help="Was wäre, wenn eine Position mehr oder weniger Gewicht hätte?"):
            _go("analysen", sec_analyse="cluster")
        if st.button("Zukunft simulieren", icon=":material/insights:", width="stretch", key="go_future"):
            _go("analysen", sec_analyse="mc")
    if not xray.analysable(ctx):
        st.info("Für die Analyse braucht dein Depot etwas Kurshistorie. Sie erscheint hier, sobald Kurse vorliegen.")
        return
    try:
        x = xray.own_or_example(run)
    except Exception as exc:  # Kurse fehlen oder Rechnung scheitert: Übersicht trotzdem zeigen
        st.warning(f"Die Analyse ließ sich gerade nicht berechnen ({exc}). Depot und Analysen funktionieren weiter.")
        return
    left, right = st.columns([3, 2], gap="medium")
    with left:
        xray.card(x, "overview")
    with right:
        _hints(x)


def _style() -> None:
    st.html("""<style>
    .po-hint-title { margin: 0.25rem 0 0; color: var(--po-ink); font-size: 1.25rem; font-weight: 600; line-height: 1.25;
                     letter-spacing: -0.02em; }
    .po-hint-text { display: block; margin: 0.25rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-hints { display: grid; gap: 0.75rem; margin: 1rem 0 !important; padding: 0 !important; list-style: none; }
    .po-hints li { margin: 0 !important; padding: 0 0 0 0.75rem !important; border-left: 3px solid var(--po-accent); }
    .po-hint-name { display: block; color: var(--po-ink); font-size: 0.9375rem; font-weight: 600; line-height: 1.4; }

    /* Verlauf unter dem Depotwert: Fläche und Linie als Maske in der Farbe der Entwicklung */
    .po-trend { margin: 1.5rem 0 0; }
    .po-trend-head { display: flex; justify-content: space-between; gap: 1rem; color: var(--po-muted);
                     font-size: 0.8125rem; line-height: 1.4; }
    .po-trend-change { color: var(--po-ink2); font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .po-trend-change.is-up { color: var(--po-up); }
    .po-trend-change.is-down { color: var(--po-down); }
    .po-spark { position: relative; height: 64px; margin-top: 0.5rem; color: var(--po-chart-ok); overflow: hidden; }
    .po-spark.is-up { color: var(--po-up); }
    .po-spark.is-down { color: var(--po-down); }
    .po-spark > span { position: absolute; inset: 0; background: currentColor;
                       -webkit-mask: var(--m) 0 0 / 100% 100% no-repeat; mask: var(--m) 0 0 / 100% 100% no-repeat; }
    .po-spark-area { opacity: 0.16; }
    /* Die Kurve zeichnet sich beim ersten Erscheinen von links nach rechts (Ausnahme: 700 ms, Datenbild) */
    .po-spark > span { animation: po-draw 700ms cubic-bezier(0.16, 1, 0.3, 1) 150ms backwards; }

    .st-key-card_actions { gap: 0.125rem; }
    .st-key-card_actions [data-testid="stButton"] button {
        justify-content: flex-start; min-height: 3.25rem; padding: 0 0.75rem; border: 0; border-radius: 12px;
        background: transparent; box-shadow: none; color: var(--po-ink); }
    .st-key-card_actions [data-testid="stButton"] button > div { justify-content: flex-start; }
    .st-key-card_actions [data-testid="stButton"] button p { font-weight: 500; }
    /* Symbol als kleine Kachel in zartem Indigo, beim Überfahren kräftiger */
    .st-key-card_actions [data-testid="stButton"] button span:has(> [data-testid="stIconMaterial"]) {
        display: inline-grid; place-items: center; width: 2.25rem; height: 2.25rem; margin-right: 0.375rem;
        border-radius: 10px; background: var(--po-primary-tint); transition: background-color 150ms ease; }
    .st-key-card_actions [data-testid="stButton"] button [data-testid="stIconMaterial"] {
        color: var(--po-primary); font-size: 1.25rem; transition: color 150ms ease; }
    .st-key-card_actions [data-testid="stButton"] button::after {
        content: "›"; content: "›" / ""; margin-left: auto; padding-left: 1rem; color: var(--po-muted);
        font-size: 1.375rem; line-height: 1; transition: transform 150ms cubic-bezier(0.16, 1, 0.3, 1); }
    .st-key-card_actions [data-testid="stButton"] button:focus-visible { outline: 2px solid var(--po-primary);
                                                                         outline-offset: 2px; }
    @media (hover: hover) {
        .st-key-card_actions [data-testid="stButton"] button:hover { background: var(--po-sunken); }
        .st-key-card_actions [data-testid="stButton"] button:hover::after { transform: translateX(3px); }
        .st-key-card_actions [data-testid="stButton"] button:hover span:has(> [data-testid="stIconMaterial"]) {
            background: var(--po-primary-fill); }
        .st-key-card_actions [data-testid="stButton"] button:hover [data-testid="stIconMaterial"] { color: #ffffff; }
    }

    .po-start-title { margin: 1rem 0 0; color: var(--po-ink); font-size: 1.25rem; font-weight: 600; line-height: 1.25;
                      letter-spacing: -0.02em; }
    .po-start-text { margin: 0.5rem 0 1rem; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.5; min-height: 4.5em; }
    [class*="st-key-card_start_"] { height: 100%; }
    </style>""")


def _performance(ctx: PortfolioContext) -> performance.Performance | None:
    """Wertentwicklung des Depots; in der Sitzung gemerkt, solange sich Depot und Kurse nicht ändern."""
    if ctx.prices.empty:
        return None
    key = hashlib.sha1(f"{ctx.provider}|{ctx.portfolio.to_json()}|{ctx.prices.shape}|{ctx.prices.index[-1]}"
                       .encode()).hexdigest()
    memo = st.session_state.get("_perf")
    if memo and memo[0] == key:
        return memo[1]
    perf = performance.compute(ctx.portfolio, ctx.prices, ctx.dividends)
    st.session_state["_perf"] = (key, perf)
    return perf


def _spark_mask(points: list[tuple[float, float]], closed: bool) -> str:
    """Linie (oder Fläche darunter) als SVG-Maske; die Farbe kommt aus dem Stylesheet."""
    path = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points)
    shape = (f"<path d='{path} L600 100 L0 100 Z' fill='black'/>" if closed else
             f"<path d='{path}' fill='none' stroke='black' stroke-width='2' stroke-linejoin='round' "
             "stroke-linecap='round' vector-effect='non-scaling-stroke'/>")
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 100' preserveAspectRatio='none'>{shape}</svg>"
    return f"url('data:image/svg+xml,{quote(svg)}')"


def _trend(ctx: PortfolioContext) -> None:
    """Zeitgewichtete Wertentwicklung der letzten zwölf Monate als kleine Kurve unter dem Depotwert."""
    perf = _performance(ctx)
    if perf is None or len(perf.twr) < 20:
        return
    twr = perf.twr
    start = twr.index[-1] - pd.DateOffset(years=1)
    window = twr[twr.index >= start]
    period = "12 Monate" if twr.index[0] <= start else f"seit {window.index[0]:%d.%m.%Y}"
    change = float(window.iloc[-1] / window.iloc[0] - 1)
    step = max(1, len(window) // 150)
    sample = pd.concat([window.iloc[::step], window.iloc[-1:]])
    sample = sample[~sample.index.duplicated(keep="last")]
    low, high = float(sample.min()), float(sample.max())
    span = (high - low) or 1.0
    points = [(600 * i / (len(sample) - 1), 6 + 88 * (1 - (float(v) - low) / span)) for i, v in enumerate(sample)]
    tone, arrow = ("is-up", "▲ ") if change > 0 else ("is-down", "▼ ") if change < 0 else ("", "")
    value = ("+" if change > 0 else "") + xray.pct_nb(change, 1)
    st.html(f'<figure class="po-trend"><figcaption class="po-trend-head">'
            f'<span>Zeitgewichtete Wertentwicklung, {period}</span>'
            f'<span class="po-trend-change {tone}"><span aria-hidden="true">{arrow}</span>{value}</span></figcaption>'
            f'<div class="po-spark {tone}" role="img" aria-label="Verlauf, {period}">'
            f'<span class="po-spark-area" style="--m: {_spark_mask(points, True)}"></span>'
            f'<span class="po-spark-line" style="--m: {_spark_mask(points, False)}"></span></div></figure>')


def _hints(x: xray.XRay) -> None:
    """Die wichtigsten Befunde in Worten, je mit dem Weg zur Lösung."""
    over = [r for r in x.rows if r.status[0] == "over"]
    with st.container(key="card_hints"):
        st.html('<p class="po-kicker">Was zu tun ist</p>')
        if not over:
            st.html('<p class="po-hint-title">Alles im Rahmen</p><p class="po-hint-text">Keine Konzentration liegt '
                    "über deinen Grenzen. Die Grenzen passt du unter Analysen → Klumpenrisiko an.</p>")
            return
        items = "".join(
            f'<li><span class="po-hint-name">{escape(r.label)}</span>'
            f'<span class="po-hint-text">{conc.KINDS[r.kind]}: {xray.pct_nb(r.weight[0])} statt höchstens '
            f"{xray.pct_nb(r.limit, 0)}, Risikoanteil {xray.pct_nb(r.risk[0])}</span></li>"
            for r in over[:3])
        total = max(x.exceeded[0], len(over))  # auch Korrelations-Cluster zählen mit
        st.html(f'<p class="po-hint-title">{total} {"Grenze" if total == 1 else "Grenzen"} überschritten'
                f'</p><ul class="po-hints">{items}</ul>')
        if x.sells[0] or x.buys[0]:
            st.html(f'<p class="po-hint-text">Mit {x.sells[0] + x.buys[0]} Transaktionen hält dein Depot danach '
                    f"{'alle Grenzen ein' if x.exceeded[1] == 0 else 'mehr Grenzen ein'}.</p>")
        if st.button("Umschichtung ansehen", type="primary", icon=":material/swap_horiz:", key="go_rebalance"):
            _go("analysen", sec_analyse="cluster")


def _onboarding(run: RunState) -> None:
    """Leeres Depot: drei klare Wege zum ersten Depot und ein Blick auf das, was danach kommt."""
    page_head("Willkommen", intro="Leg dein Depot an. Danach siehst du hier auf einen Blick, wo dein Risiko sitzt "
                                  "und was du tun kannst.")
    provider = run.ctx.provider
    a, b, c = st.columns(3, gap="medium")
    with a, st.container(key="card_start_add"):
        st.html(f'<span class="po-tile">{xray.icon("ledger")}</span><p class="po-start-title">Transaktion erfassen</p>'
                '<p class="po-start-text">Käufe und Verkäufe mit Datum, Stückzahl und Kurs eintragen.</p>')
        if st.button("Erste Transaktion erfassen", type="primary", width="stretch", key="start_add"):
            _go("depot", sec_add=True)
    with b, st.container(key="card_start_import"):
        st.html(f'<span class="po-tile">{xray.icon("swap")}</span><p class="po-start-title">Depot importieren</p>'
                '<p class="po-start-text">CSV mit Symbol und Stückzahl, optional Datum und Kurs, einen '
                "Broker-Export, eine Vermögensübersicht als PDF oder einen JSON-Export dieser App.</p>")
        st.file_uploader("Datei", type=["json", "csv", "pdf"], key="start_upload", label_visibility="collapsed")
        st.button("Importieren", width="stretch", key="start_import", on_click=header.import_upload,
                  args=(provider, "start_upload"))
    with c, st.container(key="card_start_demo"):
        st.html(f'<span class="po-tile">{xray.icon("spark")}</span><p class="po-start-title">Beispiel ansehen</p>'
                '<p class="po-start-text">Ein fiktives Depot mit Käufen über drei Jahre, zum Ausprobieren.</p>')
        if provider == "demo":
            st.button("Beispieldepot laden", width="stretch", key="start_demo", on_click=header.load_example,
                      args=("demo",))
        else:
            st.button("Offline-Demo ausprobieren", width="stretch", key="start_demo", on_click=_try_demo,
                      help="Wechselt zu fiktiven Wertpapieren. Zurück zu echten Kursen geht es unter Einstellungen.")
    st.html('<div class="po-sub-head"><h2>So sieht deine Analyse aus</h2><p class="po-intro">Am fiktiven '
            "Beispieldepot: Klumpenrisiko jetzt und nach der vorgeschlagenen Umschichtung.</p></div>")
    try:
        xray.card(xray.cached_example(run.settings.years), "preview")
    except Exception as exc:  # pragma: no cover - die Offline-Demo braucht kein Netz
        st.caption(f"Vorschau gerade nicht verfügbar ({exc}).")
