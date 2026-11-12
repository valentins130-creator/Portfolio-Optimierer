"""Startseite: was die App kann und wie es um das gewählte Depot steht.

Nichts auf dieser Seite ist ausgedacht. Die Karte im Kopf zeigt das Klumpenrisiko des gewählten
Depots – oder des fiktiven Beispieldepots, solange das eigene leer ist –, jetzt und nach der
Umschichtung, die die Ebene Lösungen mit ihren Standardeinstellungen vorschlägt.
"""

from __future__ import annotations

import hashlib
import math
from urllib.parse import quote
from dataclasses import dataclass
from datetime import date
from html import escape

import streamlit as st

from portfolio_optimizer import concentration as conc
from portfolio_optimizer import hedging as hg
from portfolio_optimizer import rebalancing as rb
from portfolio_optimizer.formatting import num, pct
from ui import header
from ui.common import show_flash
from ui.solutions_view import limits_plan, prices_for
from ui.state import (
    PortfolioContext,
    RunState,
    Settings,
    current_limits,
    example_portfolio,
    load_context,
)

PAGES = {"portfolio": "views/portfolio.py", "analysen": "views/analysen.py", "loesungen": "views/loesungen.py"}
CURRENCIES = {"USD": "US-Dollar", "GBP": "Britisches Pfund", "CHF": "Schweizer Franken", "JPY": "Japanischer Yen",
              "DKK": "Dänische Krone", "SEK": "Schwedische Krone", "NOK": "Norwegische Krone",
              "CAD": "Kanadischer Dollar", "AUD": "Australischer Dollar", "HKD": "Hongkong-Dollar"}
STATUS = {"over": "über Grenze", "near": "nahe Grenze", "ok": "im Rahmen"}
VIEWS = ("Jetzt", "Nach Umschichtung")

# Einfache Strich-Symbole (24er Raster), Farbe über currentColor
ICONS = {
    "check": '<path d="M5 12.5 9.5 17 19 7.5"/>',
    "over": '<path d="M10.3 4.3 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"/>'
            '<path d="M12 9.5v4M12 17h.01"/>',
    "near": '<path d="M4 17a8 8 0 0 1 16 0"/><path d="m12 17 4-5"/>',
    "ledger": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h4"/>'
              '<path d="m8 17.5 2.5-2.5 2 2 3.5-3.5"/>',
    "frontier": '<path d="M4 4v16h16"/><path d="M7.5 17C9 11 12.5 7.5 19 7"/>'
                '<circle cx="12.2" cy="10.3" r="1.8" fill="currentColor" stroke="none"/>',
    "swap": '<path d="M4 8h14"/><path d="m15 5 3 3-3 3"/><path d="M20 16H6"/><path d="m9 13-3 3 3 3"/>',
}


def _icon(name: str, cls: str = "po-icon") -> str:
    """Symbol als Fläche in Textfarbe; die Form kommt als SVG-Maske aus dem Stylesheet (_icon_css)."""
    return f'<span class="{cls} po-i-{name}" aria-hidden="true"></span>'


def _icon_css() -> str:
    rules = []
    for name, shape in ICONS.items():
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
               f"stroke-width='1.75' stroke-linecap='round' stroke-linejoin='round'>{shape.replace(chr(34), chr(39))}</svg>")
        rules.append(f'.po-i-{name} {{ --po-shape: url("data:image/svg+xml,{quote(svg)}"); }}')
    return "\n".join(rules)


def _pct(x: float | None, digits: int = 1) -> str:
    """Prozent mit geschütztem Leerzeichen, damit „51,5 %“ nicht umbricht."""
    return pct(x, digits).replace(" ", " ")


def _eur(x: float) -> str:
    return f"{num(x, 2)} €"


# ---------------------------------------------------------------------------
# Daten der Kopfkarte: Klumpenrisiko jetzt und nach der Umschichtung
# ---------------------------------------------------------------------------


@dataclass
class Row:
    kind: str
    group: str
    limit: float
    weight: tuple[float, float]  # jetzt, nach Umschichtung
    risk: tuple[float | None, float | None]
    status: tuple[str, str]  # over / near / ok

    @property
    def label(self) -> str:
        return CURRENCIES.get(self.group, self.group) if self.kind == "currency" else self.group


@dataclass
class XRay:
    title: str
    subtitle: str
    example: bool
    note: str | None  # warum das Beispieldepot erscheint
    positions: tuple[int, int]
    exceeded: tuple[int, int]
    effective: tuple[float, float]
    rows: list[Row]
    sells: tuple[int, float]
    buys: tuple[int, float]
    remaining: dict
    years: int


def _status(finding: conc.Finding | None) -> str:
    if finding is None or not finding.exceeded and finding.status == "ok":
        return "ok"
    return "over" if finding.exceeded else "near"


def _risk(finding: conc.Finding | None) -> float | None:
    if finding is None:
        return 0.0
    return finding.risk_share if math.isfinite(finding.risk_share) else None


