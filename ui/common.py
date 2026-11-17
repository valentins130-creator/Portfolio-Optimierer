"""Gemeinsame Bausteine der Oberfläche: Farbwelt, Bewegung, Abschnittswahl, Karten, Meldungen.

Gestaltung in zwei Welten, angelehnt an professionelle Finanz-Websites: Nachtblau rahmt und hebt hervor
(Kopfzeile, Bühne der Startseite, Depotwert), helles kühles Grau mit weißen Karten trägt die Arbeit.
Ein Indigo für alles, was man anklicken kann; Grün und Rot nur für Gewinne und Verluste, Bernstein nur
für überschrittene Grenzen. Tiefe entsteht aus Flächen und weichen, navyfarbenen Schatten.
"""

from __future__ import annotations

import json

import streamlit as st

from portfolio_optimizer import charts

# Jede Farbe gilt für hell und dunkel: Streamlit setzt das Farbschema (color-scheme) der App,
# light-dark() wählt daraus den passenden Wert. Kontraste geprüft (Text mindestens 4,5:1), Daten tragen
# die mit dem dataviz-Validator geprüfte Diagrammpalette (charts.py), Texte nie Datenfarben.
TOKENS = {
    "bg": ("#f4f6fb", "#090c16"),
    "card": ("#ffffff", "#121729"),
    "sunken": ("#eef1f7", "#1a2036"),
    "line": ("rgb(13 27 51 / 0.09)", "rgb(255 255 255 / 0.08)"),
    "line-strong": ("rgb(13 27 51 / 0.18)", "rgb(255 255 255 / 0.16)"),
    "ink": ("#0d1b33", "#eef1f8"),
    "ink2": ("#3a4660", "#c0c7d8"),
    "muted": ("#66718a", "#8d96ad"),
    "primary": ("#3846d6", "#9aa4ff"),  # Links, aktive Symbole, Zahlen in Markenfarbe
    "primary-fill": ("#4352e6", "#5563ee"),  # Flächen mit weißer Schrift
    "primary-tint": ("#eceefe", "rgb(104 116 242 / 0.16)"),  # zarte Fläche hinter Symbolen
    "accent": ("#d97000", "#d67600"),  # überschrittene Grenze (Fläche)
    "accent-text": ("#a85300", "#ffad42"),
    "accent-tint": ("#fdf1e3", "rgb(255 173 66 / 0.14)"),
    "up": ("#08784e", "#3ddc97"),
    "up-tint": ("#e6f5ee", "rgb(61 220 151 / 0.14)"),
    "down": ("#cc2338", "#ff6b7a"),
    "shadow": ("rgb(13 37 61 / 0.08)", "rgb(0 0 0 / 0.45)"),
    "shadow-strong": ("rgb(13 37 61 / 0.16)", "rgb(0 0 0 / 0.6)"),
    "edge": ("transparent", "rgb(255 255 255 / 0.04)"),
    # Nachtflächen, in beiden Modi dunkel: Kopfzeile, Bühne der Startseite, Depotwert
    "night": ("#0c1430", "#111a3a"),
    "night-raised": ("#16204a", "#1a2550"),
    "glow": ("rgb(91 106 240 / 0.5)", "rgb(91 106 240 / 0.4)"),
    "warm": ("#f7f1e7", "#10162c"),  # warmes Zwischenband der Startseite
    # Balken (Palette mit dem dataviz-Validator geprüft)
    "chart-ok": ("#4352e6", "#6874f2"),
    "chart-warn": ("#d97000", "#d67600"),
    "chart-track": ("#e6e9f2", "#232a42"),
    "chart-muted": ("#a3abc0", "#4d5672"),
}

