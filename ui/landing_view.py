"""Startseite für Abgemeldete: was die App kann, Anmelden und Konto erstellen, ein Beispiel zum Ansehen.

Die Beispielkarte rechnet mit dem fiktiven Beispieldepot der Offline-Demo; nichts ist ausgedacht.
"""

from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from portfolio_optimizer import concentration as conc
from ui import auth, xray
from ui.common import show_flash
from ui.state import Settings

FEATURES = [
    ("ledger", "Depot", "Stand erfassen",
     "Käufe und Verkäufe mit Datum, Stückzahl und Kurs eintragen oder als CSV importieren.",
     ["Depotwert und Einzahlungen im Verlauf", "Persönliche und zeitgewichtete Rendite", "Vergleich mit einem Index",
      "Aufteilung nach Sektor und Währung"]),
    ("frontier", "Analysen", "Risiken verstehen",
     "Kennzahlen, die zeigen, wo das Risiko sitzt und was eine Optimierung leisten kann.",
     ["Klumpenrisiko mit Risikoanteilen", "Was wäre, wenn: Gewichte ausprobieren", "Efficient Frontier nach Markowitz",
      "Monte-Carlo-Simulation mit Sparrate"]),
    ("swap", "Lösungen", "Lösungen durchrechnen",
     "Konkrete Vorschläge in Stück und Euro, direkt bei der passenden Analyse.",
     ["Umschichtung mit möglichst wenig Handel", "Realisierte Gewinne nach FIFO", "Markt-Hedge über das Beta",
      "Beimischung von Anleihen, Gold oder Geldmarkt"]),
]

METHODS = [("Markowitz (1952)", "Portfolio Selection"), ("Jorion (1986)", "Bayes-Stein-Schätzung"),
           ("Michaud (1989)", "Resampled Efficiency"), ("Ledoit & Wolf (2004)", "Shrinkage der Kovarianzmatrix"),
           ("DeMiguel, Garlappi & Uppal (2009)", "1/N als Vergleichsmaßstab")]


def render() -> None:
    show_flash()
    _style()
    left, right = st.columns([7, 5], gap="large", vertical_alignment="center")
    with left:
        st.html(
            '<div class="po-landing-hero">'
            '<p class="po-landing-eyebrow">Depot-Analyse für Privatanleger</p>'
            "<h1>Sieh, wo dein Depot wirklich Risiko trägt.</h1>"
            '<p class="po-landing-lead">Der Portfolio-Optimierer zerlegt dein Depot nach Aktien, Sektoren und '
            "Währungen, zeigt, woher die Schwankung kommt, und rechnet Umschichtungen durch, die deine eigenen "
            "Grenzen einhalten.</p>"
            '<ul class="po-facts">'
            f"<li>{xray.icon('check', 'po-icon po-icon-s')}<span>Analyse- und Lernwerkzeug, keine Anlageberatung</span></li>"
            f"<li>{xray.icon('lock', 'po-icon po-icon-s')}<span>Deine Depots sieht nur dein Konto</span></li>"
            f"<li>{xray.icon('check', 'po-icon po-icon-s')}<span>Methoden nach Markowitz, Ledoit-Wolf und Bayes-Stein</span></li>"
            "</ul></div>"
        )
    with right:
        auth.panel()

    try:
        example = xray.cached_example(Settings().years)
    except Exception:  # pragma: no cover - die Offline-Demo braucht kein Netz
        example = None
    _section_head("beispiel", "Beispiel", "So sieht deine Analyse aus",
                  "Am fiktiven Beispieldepot: Wo die Grenzen überschritten sind und wie es nach der vorgeschlagenen "
                  "Umschichtung aussieht. Schalte zwischen beiden Zuständen um.")
    if example is not None:
        xray.card(example, "landing")
    _questions(example)
    _features()
    _footer()


def _section_head(anchor: str, eyebrow: str, title: str, intro: str) -> None:
    st.html(f'<div class="po-section-head" id="{anchor}"><p class="po-landing-eyebrow">{eyebrow}</p>'
            f'<h2>{title}</h2><p class="po-section-intro">{intro}</p></div>')