def _rows(before: conc.ConcentrationReport, after: conc.ConcentrationReport, limit: int = 5) -> list[Row]:
    """Die auffälligsten Einzelwerte, Sektoren und Währungen: Überschreitungen zuerst, nach Überhang."""
    later = {(f.kind, f.group): f for f in after.findings}
    candidates = [f for f in before.findings if f.kind in ("position", "sector", "currency")]
    exceeded = sorted((f for f in candidates if f.exceeded), key=lambda f: f.excess, reverse=True)
    rest = sorted((f for f in candidates if not f.exceeded), key=lambda f: f.weight / f.limit, reverse=True)
    rows = []
    for f in (exceeded + rest)[:limit]:
        g = later.get((f.kind, f.group))
        rows.append(Row(f.kind, f.group, f.limit, (f.weight, g.weight if g else 0.0), (_risk(f), _risk(g)),
                        (_status(f), _status(g))))
    return rows


def _analyse(ctx: PortfolioContext, limits: conc.Limits, years: int, title: str, subtitle: str,
             example: bool, note: str | None) -> XRay:
    before = conc.analyze(ctx.weights, ctx.infos, ctx.weekly, limits)
    target, infos, prices, remaining = limits_plan(ctx, before, limits)
    tr = rb.trades(ctx.valued, target, prices, whole_shares=True, min_trade=50.0, sale_gain=ctx.portfolio.sale_gain)
    held_after = tr["weight_after"][tr["weight_after"] > 0]
    after = conc.analyze(held_after, infos, hg.weekly_returns(prices_for(ctx, held_after.index, infos)), limits)
    sells, buys = tr[tr["amount"] < 0], tr[tr["amount"] > 0]
    return XRay(
        title=title, subtitle=subtitle, example=example, note=note,
        positions=(len(ctx.weights), len(held_after)),
        exceeded=(len(before.exceeded), len(after.exceeded)),
        effective=(before.effective_positions, after.effective_positions),
        rows=_rows(before, after),
        sells=(len(sells), float(-sells["amount"].sum())), buys=(len(buys), float(buys["amount"].sum())),
        remaining=remaining, years=years,
    )


def _analysable(ctx: PortfolioContext) -> bool:
    return ctx.value > 0 and ctx.weekly.dropna().shape[0] >= 10


def _xray(run: RunState) -> XRay:
    """Eigenes Depot, sobald es Positionen mit Kurshistorie hat, sonst das Beispieldepot der Offline-Demo.

    Das Ergebnis bleibt in der Sitzung gespeichert, solange sich Depot, Grenzen und Zeitraum nicht ändern;
    so rechnet das Umschalten zwischen „Jetzt“ und „Nach Umschichtung“ nichts neu.
    """
    ctx, limits, years = run.ctx, current_limits(), run.settings.years
    own = _analysable(ctx)
    source = ctx.portfolio.to_json() if own else "beispiel"
    key = hashlib.sha1(f"{ctx.provider}|{source}|{limits}|{years}|{date.today()}".encode()).hexdigest()
    memo = st.session_state.get("_start_xray")
    if memo and memo[0] == key:
        return memo[1]
    if own:
        n = len(ctx.weights)
        x = _analyse(ctx, limits, years, title=ctx.portfolio.name,
                     subtitle=f"{n} {'Position' if n == 1 else 'Positionen'} · {num(ctx.value)} €",
                     example=False, note=None)
    else:
        note = ("Dein Depot ist noch leer." if not ctx.portfolio.positions
                else "Dein Depot hat noch zu wenig Kurshistorie für die Analyse.")
        settings = Settings(provider="demo", years=years)
        example = load_context(settings, portfolio=example_portfolio("demo"))
        n = len(example.weights)
        x = _analyse(example, limits, years, title="Beispieldepot",
                     subtitle=f"{n} Positionen · rund {num(round(example.value, -1))} € · fiktive Werte",
                     example=True, note=note)
    st.session_state["_start_xray"] = (key, x)
    return x


# ---------------------------------------------------------------------------
# Darstellung
# ---------------------------------------------------------------------------


def _go(page: str, section: str | None = None) -> None:
    """Zur Ebene wechseln und den passenden Abschnitt gleich aufgeklappt zeigen."""
    if section:
        st.session_state[section] = True
    st.switch_page(PAGES[page])


def _try_demo() -> None:
    header.use_provider("demo")
    header.load_example("demo")


