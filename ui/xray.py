"""Karte „Klumpenrisiko“: Gewicht, Grenze und Risikoanteil der auffälligsten Gruppen in zwei Zuständen.

Zwei Zustände nebeneinander, umschaltbar: jetzt und nach der Umschichtung (Übersicht, Startseite)
oder jetzt und nach einer selbst gewählten Änderung (Was-wäre-wenn-Regler). Alle Zahlen kommen aus
``portfolio_optimizer``; nichts ist ausgedacht.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from html import escape
from urllib.parse import quote

import numpy as np
import pandas as pd
import streamlit as st

from portfolio_optimizer import concentration as conc
from portfolio_optimizer import hedging as hg
from portfolio_optimizer import rebalancing as rb
from portfolio_optimizer.formatting import num, pct
from ui.solutions_view import limits_plan, prices_for
from ui.state import PortfolioContext, RunState, Settings, current_limits, example_portfolio, load_context

CURRENCIES = {"USD": "US-Dollar", "GBP": "Britisches Pfund", "CHF": "Schweizer Franken", "JPY": "Japanischer Yen",
              "DKK": "Dänische Krone", "SEK": "Schwedische Krone", "NOK": "Norwegische Krone",
              "CAD": "Kanadischer Dollar", "AUD": "Australischer Dollar", "HKD": "Hongkong-Dollar"}
STATUS = {"over": "über Grenze", "near": "nahe Grenze", "ok": "im Rahmen"}

# Einfache Strich-Symbole (24er Raster); st.html entfernt eingebettetes SVG, deshalb als CSS-Maske
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
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
}


def icon(name: str, cls: str = "po-icon") -> str:
    """Symbol als Fläche in Textfarbe; die Form kommt als SVG-Maske aus dem Stylesheet."""
    return f'<span class="{cls} po-i-{name}" aria-hidden="true"></span>'


def pct_nb(x: float | None, digits: int = 1) -> str:
    """Prozent mit geschütztem Leerzeichen, damit „51,5 %“ nicht umbricht."""
    return pct(x, digits).replace(" ", " ")


def eur_nb(x: float, digits: int = 2) -> str:
    return f"{num(x, digits)} €"


# ---------------------------------------------------------------------------
# Daten
# ---------------------------------------------------------------------------


@dataclass
class Row:
    kind: str
    group: str
    limit: float
    weight: tuple[float, float]  # Zustand 0, Zustand 1
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
    note: str | None
    states: tuple[str, str]  # Beschriftung der beiden Zustände
    positions: tuple[int, int]
    exceeded: tuple[int, int]
    effective: tuple[float, float]
    vol: tuple[float | None, float | None]
    rows: list[Row]
    sells: tuple[int, float] = (0, 0.0)
    buys: tuple[int, float] = (0, 0.0)
    years: int = 5


def _status(finding: conc.Finding | None) -> str:
    if finding is None or (not finding.exceeded and finding.status == "ok"):
        return "ok"
    return "over" if finding.exceeded else "near"


def _risk(finding: conc.Finding | None) -> float | None:
    if finding is None:
        return 0.0
    return finding.risk_share if math.isfinite(finding.risk_share) else None


def rows(before: conc.ConcentrationReport, after: conc.ConcentrationReport, limit: int = 5,
         must: tuple[str, ...] = ()) -> list[Row]:
    """Die auffälligsten Einzelwerte, Sektoren und Währungen: Überschreitungen zuerst, nach Überhang.

    ``must``: Gruppen, die auf jeden Fall erscheinen (z. B. die Position, die der Regler verändert).
    """
    later = {(f.kind, f.group): f for f in after.findings}
    candidates = [f for f in before.findings if f.kind in ("position", "sector", "currency")]
    exceeded = sorted((f for f in candidates if f.exceeded), key=lambda f: f.excess, reverse=True)
    rest = sorted((f for f in candidates if not f.exceeded), key=lambda f: f.weight / f.limit, reverse=True)
    ordered = exceeded + rest
    chosen = [f for f in ordered if f.group in must][:1] + [f for f in ordered if f.group not in must]
    result = []
    for f in chosen[:limit]:
        g = later.get((f.kind, f.group))
        result.append(Row(f.kind, f.group, f.limit, (f.weight, g.weight if g else 0.0), (_risk(f), _risk(g)),
                          (_status(f), _status(g))))
    return result


def portfolio_vol(weights: pd.Series, weekly: pd.DataFrame) -> float | None:
    """Schwankung p. a. aus Wochenrenditen (wie im Klumpenrisiko)."""
    rets = weekly.reindex(columns=weights.index).dropna()
    if len(rets) < 10:
        return None
    w = weights.to_numpy()
    return float(np.sqrt(w @ (rets.cov().to_numpy() * conc.PERIODS_PER_YEAR) @ w))


def rebalance(ctx: PortfolioContext, limits: conc.Limits, years: int, title: str, subtitle: str,
              example: bool, note: str | None) -> XRay:
    """Jetzt und nach der Umschichtung, die die Grenzen mit möglichst wenig Handel einhält."""
    before = conc.analyze(ctx.weights, ctx.infos, ctx.weekly, limits)
    target, infos, prices, _remaining = limits_plan(ctx, before, limits)
    tr = rb.trades(ctx.valued, target, prices, whole_shares=True, min_trade=50.0, sale_gain=ctx.portfolio.sale_gain)
    held = tr["weight_after"][tr["weight_after"] > 0]
    weekly_after = hg.weekly_returns(prices_for(ctx, held.index, infos))
    after = conc.analyze(held, infos, weekly_after, limits)
    sells, buys = tr[tr["amount"] < 0], tr[tr["amount"] > 0]
    return XRay(
        title=title, subtitle=subtitle, example=example, note=note, states=("Jetzt", "Nach Umschichtung"),
        positions=(len(ctx.weights), len(held)), exceeded=(len(before.exceeded), len(after.exceeded)),
        effective=(before.effective_positions, after.effective_positions),
        vol=(portfolio_vol(ctx.weights, ctx.weekly), portfolio_vol(held, weekly_after)),
        rows=rows(before, after), sells=(len(sells), float(-sells["amount"].sum())),
        buys=(len(buys), float(buys["amount"].sum())), years=years,
    )


def what_if(ctx: PortfolioContext, limits: conc.Limits, symbol: str, weight: float) -> XRay:
    """Jetzt und nach einer selbst gewählten Änderung: eine Position bekommt ``weight``, die übrigen
    teilen sich den Rest im bisherigen Verhältnis."""
    w = ctx.weights.copy()
    rest = float(w.drop(symbol).sum())
    if rest > 0:
        w[w.index != symbol] = w.drop(symbol) / rest * (1 - weight)
    w[symbol] = weight
    w = w[w > 1e-9]
    before = conc.analyze(ctx.weights, ctx.infos, ctx.weekly, limits)
    after = conc.analyze(w, ctx.infos, ctx.weekly, limits)
    name = ctx.infos[symbol].name
    return XRay(
        title=name, subtitle="", example=False, note=None, states=("Jetzt", "Was wäre, wenn"),
        positions=(len(ctx.weights), len(w)), exceeded=(len(before.exceeded), len(after.exceeded)),
        effective=(before.effective_positions, after.effective_positions),
        vol=(portfolio_vol(ctx.weights, ctx.weekly), portfolio_vol(w, ctx.weekly)),
        rows=rows(before, after, must=(name,)),
    )


def analysable(ctx: PortfolioContext) -> bool:
    return ctx.value > 0 and ctx.weekly.dropna().shape[0] >= 10


def example(years: int, note: str | None = None) -> XRay:
    """Beispieldepot der Offline-Demo (fiktive Wertpapiere, ohne Netz)."""
    ctx = load_context(Settings(provider="demo", years=years), portfolio=example_portfolio("demo"))
    n = len(ctx.weights)
    return rebalance(ctx, current_limits(), years, title="Beispieldepot",
                     subtitle=f"{n} Positionen · rund {num(round(ctx.value, -1))} € · fiktive Werte",
                     example=True, note=note)


def own_or_example(run: RunState) -> XRay:
    """Eigenes Depot, sobald es Positionen mit Kurshistorie hat, sonst das Beispieldepot.

    Bleibt in der Sitzung gespeichert, solange sich Depot, Grenzen und Zeitraum nicht ändern; so rechnet
    das Umschalten zwischen den Zuständen nichts neu.
    """
    ctx, limits, years = run.ctx, current_limits(), run.settings.years
    own = analysable(ctx)
    source = ctx.portfolio.to_json() if own else "beispiel"
    key = hashlib.sha1(f"{ctx.provider}|{source}|{limits}|{years}|{date.today()}".encode()).hexdigest()
    memo = st.session_state.get("_xray")
    if memo and memo[0] == key:
        return memo[1]
    if own:
        n = len(ctx.weights)
        x = rebalance(ctx, limits, years, title=ctx.portfolio.name,
                      subtitle=f"{n} {'Position' if n == 1 else 'Positionen'} · {num(ctx.value)} €",
                      example=False, note=None)
    else:
        note = ("Dein Depot ist noch leer." if not ctx.portfolio.positions
                else "Dein Depot hat noch zu wenig Kurshistorie für die Analyse.")
        x = example(years, note)
    st.session_state["_xray"] = (key, x)
    return x


def cached_example(years: int) -> XRay:
    memo = st.session_state.get("_xray_example")
    if memo and memo[0] == (years, date.today()):
        return memo[1]
    x = example(years)
    st.session_state["_xray_example"] = ((years, date.today()), x)
    return x


# ---------------------------------------------------------------------------
# Darstellung
# ---------------------------------------------------------------------------


def card(x: XRay, key: str, kicker: str = "Klumpenrisiko", default: int = 0) -> None:
    """Karte mit Kopf, Umschalter zwischen beiden Zuständen, Kennzahlen und Balken."""
    style()
    with st.container(key=f"card_{key}"):
        sub = escape(x.subtitle) + (f" · {escape(x.note)}" if x.note else "")
        st.html(f'<div class="po-xray-head"><p class="po-kicker">{escape(kicker)}</p>'
                f'<p class="po-xray-title">{escape(x.title)}</p>'
                + (f'<p class="po-xray-sub">{sub}</p>' if sub else "") + "</div>")
        if st.session_state.get(f"{key}_view") not in x.states:
            st.session_state[f"{key}_view"] = x.states[default]
        view = st.segmented_control("Zustand", list(x.states), key=f"{key}_view", required=True,
                                    label_visibility="collapsed") or x.states[default]
        i = x.states.index(view)
        st.html(stats_html(x, i) + meters_html(x, i) + summary_html(x, i) + note_html(x))


def stats_html(x: XRay, i: int) -> str:
    vol = pct_nb(x.vol[i]) if x.vol[i] is not None else "–"
    return (
        '<dl class="po-stats">'
        f'<div><dt>Grenzen überschritten</dt><dd>{x.exceeded[i]}</dd></div>'
        f'<div><dt>Effektive Positionen</dt><dd>{num(x.effective[i], 1)} '
        f'<span class="po-of">von {x.positions[i]}</span></dd></div>'
        f"<div><dt>Schwankung p. a.</dt><dd>{vol}</dd></div>"
        "</dl>"
    )


def meters_html(x: XRay, i: int) -> str:
    if not x.rows:
        return '<p class="po-xray-empty">Keine Einzelwerte, Sektoren oder Währungen zu prüfen.</p>'
    scale = max(0.2, math.ceil(max(max(r.weight) for r in x.rows) * 10 + 1e-9) / 10,
                max(r.limit for r in x.rows) + 0.1)
    items = []
    for r in x.rows:
        status = r.status[i]
        risk = pct_nb(r.risk[i]) if r.risk[i] is not None else "–"
        items.append(
            f'<li class="po-meter is-{status}">'
            f'<div class="po-meter-label"><span class="po-meter-name">{escape(r.label)}</span>'
            f'<span class="po-meter-meta">{conc.KINDS[r.kind]} · Grenze {pct_nb(r.limit, 0)} · '
            f"Risikoanteil {risk}</span></div>"
            '<div class="po-meter-bar" aria-hidden="true">'
            f'<div class="po-meter-track"><span class="po-meter-fill" style="--v: {min(r.weight[i] / scale, 1):.4f}">'
            f'</span></div><span class="po-meter-limit" style="--l: {r.limit / scale:.4f}"></span></div>'
            f'<div class="po-meter-value"><span class="po-meter-figure">{pct_nb(r.weight[i])}</span>'
            f'<span class="po-meter-status">{icon(status, "po-icon po-icon-s")}{STATUS[status]}</span></div>'
            "</li>"
        )
    return f'<ul class="po-meters">{"".join(items)}</ul>'


def summary_html(x: XRay, i: int) -> str:
    n = x.exceeded[i]
    if i == 0 or x.states[1] != "Nach Umschichtung":
        text = ("Alle Grenzen sind eingehalten." if n == 0 else
                f"{n} {'Grenze ist' if n == 1 else 'Grenzen sind'} überschritten.")
    elif not x.sells[0] and not x.buys[0]:
        text = "Keine Umschichtung nötig."
    else:
        text = (f"Vorschlag: {x.sells[0]} {'Verkauf' if x.sells[0] == 1 else 'Verkäufe'} für {eur_nb(x.sells[1])} "
                f"und {x.buys[0]} {'Kauf' if x.buys[0] == 1 else 'Käufe'} für {eur_nb(x.buys[1])}, in ganzen Stücken.")
        text += (" Danach hält das Depot alle Grenzen ein." if n == 0 else
                 f" Danach {'bleibt' if n == 1 else 'bleiben'} {n} {'Grenze' if n == 1 else 'Grenzen'} überschritten.")
    return f'<p class="po-xray-summary">{text}</p>'


def note_html(x: XRay) -> str:
    if x.states[1] != "Nach Umschichtung":
        return ""
    source = "der Offline-Demo mit fiktiven Wertpapieren" if x.example else "den Kursen deines Depots"
    return (f'<p class="po-xray-note">Berechnet aus {source}, Wochenrenditen in Euro über {x.years} '
            f"{'Jahr' if x.years == 1 else 'Jahre'}. Balken zeigen das Gewicht, der senkrechte Strich die Grenze. "
            "Effektive Positionen: so viele gleich große Positionen hätten dieselbe Konzentration.</p>")


def _icon_css() -> str:
    out = []
    for name, shape in ICONS.items():
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
               f"stroke-width='1.75' stroke-linecap='round' stroke-linejoin='round'>{shape.replace(chr(34), chr(39))}</svg>")
        out.append(f'.po-i-{name} {{ --po-shape: url("data:image/svg+xml,{quote(svg)}"); }}')
    return "\n".join(out)


def style() -> None:
    st.html(f"<style>{_icon_css()}</style>")
    st.html("""<style>
    .po-icon { display: inline-block; width: 20px; height: 20px; flex: none; background-color: currentColor;
               -webkit-mask: var(--po-shape) center / contain no-repeat; mask: var(--po-shape) center / contain no-repeat; }
    .po-icon-s { width: 16px; height: 16px; }
    .po-icon-l { width: 28px; height: 28px; color: var(--po-primary); }
    .po-kicker { margin: 0; color: var(--po-muted); font-size: 0.8125rem; font-weight: 500; line-height: 1.4; }
    .po-xray-title { margin: 0.25rem 0 0; color: var(--po-ink); font-size: 1.375rem; font-weight: 600; line-height: 1.2;
                     letter-spacing: -0.02em; }
    .po-xray-sub { margin: 0.25rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin: 0 !important;
                padding: 1rem 0 !important; border-block: 1px solid var(--po-line); }
    .po-stats > div { display: flex; flex-direction: column; }
    .po-stats dt { flex: 1; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .po-stats dd { margin: 0.25rem 0 0; color: var(--po-ink); font-size: 1.5rem; font-weight: 600; line-height: 1.15;
                   letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
    .po-of { color: var(--po-muted); font-size: 0.875rem; font-weight: 400; letter-spacing: 0; }
    .po-meters { display: grid; gap: 0.25rem; margin: 1rem 0 0 !important; padding: 0 !important; list-style: none; }
    .po-meter { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "label value" "bar bar";
                gap: 0.5rem 1rem; align-items: center; margin: 0 -0.75rem !important; padding: 0.625rem 0.75rem !important;
                border-radius: 12px; transition: background-color 150ms ease; }
    @media (hover: hover) { .po-meter:hover { background: var(--po-sunken); } }
    [class*="st-key-card_"] { container-type: inline-size; }
    @container (min-width: 32rem) {
        .po-meter { grid-template-columns: minmax(0, 11rem) minmax(0, 1fr) 6.5rem; grid-template-areas: "label bar value"; }
    }
    .po-meter-label { grid-area: label; min-width: 0; }
    .po-meter-name { display: block; overflow-wrap: anywhere; color: var(--po-ink); font-size: 0.9375rem;
                     font-weight: 500; line-height: 1.4; }
    .po-meter-meta { display: block; color: var(--po-muted); font-size: 0.75rem; line-height: 1.4; }
    .po-meter-bar { grid-area: bar; position: relative; height: 16px; }
    .po-meter-track { position: absolute; inset: 5px 0; overflow: hidden; border-radius: 3px; background: var(--po-chart-track); }
    .po-meter-fill { position: absolute; inset: 0; border-radius: 0 3px 3px 0; background: var(--po-chart-ok);
                     transform: translateX(calc((var(--v) - 1) * 100%)); }
    .po-meter.is-over .po-meter-fill { background: var(--po-chart-warn); }
    .po-meter-limit { position: absolute; top: 0; bottom: 0; left: calc(var(--l) * 100%); width: 2px; margin-left: -1px;
                      border-radius: 1px; background: var(--po-ink); box-shadow: 0 0 0 2px var(--po-card); }
    .po-meter-value { grid-area: value; display: grid; justify-items: end; text-align: right; }
    .po-meter-figure { color: var(--po-ink); font-size: 1rem; font-weight: 600; line-height: 1.5;
                       font-variant-numeric: tabular-nums; }
    .po-meter-status { display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; line-height: 1.4;
                       white-space: nowrap; }
    .po-meter-status .po-icon { width: 14px; height: 14px; }
    .po-meter.is-over .po-meter-status { color: var(--po-accent-text); }
    .po-meter.is-near .po-meter-status { color: var(--po-ink2); }
    .po-meter.is-ok .po-meter-status { color: var(--po-up); }
    .po-xray-summary { margin: 1rem 0 0; color: var(--po-ink2); font-size: 0.875rem; line-height: 1.5; }
    .po-xray-note { margin: 1rem 0 0; padding-top: 1rem; border-top: 1px solid var(--po-line); color: var(--po-muted);
                    font-size: 0.75rem; line-height: 1.4; }
    .po-xray-empty { color: var(--po-ink2); font-size: 0.875rem; }
    </style>""")
