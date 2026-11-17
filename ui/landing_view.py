"""Startseite für Abgemeldete: anmelden oder Konto erstellen, die Analyse am Beispiel, die Details.

Aufbau: Titel und Anmeldung, darunter die echte Klumpenrisiko-Karte als Produktbild, drei Zahlen aus
dem Beispiel und ein nüchternes Datenblatt statt Funktionskacheln. Alle Zahlen rechnet
``portfolio_optimizer`` mit dem fiktiven Beispieldepot der Offline-Demo; nichts ist ausgedacht.
"""

from __future__ import annotations

import os
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
    with st.container(key="po_stage"):  # nachtblaue Bühne mit Titel und Anmeldung
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
        st.html('<p class="po-landing-caption po-rise" style="--i: 2">Unten das fiktive Beispieldepot: '
                "Klumpenrisiko jetzt und nach der vorgeschlagenen Umschichtung. Schalte zwischen beiden "
                "Zuständen um.</p>")

    try:
        example = xray.cached_example(Settings().years)
    except Exception:  # pragma: no cover - die Offline-Demo braucht kein Netz
        example = None
    if example is not None:
        xray.card(example, "landing")  # ragt als Produktbild aus der Bühne heraus
        _numbers(example)
    _specs()
    _footer()


def _numbers(x: xray.XRay) -> None:
    """Drei Zahlen aus dem Beispiel, die ein Depotauszug nicht zeigt, auf einem warmen Band."""
    stats = []
    top = x.rows[0] if x.rows else None
    if top is not None and top.risk[0] is not None:
        stats.append((xray.count(top.risk[0] * 100, xray.pct_nb(top.risk[0]), 1, "\u00a0%", "stat-risk"),
                      f"der Schwankung entfallen auf {escape(top.label)} ({conc.KINDS[top.kind]}), bei "
                      f"{xray.pct_nb(top.weight[0])} Gewicht."))
    stats.append((f'{xray.count(x.effective[0], num(x.effective[0], 1), 1, key="stat-eff")}<small> von {x.positions[0]}</small>',
                  "Positionen wirken effektiv: So viele gleich große hätten dieselbe Konzentration."))
    stats.append((f'{xray.count(x.exceeded[0], str(x.exceeded[0]), 0, key="stat-limits")}<small><span aria-hidden="true"> → </span>'
                  f'<span class="po-sr">, danach </span>{x.exceeded[1]}</small>',
                  "überschrittene Grenzen, vor und nach der vorgeschlagenen Umschichtung."))
    cells = "".join(f'<div class="po-stat" data-po-reveal="stat-{i}" style="--i: {i}"><p class="po-stat-value">'
                    f'{value}</p><p class="po-stat-text">{text}</p></div>' for i, (value, text) in enumerate(stats))
    st.html(f'<section class="po-band po-band-warm"><h2 data-po-reveal="stats-head">Was ein Depotauszug nicht '
            f'zeigt</h2><div class="po-stat-row">{cells}</div></section>')


def _specs() -> None:
    rows = "".join(f'<div data-po-reveal="spec-{i}" style="--i: {i % 4}"><dt>{name}</dt><dd>{text}</dd></div>'
                   for i, (name, text) in enumerate(SPECS))
    st.html(f'<section class="po-band"><h2 data-po-reveal="specs-head">Im Detail</h2>'
            f'<dl class="po-specs">{rows}</dl></section>')


OWNER = "Valentin Siemke"
ADDRESS = "Kleine Fischerstraße 24  \n27283 Verden"
EMAIL = "valentins130@gmail.com"