# Text auf Nachtflächen (überschreibt die Tokens darin; Kontraste gegen #0c1430 und #111a3a geprüft)
NIGHT_TOKENS = ("--po-ink: #ffffff; --po-ink2: rgb(255 255 255 / 0.74); --po-muted: rgb(255 255 255 / 0.6); "
                "--po-line: rgb(255 255 255 / 0.12); --po-line-strong: rgb(255 255 255 / 0.22); "
                "--po-up: #4fe0a3; --po-down: #ff8a96; --po-primary: #a9b2ff; --po-sunken: rgb(255 255 255 / 0.06); "
                "--po-card: var(--po-night); --po-chart-track: rgb(255 255 255 / 0.1); color: #ffffff;")


def is_dark() -> bool:
    return st.context.theme.type == "dark"


def theme() -> charts.Theme:
    """Diagrammfarben passend zum hellen oder dunklen Design der App."""
    return charts.get_theme(is_dark())


def css_tokens() -> str:
    return " ".join(f"--po-{name}: light-dark({light}, {dark});" for name, (light, dark) in TOKENS.items())


def inject_style() -> None:
    st.html(f"""<style>
    .stApp, .st-key-card_auth {{ {css_tokens()} }}
    /* Nachtflächen: Text, Linien und Gewinn/Verlust-Farben für dunklen Grund */
    .po-night, .st-key-card_value, .st-key-card_hero, .st-key-po_stage, .st-key-po_footer {{ {NIGHT_TOKENS} }}

    /* Kopfzeile in Nachtblau, wie bei Banken üblich: rahmt die App und trennt sie von der Arbeitsfläche */
    header[data-testid="stHeader"] {{ background: var(--po-night); border-bottom: 1px solid rgb(255 255 255 / 0.06); }}
    header[data-testid="stHeader"] button, header[data-testid="stHeader"] [data-testid="stIconMaterial"] {{
        color: rgb(255 255 255 / 0.82) !important; }}
    [data-testid="stTopNavLink"] {{ border-radius: 999px; transition: background-color 150ms ease; }}
    [data-testid="stTopNavLink"] p {{ color: rgb(255 255 255 / 0.72) !important; font-weight: 500; }}
    [data-testid="stTopNavLink"]:hover {{ background: rgb(255 255 255 / 0.08) !important; }}
    [data-testid="stTopNavLink"]:hover p, [data-testid="stTopNavLink"][aria-current="page"] p {{ color: #ffffff !important; }}
    [data-testid="stTopNavLink"][aria-current="page"] {{ background: rgb(255 255 255 / 0.14) !important; }}
    /* Hauptmenü (⋮): nur Hell, Dunkel, System; ohne Drucken, Bildschirmaufnahme und Versionszeile */
    [data-testid="stMainMenuItem-print"], [data-testid="stMainMenuItem-recordScreencast"],
    [data-testid="stMainMenuPopover"] [data-testid="stMainMenuDivider"],
    [data-testid="stMainMenuPopover"] [data-testid="stMainMenuList"] ~ div {{ display: none !important; }}
    /* Bildmarke als Bild, Name als echter Text */
    :has(> img[data-testid="stHeaderLogo"]) {{
        display: flex; align-items: center; gap: 0.75rem; width: auto !important; max-width: none !important; }}
    :has(> img[data-testid="stHeaderLogo"])::after {{
        content: "Portfolio-Optimierer"; color: #ffffff; font-weight: 600; font-size: 1.05rem; letter-spacing: -0.01em;
        white-space: nowrap; }}
    @media (max-width: 767.98px) {{ :has(> img[data-testid="stHeaderLogo"])::after {{ display: none; }} }}
    [data-testid="stMainBlockContainer"] {{ padding-top: 5rem; padding-bottom: 5rem; max-width: 1180px; }}

    h1, h2, h3, h4 {{ color: var(--po-ink); letter-spacing: -0.02em; text-wrap: balance; }}
    .po-num, .po-value, [data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
    /* unsichtbare Rahmen: setzen nur das Cookie bzw. Sprache, Browserfarbe und Bewegung */
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

    /* Buttons: Hauptaktion in Indigo mit weichem Schatten, beim Überfahren 1 px höher, beim Klicken gedrückt */
    [data-testid^="stBaseButton"] {{ transition: transform 150ms cubic-bezier(0.16, 1, 0.3, 1), background-color 150ms ease,
                                     border-color 150ms ease, color 150ms ease; }}
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
        box-shadow: 0 1px 2px rgb(13 27 51 / 0.18), 0 8px 20px -10px var(--po-primary-fill); }}
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] p,
    [data-testid="stBaseButton-primaryFormSubmit"], [data-testid="stBaseButton-primaryFormSubmit"] p {{ color: #ffffff; }}
    [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"] {{
        border-color: var(--po-line-strong); }}
    @media (hover: hover) {{
        [data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
            transform: translateY(-1px); box-shadow: 0 2px 4px rgb(13 27 51 / 0.2), 0 12px 24px -10px var(--po-primary-fill); }}
        [data-testid="stBaseButton-secondary"]:hover, [data-testid="stBaseButton-secondaryFormSubmit"]:hover {{
            border-color: var(--po-primary); color: var(--po-primary); }}
    }}
    [data-testid^="stBaseButton"]:active {{ transform: scale(0.98); }}

    /* Segment-Schalter wie bei Apple: Schiene in Grau, eine helle Markierung gleitet zum gewählten Abschnitt
       (Lage setzt das Skript aus page_meta als CSS-Variablen; ohne Skript trägt der Knopf selbst die Fläche) */
    [data-testid="stButtonGroup"] > div:has(> button[data-variant="segmented_control"]) {{
        position: relative; gap: 0.25rem; padding: 0.25rem; border-radius: 999px; background: var(--po-sunken);
        border: 1px solid var(--po-line); width: fit-content; max-width: 100%; flex-wrap: wrap; }}
    button[data-variant="segmented_control"] {{
        position: relative; z-index: 1; min-height: 2.75rem; padding: 0 1.1rem; border: 0 !important;
        border-radius: 999px !important; background: transparent !important; color: var(--po-ink2) !important;
        box-shadow: none; transition: background-color 150ms ease, color 150ms ease; }}
    button[data-variant="segmented_control"] p {{ font-weight: 500; }}
    @media (hover: hover) {{
        button[data-variant="segmented_control"]:not([aria-checked="true"]):hover {{ color: var(--po-ink) !important; }}
    }}
    button[data-variant="segmented_control"][aria-checked="true"] {{
        background: var(--po-card) !important; color: var(--po-ink) !important;
        box-shadow: 0 1px 3px var(--po-shadow), 0 0 0 1px var(--po-line); }}
    [data-testid="stButtonGroup"] > div[style*="--po-tw"]::before {{
        content: ""; position: absolute; left: 0; top: 0; width: var(--po-tw); height: var(--po-th);
        transform: translate(var(--po-tx), var(--po-ty)); border-radius: 999px; background: var(--po-card);
        box-shadow: 0 1px 3px var(--po-shadow), 0 0 0 1px var(--po-line); pointer-events: none;
        /* Breite gleitet mit: ein einzelnes, frei liegendes Element, kein Seitenumbruch */
        transition: transform var(--po-td, 0ms) cubic-bezier(0.16, 1, 0.3, 1),
                    width var(--po-td, 0ms) cubic-bezier(0.16, 1, 0.3, 1), height var(--po-td, 0ms) ease; }}
    [data-testid="stButtonGroup"] > div[style*="--po-tw"] > button[aria-checked="true"] {{
        background: transparent !important; box-shadow: none !important; }}
    button[data-variant="segmented_control"]:focus-visible {{ outline: 2px solid var(--po-primary); outline-offset: 2px; }}
    /* Handy: gleich breite Felder im Raster statt einer umbrechenden Pille */
    @media (max-width: 767.98px) {{
        .stElementContainer:has(> [data-testid="stButtonGroup"] button[data-variant="segmented_control"]),
        [data-testid="stButtonGroup"]:has(> div > button[data-variant="segmented_control"]) {{ width: 100% !important; }}
        [data-testid="stButtonGroup"] > div:has(> button[data-variant="segmented_control"]) {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); width: 100%;
            border-radius: 26px; }}
        button[data-variant="segmented_control"] {{ padding: 0 0.75rem; }}
        /* lange Beschriftungen („Nach Umschichtung“) umbrechen statt mit „…“ abgeschnitten zu werden */
        button[data-variant="segmented_control"], button[data-variant="segmented_control"] * {{
            white-space: normal !important; text-overflow: clip !important; }}
        button[data-variant="segmented_control"] p {{ line-height: 1.2; text-align: center; text-wrap: balance; }}
    }}

    /* Karten: weiße Flächen mit weichem, navyfarbenem Schatten statt harter Rahmen. Sie reagieren auf die
       Maus: heben sich an, die Kante färbt sich leicht indigo, ein tieferer Schatten blendet ein. */
    [class*="st-key-card_"], .po-card, [data-testid="stMetric"], [data-testid="stExpander"] details {{
        position: relative; background: var(--po-card); border: 1px solid var(--po-line); border-radius: 20px;
        box-shadow: 0 1px 2px var(--po-shadow), 0 6px 20px -12px var(--po-shadow-strong), inset 0 1px 0 var(--po-edge);
        transition: transform 300ms cubic-bezier(0.16, 1, 0.3, 1), border-color 200ms ease; }}
    [class*="st-key-card_"] {{ padding: 1.5rem; }}
    [class*="st-key-card_"]::after, .po-card::after, [data-testid="stMetric"]::after {{
        content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
        box-shadow: 0 22px 48px -20px var(--po-shadow-strong); opacity: 0; transition: opacity 300ms ease; }}
    @media (hover: hover) {{
        [class*="st-key-card_"]:hover, .po-card:hover, [data-testid="stMetric"]:hover {{
            transform: translateY(-3px); border-color: color-mix(in srgb, var(--po-primary) 30%, var(--po-line)); }}
        [class*="st-key-card_"]:hover::after, .po-card:hover::after, [data-testid="stMetric"]:hover::after {{ opacity: 1; }}
    }}
    /* Nachtkarten (Depotwert): Nachtblau mit indigofarbenem Schein oben rechts */
    .st-key-card_value, .st-key-card_hero {{
        background: radial-gradient(42rem 22rem at 105% -10%, var(--po-glow), transparent 62%), var(--po-night);
        border-color: rgb(255 255 255 / 0.08); }}
    @media (hover: hover) {{ .st-key-card_value:hover, .st-key-card_hero:hover {{ border-color: rgb(255 255 255 / 0.2); }} }}
    [data-testid="stExpander"] details {{ border-radius: 14px; }}
    [data-testid="stExpander"] summary p {{ font-weight: 600; color: var(--po-ink); }}
    [data-testid="stExpanderIcon"] {{ color: var(--po-primary); }}

    /* Kennzahlen: ruhige Beschriftung, große Zahl */
    [data-testid="stMetric"] {{ padding: 1rem 1.25rem; }}
    [data-testid="stMetricLabel"] p {{ color: var(--po-muted); font-size: 0.875rem; }}
    [data-testid="stMetricValue"] > div {{ font-weight: 600; letter-spacing: -0.02em; }}

    /* Tabellen in einer ruhigen Fläche */
    [data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; }}

    /* Depotwert */
    .po-hero {{ margin: 0 0 0.5rem; }}
    .po-hero .po-label {{ color: var(--po-muted); font-size: 0.875rem; font-weight: 500; }}
    .po-hero .po-value {{ color: var(--po-ink); font-size: 3.4rem; font-weight: 560; line-height: 1.05;
                         letter-spacing: -0.035em; }}
    /* Teile umbrechen als Ganzes; der Trennpunkt sitzt in der Lücke und fällt am Zeilenanfang weg
       (er liegt dort links außerhalb und wird abgeschnitten) */
    .po-hero .po-sub {{ display: flex; flex-wrap: wrap; column-gap: 1.1rem; overflow: hidden; color: var(--po-ink2);
                       font-size: 0.9375rem; line-height: 1.5; margin-top: 0.5rem; }}
    .po-hero .po-sub > span {{ position: relative; white-space: nowrap; }}
    .po-hero .po-sub > span + span::before {{ content: "·"; content: "·" / ""; position: absolute; left: -0.72rem;
                                              color: var(--po-muted); }}
    .po-up {{ color: var(--po-up); font-weight: 600; }}
    .po-down {{ color: var(--po-down); font-weight: 600; }}

    /* Seitenkopf: kleine Zeile darüber, große Überschrift */
    .po-page-head {{ margin: 0 0 1.5rem; }}
    .po-page-head .po-eyebrow {{ margin: 0 0 0.25rem; color: var(--po-primary); font-size: 0.875rem; font-weight: 600; }}
    .po-page-head h1 {{ margin: 0; padding: 0; font-size: 2.75rem; font-weight: 560; line-height: 1.08;
                       letter-spacing: -0.035em; color: var(--po-ink); }}
    .po-page-head p.po-intro {{ margin: 0.75rem 0 0; max-width: 60ch; color: var(--po-ink2); font-size: 1.0625rem;
                               line-height: 1.5; }}
    .po-sub-head {{ margin: 2.5rem 0 0.5rem; }}
    .po-sub-head h2 {{ margin: 0; padding: 0; font-size: 1.5rem; font-weight: 580; line-height: 1.2;
                      letter-spacing: -0.02em; color: var(--po-ink); }}
    .po-sub-head p.po-intro {{ margin: 0.5rem 0 0; max-width: 65ch; color: var(--po-ink2); font-size: 0.9375rem;
                              line-height: 1.5; }}
    @media (max-width: 767.98px) {{ .po-page-head h1 {{ font-size: 2.125rem; }} .po-hero .po-value {{ font-size: 2.6rem; }} }}

    /* Symbol in einer zarten Fläche (Schnellzugriff, Einstiege): gibt Listen Farbe und Halt */
    .po-tile {{ display: inline-grid; place-items: center; width: 2.5rem; height: 2.5rem; border-radius: 12px;
               background: var(--po-primary-tint); color: var(--po-primary); flex: none; }}
    /* Zustand als kleines Etikett mit Symbol und Wort, nie nur Farbe */
    .po-chip {{ display: inline-flex; align-items: center; gap: 0.25rem; padding: 0.125rem 0.5rem; border-radius: 999px;
               font-size: 0.75rem; font-weight: 600; line-height: 1.5; white-space: nowrap; }}
    .po-chip.is-over {{ background: var(--po-accent-tint); color: var(--po-accent-text); }}
    .po-chip.is-ok {{ background: var(--po-up-tint); color: var(--po-up); }}
    .po-chip.is-near {{ background: var(--po-sunken); color: var(--po-ink2); }}

    /* Mehrere Angaben in einer Zeile, getrennt durch Punkte (wie beim Depotwert) */
    .po-dots {{ display: flex; flex-wrap: wrap; column-gap: 1.1rem; overflow: hidden; }}
    .po-dots > span {{ position: relative; white-space: nowrap; }}
    .po-dots > span + span::before {{ content: "·"; content: "·" / ""; position: absolute; left: -0.72rem;
                                     color: var(--po-muted); }}
    /* nur für Screenreader */
    .po-sr {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }}

    /* Bewegung mit Zweck. App: 300 ms, sanft auslaufend, nur transform und opacity; neue Inhalte steigen beim
       Erscheinen auf, Balken wachsen, Kurven zeichnen sich. Startseite (Werbefläche, bewusste Ausnahme):
       Abschnitte blenden beim Scrollen in 500 ms ein, Kennzahlen zählen einmal hoch. Alles nur beim ersten
       Zeichnen, nicht bei jedem Klick; bei „Bewegung reduzieren“ aus. */
    @keyframes po-rise {{ from {{ opacity: 0; transform: translateY(8px); }} }}
    @keyframes po-grow {{ from {{ transform: translateX(-100%); }} }}
    @keyframes po-draw {{ from {{ clip-path: inset(0 100% 0 0); }} }}
    .po-page-head, .po-hero, [class*="st-key-card_"], .po-rise {{
        animation: po-rise 300ms cubic-bezier(0.16, 1, 0.3, 1) backwards; animation-delay: calc(var(--i, 0) * 60ms); }}
    html.po-js [data-po-reveal] {{ transition: opacity 500ms ease-out, transform 500ms cubic-bezier(0.16, 1, 0.3, 1);
                                   transition-delay: calc(var(--i, 0) * 90ms); }}
    html.po-js [data-po-reveal]:not(.is-in) {{ opacity: 0; transform: translateY(18px); }}
    html.po-js [data-po-reveal].is-instant {{ transition: none; }}

    @media (prefers-reduced-motion: reduce) {{
        [class*="st-key-card_"], .po-card, [data-testid="stMetric"], [data-testid^="stBaseButton"] {{ transition: none; }}
        [class*="st-key-card_"]:hover, .po-card:hover, [data-testid="stMetric"]:hover,
        [data-testid^="stBaseButton"]:hover, [data-testid^="stBaseButton"]:active {{ transform: none; }}
        [class*="po-"], [class*="po-"]::before, [class*="po-"]::after, [class*="st-key-card_"], [data-po-reveal],
        [data-testid="stButtonGroup"] > div::before {{ animation: none !important; transition: none !important; }}
        html.po-js [data-po-reveal]:not(.is-in) {{ opacity: 1; transform: none; }}
    }}
    </style>""")