def _hero(run: RunState, x: XRay) -> None:
    left, right = st.columns([1, 1], gap="large", vertical_alignment="center")
    with left:
        st.html(
            '<div class="po-start-hero">'
            '<p class="po-eyebrow">Depot-Analyse für Privatanleger</p>'
            "<h1>Sieh, wo dein Depot wirklich Risiko trägt.</h1>"
            '<p class="po-lead">Der Portfolio-Optimierer zerlegt dein Depot nach Aktien, Sektoren und Währungen. '
            "Er zeigt, woher die Schwankung kommt, und rechnet Umschichtungen durch, die deine eigenen Grenzen "
            "einhalten.</p></div>"
        )
        with st.container(horizontal=True, gap="small", key="po_cta"):
            if not x.example:
                if st.button("Depot prüfen", type="primary", icon=":material/troubleshoot:"):
                    _go("analysen", "sec_cluster")
                if st.button("Umschichtung ansehen", icon=":material/swap_horiz:"):
                    _go("loesungen", "sec_rebalance")
            else:
                if st.button("Depot erfassen", type="primary", icon=":material/add_circle:"):
                    _go("portfolio", "sec_add")
                if run.ctx.provider == "demo":
                    st.button("Beispieldepot laden", icon=":material/folder_open:", on_click=header.load_example,
                              args=("demo",))
                else:
                    st.button("Offline-Demo ausprobieren", icon=":material/science:", on_click=_try_demo,
                              help="Wechselt zu fiktiven Wertpapieren und lädt das Beispieldepot. Zurück zu echten "
                                   "Kursen geht es unter Einstellungen → Marktdaten.")
        st.html(
            '<ul class="po-facts">'
            f"<li>{_icon('check')}<span>Analyse- und Lernwerkzeug, keine Anlageberatung</span></li>"
            f"<li>{_icon('check')}<span>Depots werden lokal als Datei gespeichert</span></li>"
            f"<li>{_icon('check')}<span>Methoden nach Markowitz, Ledoit-Wolf und Bayes-Stein</span></li>"
            "</ul>"
        )
    with right:
        _xray_card(x)


def _xray_card(x: XRay) -> None:
    with st.container(key="po_xray"):
        sub = escape(x.subtitle) + (f" · {escape(x.note)}" if x.note else "")
        st.html(
            '<div class="po-xray-head"><p class="po-kicker">Analysen · Klumpenrisiko</p>'
            f'<p class="po-xray-title">{escape(x.title)}</p><p class="po-xray-sub">{sub}</p></div>'
        )
        view = st.segmented_control("Depotstand", VIEWS, default=VIEWS[0], key="start_view", required=True,
                                    label_visibility="collapsed") or VIEWS[0]
        i = VIEWS.index(view)
        st.html(_stats_html(x, i) + _meters_html(x, i) + _summary_html(x, i) + _note_html(x))


def _stats_html(x: XRay, i: int) -> str:
    top = x.rows[0] if x.rows else None
    top_risk = _pct(top.risk[i]) if top and top.risk[i] is not None else "–"
    top_label = f"Risikoanteil {escape(top.label)}" if top else "Risikoanteil"
    return (
        '<dl class="po-stats">'
        f'<div><dt>Grenzen überschritten</dt><dd>{x.exceeded[i]}</dd></div>'
        f'<div><dt>Effektive Positionen</dt><dd>{num(x.effective[i], 1)} '
        f'<span class="po-of">von {x.positions[i]}</span></dd></div>'
        f"<div><dt>{top_label}</dt><dd>{top_risk}</dd></div>"
        "</dl>"
    )


def _meters_html(x: XRay, i: int) -> str:
    if not x.rows:
        return '<p class="po-xray-empty">Keine Einzelwerte, Sektoren oder Währungen zu prüfen.</p>'
    scale = max(0.2, math.ceil(max(max(r.weight) for r in x.rows) * 10 + 1e-9) / 10,
                max(r.limit for r in x.rows) + 0.1)
    items = []
    for r in x.rows:
        status = r.status[i]
        risk = _pct(r.risk[i]) if r.risk[i] is not None else "–"
        items.append(
            f'<li class="po-meter is-{status}">'
            f'<div class="po-meter-label"><span class="po-meter-name">{escape(r.label)}</span>'
            f'<span class="po-meter-meta">{conc.KINDS[r.kind]} · Grenze {_pct(r.limit, 0)}</span>'
            f'<span class="po-meter-meta">Risikoanteil {risk}</span></div>'
            '<div class="po-meter-bar" aria-hidden="true">'
            f'<div class="po-meter-track"><span class="po-meter-fill" style="--v: {min(r.weight[i] / scale, 1):.4f}">'
            f'</span></div><span class="po-meter-limit" style="--l: {r.limit / scale:.4f}"></span></div>'
            f'<div class="po-meter-value"><span class="po-meter-figure">{_pct(r.weight[i])}</span>'
            f'<span class="po-meter-status">{_icon(status, "po-icon po-icon-s")}{STATUS[status]}</span></div>'
            "</li>"
        )
    return f'<ul class="po-meters">{"".join(items)}</ul>'


