"""Startseite für Abgemeldete: anmelden oder Konto erstellen, die Analyse am Beispiel, die Details.

Aufbau: Titel und Anmeldung, darunter die echte Klumpenrisiko-Karte als Produktbild, drei Zahlen aus
dem Beispiel und ein nüchternes Datenblatt statt Funktionskacheln. Alle Zahlen rechnet
``portfolio_optimizer`` mit dem fiktiven Beispieldepot der Offline-Demo; nichts ist ausgedacht.
"""

from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from portfolio_optimizer import concentration as conc
from portfolio_optimizer.formatting import num
from ui import auth, xray
from ui.common import show_flash
from ui.state import Settings

SPECS = [
    ("Depot", "Käufe und Verkäufe mit Datum, Stückzahl und Kurs. Einstandskurse nach FIFO, Aktiensplits, "
              "Import als CSV oder JSON."),
    ("Rendite", "Persönliche Rendite (interner Zinsfuß) und zeitgewichtete Rendite, Vergleich mit einem Index, "
                "Aufteilung nach Sektor und Währung."),
    ("Risiko", "Klumpenrisiko nach Einzelwert, Sektor, Währung und Gruppen stark korrelierter Werte, jeweils mit "
               "dem Anteil an der Schwankung und gemessen an deinen eigenen Grenzen."),
    ("Optimierung", "Efficient Frontier nach Markowitz, Monte-Carlo-Simulation mit Sparrate und ein eigener "
                    "Abschnitt dazu, wie belastbar die Schätzungen sind."),
    ("Lösungen", "Umschichtung in ganzen Stücken mit möglichst wenig Handel, Was-wäre-wenn-Regler, Markt-Hedge "
                 "über das Beta, Beimischung von Anleihen, Gold oder Geldmarkt."),
    ("Daten", "Kurse und Wechselkurse von Yahoo Finance, alles in Euro. Zum Ausprobieren eine Offline-Demo mit "
              "fiktiven Wertpapieren."),
    ("Methoden", "Markowitz (1952), Jorion (1986), Michaud (1989), Ledoit &amp; Wolf (2004), "
                 "DeMiguel, Garlappi &amp; Uppal (2009)."),
]


def render() -> None:
    show_flash()
    _style()
    left, right = st.columns([7, 5], gap="large", vertical_alignment="center")
    with left:
        st.html(
            '<div class="po-landing-hero po-rise">'
            "<h1>Sieh, wo dein Depot wirklich Risiko trägt.</h1>"
            '<p class="po-landing-lead">Der Portfolio-Optimierer zerlegt dein Depot nach Aktien, Sektoren und '
            "Währungen, zeigt, woher die Schwankung kommt, und rechnet Umschichtungen durch, die deine eigenen "
            "Grenzen einhalten.</p>"
            '<p class="po-landing-meta po-dots"><span>Kostenlos</span><span>Keine Anlageberatung</span>'
            "<span>Deine Depots sieht nur dein Konto</span></p></div>"
        )
    with right:
        auth.panel()

    try:
        example = xray.cached_example(Settings().years)
    except Exception:  # pragma: no cover - die Offline-Demo braucht kein Netz
        example = None
    if example is not None:
        st.html('<p class="po-landing-caption">Am fiktiven Beispieldepot: Klumpenrisiko jetzt und nach der '
                "vorgeschlagenen Umschichtung. Schalte zwischen beiden Zuständen um.</p>")
        xray.card(example, "landing")
        _numbers(example)
    _specs()
    _footer()