# Läuft einmal in der Seite selbst (nicht im unsichtbaren Rahmen, der bei jedem Neuladen neu entsteht).
# Ohne Skript bleibt alles sichtbar und statisch: Verstecken vor dem Einblenden setzt die Klasse po-js voraus.
MOTION_JS = """
(function () {
  if (window.__poMotion) return;
  window.__poMotion = true;
  var doc = document, reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  doc.documentElement.classList.add('po-js');

  // E-Mail-Felder: E-Mail-Tastatur, ohne Großschreibung, Autokorrektur und Rechtschreibprüfung
  function fixEmail() {
    doc.querySelectorAll('input[autocomplete="email"]:not([inputmode])').forEach(function (el) {
      el.name = 'email'; el.inputMode = 'email'; el.spellcheck = false;
      el.setAttribute('autocapitalize', 'none'); el.setAttribute('autocorrect', 'off');
    });
  }

  // Segment-Schalter: die helle Markierung gleitet zum gewählten Abschnitt
  var placed = new WeakSet(), instant = false;
  function placeThumbs() {
    doc.querySelectorAll('[data-testid="stButtonGroup"] > div').forEach(function (rail) {
      var active = rail.querySelector(':scope > button[data-variant="segmented_control"][aria-checked="true"]');
      if (!active) { rail.style.removeProperty('--po-tw'); return; }
      var r = rail.getBoundingClientRect(), a = active.getBoundingClientRect();
      if (!a.width || !r.width) return;
      var slide = placed.has(rail) && !instant && !reduce.matches;
      rail.style.setProperty('--po-td', slide ? '300ms' : '0ms');
      rail.style.setProperty('--po-tx', (a.left - r.left - rail.clientLeft) + 'px');
      rail.style.setProperty('--po-ty', (a.top - r.top - rail.clientTop) + 'px');
      rail.style.setProperty('--po-th', a.height + 'px');
      rail.style.setProperty('--po-tw', a.width + 'px');
      placed.add(rail);
    });
    instant = false;
  }

  // Zahlen zählen einmal hoch (deutsches Format), sobald sie zu sehen sind; danach steht der echte Text
  var counted = new Set();
  function count(el) {
    var key = el.dataset.poKey || '', target = parseFloat(el.dataset.poCount);
    if (reduce.matches || !isFinite(target) || (key && counted.has(key))) return;
    if (key) counted.add(key);
    var digits = +(el.dataset.poDigits || 0), suffix = el.dataset.poSuffix || '', final = el.textContent;
    var fmt = new Intl.NumberFormat('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
    var start = performance.now(), duration = 900;
    function tick(now) {
      var p = Math.min(1, (now - start) / duration), e = 1 - Math.pow(1 - p, 3);
      el.textContent = p < 1 ? fmt.format(target * e) + suffix : final;
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  // Einblenden beim Scrollen: einmal je Abschnitt, bei erneutem Zeichnen sofort sichtbar
  var shown = new Set();
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var el = entry.target;
      io.unobserve(el);
      if (el.hasAttribute('data-po-reveal')) {
        el.classList.add('is-in');
        el.querySelectorAll('[data-po-count]').forEach(count);
      } else {
        count(el);
      }
    });
  }, { threshold: 0.2 });
  function scan() {
    doc.querySelectorAll('[data-po-reveal]:not([data-po-watched])').forEach(function (el) {
      el.setAttribute('data-po-watched', '');
      var id = el.dataset.poReveal;
      if (reduce.matches || shown.has(id)) { el.classList.add('is-in', 'is-instant'); return; }
      shown.add(id);
      io.observe(el);
    });
    doc.querySelectorAll('[data-po-count]:not([data-po-watched])').forEach(function (el) {
      el.setAttribute('data-po-watched', '');
      if (!el.closest('[data-po-reveal]')) io.observe(el);
    });
  }

  var queued = 0;
  function update() {
    if (queued) return;
    queued = requestAnimationFrame(function () { queued = 0; fixEmail(); placeThumbs(); scan(); });
  }
  new MutationObserver(update).observe(doc.body, { childList: true, subtree: true, attributes: true,
                                                   attributeFilter: ['aria-checked'] });
  window.addEventListener('resize', function () { instant = true; update(); });
  if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(function () { instant = true; update(); });
  update();
})();
"""