def _bars_html(caption: str, sub: str, rows: list[tuple[str, float, str, bool]]) -> str:
    """Kleine Balkenfigur: (Beschriftung, Anteil 0–1, Wert als Text, hervorgehoben)."""
    bars = "".join(
        f'<div class="po-bar-row"><span class="po-bar-label">{escape(label)}</span>'
        f'<span class="po-bar-track" aria-hidden="true"><span class="po-bar-fill{" is-key" if key else ""}" '
        f'style="--v: {max(0.0, min(v, 1.0)):.4f}"></span></span><span class="po-bar-value">{text}</span></div>'
        for label, v, text, key in rows)
    return (f'<figure class="po-proof"><figcaption><span class="po-proof-title">{escape(caption)}</span>'
            f'<span class="po-proof-sub">{escape(sub)}</span></figcaption><div class="po-bars">{bars}</div></figure>')


def _questions(x: xray.XRay | None) -> None:
    _section_head("streuung", "Problem und Lösung", "Ein volles Depot ist noch kein gestreutes.",
                  "10 Positionen wirken breit. Steckt die Hälfte davon in einer Branche und fällt gemeinsam, bleibt "
                  "vom Streueffekt wenig übrig. Der Optimierer beantwortet 3 Fragen, die ein Depotauszug offenlässt.")
    top = x.rows[0] if x and x.rows else None
    if top and top.risk[0] is not None:
        proof1 = _bars_html(f"Beispieldepot, {conc.KINDS[top.kind]} {top.label}", "Wochenrenditen in Euro",
                            [("Gewicht", top.weight[0], xray.pct_nb(top.weight[0]), False),
                             ("Risikoanteil", top.risk[0], xray.pct_nb(top.risk[0]), True)])
    else:
        proof1 = ""
    proof2 = (
        '<figure class="po-proof"><figcaption><span class="po-proof-title">2 Renditen, 2 Antworten</span>'
        '</figcaption><dl class="po-terms">'
        "<div><dt>Persönliche Rendite p. a.</dt><dd>Interner Zinsfuß aller Zahlungen. Er berücksichtigt, "
        "wann du wie viel investiert hast.</dd></div>"
        "<div><dt>Zeitgewichtete Rendite p. a.</dt><dd>Unabhängig vom Zeitpunkt deiner Käufe und damit "
        "vergleichbar mit Fonds und Indizes.</dd></div></dl></figure>"
    )
    if x and (x.sells[0] or x.buys[0]):
        proof3 = _bars_html("Beispieldepot, Umschichtung nach den Grenzen", "Ganze Stücke, ohne Kosten und Steuern",
                            [("Grenzen jetzt", 1.0 if x.exceeded[0] else 0.0, str(x.exceeded[0]), False),
                             ("Grenzen danach", x.exceeded[1] / max(x.exceeded[0], 1), str(x.exceeded[1]), True)])
    else:
        proof3 = ""
    questions = [
        ("Wie gut ist mein Depot wirklich gestreut?",
         "Der Depotauszug zeigt Stückzahlen und Gewichte. Wie stark eine Position das ganze Depot schwanken lässt, "
         "steht dort nicht.",
         "Er prüft Einzelaktien, Sektoren, Fremdwährungen und Gruppen stark korrelierter Werte gegen deine Grenzen und "
         "berechnet für jede Gruppe den Risikoanteil: den Teil der Depotschwankung, den sie verursacht.", proof1),
        ("Wie steht mein Depot heute da?",
         "Nachkäufe und Teilverkäufe machen die Rendite schwer vergleichbar. Ein Plus seit dem ersten Kauf sagt wenig "
         "darüber, wie gut die Auswahl war.",
         "Du erfasst Käufe und Verkäufe mit Datum. Die App bewertet täglich in Euro, führt Einstandskurse nach FIFO "
         "und vergleicht dein Depot mit einem Index.", proof2),
        ("Was sollte ich ändern, und wie belastbar ist der Vorschlag?",
         "Optimierer rechnen mit geschätzten Renditen. Kleine Schätzfehler führen zu extremen Gewichten, die später "
         "selten halten, was sie versprechen.",
         "Die Umschichtung hält deine Grenzen mit möglichst wenig Handel ein. Mit dem Was-wäre-wenn-Regler probierst "
         "du eigene Gewichte aus, und der Abschnitt Schätzfehler zeigt, wie belastbar ein Ergebnis ist.", proof3),
    ]
    for n, (question, problem, answer, proof) in enumerate(questions):
        with st.container(key=f"po_q_{n}"):
            text, figure = st.columns([7, 5], gap="large")
            text.html(f'<div class="po-question"><h3>{question}</h3><p>{problem}</p>'
                      f'<p class="po-answer-label">So hilft der Optimierer</p><p>{answer}</p></div>')
            if proof:
                figure.html(proof)