def _mail_note() -> str:
    """Wer die E-Mails verschickt, je nach Einrichtung (``portfolio_optimizer/mailer.py``)."""
    if os.environ.get("RESEND_API_KEY"):
        return ("Den Versand übernimmt Resend (Resend, Inc., USA) in meinem Auftrag auf Grundlage eines Vertrags zur "
                "Auftragsverarbeitung; Resend erhält dabei deine E-Mail-Adresse und den Inhalt der Nachricht. Für die "
                "Übermittlung in die USA gelten die EU-Standardvertragsklauseln.")
    if os.environ.get("SMTP_HOST"):
        return (f"Den Versand übernimmt mein E-Mail-Anbieter ({os.environ['SMTP_HOST']}); er erhält dabei deine "
                "E-Mail-Adresse und den Inhalt der Nachricht.")
    return "Derzeit verschickt die Website keine E-Mails; schreib mir in dem Fall bitte eine E-Mail."


@st.dialog("Impressum", width="large")
def _imprint() -> None:
    st.markdown(
        f"**Angaben gemäß § 5 DDG**  \n{OWNER}  \n{ADDRESS}\n\n"
        f"**Kontakt**  \nE-Mail: [{EMAIL}](mailto:{EMAIL})\n\n"
        f"**Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV**  \n{OWNER}, Anschrift wie oben\n\n"
        "**Keine Anlageberatung**  \nDer Portfolio-Optimierer ist ein Analyse- und Lernwerkzeug. Seine Inhalte sind "
        "keine Anlageberatung und keine Aufforderung zum Kauf oder Verkauf von Wertpapieren. Alle Auswertungen "
        "beruhen auf historischen Daten und berücksichtigen weder Transaktionskosten noch Steuern."
    )


