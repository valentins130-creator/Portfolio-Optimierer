"""Übersicht: Depotwert, Klumpenrisiko jetzt und nach Umschichtung, Hinweise und Schnellzugriff.

Ohne Depot führt sie mit drei Einstiegen zum ersten Depot: erfassen, importieren, Beispiel ansehen.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from portfolio_optimizer import concentration as conc
from ui import header, xray
from ui.common import page_head, show_flash
from ui.portfolio_view import _hero
from ui.state import RunState

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
    ctx = run.ctx
    if not ctx.portfolio.positions:
        _onboarding(run)
        return
    page_head("Übersicht", eyebrow=ctx.portfolio.name)
    left, right = st.columns([3, 2], gap="medium")
    with left, st.container(key="card_value"):
        _hero(ctx)
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
    st.html("""<style>
    .po-hint-title { margin: 0.25rem 0 0; color: var(--po-ink); font-size: 1.25rem; font-weight: 600; line-height: 1.25;
                     letter-spacing: -0.02em; }
    .po-hint-text { display: block; margin: 0.25rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-hints { display: grid; gap: 0.75rem; margin: 1rem 0 !important; padding: 0 !important; list-style: none; }
    .po-hints li { margin: 0 !important; padding: 0 0 0 0.75rem !important; border-left: 3px solid var(--po-accent); }
    .po-hint-name { display: block; color: var(--po-ink); font-size: 0.9375rem; font-weight: 600; line-height: 1.4; }
    </style>""")


def _onboarding(run: RunState) -> None:
    """Leeres Depot: drei klare Wege zum ersten Depot und ein Blick auf das, was danach kommt."""
    page_head("Willkommen", intro="Leg dein Depot an. Danach siehst du hier auf einen Blick, wo dein Risiko sitzt "
                                  "und was du tun kannst.")
    provider = run.ctx.provider
    a, b, c = st.columns(3, gap="medium")
    with a, st.container(key="card_start_add"):
        st.html(f'{xray.icon("ledger", "po-icon po-icon-l")}<p class="po-start-title">Transaktion erfassen</p>'
                '<p class="po-start-text">Käufe und Verkäufe mit Datum, Stückzahl und Kurs eintragen.</p>')
        if st.button("Erste Transaktion erfassen", type="primary", width="stretch", key="start_add"):
            _go("depot", sec_add=True)
    with b, st.container(key="card_start_import"):
        st.html(f'{xray.icon("swap", "po-icon po-icon-l")}<p class="po-start-title">Depot importieren</p>'
                '<p class="po-start-text">CSV mit Symbol und Stückzahl, optional Datum und Kurs, oder ein '
                "JSON-Export dieser App.</p>")
        st.file_uploader("Datei", type=["json", "csv"], key="start_upload", label_visibility="collapsed")
        st.button("Importieren", width="stretch", key="start_import", on_click=header.import_upload,
                  args=(provider, "start_upload"))
    with c, st.container(key="card_start_demo"):
        st.html(f'{xray.icon("spark", "po-icon po-icon-l")}<p class="po-start-title">Beispiel ansehen</p>'
                '<p class="po-start-text">Ein fiktives Depot mit Käufen über drei Jahre, zum Ausprobieren.</p>')
        if provider == "demo":
            st.button("Beispieldepot laden", width="stretch", key="start_demo", on_click=header.load_example,
                      args=("demo",))
        else:
            st.button("Offline-Demo ausprobieren", width="stretch", key="start_demo", on_click=_try_demo,
                      help="Wechselt zu fiktiven Wertpapieren. Zurück zu echten Kursen geht es unter Einstellungen.")
    st.html("""<style>
    .po-start-title { margin: 1rem 0 0; color: var(--po-ink); font-size: 1.25rem; font-weight: 600; line-height: 1.25;
                      letter-spacing: -0.02em; }
    .po-start-text { margin: 0.5rem 0 1rem; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.5; min-height: 4.5em; }
    [class*="st-key-card_start_"] { height: 100%; }
    </style>""")
    st.html('<div class="po-sub-head"><h2>So sieht deine Analyse aus</h2><p class="po-intro">Am fiktiven '
            "Beispieldepot: Klumpenrisiko jetzt und nach der vorgeschlagenen Umschichtung.</p></div>")
    try:
        xray.card(xray.cached_example(run.settings.years), "preview")
    except Exception as exc:  # pragma: no cover - die Offline-Demo braucht kein Netz
        st.caption(f"Vorschau gerade nicht verfügbar ({exc}).")