def _summary_html(x: XRay, i: int) -> str:
    if i == 0:
        n = x.exceeded[0]
        text = ("Alle Grenzen sind eingehalten." if n == 0 else
                f"{n} {'Grenze ist' if n == 1 else 'Grenzen sind'} überschritten.")
    elif not x.sells[0] and not x.buys[0]:
        text = "Keine Umschichtung nötig."
    else:
        text = (f"Vorschlag: {x.sells[0]} {'Verkauf' if x.sells[0] == 1 else 'Verkäufe'} für {_eur(x.sells[1])} "
                f"und {x.buys[0]} {'Kauf' if x.buys[0] == 1 else 'Käufe'} für {_eur(x.buys[1])}, in ganzen Stücken.")
        text += (" Danach hält das Depot alle Grenzen ein." if x.exceeded[1] == 0 else
                 f" Danach {'bleibt' if x.exceeded[1] == 1 else 'bleiben'} {x.exceeded[1]} "
                 f"{'Grenze' if x.exceeded[1] == 1 else 'Grenzen'} überschritten.")
    return f'<p class="po-xray-summary">{text}</p>'


def _note_html(x: XRay) -> str:
    source = "Offline-Demo mit fiktiven Wertpapieren" if x.example else "Kurse deines Depots"
    return (f'<p class="po-xray-note">Berechnet aus {source}, Wochenrenditen in Euro über {x.years} '
            f"{'Jahr' if x.years == 1 else 'Jahre'} und deinen Grenzen (anpassbar unter Analysen → Klumpenrisiko). "
            "Balken zeigen das Gewicht, der senkrechte Strich die Grenze. Effektive Positionen geben an, wie viele "
            "gleich große Positionen dieselbe Konzentration hätten.</p>")


def _section_head(anchor: str, eyebrow: str, title: str, intro: str) -> None:
    st.html(f'<div class="po-section-head" id="{anchor}"><p class="po-eyebrow">{eyebrow}</p>'
            f"<h2>{title}</h2><p class=\"po-intro\">{intro}</p></div>")


def _bars_html(caption: str, sub: str, rows: list[tuple[str, float, str, bool]]) -> str:
    """Kleine Balkenfigur: (Beschriftung, Anteil 0–1, Wert als Text, hervorgehoben)."""
    bars = "".join(
        f'<div class="po-bar-row"><span class="po-bar-label">{escape(label)}</span>'
        f'<span class="po-bar-track" aria-hidden="true"><span class="po-bar-fill{" is-key" if key else ""}" '
        f'style="--v: {max(0.0, min(v, 1.0)):.4f}"></span></span><span class="po-bar-value">{text}</span></div>'
        for label, v, text, key in rows
    )
    return (f'<figure class="po-proof"><figcaption><span class="po-proof-title">{escape(caption)}</span>'
            f'<span class="po-proof-sub">{escape(sub)}</span></figcaption><div class="po-bars">{bars}</div></figure>')