def _features() -> None:
    _section_head("funktionen", "Funktionen", "3 Bereiche, vom Stand bis zur Lösung",
                  "Übersicht, Depot und Analysen. Jeder Bereich zeigt nur, was du gerade brauchst, und rechnet erst, "
                  "wenn du ihn öffnest.")
    for col, (icon_name, level, title, text, items) in zip(st.columns(3, gap="medium"), FEATURES):
        with col, st.container(key=f"card_feat_{icon_name}"):
            listing = "".join(f"<li>{xray.icon('check', 'po-icon po-icon-s')}<span>{item}</span></li>" for item in items)
            st.html(f'<div class="po-feature">{xray.icon(icon_name, "po-icon po-icon-l")}'
                    f'<p class="po-feature-level">{level}</p><h3>{title}</h3><p>{text}</p><ul>{listing}</ul></div>')
    methods = "".join(f'<li><span class="po-who">{escape(who)}</span><span class="po-what">{what}</span></li>'
                      for who, what in METHODS)
    st.html(f'<div class="po-methods"><p class="po-methods-title">Methoden aus der Forschung</p><ul>{methods}</ul></div>')


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
    .po-landing-hero h1 { margin: 0; padding: 0; color: var(--po-ink); font-size: 3.5rem; font-weight: 600;
                          line-height: 1.05; letter-spacing: -0.035em; text-wrap: balance; }
    .po-landing-eyebrow { margin: 0 0 0.75rem; color: var(--po-primary); font-size: 0.9375rem; font-weight: 600; }
    .po-landing-lead { margin: 1.5rem 0 0; max-width: 34rem; color: var(--po-ink2); font-size: 1.25rem; line-height: 1.5; }
    .po-facts { display: grid; gap: 0.625rem; margin: 2rem 0 0 !important; padding: 0 !important; list-style: none;
                color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.5; }
    .po-facts li { display: flex; gap: 0.625rem; margin: 0 !important; padding: 0 !important; }
    .po-facts .po-icon { margin-top: 3px; color: var(--po-up); }
    .st-key-card_auth { padding: 2rem; }
    .po-section-head { max-width: 46rem; margin: 7rem 0 2rem; scroll-margin-top: 5rem; }
    .po-section-head h2 { margin: 0; padding: 0; color: var(--po-ink); font-size: 2.5rem; font-weight: 600;
                          line-height: 1.1; letter-spacing: -0.03em; text-wrap: balance; }
    .po-section-intro { margin: 1rem 0 0; color: var(--po-ink2); font-size: 1.125rem; line-height: 1.5; }
    .st-key-po_q_0, .st-key-po_q_1, .st-key-po_q_2 { padding-block: 2rem; border-top: 1px solid var(--po-line); }
    .st-key-po_q_2 { border-bottom: 1px solid var(--po-line); }
    .po-question h3 { margin: 0; padding: 0; color: var(--po-ink); font-size: 1.5rem; font-weight: 600;
                      line-height: 1.25; letter-spacing: -0.02em; }
    .po-question p { margin: 1rem 0 0; max-width: 62ch; color: var(--po-ink2); line-height: 1.55; }
    .po-question .po-answer-label { margin-top: 1.5rem; color: var(--po-ink); font-size: 0.875rem; font-weight: 600; }
    .po-question .po-answer-label + p { margin-top: 0.25rem; }
    .po-proof { margin: 0; padding: 1.5rem; background: var(--po-card); border: 1px solid var(--po-line);
                border-radius: 18px; container-type: inline-size; }
    .po-proof-title, .po-proof-sub { display: block; }
    .po-proof-title { color: var(--po-ink); font-size: 0.9375rem; font-weight: 600; line-height: 1.4; }
    .po-proof-sub { margin-top: 0.25rem; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .po-bars { display: grid; gap: 0.75rem; margin-top: 1rem; }
    .po-bar-row { display: grid; grid-template-columns: minmax(0, 1fr) 3.5rem; grid-template-areas: "label label" "bar value";
                  gap: 0.25rem 0.75rem; align-items: center; font-size: 0.875rem; }
    @container (min-width: 24rem) {
        .po-bar-row { grid-template-columns: 8.5rem minmax(0, 1fr) 3.5rem; grid-template-areas: "label bar value"; gap: 0.75rem; }
    }
    .po-bar-label { grid-area: label; color: var(--po-ink2); }
    .po-bar-track { grid-area: bar; position: relative; height: 10px; }
    .po-bar-fill { position: absolute; inset: 0 auto 0 0; width: calc(var(--v) * 100%); border-radius: 0 3px 3px 0;
                   background: var(--po-chart-muted); }
    .po-bar-fill.is-key { background: var(--po-chart-ok); }
    .po-bar-value { grid-area: value; color: var(--po-ink); font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
    .po-terms { display: grid; gap: 1rem; margin: 1rem 0 0 !important; }
    .po-terms dt { color: var(--po-ink); font-size: 0.875rem; font-weight: 600; line-height: 1.5; }
    .po-terms dd { margin: 0.25rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    [class*="st-key-card_feat_"] { height: 100%; }
    .po-feature-level { margin: 1.25rem 0 0; color: var(--po-muted); font-size: 0.8125rem; font-weight: 500; }
    .po-feature h3 { margin: 0.25rem 0 0; padding: 0; color: var(--po-ink); font-size: 1.375rem; font-weight: 600;
                     line-height: 1.2; letter-spacing: -0.02em; }
    .po-feature > p { margin: 0.75rem 0 0; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.5; }
    .po-feature ul { display: grid; gap: 0.5rem; margin: 1.25rem 0 0 !important; padding: 1rem 0 0 !important;
                     list-style: none; border-top: 1px solid var(--po-line); font-size: 0.875rem; line-height: 1.5;
                     color: var(--po-ink); }
    .po-feature li { display: flex; gap: 0.5rem; margin: 0 !important; padding: 0 !important; }
    .po-feature li .po-icon { margin-top: 3px; color: var(--po-primary); }
    .po-methods { margin-top: 3rem; }
    .po-methods-title { margin: 0; color: var(--po-ink); font-size: 0.9375rem; font-weight: 600; }
    .po-methods ul { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr));
                     gap: 1rem 1.5rem; margin: 1rem 0 0 !important; padding: 0 !important; list-style: none; }
    .po-methods li { margin: 0 !important; padding: 0.75rem 0 0 !important; border-top: 1px solid var(--po-line-strong); }
    .po-who { display: block; color: var(--po-ink); font-size: 0.875rem; font-weight: 600; line-height: 1.5; }
    .po-what { display: block; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .st-key-po_footer { margin-top: 6rem; padding-top: 2rem; border-top: 1px solid var(--po-line); }
    .po-footer-about { margin: 0; max-width: 40rem; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-footer-meta { margin: 0.5rem 0 0; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    @media (max-width: 767.98px) {
        .po-landing-hero h1 { font-size: 2.5rem; }
        .po-section-head { margin-top: 4.5rem; }
        .po-section-head h2 { font-size: 2rem; }
        .st-key-card_auth { padding: 1.5rem; }
    }
    </style>""")