def page_meta() -> None:
    """Sprache, Browserfarbe, E-Mail-Felder und Bewegung der Seite einrichten; Streamlit bietet dafür keine Option.

    ``lang="de"``: Screenreader lesen deutsch vor, der Browser bietet keine Übersetzung an. ``theme-color``
    färbt die Browserleiste auf dem Handy wie die nachtblaue Kopfzeile. Das Bewegungsskript (``MOTION_JS``)
    hängt sich einmal in die Seite: gleitende Markierung der Segment-Schalter, Einblenden beim Scrollen,
    hochzählende Zahlen, E-Mail-Tastatur in E-Mail-Feldern.
    """
    night = TOKENS["night"][1 if is_dark() else 0]
    with st.container(key="po_meta"):
        st.iframe(f"""<script>
        const doc = window.parent.document;
        doc.documentElement.lang = "de";
        let meta = doc.querySelector('meta[name="theme-color"]');
        if (!meta) {{ meta = doc.createElement("meta"); meta.name = "theme-color"; doc.head.appendChild(meta); }}
        meta.content = "{night}";
        if (!window.parent.__poMotion) {{
            const script = doc.createElement("script");
            script.textContent = {json.dumps(MOTION_JS)};
            doc.head.appendChild(script);
        }}
        </script>""", width=1, height=1, tab_index=-1)


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