def _numbers(x: xray.XRay) -> None:
    """Drei Zahlen aus dem Beispiel, die ein Depotauszug nicht zeigt."""
    stats = []
    top = x.rows[0] if x.rows else None
    if top is not None and top.risk[0] is not None:
        stats.append((xray.pct_nb(top.risk[0]),
                      f"der Schwankung entfallen auf {escape(top.label)} ({conc.KINDS[top.kind]}), bei "
                      f"{xray.pct_nb(top.weight[0])} Gewicht."))
    stats.append((f'{num(x.effective[0], 1)}<small> von {x.positions[0]}</small>',
                  "Positionen wirken effektiv: So viele gleich große hätten dieselbe Konzentration."))
    stats.append((f'{x.exceeded[0]}<small><span aria-hidden="true"> → </span><span class="po-sr">, danach </span>'
                  f'{x.exceeded[1]}</small>',
                  "überschrittene Grenzen, vor und nach der vorgeschlagenen Umschichtung."))
    cells = "".join(f'<div class="po-stat po-rise" style="--i: {i}"><p class="po-stat-value">{value}</p>'
                    f'<p class="po-stat-text">{text}</p></div>' for i, (value, text) in enumerate(stats))
    st.html(f'<section class="po-band"><h2>Was ein Depotauszug nicht zeigt</h2>'
            f'<div class="po-stat-row">{cells}</div></section>')


def _specs() -> None:
    rows = "".join(f"<div><dt>{name}</dt><dd>{text}</dd></div>" for name, text in SPECS)
    st.html(f'<section class="po-band"><h2>Im Detail</h2><dl class="po-specs">{rows}</dl></section>')


@st.dialog("Impressum", width="large")
def _imprint() -> None:
    st.caption("Vorlage: Markierte Angaben ersetzen und vor der Veröffentlichung rechtlich prüfen lassen.")
    st.markdown(
        "**Angaben gemäß § 5 DDG**  \n:orange[Vor- und Nachname oder Firma]  \n:orange[Straße und Hausnummer]  \n"
        ":orange[Postleitzahl und Ort]\n\n"
        "**Kontakt**  \nE-Mail: :orange[adresse@beispiel.de]\n\n"
        "**Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV**  \n:orange[Vor- und Nachname, Anschrift wie oben]\n\n"
        "**Keine Anlageberatung**  \nDer Portfolio-Optimierer ist ein Analyse- und Lernwerkzeug. Seine Inhalte sind "
        "keine Anlageberatung und keine Aufforderung zum Kauf oder Verkauf von Wertpapieren. Alle Auswertungen "
        "beruhen auf historischen Daten und berücksichtigen weder Transaktionskosten noch Steuern."
    )


@st.dialog("Datenschutz", width="large")
def _privacy() -> None:
    st.caption("Vorlage: beschreibt, was die Website technisch tut. Markierte Angaben ergänzen und vor der "
               "Veröffentlichung rechtlich prüfen lassen.")
    st.markdown(
        "**Verantwortlicher**  \n:orange[Name, Anschrift, E-Mail]\n\n"
        "**Konto**  \nFür ein Konto speichern wir deine E-Mail-Adresse und einen Hash deines Passworts, nie das "
        "Passwort selbst. Rechtsgrundlage ist Art. 6 Abs. 1 lit. b DSGVO (Nutzungsvertrag).\n\n"
        "**Deine Depots**  \nDepots, Transaktionen und Einstellungen liegen in einem eigenen Ordner deines Kontos auf "
        "dem Server, nur dein Konto greift darauf zu. Unter Konto → Konto löschen entfernst du Konto und Daten "
        "endgültig.\n\n"
        "**Angemeldet bleiben**  \nWählst du es, legt die Seite ein Cookie mit einem zufälligen Schlüssel ab "
        "(30 Tage). Es dient nur der Anmeldung; beim Abmelden wird es ungültig. Keine Werbe- oder Analyse-Cookies.\n\n"
        "**Passwort vergessen**  \nFür einen Link zum Zurücksetzen schicken wir eine E-Mail über "
        ":orange[Name des E-Mail-Dienstes, z. B. Resend]. Der Dienst erhält dabei deine E-Mail-Adresse und den "
        "Inhalt der Nachricht. Der Link gilt eine Stunde.\n\n"
        "**Kurse von Yahoo Finance**  \nFür Kurse, Wechselkurse und Stammdaten fragt der Server bei Yahoo an. Dabei "
        "erhält Yahoo die angefragten Wertpapiere, aber keine Angaben zu deiner Person.\n\n"
        "**Hosting**  \nDie Website läuft bei :orange[Name und Sitz des Hosting-Anbieters, z. B. Railway]; der "
        "Anbieter verarbeitet technisch notwendige Verbindungsdaten. :orange[Speicherdauer der Server-Protokolle "
        "ergänzen.]\n\n"
        "**Deine Rechte**  \nAuskunft, Berichtigung, Löschung, Einschränkung, Datenübertragbarkeit, Widerspruch und "
        "Beschwerde bei einer Datenschutz-Aufsichtsbehörde."
    )