@st.dialog("Datenschutz", width="large")
def _privacy() -> None:
    st.caption("Stand: November 2026")
    st.markdown(
        f"**Verantwortlicher**  \n{OWNER}  \n{ADDRESS}  \nE-Mail: [{EMAIL}](mailto:{EMAIL})\n\n"
        "**Hosting**  \nDie Website läuft bei der Railway Corporation, 548 Market St PMB 68956, San Francisco, "
        "CA 94104, USA. Server und Speicher stehen in der EU (Amsterdam, Niederlande). Railway verarbeitet die Daten "
        "in meinem Auftrag auf Grundlage eines Vertrags zur Auftragsverarbeitung (Art. 28 DSGVO). Railway ist ein "
        "US-Unternehmen; ein Zugriff aus den USA, etwa für Wartung, ist nicht ausgeschlossen. Dafür gelten die "
        "EU-Standardvertragsklauseln (Art. 46 Abs. 2 lit. c DSGVO).\n\n"
        "**Server-Protokolle**  \nBeim Aufruf der Website verarbeitet Railway technisch notwendige Verbindungsdaten, "
        "darunter deine IP-Adresse, den Zeitpunkt und die aufgerufene Adresse. Die Protokolle werden nach 7 Tagen "
        "gelöscht. Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO; mein berechtigtes Interesse ist ein sicherer und "
        "stabiler Betrieb.\n\n"
        "**Konto**  \nFür ein Konto speichere ich deine E-Mail-Adresse, den Zeitpunkt der Registrierung und einen "
        "Hash deines Passworts (scrypt), nie das Passwort selbst. Rechtsgrundlage ist Art. 6 Abs. 1 lit. b DSGVO "
        "(Nutzungsvertrag). Die Daten bleiben gespeichert, bis du dein Konto löschst. Ohne E-Mail-Adresse und "
        "Passwort lässt sich kein Konto anlegen.\n\n"
        "**Schutz vor Fehlversuchen**  \nBei einer falschen Anmeldung speichere ich die eingegebene E-Mail-Adresse "
        "und den Zeitpunkt. Nach 5 Fehlversuchen ist die Anmeldung für diese Adresse 15 Minuten gesperrt. Danach "
        "werden die Einträge gelöscht, nach einer erfolgreichen Anmeldung sofort. Rechtsgrundlage ist Art. 6 Abs. 1 "
        "lit. f DSGVO; mein berechtigtes Interesse ist der Schutz der Konten vor dem Erraten von Passwörtern.\n\n"
        "**Deine Depots**  \nDepots, Transaktionen und Einstellungen liegen in einem eigenen Ordner deines Kontos auf "
        "dem Server, nur dein Konto greift darauf zu. Unter Konto → Konto löschen entfernst du Konto, Depots und "
        "Anmeldungen endgültig.\n\n"
        "**Cookies**  \nDie Website setzt nur technisch notwendige Cookies (§ 25 Abs. 2 Nr. 2 TDDDG):  \n"
        "• `_streamlit_xsrf` schützt vor gefälschten Anfragen (Cross-Site-Request-Forgery) und gilt bis zum "
        "Schließen des Browsers.  \n"
        "• `po_session` setzt die Seite nur, wenn du „Angemeldet bleiben“ wählst. Es enthält einen zufälligen "
        "Schlüssel, gilt 30 Tage und wird beim Abmelden ungültig.  \n"
        "Es gibt keine Werbe-, Analyse- oder Tracking-Cookies und keine Nutzungsstatistik. Schriften und Grafiken "
        "kommen vom eigenen Server.\n\n"
        "**Passwort vergessen**  \nAuf Wunsch schicke ich dir einen Link für ein neues Passwort an die E-Mail-Adresse "
        "deines Kontos. Gespeichert wird nur ein Hash des Links mit Ablaufzeit; nach einer Stunde oder sobald du ihn "
        f"benutzt hast, ist er ungültig und wird gelöscht. {_mail_note()} Rechtsgrundlage ist Art. 6 Abs. 1 lit. b "
        "DSGVO (Nutzungsvertrag).\n\n"
        "**Kurse von Yahoo Finance**  \nFür Kurse, Wechselkurse und Stammdaten fragt der Server bei Yahoo an. Dabei "
        "erhält Yahoo die angefragten Wertpapiere und die IP-Adresse des Servers, aber keine Angaben zu deiner "
        "Person.\n\n"
        "**Deine Rechte**  \nDu hast das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16), Löschung "
        "(Art. 17), Einschränkung der Verarbeitung (Art. 18) und Datenübertragbarkeit (Art. 20). Einer Verarbeitung "
        "nach Art. 6 Abs. 1 lit. f kannst du widersprechen (Art. 21). Schreib mir dafür eine E-Mail. Außerdem kannst "
        "du dich bei einer Datenschutz-Aufsichtsbehörde beschweren, zum Beispiel bei der Landesbeauftragten für den "
        "Datenschutz Niedersachsen. Eine automatisierte Entscheidungsfindung findet nicht statt."
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
    /* Bühne: nachtblaue Fläche mit indigofarbenem Schein, darin Titel und Anmeldung */
    .st-key-po_stage { position: relative; overflow: hidden; margin-top: -1.5rem; padding: 4.5rem 3.5rem 9rem;
                       border-radius: 32px;
                       background: radial-gradient(48rem 26rem at 8% -6%, var(--po-glow), transparent 64%),
                                   radial-gradient(34rem 22rem at 96% 108%, rgb(74 92 230 / 0.32), transparent 62%),
                                   var(--po-night); }
    .po-landing-hero h1 { margin: 0; padding: 0; max-width: 12em; color: var(--po-ink); font-size: 4rem;
                          font-weight: 560; line-height: 1.02; letter-spacing: -0.04em; text-wrap: balance; }
    .po-landing-lead { margin: 1.75rem 0 0; max-width: 34rem; color: var(--po-ink2); font-size: 1.25rem; line-height: 1.55; }
    .po-landing-meta { margin: 1.75rem 0 0 !important; color: var(--po-muted); font-size: 0.9375rem; line-height: 1.5; }
    .po-landing-caption { margin: 3rem 0 0; color: var(--po-muted); font-size: 0.9375rem; line-height: 1.5; }
    .st-key-card_auth { color: var(--po-ink); padding: 2rem; box-shadow: 0 30px 60px -24px rgb(0 0 0 / 0.55), 0 0 0 1px rgb(255 255 255 / 0.06); }
    /* Produktbild: die Analyse-Karte ragt aus der Bühne heraus */
    .st-key-card_landing { margin: -7.5rem 2.5rem 0; z-index: 2;
                           box-shadow: 0 40px 80px -32px var(--po-shadow-strong), 0 1px 2px var(--po-shadow); }

    /* Abschnitte darunter: Überschrift, Inhalt auf feinen Linien */
    .po-band { margin: 6rem 0 0; }
    .po-band h2 { margin: 0 0 2.25rem; padding: 0; max-width: 16em; color: var(--po-ink); font-size: 2.5rem;
                  font-weight: 560; line-height: 1.1; letter-spacing: -0.035em; text-wrap: balance; }
    /* warmes Band: unterbricht Weiß und Nachtblau, trägt die drei Zahlen */
    .po-band-warm { padding: 3.5rem 3.5rem 3.75rem; border-radius: 32px; background: var(--po-warm); }
    .po-stat-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 2.5rem; }
    .po-stat { padding-top: 1.25rem; border-top: 2px solid var(--po-primary); }
    .po-stat-value { margin: 0; color: var(--po-primary); font-size: 3.5rem; font-weight: 520; line-height: 1;
                     letter-spacing: -0.04em; white-space: nowrap; font-variant-numeric: tabular-nums; }
    .po-stat-value small { color: var(--po-muted); font-size: 1.25rem; font-weight: 450; letter-spacing: -0.01em; }
    .po-stat-text { margin: 0.875rem 0 0; max-width: 22rem; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.55; }
    .po-specs { margin: 0 !important; padding: 0 !important; border-bottom: 1px solid var(--po-line); }
    .po-specs > div { display: grid; grid-template-columns: 11rem minmax(0, 1fr); gap: 0.25rem 2rem;
                      padding: 1.25rem 0; border-top: 1px solid var(--po-line); }
    .po-specs dt { color: var(--po-ink); font-size: 0.9375rem; font-weight: 600; line-height: 1.5; }
    .po-specs dd { margin: 0; max-width: 46rem; color: var(--po-ink2); font-size: 0.9375rem; line-height: 1.55; }

    /* Fußzeile als nachtblaue Fläche: rahmt die Seite unten wie die Kopfzeile oben */
    .st-key-po_footer { margin-top: 6rem; padding: 2.5rem 3.5rem; border-radius: 32px; background: var(--po-night); }
    .po-footer-about { margin: 0; max-width: 40rem; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.55; }
    .po-footer-meta { margin: 0.5rem 0 0; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .st-key-po_footer [data-testid="stBaseButton-tertiary"], .st-key-po_footer [data-testid="stBaseButton-tertiary"] p {
        color: rgb(255 255 255 / 0.82) !important; }
    @media (hover: hover) {
        .st-key-po_footer [data-testid="stBaseButton-tertiary"]:hover p { color: #ffffff !important; } }
    @media (max-width: 767.98px) {
        .st-key-po_stage { margin-top: -2rem; padding: 2.5rem 1.25rem 7rem; border-radius: 24px; }
        .po-landing-hero h1 { font-size: 2.6rem; }
        .po-landing-lead { font-size: 1.125rem; }
        .st-key-card_auth { padding: 1.5rem; }
        .st-key-card_landing { margin: -5.5rem 0.5rem 0; }
        .po-band { margin-top: 4.5rem; }
        .po-band h2 { font-size: 1.875rem; }
        .po-band-warm { padding: 2.25rem 1.25rem; border-radius: 24px; }
        .po-stat-row { grid-template-columns: minmax(0, 1fr); gap: 2rem; }
        .po-stat-value { font-size: 3rem; }
        .po-specs > div { grid-template-columns: minmax(0, 1fr); }
        .st-key-po_footer { padding: 2rem 1.25rem; border-radius: 24px; }
    }
    </style>""")