def _questions(x: XRay) -> None:
    _section_head("streuung", "Problem und Lösung", "Ein volles Depot ist noch kein gestreutes.",
                  "10 Positionen wirken breit. Steckt die Hälfte davon in einer Branche und fällt gemeinsam, bleibt "
                  "vom Streueffekt wenig übrig. Der Optimierer beantwortet 3 Fragen, die ein Depotauszug offenlässt.")
    owner = "Beispieldepot" if x.example else "Dein Depot"
    top = x.rows[0] if x.rows else None
    if top and top.risk[0] is not None:
        proof1 = _bars_html(f"{owner}, {conc.KINDS[top.kind]} {top.label}", "Wochenrenditen in Euro",
                            [("Gewicht", top.weight[0], _pct(top.weight[0]), False),
                             ("Risikoanteil", top.risk[0], _pct(top.risk[0]), True)])
    else:
        proof1 = '<figure class="po-proof"><p class="po-proof-sub">Für Risikoanteile fehlt noch Kurshistorie.</p></figure>'
    proof2 = (
        '<figure class="po-proof"><figcaption><span class="po-proof-title">2 Renditen, 2 Antworten</span>'
        '</figcaption><dl class="po-terms">'
        "<div><dt>Persönliche Rendite p. a.</dt><dd>Interner Zinsfuß aller Zahlungen. Er berücksichtigt, "
        "wann du wie viel investiert hast.</dd></div>"
        "<div><dt>Zeitgewichtete Rendite p. a.</dt><dd>Unabhängig vom Zeitpunkt deiner Käufe und damit "
        "vergleichbar mit Fonds und Indizes.</dd></div>"
        "<div><dt>Kursstand</dt><dd>Während der Handelszeit der letzte Minutenkurs, meist etwa 15 Minuten "
        "verzögert, sonst der Schlusskurs.</dd></div></dl></figure>"
    )
    if x.sells[0] or x.buys[0]:
        proof3 = _bars_html(f"{owner}, Umschichtung nach deinen Grenzen", "Ganze Stücke, ohne Kosten und Steuern",
                            [("Grenzen jetzt", 1.0 if x.exceeded[0] else 0.0, str(x.exceeded[0]), False),
                             ("Grenzen danach", x.exceeded[1] / max(x.exceeded[0], 1), str(x.exceeded[1]), True)])
        proof3 = proof3.replace("</figure>", f'<p class="po-proof-sub po-proof-foot">{x.sells[0]} '
                                f"{'Verkauf' if x.sells[0] == 1 else 'Verkäufe'}, {x.buys[0]} "
                                f"{'Kauf' if x.buys[0] == 1 else 'Käufe'}</p></figure>")
    else:
        proof3 = (f'<figure class="po-proof"><figcaption><span class="po-proof-title">{owner}</span></figcaption>'
                  '<p class="po-proof-sub">Alle Grenzen sind eingehalten, eine Umschichtung ist nicht nötig.</p></figure>')
    questions = [
        ("Wie gut ist mein Depot wirklich gestreut?",
         "Der Depotauszug zeigt Stückzahlen und Gewichte. Wie stark eine Position das ganze Depot schwanken lässt, "
         "steht dort nicht.",
         "Er prüft Einzelaktien, Sektoren, Fremdwährungen und Gruppen stark korrelierter Werte gegen deine Grenzen. "
         "Für jede Gruppe berechnet er den Risikoanteil, also den Teil der Depotschwankung, den sie verursacht.",
         proof1, ("Klumpenrisiko öffnen", "analysen", "sec_cluster")),
        ("Wie steht mein Depot heute da?",
         "Nachkäufe und Teilverkäufe machen die Rendite schwer vergleichbar. Ein Plus seit dem ersten Kauf sagt wenig "
         "darüber, wie gut die Auswahl war.",
         "Du erfasst Käufe und Verkäufe mit Datum. Die App bewertet täglich in Euro, führt Einstandskurse nach FIFO "
         "und vergleicht dein Depot mit einem Index, auf Wunsch mit denselben Ein- und Auszahlungen.",
         proof2, ("Wertentwicklung öffnen", "portfolio", "sec_performance")),
        ("Was sollte ich ändern, und wie belastbar ist der Vorschlag?",
         "Optimierer rechnen mit geschätzten Renditen. Kleine Schätzfehler führen zu extremen Gewichten, die später "
         "selten halten, was sie versprechen.",
         "Die Umschichtung hält deine Grenzen mit möglichst wenig Handel ein und nennt Stückzahlen, Beträge und "
         "realisierte Gewinne. Der Abschnitt Schätzfehler zeigt, wie stark ein Ergebnis von der Schätzung abhängt.",
         proof3, ("Umschichtung öffnen", "loesungen", "sec_rebalance")),
    ]
    for n, (question, problem, answer, proof, (label, page, section)) in enumerate(questions):
        with st.container(key=f"po_q_{n}"):
            text, figure = st.columns([7, 5], gap="large")
            with text:
                st.html(f'<div class="po-question"><h3>{question}</h3><p>{problem}</p>'
                        f'<p class="po-answer-label">So hilft der Optimierer</p><p>{answer}</p></div>')
                if st.button(label, key=f"po_q_btn_{n}", type="tertiary", icon=":material/arrow_forward:"):
                    _go(page, section)
            with figure:
                st.html(proof)


FEATURES = [
    ("portfolio", "ledger", "Ebene 1 · Portfolio", "Stand erfassen",
     "Käufe und Verkäufe mit Datum, Stückzahl und Kurs eintragen oder als CSV importieren.",
     ["Depotwert und Einzahlungen im Verlauf", "Persönliche und zeitgewichtete Rendite", "Vergleich mit einem Index",
      "Aufteilung nach Sektor und Währung"], "Portfolio öffnen"),
    ("analysen", "frontier", "Ebene 2 · Analysen", "Risiken verstehen",
     "Kennzahlen, die zeigen, wo das Risiko sitzt und was eine Optimierung leisten kann.",
     ["Klumpenrisiko mit Risikoanteilen", "Efficient Frontier nach Markowitz", "Monte-Carlo-Simulation mit Sparrate",
      "Schätzfehler und ihre Folgen"], "Analysen öffnen"),
    ("loesungen", "swap", "Ebene 3 · Lösungen", "Lösungen durchrechnen",
     "Konkrete Vorschläge in Stück und Euro, abgestimmt auf deine Grenzen.",
     ["Umschichtung mit möglichst wenig Handel", "Realisierte Gewinne nach FIFO", "Markt-Hedge über das Beta",
      "Beimischung von Anleihen, Gold oder Geldmarkt"], "Lösungen öffnen"),
]

METHODS = [("Markowitz (1952)", "Portfolio Selection"), ("Jorion (1986)", "Bayes-Stein-Schätzung"),
           ("Michaud (1989)", "Resampled Efficiency"), ("Ledoit & Wolf (2004)", "Shrinkage der Kovarianzmatrix"),
           ("DeMiguel, Garlappi & Uppal (2009)", "1/N als Vergleichsmaßstab")]