def _footer() -> None:
    with st.container(key="po_footer"):
        st.html('<div class="po-footer"><p class="po-footer-about">Analyse- und Lernwerkzeug für dein Depot. '
                "Keine Anlageberatung. Die Auswertungen beruhen auf historischen Daten und berücksichtigen weder "
                "Kosten noch Steuern.</p>"
                f'<p class="po-footer-meta">© {date.today().year} Portfolio-Optimierer</p></div>')
        with st.container(horizontal=True, gap="small"):
            if st.button("Impressum", type="tertiary", key="po_imprint"):
                _imprint()
            if st.button("Datenschutz", type="tertiary", key="po_privacy"):
                _privacy()


def _style() -> None:
    xray.style()
    st.html("""<style>
    .po-landing-hero h1 { margin: 0; padding: 0; max-width: 13em; color: var(--po-ink); font-size: 3.5rem;
                          font-weight: 560; line-height: 1.04; letter-spacing: -0.035em; text-wrap: balance; }
    .po-landing-lead { margin: 1.5rem 0 0; max-width: 34rem; color: var(--po-ink2); font-size: 1.25rem; line-height: 1.5; }
    .po-landing-meta { margin: 1.5rem 0 0 !important; color: var(--po-muted); font-size: 0.9375rem; line-height: 1.5; }
    .st-key-card_auth { padding: 2rem; }
    .po-landing-caption { margin: 5rem 0 0; max-width: 46rem; color: var(--po-muted); font-size: 0.9375rem;
                          line-height: 1.5; }

    /* Abschnitte: Überschrift links, Inhalt darunter, getragen von feinen Linien statt Kacheln */
    .po-band { margin: 7rem 0 0; }
    .po-band h2 { margin: 0 0 2rem; padding: 0; max-width: 16em; color: var(--po-ink); font-size: 2.25rem;
                  font-weight: 560; line-height: 1.1; letter-spacing: -0.03em; text-wrap: balance; }
    .po-stat-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 2rem; }
    .po-stat { padding-top: 1.25rem; border-top: 1px solid var(--po-line-strong); }
    .po-stat-value { margin: 0; color: var(--po-ink); font-size: 3rem; font-weight: 500; line-height: 1;
                     letter-spacing: -0.035em; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .po-stat-value small { color: var(--po-muted); font-size: 1.25rem; font-weight: 450; letter-spacing: -0.01em; }
    .po-stat-text { margin: 0.75rem 0 0; max-width: 22rem; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.5; }
    .po-specs { margin: 0 !important; padding: 0 !important; border-bottom: 1px solid var(--po-line); }
    .po-specs > div { display: grid; grid-template-columns: 11rem minmax(0, 1fr); gap: 0.25rem 2rem;
                      padding: 1.125rem 0; border-top: 1px solid var(--po-line); }
    .po-specs dt { color: var(--po-ink); font-size: 0.9375rem; font-weight: 600; line-height: 1.5; }
    .po-specs dd { margin: 0; max-width: 46rem; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.5; }

    .st-key-po_footer { margin-top: 6rem; padding-top: 2rem; border-top: 1px solid var(--po-line); }
    .po-footer-about { margin: 0; max-width: 40rem; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-footer-meta { margin: 0.5rem 0 0; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    @media (max-width: 767.98px) {
        .po-landing-hero h1 { font-size: 2.5rem; }
        .st-key-card_auth { padding: 1.5rem; }
        .po-landing-caption { margin-top: 3.5rem; }
        .po-band { margin-top: 4.5rem; }
        .po-band h2 { font-size: 1.875rem; }
        .po-stat-row { grid-template-columns: minmax(0, 1fr); gap: 1.75rem; }
        .po-specs > div { grid-template-columns: minmax(0, 1fr); }
    }
    </style>""")