def _features() -> None:
    _section_head("funktionen", "Funktionen", "3 Ebenen, vom Stand bis zur Lösung",
                  "So ist die App aufgebaut. Jede Ebene besteht aus aufklappbaren Abschnitten, die erst rechnen, wenn "
                  "du sie öffnest.")
    with st.container(key="po_features"):
        for col, (page, icon, level, title, text, items, cta) in zip(st.columns(3, gap="medium"), FEATURES):
            with col, st.container(key=f"po_feat_{page}"):
                listing = "".join(f"<li>{_icon('check', 'po-icon po-icon-s')}<span>{item}</span></li>" for item in items)
                st.html(f'<div class="po-feature">{_icon(icon, "po-icon po-icon-l")}'
                        f'<p class="po-feature-level">{level}</p><h3>{title}</h3><p>{text}</p>'
                        f"<ul>{listing}</ul></div>")
                st.page_link(PAGES[page], label=cta, icon=":material/arrow_forward:")
        methods = "".join(f'<li><span class="po-who">{escape(who)}</span><span class="po-what">{what}</span></li>'
                          for who, what in METHODS)
        st.html(f'<div class="po-methods"><p class="po-methods-title">Methoden aus der Forschung</p>'
                f"<ul>{methods}</ul></div>")


@st.dialog("Impressum", width="large")
def _imprint() -> None:
    st.caption("Vorlage: Nötig, sobald die App öffentlich erreichbar ist. Markierte Angaben ersetzen und rechtlich "
               "prüfen lassen.")
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
    st.caption("Vorlage: beschreibt, was die App heute technisch tut. Vor einer Veröffentlichung um Verantwortlichen, "
               "Hosting und Speicherdauer ergänzen und rechtlich prüfen lassen.")
    st.markdown(
        "**Speicherung deiner Depots**  \nDepots, Transaktionen und geladene Kurse speichert die App als Dateien im "
        "Ordner `portfolios/` auf dem Rechner, auf dem sie läuft. Es gibt kein Benutzerkonto, keine Cookies zu "
        "Werbe- oder Analysezwecken und keine eingebundenen Analyse- oder Werbedienste.\n\n"
        "**Kurse von Yahoo Finance**  \nMit der Einstellung Yahoo Finance fragt die App Kurse, Wechselkurse und "
        "Stammdaten bei Yahoo ab. Dabei erhält Yahoo die angefragten Wertpapiere und die IP-Adresse des Rechners; "
        "es gelten die Datenschutzbestimmungen von Yahoo. Die Offline-Demo stellt keine Verbindung her.\n\n"
        "**Schrift**  \nDie Schrift liegt bei der App selbst, es entsteht keine Verbindung zu Google Fonts.\n\n"
        ":orange[Verantwortlicher, Hosting-Anbieter, Server-Protokolle, Speicherdauer und Rechte der Betroffenen "
        "ergänzen, sobald die App öffentlich betrieben wird.]"
    )


def _footer() -> None:
    with st.container(key="po_footer"):
        st.html(f'<div class="po-footer"><p class="po-footer-about">Analyse- und Lernwerkzeug für dein Depot. '
                "Keine Anlageberatung. Die Auswertungen beruhen auf historischen Daten und berücksichtigen weder "
                "Kosten noch Steuern.</p>"
                f'<p class="po-footer-meta">© {date.today().year} Portfolio-Optimierer</p></div>')
        with st.container(horizontal=True, gap="small"):
            if st.button("Impressum", type="tertiary", key="po_imprint"):
                _imprint()
            if st.button("Datenschutz", type="tertiary", key="po_privacy"):
                _privacy()


def render(run: RunState) -> None:
    show_flash()
    _style()
    try:
        x = _xray(run)
    except Exception as exc:  # Kurse fehlen oder Rechnung scheitert: Seite trotzdem zeigen
        st.warning(f"Die Analyse für die Startseite ließ sich gerade nicht berechnen ({exc}). Die Ebenen oben "
                   "funktionieren weiter.")
        return
    _hero(run, x)
    _questions(x)
    _features()
    _footer()


def _style() -> None:
    st.html(f"<style>{_icon_css()}</style>")
    st.html("""<style>
    .po-icon { display: inline-block; width: 20px; height: 20px; flex: none; background-color: currentColor;
               -webkit-mask: var(--po-shape) center / contain no-repeat; mask: var(--po-shape) center / contain no-repeat; }
    .po-icon-s { width: 16px; height: 16px; }
    .po-icon-l { width: 24px; height: 24px; color: var(--po-primary); }
    .po-eyebrow { margin: 0 0 0.75rem; color: var(--po-accent-text); font-size: 0.875rem; font-weight: 500;
                  line-height: 1.5; }

    /* Kopf */
    .po-start-hero h1 { margin: 0; padding: 0; color: var(--po-ink); font-size: 2.488rem; font-weight: 600;
                        line-height: 1.1; letter-spacing: -0.02em; text-wrap: balance; }
    .po-lead { margin: 1.5rem 0 0; max-width: 34rem; color: var(--po-ink2); font-size: 1.2rem; line-height: 1.5; }
    .st-key-po_cta { margin-top: 1rem; }
    .st-key-po_cta button { min-height: 48px; padding-inline: 1.25rem; }
    .po-facts { display: grid; gap: 0.5rem; margin: 1rem 0 0; padding: 0; list-style: none; color: var(--po-ink2);
                font-size: 0.875rem; line-height: 1.5; }
    .po-facts li { display: flex; gap: 0.5rem; }
    .po-facts .po-icon { width: 16px; height: 16px; margin-top: 3px; color: var(--po-up); }

    /* Karte: Klumpenrisiko jetzt und nach Umschichtung */
    .st-key-po_xray { container-type: inline-size; padding: 1.5rem; background: var(--po-card);
                      border: 1px solid var(--po-line); border-radius: 12px;
                      box-shadow: 0 4px 12px var(--po-shadow), inset 0 1px 0 var(--po-edge); }
    .po-kicker { margin: 0; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .po-xray-title { margin: 0.25rem 0 0; color: var(--po-ink); font-size: 1.2rem; font-weight: 600; line-height: 1.25; }
    .po-xray-sub { margin: 0.25rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin: 0;
                padding: 1rem 0; border-block: 1px solid var(--po-line); }
    .po-stats dt { color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .po-stats dd { margin: 0.25rem 0 0; color: var(--po-ink); font-size: 1.44rem; font-weight: 600; line-height: 1.2; }
    .po-of { color: var(--po-muted); font-size: 0.875rem; font-weight: 400; }
    .po-stats > div { display: flex; flex-direction: column; }
    .po-stats dt { flex: 1; }
    /* Streamlit rückt Listen in HTML-Blöcken ein; hier stehen sie bündig */
    .stApp :is(.po-facts, .po-meters, .po-stats, .po-feature ul, .po-methods ul, .po-terms) {
        margin-left: 0; padding-left: 0; }
    .stApp :is(.po-facts, .po-meters, .po-feature ul, .po-methods ul) > li { margin: 0; padding: 0; }
    .po-meters { display: grid; gap: 1rem; margin: 1.5rem 0 0; padding: 0; list-style: none; }
    .po-meter { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "label value" "bar bar";
                gap: 0.5rem 1rem; align-items: center; }
    @container (min-width: 30rem) {
        .po-meter { grid-template-columns: minmax(0, 10.5rem) minmax(0, 1fr) 6.5rem;
                    grid-template-areas: "label bar value"; }
    }
    .po-meter-label { grid-area: label; min-width: 0; }
    .po-meter-name { display: block; overflow-wrap: anywhere; color: var(--po-ink); font-size: 0.875rem;
                     font-weight: 500; line-height: 1.5; }
    .po-meter-meta { display: block; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .po-meter-bar { grid-area: bar; position: relative; height: 16px; }
    .po-meter-track { position: absolute; inset: 4px 0; overflow: hidden; border-radius: 4px;
                      background: var(--po-chart-track); }
    .po-meter-fill { position: absolute; inset: 0; border-radius: 0 4px 4px 0; background: var(--po-chart-ok);
                     transform: translateX(calc((var(--v) - 1) * 100%)); }
    .po-meter.is-over .po-meter-fill { background: var(--po-chart-warn); }
    .po-meter-limit { position: absolute; top: 0; bottom: 0; left: calc(var(--l) * 100%); width: 2px; margin-left: -1px;
                      border-radius: 1px; background: var(--po-ink2); box-shadow: 0 0 0 2px var(--po-card); }
    .po-meter-value { grid-area: value; display: grid; justify-items: end; text-align: right; }
    .po-meter-figure { color: var(--po-ink); font-size: 1rem; font-weight: 600; line-height: 1.5;
                       font-variant-numeric: tabular-nums; }
    .po-meter-status { display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; line-height: 1.4;
                       white-space: nowrap; }
    .po-meter-status .po-icon { width: 14px; height: 14px; stroke-width: 2; }
    .po-meter.is-over .po-meter-status { color: var(--po-accent-text); }
    .po-meter.is-near .po-meter-status { color: var(--po-ink2); }
    .po-meter.is-ok .po-meter-status { color: var(--po-up); }
    .po-xray-summary { margin: 1.5rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-xray-note { margin: 1rem 0 0; padding-top: 1rem; border-top: 1px solid var(--po-line); color: var(--po-muted);
                    font-size: 0.75rem; line-height: 1.4; }
    .po-xray-empty { color: var(--po-ink2); font-size: 0.875rem; }

    /* Abschnitte */
    .po-section-head { max-width: 44rem; margin-top: 6rem; scroll-margin-top: 5rem; }
    .po-section-head h2 { margin: 0; padding: 0; color: var(--po-ink); font-size: 1.728rem; font-weight: 600;
                          line-height: 1.2; text-wrap: balance; }
    .po-intro { margin: 1rem 0 0; max-width: 65ch; color: var(--po-ink2); font-size: 1.2rem; line-height: 1.5; }

    /* Problem und Lösung */
    .st-key-po_q_0, .st-key-po_q_1, .st-key-po_q_2 { padding-block: 2rem; border-top: 1px solid var(--po-line); }
    .st-key-po_q_0 { margin-top: 2rem; }
    .st-key-po_q_2 { border-bottom: 1px solid var(--po-line); }
    .po-question h3 { margin: 0; padding: 0; color: var(--po-ink); font-size: 1.44rem; font-weight: 600;
                      line-height: 1.25; text-wrap: balance; }
    .po-question p { margin: 1rem 0 0; max-width: 65ch; color: var(--po-ink2); line-height: 1.55; }
    .po-question .po-answer-label { margin-top: 1.5rem; color: var(--po-ink); font-size: 0.875rem; font-weight: 500; }
    .po-question .po-answer-label + p { margin-top: 0.25rem; }
    .po-proof { margin: 0; padding: 1.5rem; background: var(--po-sunken); border: 1px solid var(--po-line);
                border-radius: 12px; container-type: inline-size; }
    .po-proof-title, .po-proof-sub { display: block; }
    .po-proof-title { color: var(--po-ink); font-size: 0.875rem; font-weight: 500; line-height: 1.5; }
    .po-proof-sub { margin-top: 0.25rem; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .po-proof-foot { margin-top: 1rem; }
    .po-bars { display: grid; gap: 0.75rem; margin-top: 1rem; }
    .po-bar-row { display: grid; grid-template-columns: minmax(0, 1fr) 3.5rem; grid-template-areas: "label label" "bar value";
                  gap: 0.25rem 0.75rem; align-items: center; font-size: 0.875rem; }
    @container (min-width: 24rem) {
        .po-bar-row { grid-template-columns: 8.5rem minmax(0, 1fr) 3.5rem; grid-template-areas: "label bar value";
                      gap: 0.75rem; }
    }
    .po-bar-label { grid-area: label; color: var(--po-ink2); }
    .po-bar-track { grid-area: bar; position: relative; height: 12px; }
    .po-bar-fill { position: absolute; inset: 0 auto 0 0; width: calc(var(--v) * 100%); border-radius: 0 4px 4px 0;
                   background: var(--po-chart-muted); }
    .po-bar-fill.is-key { background: var(--po-chart-ok); }
    .po-bar-value { grid-area: value; color: var(--po-ink); font-weight: 600; text-align: right;
                    font-variant-numeric: tabular-nums; }
    .po-terms { display: grid; gap: 1rem; margin: 1rem 0 0; }
    .po-terms dt { color: var(--po-ink); font-size: 0.875rem; font-weight: 500; line-height: 1.5; }
    .po-terms dd { margin: 0.25rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }

    /* Funktionen */
    .st-key-po_features { margin-top: 2rem; padding: 1.5rem; background: var(--po-sunken);
                          border: 1px solid var(--po-line); border-radius: 16px; }
    @media (min-width: 768px) { .st-key-po_features { padding: 3rem; } }
    [class*="st-key-po_feat_"] { flex: 1; padding: 1.5rem; background: var(--po-card);
                                 border: 1px solid var(--po-line); border-radius: 12px;
                                 box-shadow: 0 1px 2px var(--po-shadow), inset 0 1px 0 var(--po-edge); }
    .st-key-po_features [data-testid="stColumn"] { display: flex; flex-direction: column; }
    .st-key-po_features [data-testid="stColumn"] > [data-testid="stVerticalBlock"] { flex: 1; }
    .st-key-po_features [data-testid="stLayoutWrapper"]:has(> [class*="st-key-po_feat_"]) { flex: 1; }
    [class*="st-key-po_feat_"] { justify-content: space-between; }
    .po-feature-level { margin: 1.5rem 0 0; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .po-feature h3 { margin: 0.25rem 0 0; padding: 0; color: var(--po-ink); font-size: 1.2rem; font-weight: 600;
                     line-height: 1.25; }
    .po-feature > p { margin: 0.75rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-feature ul { display: grid; gap: 0.5rem; margin: 1.5rem 0 0; padding: 1rem 0 0; list-style: none;
                     border-top: 1px solid var(--po-line); font-size: 0.875rem; line-height: 1.5; color: var(--po-ink); }
    .po-feature li { display: flex; gap: 0.5rem; }
    .po-feature li .po-icon { margin-top: 3px; color: var(--po-ink2); }
    .po-methods { margin-top: 2rem; }
    .po-methods-title { margin: 0; color: var(--po-ink); font-size: 0.875rem; font-weight: 500; }
    .po-methods ul { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
                     gap: 1rem 1.5rem; margin: 1rem 0 0; padding: 0; list-style: none; }
    .po-methods li { padding-top: 0.75rem; border-top: 1px solid var(--po-line-strong); }
    .po-who { display: block; color: var(--po-ink); font-size: 0.875rem; font-weight: 500; line-height: 1.5; }
    .po-what { display: block; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }

    /* Fußzeile */
    .st-key-po_footer { margin-top: 4rem; padding-top: 2rem; border-top: 1px solid var(--po-line); }
    .po-footer-about { margin: 0; max-width: 40rem; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-footer-meta { margin: 0.5rem 0 0; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }

    @media (max-width: 767.98px) {
        .po-start-hero h1 { font-size: 2.074rem; }
        .po-section-head { margin-top: 4rem; }
        .st-key-po_cta > * { flex: 1 1 14rem; }
        .st-key-po_cta button { width: 100%; }
    }
    </style>""")
