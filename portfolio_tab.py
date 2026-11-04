"""Tab „Mein Portfolio“: eigenes Depot anlegen, aufteilen, Klumpenrisiken finden,
Absicherungen vorschlagen und Umschichtungen berechnen."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from portfolio_optimizer import charts, hedging as hg, optimization as opt, rebalancing as rb
from portfolio_optimizer import concentration as conc
from portfolio_optimizer.formatting import num, pct, ratio, styled
from portfolio_optimizer.market import (
    BASE_CURRENCY,
    DEMO_EXAMPLE,
    SearchHit,
    SecurityInfo,
    get_provider,
    major_currency,
    to_base_currency,
)
from portfolio_optimizer.portfolio import (
    Portfolio,
    PortfolioStore,
    exposures,
    is_concentration_group,
    read_positions_csv,
    valuation,
)

PROVIDERS = {"yahoo": "Yahoo Finance (live)", "demo": "Offline-Demo"}
DIMENSIONS = {"Sektoren": "sector", "Länder": "country", "Währungen": "currency"}
DEFAULT_NAME = "Mein Depot"
ANALYSIS_LIMIT = 24  # so viele Positionen nutzen die Analyse-Tabs höchstens

def store(provider: str) -> PortfolioStore:
    """Echte und Demo-Portfolios liegen getrennt, weil die Symbole nicht zusammenpassen.

    Ablageort: Ordner ``portfolios`` neben der App oder die Umgebungsvariable ``PORTFOLIO_DIR``.
    """
    root = Path(os.environ.get("PORTFOLIO_DIR") or Path(__file__).resolve().parent / "portfolios")
    return PortfolioStore(root if provider == "yahoo" else root / "demo")


# ---------------------------------------------------------------------------
# Zwischengespeicherte Marktdaten
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def search(provider: str, query: str) -> list[SearchHit]:
    return get_provider(provider).search(query)


@st.cache_data(ttl=86400, show_spinner=False)
def security_info(provider: str, symbol: str) -> SecurityInfo:
    return get_provider(provider).info(symbol)


@st.cache_data(ttl=3600, show_spinner="Lade Kurse …")
def prices_eur(provider: str, symbols: tuple[str, ...], currencies: tuple[str, ...], start: date, end: date):
    """Tageskurse in Euro; Spalten ohne Daten fehlen."""
    source = get_provider(provider)
    raw = source.prices(list(symbols), start, end)
    majors = sorted({major_currency(c)[0] for c in currencies} - {BASE_CURRENCY})
    fx = source.fx_rates(majors, start, end) if majors else pd.DataFrame()
    return to_base_currency(raw, dict(zip(symbols, currencies)), fx).dropna(how="all")


@st.cache_data(ttl=3600, show_spinner=False)
def fx_weekly_returns(provider: str, currencies: tuple[str, ...], start: date, end: date) -> pd.DataFrame:
    """Wochenrenditen eines in Fremdwährung gehaltenen Euros."""
    majors = sorted(set(currencies) - {BASE_CURRENCY})
    if not majors:
        return pd.DataFrame()
    fx = get_provider(provider).fx_rates(majors, start, end)
    return hg.weekly_returns(1 / fx) if not fx.empty else pd.DataFrame()


def instrument_prices(provider: str, start: date, end: date) -> pd.DataFrame:
    instruments = {i.symbol: i.currency for i in get_provider(provider).instruments}
    return prices_eur(provider, tuple(instruments), tuple(instruments.values()), start, end)


# ---------------------------------------------------------------------------
# Kontext: alles, was aus dem Portfolio und den Kursen folgt
# ---------------------------------------------------------------------------


@dataclass
class PortfolioContext:
    provider: str
    start: date
    end: date
    portfolio: Portfolio
    prices: pd.DataFrame  # Tageskurse in Euro je Symbol
    valuation: pd.DataFrame
    missing: list[str] = field(default_factory=list)

    @property
    def infos(self) -> dict[str, SecurityInfo]:
        return {p.symbol: p.info for p in self.portfolio.positions}

    @property
    def valued(self) -> pd.DataFrame:
        return self.valuation[self.valuation["value"] > 0]

    @property
    def value(self) -> float:
        return float(self.valued["value"].sum())

    @property
    def weights(self) -> pd.Series:
        return self.valued["weight"]

    @property
    def weekly(self) -> pd.DataFrame:
        return hg.weekly_returns(self.prices[list(self.weights.index)])

    @property
    def labels(self) -> dict[str, str]:
        """Kurze, eindeutige Namen für Diagramme."""
        out, seen = {}, set()
        for p in self.portfolio.positions:
            label = p.info.name if len(p.info.name) <= 26 else p.info.name[:25].rstrip() + "…"
            if label in seen:
                label = f"{label} ({p.symbol})"
            seen.add(label)
            out[p.symbol] = label
        return out

    def analysis_symbols(self) -> list[str]:
        return list(self.weights.sort_values(ascending=False).index[:ANALYSIS_LIMIT])

    def analysis_prices(self) -> pd.DataFrame:
        symbols = self.analysis_symbols()
        return self.prices[symbols].rename(columns=self.labels)

    def own_weights(self, assets: list[str]) -> np.ndarray:
        """Eigene Gewichte in der Reihenfolge der Analyse-Assets (Namen), normiert."""
        by_label = {self.labels[s]: w for s, w in self.weights.items()}
        w = np.array([by_label.get(a, 0.0) for a in assets])
        return w / w.sum()


def _session_key(provider: str) -> str:
    return f"portfolio_{provider}"


def current_portfolio(provider: str) -> Portfolio:
    key = _session_key(provider)
    if key not in st.session_state:
        names = store(provider).names()
        st.session_state[key] = store(provider).load(names[0]) if names else Portfolio(DEFAULT_NAME)
    return st.session_state[key]


def _set_portfolio(provider: str, portfolio: Portfolio, save: bool = True) -> None:
    st.session_state[_session_key(provider)] = portfolio
    st.session_state[f"pf_select_{provider}"] = portfolio.name
    if save:
        store(provider).save(portfolio)
    _bump_editor()


def _save(provider: str) -> None:
    store(provider).save(current_portfolio(provider))


def _bump_editor() -> None:
    st.session_state["pf_editor_version"] = st.session_state.get("pf_editor_version", 0) + 1


def _flash(message: str, kind: str = "success") -> None:
    st.session_state["pf_flash"] = (message, kind)


def _show_flash() -> None:
    message = st.session_state.pop("pf_flash", None)
    if message:
        text, kind = message
        st.toast(text, icon="✅" if kind == "success" else "⚠️")


def sidebar() -> tuple[str, date, date]:
    sb = st.sidebar
    provider = sb.radio(
        "Marktdaten", list(PROVIDERS), format_func=PROVIDERS.get, key="pf_provider",
        help="Die Offline-Demo nutzt fiktive Wertpapiere mit simulierten Kursen – zum Ausprobieren ohne Internet.",
    )
    years = sb.select_slider("Historie", [1, 2, 3, 5, 10, 15, 20], value=5, key="pf_years",
                             format_func=lambda y: f"{y} Jahr" if y == 1 else f"{y} Jahre",
                             help="Zeitraum für Risiko-, Hedge- und Optimierungsrechnungen.")
    end = date.today()
    start = (pd.Timestamp(end) - pd.DateOffset(years=years)).date()
    sb.caption("Alle Werte in Euro. Fremdwährungskurse werden mit den Wechselkursen umgerechnet.")
    return provider, start, end


def load_context(provider: str, start: date, end: date) -> PortfolioContext:
    portfolio = current_portfolio(provider)
    symbols = tuple(portfolio.symbols)
    currencies = tuple(p.info.currency for p in portfolio.positions)
    prices = pd.DataFrame()
    if symbols:
        try:
            prices = prices_eur(provider, symbols, currencies, start, end)
        except Exception as exc:  # Netzwerkfehler von yfinance sind nicht einheitlich typisiert
            st.error(f"Kurse konnten nicht geladen werden: {exc}")
    missing = [s for s in symbols if s not in prices.columns or prices[s].dropna().empty]
    last = prices.ffill().iloc[-1] if not prices.empty else pd.Series(dtype=float)
    ctx = PortfolioContext(provider, start, end, portfolio, prices, valuation(portfolio, last), missing)
    return ctx


# ---------------------------------------------------------------------------
# Verwaltung: Auswahl, Neu, Export/Import, Löschen
# ---------------------------------------------------------------------------


def _switch(provider: str) -> None:
    name = st.session_state[f"pf_select_{provider}"]
    _set_portfolio(provider, store(provider).load(name), save=False)


def _create(provider: str) -> None:
    name = st.session_state.get("pf_new_name", "").strip()
    if not name:
        _flash("Bitte einen Namen eingeben.", "error")
    elif store(provider).exists(name):
        _flash(f"Ein Portfolio „{name}“ gibt es schon.", "error")
    else:
        _set_portfolio(provider, Portfolio(name))
        st.session_state["pf_new_name"] = ""
        _flash(f"Portfolio „{name}“ angelegt.")


def _delete(provider: str) -> None:
    name = current_portfolio(provider).name
    store(provider).delete(name)
    names = store(provider).names()
    _set_portfolio(provider, store(provider).load(names[0]) if names else Portfolio(DEFAULT_NAME), save=False)
    _flash(f"Portfolio „{name}“ gelöscht.")


def _unique_name(provider: str, name: str) -> str:
    candidate, i = name, 2
    while store(provider).exists(candidate):
        candidate, i = f"{name} ({i})", i + 1
    return candidate


def _import(provider: str) -> None:
    upload = st.session_state.get("pf_upload")
    if upload is None:
        _flash("Bitte zuerst eine Datei auswählen.", "error")
        return
    content = upload.getvalue()
    stem = Path(upload.name).stem
    try:
        if upload.name.lower().endswith(".json"):
            portfolio = Portfolio.from_dict(json.loads(content.decode("utf-8-sig")))
            failed = []
        else:
            portfolio, failed = Portfolio(stem), []
            for symbol, shares, price in read_positions_csv(content):
                try:
                    portfolio.add(security_info(provider, symbol), shares, price)
                except Exception:  # unbekanntes Symbol oder Netzwerkfehler: Position überspringen
                    failed.append(symbol)
    except (ValueError, KeyError, TypeError) as exc:
        _flash(f"Import fehlgeschlagen: {exc}", "error")
        return
    portfolio.name = _unique_name(provider, portfolio.name)
    _set_portfolio(provider, portfolio)
    note = f" Nicht gefunden: {', '.join(failed)}." if failed else ""
    _flash(f"Portfolio „{portfolio.name}“ mit {len(portfolio.positions)} Positionen importiert.{note}",
           "error" if failed else "success")


def _load_example(provider: str) -> None:
    source = get_provider(provider)
    portfolio = Portfolio(_unique_name(provider, "Beispieldepot"))
    end = source.end if hasattr(source, "end") else date.today()
    start = (pd.Timestamp(end) - pd.DateOffset(years=3)).date()
    infos = {s: source.info(s) for s in DEMO_EXAMPLE}
    px = prices_eur(provider, tuple(infos), tuple(i.currency for i in infos.values()), start, end)
    two_years_ago = px.index[-1] - pd.DateOffset(years=2)
    for symbol, amount in DEMO_EXAMPLE.items():
        price = float(px[symbol].iloc[-1])
        portfolio.add(infos[symbol], round(amount / price, 2), round(float(px[symbol].asof(two_years_ago)), 2))
    _set_portfolio(provider, portfolio)
    _flash("Beispieldepot geladen.")


def _management(ctx: PortfolioContext) -> None:
    provider, portfolio = ctx.provider, ctx.portfolio
    names = store(provider).names()
    if portfolio.name not in names:
        names = [portfolio.name, *names]
    st.session_state.setdefault(f"pf_select_{provider}", portfolio.name)
    c1, c2, c3, c4 = st.columns([4, 1, 1, 1], vertical_alignment="bottom")
    c1.selectbox("Portfolio", names, key=f"pf_select_{provider}", on_change=_switch, args=(provider,))
    with c2.popover("Neu", icon=":material/add:", width="stretch"):
        st.text_input("Name des neuen Portfolios", key="pf_new_name")
        st.button("Anlegen", on_click=_create, args=(provider,), type="primary")
        if provider == "demo":
            st.divider()
            st.button("Beispieldepot laden", on_click=_load_example, args=(provider,),
                      help="Fiktives Depot mit Tech-Übergewicht und hohem Dollar-Anteil.")
    with c3.popover("Export/Import", icon=":material/swap_vert:", width="stretch"):
        st.download_button("Als JSON exportieren", portfolio.to_json(), file_name=f"{portfolio.name}.json",
                           mime="application/json", width="stretch")
        st.download_button("Als CSV exportieren (Excel)", portfolio.to_csv(), file_name=f"{portfolio.name}.csv",
                           mime="text/csv", width="stretch")
        st.divider()
        st.file_uploader("Importieren (JSON oder CSV)", type=["json", "csv"], key="pf_upload",
                         help="CSV mit den Spalten Symbol, Stück und optional Kaufkurs (EUR).")
        st.button("Importieren", on_click=_import, args=(provider,))
    with c4.popover("Löschen", icon=":material/delete:", width="stretch"):
        st.write(f"Portfolio „{portfolio.name}“ endgültig löschen?")
        st.button("Ja, löschen", on_click=_delete, args=(provider,), type="primary")


# ---------------------------------------------------------------------------
# Wertpapiersuche und Positionstabelle
# ---------------------------------------------------------------------------


def _add(provider: str, symbol: str) -> None:
    shares = float(st.session_state.get("pf_shares") or 0)
    price = float(st.session_state.get("pf_price") or 0) or None
    if shares <= 0:
        _flash("Bitte eine Stückzahl größer als null eingeben.", "error")
        return
    try:
        info = security_info(provider, symbol)
    except Exception as exc:  # Netzwerk- oder Datenfehler
        _flash(f"Stammdaten für {symbol} nicht abrufbar: {exc}", "error")
        return
    current_portfolio(provider).add(info, shares, price)
    _save(provider)
    _bump_editor()
    st.session_state["pf_query"] = ""
    _flash(f"{info.name} hinzugefügt.")


def _search_box(ctx: PortfolioContext) -> None:
    provider = ctx.provider
    st.markdown("**Wertpapier hinzufügen**")
    placeholder = ("z. B. Nordlicht, Technologie, ETF" if provider == "demo"
                   else "Name, Ticker oder ISIN – z. B. Apple, SAP.DE oder IE00B4L5Y983")
    query = st.text_input("Suche", key="pf_query", placeholder=placeholder, label_visibility="collapsed").strip()
    if not query:
        return
    try:
        hits = search(provider, query)
    except Exception as exc:  # Netzwerkfehler
        st.error(f"Die Suche ist fehlgeschlagen ({exc}). Ist Yahoo Finance erreichbar?")
        return
    if not hits:
        st.info("Keine passenden Wertpapiere gefunden. Versuche den Ticker (z. B. „SAP.DE“) oder die ISIN.")
        return
    c1, c2, c3, c4 = st.columns([4, 1.2, 1.6, 1.1], vertical_alignment="bottom")
    index = c1.selectbox("Treffer", range(len(hits)), format_func=lambda i: hits[i].label,
                         key=f"pf_hit_{query}")
    c2.number_input("Stückzahl", min_value=0.0, value=1.0, step=1.0, key="pf_shares")
    c3.number_input("Kaufkurs je Stück (EUR)", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="pf_price",
                    help="Einstandskurs laut Depotauszug in Euro. 0 = unbekannt (dann ohne Gewinn/Verlust).")
    hit = hits[index]
    c4.button("Hinzufügen", type="primary", on_click=_add, args=(provider, hit.symbol), width="stretch")
    try:
        info = security_info(provider, hit.symbol)
        px = prices_eur(provider, (hit.symbol,), (info.currency,),
                        (pd.Timestamp(ctx.end) - pd.DateOffset(days=14)).date(), ctx.end)
        price = f"Aktueller Kurs: {num(float(px[hit.symbol].dropna().iloc[-1]), 2)} € · " if not px.empty else ""
        st.caption(f"{price}{info.quote_type} · {info.sector} · {info.country} · Handelswährung {info.currency}")
    except Exception:  # Zusatzinfo ist optional
        pass


def _apply_edits(provider: str, editor_key: str, symbols: list[str]) -> None:
    portfolio = current_portfolio(provider)
    for row, changes in st.session_state[editor_key].get("edited_rows", {}).items():
        symbol = symbols[int(row)]
        position = portfolio.get(symbol)
        if position is None:
            continue
        if changes.get("Entfernen"):
            portfolio.remove(symbol)
            continue
        if "Stück" in changes:
            shares = changes["Stück"]
            if not shares or shares <= 0:
                portfolio.remove(symbol)
                continue
            position.shares = float(shares)
        if "Kaufkurs" in changes:
            position.purchase_price = float(changes["Kaufkurs"]) if changes["Kaufkurs"] else None
    _save(provider)
    _bump_editor()


def _positions(ctx: PortfolioContext) -> None:
    val = ctx.valuation
    cost_known = val["cost"].notna()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Depotwert", f"{num(ctx.value)} €", border=True)
    if cost_known.any():
        cost, now = float(val.loc[cost_known, "cost"].sum()), float(val.loc[cost_known, "value"].sum())
        c2.metric("Einstandswert", f"{num(cost)} €", border=True,
                  help=None if cost_known.all() else "Nur Positionen mit Kaufkurs.")
        c3.metric("Gewinn/Verlust", f"{num(now - cost)} €", delta=pct(now / cost - 1, signed=True) if cost else None,
                  border=True)
    else:
        c2.metric("Einstandswert", "–", border=True, help="Kaufkurse eintragen, um Gewinn/Verlust zu sehen.")
        c3.metric("Gewinn/Verlust", "–", border=True)
    c4.metric("Positionen", str(len(ctx.portfolio.positions)), border=True)
    if ctx.missing:
        st.warning(f"Keine Kurse für: {', '.join(ctx.missing)}. Diese Positionen fehlen in Wert und Analysen.")

    symbols = list(val.index)
    table = pd.DataFrame({
        "Entfernen": False,
        "Name": val["name"],
        "Symbol": symbols,
        "Stück": val["shares"],
        "Kaufkurs": val["purchase_price"],
        "Kurs": val["price"],
        "Wert": val["value"],
        "G/V": val["pnl"],
        "G/V %": val["pnl_pct"],
        "Gewicht": val["weight"],
    })
    key = f"pf_editor_{st.session_state.get('pf_editor_version', 0)}"
    st.data_editor(
        table, key=key, hide_index=True, on_change=_apply_edits, args=(ctx.provider, key, symbols),
        disabled=["Name", "Symbol", "Kurs", "Wert", "G/V", "G/V %", "Gewicht"],
        column_config={
            "Entfernen": st.column_config.CheckboxColumn("🗑", help="Position entfernen", width=40),
            "Name": st.column_config.TextColumn("Name", width=190),
            "Symbol": st.column_config.TextColumn("Symbol", width=85),
            "Stück": st.column_config.NumberColumn("Stück", min_value=0.0, format="localized", width=70),
            "Kaufkurs": st.column_config.NumberColumn("Kaufkurs €", min_value=0.0, format="euro", width=95,
                                                      help="Einstandskurs je Stück in Euro"),
            "Kurs": st.column_config.NumberColumn("Kurs €", format="euro", width=90),
            "Wert": st.column_config.NumberColumn("Wert €", format="euro", width=100),
            "G/V": st.column_config.NumberColumn("G/V €", format="euro", width=90),
            "G/V %": st.column_config.NumberColumn("G/V %", format="percent", width=70),
            "Gewicht": st.column_config.ProgressColumn("Gewicht", min_value=0.0, max_value=1.0, format="percent",
                                                       width=100),
        },
    )
    st.caption("Stückzahl und Kaufkurs lassen sich direkt in der Tabelle ändern; 🗑 entfernt eine Position.")


# ---------------------------------------------------------------------------
# Analysen
# ---------------------------------------------------------------------------


def current_limits() -> conc.Limits:
    return st.session_state.get("pf_limits", conc.Limits())


def _limits_editor() -> conc.Limits:
    d = current_limits()
    with st.expander("Grenzen für Klumpenrisiko anpassen"):
        c1, c2, c3 = st.columns(3)
        position = c1.slider("Einzelaktie", 2, 50, int(d.position * 100), 1, format="%d %%", key="pf_lim_position")
        sector = c2.slider("Sektor", 10, 80, int(d.sector * 100), 5, format="%d %%", key="pf_lim_sector")
        country = c3.slider("Land", 20, 100, int(d.country * 100), 5, format="%d %%", key="pf_lim_country")
        c4, c5, c6 = st.columns(3)
        currency = c4.slider("Fremdwährung (je Währung)", 10, 100, int(d.currency * 100), 5, format="%d %%",
                             key="pf_lim_currency")
        cluster = c5.slider("Korrelations-Cluster", 10, 100, int(d.cluster * 100), 5, format="%d %%",
                            key="pf_lim_cluster")
        corr = c6.slider("Korrelation ab", 0.5, 0.95, float(d.correlation), 0.05, key="pf_lim_corr",
                         help="Einzelwerte, die im Mittel mindestens so stark korrelieren, bilden einen Cluster.")
        st.caption("Fonds und ETFs zählen nicht als Einzelaktie, weil sie selbst breit gestreut sind. "
                   "Euro, Anleihen und Geldmarkt sind von den Grenzen ausgenommen.")
    limits = conc.Limits(position / 100, sector / 100, country / 100, currency / 100, cluster / 100, corr)
    st.session_state["pf_limits"] = limits
    return limits


def _allocation(ctx: PortfolioContext, theme) -> None:
    choice = st.segmented_control("Aufteilung nach", list(DIMENSIONS), default="Sektoren", key="pf_dim",
                                 required=True) or "Sektoren"
    by = DIMENSIONS[choice]
    shares = exposures(ctx.weights, ctx.infos, by)
    limits = current_limits()
    limited = {g for g in shares.index if is_concentration_group(by, g)}
    charts_col, table_col = st.columns([3, 2])
    with charts_col:
        st.plotly_chart(charts.exposure_chart(shares, theme, limits.for_kind(by), limited), theme=None,
                        config={"displaylogo": False})
    with table_col:
        table = pd.DataFrame({"Anteil": shares, "Wert (EUR)": shares * ctx.value})
        table.index.name = choice[:-2] if choice.endswith("en") else choice
        st.dataframe(styled(table, pct_cols=("Anteil",), num_cols=("Wert (EUR)",)))
    notes = {
        "sector": "ETFs und Fonds werden über ihre Sektorgewichte aufgeteilt (Durchschau), soweit Yahoo diese "
                  "liefert. Anleihen, Geldmarkt und Rohstoffe erscheinen als eigene Gruppen.",
        "country": "Für Fonds liefert Yahoo keine Länderaufteilung; sie erscheinen als „Mehrere Länder (Fonds)“.",
        "currency": "Maßgeblich ist die Handelswährung. Ein in Euro gehandelter Welt-ETF enthält wirtschaftlich "
                    "trotzdem Dollar-Risiko.",
    }
    st.caption(notes[by])


def _concentration(ctx: PortfolioContext, theme) -> conc.ConcentrationReport:
    limits = _limits_editor()
    report = conc.analyze(ctx.weights, ctx.infos, ctx.weekly, limits)
    singles = [w for s, w in ctx.weights.items() if not ctx.infos[s].is_fund]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Effektive Anzahl Positionen", num(report.effective_positions, 1), border=True,
              help="1 / Herfindahl-Index: So viele gleich große Positionen hätten dieselbe Konzentration.")
    c2.metric("Top-5-Anteil", pct(report.top5), border=True)
    c3.metric("Größte Einzelaktie", pct(max(singles)) if singles else "–", border=True)
    c4.metric("Diversifikationsquote", ratio(report.diversification_ratio), border=True,
              help="Gewichtete Einzelvolatilitäten geteilt durch die Depotvolatilität. Je höher, desto mehr "
                   "gleichen sich die Positionen gegenseitig aus (1 = keine Streuungswirkung).")

    if report.exceeded:
        st.markdown("**Über den Grenzen**")
        for f in report.exceeded:
            st.markdown(
                f"- 🔴 **{conc.KINDS[f.kind]} {f.group}**: {pct(f.weight)} des Depots (Grenze {pct(f.limit, 0)}), "
                f"verursacht {pct(f.risk_share)} der Schwankung"
            )
    else:
        st.success("Keine Konzentration über den Grenzen.")
    near = [f for f in report.findings if f.status == "nahe Grenze"]
    if near:
        st.caption("Nahe an der Grenze: " + ", ".join(f"{f.group} ({pct(f.weight)})" for f in near))

    st.markdown("**Gewicht und Risikoanteil je Position**")
    order = ctx.weights.sort_values(ascending=False).index
    labels = [ctx.labels[s] for s in order]
    st.plotly_chart(
        charts.weight_risk_chart(labels, ctx.weights[order].to_numpy(), report.risk_shares.reindex(order).to_numpy(),
                                 theme),
        theme=None, config={"displaylogo": False},
    )
    st.caption("Der Risikoanteil zeigt, welcher Teil der Depotschwankung auf eine Position entfällt. Liegt er "
               "deutlich über dem Gewicht, ist die Position volatil oder läuft stark mit dem Rest des Depots.")
    with st.expander("Alle Konzentrationen als Tabelle"):
        rows = [{"Art": conc.KINDS[f.kind], "Gruppe": f.group, "Gewicht": f.weight, "Risikoanteil": f.risk_share,
                 "Grenze": f.limit, "Status": f.status} for f in report.findings]
        st.dataframe(styled(pd.DataFrame(rows), pct_cols=("Gewicht", "Risikoanteil", "Grenze")), hide_index=True)
    return report


def _hedges(ctx: PortfolioContext, report: conc.ConcentrationReport, theme) -> None:
    provider = get_provider(ctx.provider)
    try:
        inst_prices = instrument_prices(ctx.provider, ctx.start, ctx.end)
    except Exception as exc:  # Netzwerkfehler
        st.error(f"Kurse der Absicherungsinstrumente konnten nicht geladen werden: {exc}")
        return
    inst_ret = hg.weekly_returns(inst_prices)
    port = hg.portfolio_returns(ctx.weights, ctx.weekly)
    if len(port) < hg.MIN_OBSERVATIONS:
        st.info("Für Absicherungsvorschläge wird mindestens ein halbes Jahr gemeinsamer Kurshistorie benötigt.")
        return
    value = ctx.value

    st.subheader("Markt-Hedge (Beta)")
    quote = st.slider("Absicherungsquote", 0, 100, 100, 10, format="%d %%", key="pf_hedge_ratio",
                      help="Welcher Teil des Marktrisikos abgesichert werden soll.") / 100
    hedges = hg.beta_hedges(port, inst_ret, provider.instruments, value, quote)
    if hedges:
        best = hedges[0]
        st.markdown(
            f"Am besten erklärt **{best.instrument.label}** dein Depot (R² {ratio(best.r2)}, Beta {ratio(best.beta)}). "
            f"Eine Short-Position von **{num(best.notional)} €** senkt die Volatilität von {pct(best.vol_before)} "
            f"auf **{pct(best.vol_after)}** und den größten historischen Rückgang von {pct(best.mdd_before)} auf "
            f"{pct(best.mdd_after)}."
        )
        table = pd.DataFrame([{
            "Index": h.instrument.label, "Beta": h.beta, "R²": h.r2, "Short-Betrag (EUR)": h.notional,
            "Volatilität danach": h.vol_after, "Max. Rückgang danach": h.mdd_after, "Rendite p. a. danach": h.ret_after,
        } for h in hedges])
        st.dataframe(styled(table, pct_cols=("Volatilität danach", "Max. Rückgang danach", "Rendite p. a. danach"),
                            ratio_cols=("Beta", "R²"), num_cols=("Short-Betrag (EUR)",)), hide_index=True)
        st.caption(
            "Umsetzung über Index-Futures, Short-ETFs oder Put-Optionen. Mit dem Marktrisiko sichert man auch "
            "die erwartete Marktrendite ab. Short-ETFs mit täglicher Neugewichtung weichen über längere Zeiträume "
            "vom einfachen Gegenteil des Index ab. Rendite danach: historisch, ohne Kosten und Zinsen."
        )
    else:
        st.info("Für die Marktindizes liegen keine ausreichenden Kurse vor.")

    st.subheader("Diversifizierende Beimischung")
    share = st.slider("Anteil der Beimischung", 5, 50, 20, 5, format="%d %%", key="pf_mix_share",
                      help="Welcher Teil des Depots in die Beimischung umgeschichtet würde.") / 100
    divs = hg.diversifiers(port, inst_ret, provider.instruments, share, exclude=set(ctx.weights.index))
    if divs:
        table = pd.DataFrame([{
            "Beimischung": d.instrument.label, "Korrelation": d.corr, "Eigene Volatilität": d.vol,
            "Depot-Volatilität danach": d.vol_after, "Max. Rückgang danach": d.mdd_after,
            "Rendite p. a. danach": d.ret_after,
        } for d in divs])
        st.dataframe(styled(table, pct_cols=("Eigene Volatilität", "Depot-Volatilität danach",
                                             "Max. Rückgang danach", "Rendite p. a. danach"),
                            ratio_cols=("Korrelation",)), hide_index=True)
        st.caption(f"Ohne Beimischung: Volatilität {pct(divs[0].vol_before)}, größter Rückgang "
                   f"{pct(divs[0].mdd_before)}, Rendite p. a. {pct(divs[0].ret_before)} (historisch). "
                   "Das Diagramm zeigt die Volatilität für die drei wirksamsten Beimischungen bei steigendem Anteil.")
        curves = {d.instrument.label: hg.mix_curve(port, inst_ret[d.instrument.symbol], np.linspace(0, 0.6, 25))
                  for d in divs[:3]}
        st.plotly_chart(charts.mix_curve_chart(curves, theme, share), theme=None, config={"displaylogo": False})

    st.subheader("Klumpenrisiko absichern")
    fx_ret = fx_weekly_returns(ctx.provider, tuple(sorted({major_currency(i.currency)[0] for i in ctx.infos.values()})),
                               ctx.start, ctx.end)
    items = hg.concentration_hedges(report.findings, ctx.weights, ctx.weekly, value, inst_ret,
                                    provider.instruments, fx_ret)
    if not items:
        st.success("Keine Konzentration über den Grenzen – hier gibt es nichts abzusichern.")
    for item in items:
        f = item.finding
        with st.container(border=True):
            st.markdown(f"**{conc.KINDS[f.kind]} {f.group}**: {pct(f.weight)} des Depots, Grenze {pct(f.limit, 0)}")
            left, right = st.columns(2)
            left.markdown(f"**Reduzieren:** {num(item.reduce_amount)} € verkaufen und breiter anlegen "
                          "(siehe *Umschichtung*).")
            if item.instrument is None:
                right.markdown("**Absichern:** kein passendes Instrument mit ausreichender Historie gefunden.")
            elif f.kind == "currency":
                right.markdown(
                    f"**Absichern:** {f.group} im Wert von {num(item.notional)} € per Devisentermingeschäft "
                    "verkaufen oder währungsgesicherte Anteilsklassen („EUR Hedged“) nutzen. Depot-Volatilität "
                    f"{pct(item.vol_before)} → **{pct(item.vol_after)}**."
                )
            else:
                right.markdown(
                    f"**Absichern:** Short {num(item.notional)} € **{item.instrument.label}** "
                    f"(Beta {ratio(item.beta)}, R² {ratio(item.r2)}). Depot-Volatilität {pct(item.vol_before)} → "
                    f"**{pct(item.vol_after)}**."
                )
    st.caption("Abgesichert wird jeweils nur der Teil über der Grenze. Alle Kennzahlen beruhen auf historischen "
               "Wochenrenditen in Euro und sind keine Anlageberatung.")


def _target_weights(ctx, goal, report, est, rf, bounds, use_world) -> tuple[pd.Series | None, dict]:
    """Zielgewichte je Symbol und Zusatzinfos (Kurse, Stammdaten) für neue Positionen."""
    infos, prices = dict(ctx.infos), ctx.prices.ffill().iloc[-1]
    if goal == "limits":
        current = ctx.weights.copy()
        world = get_provider(ctx.provider).world_fund
        if use_world and world not in current.index:
            try:
                infos[world] = security_info(ctx.provider, world)
                px = prices_eur(ctx.provider, (world,), (infos[world].currency,), ctx.start, ctx.end)
                prices = pd.concat([prices, px.ffill().iloc[-1]])
                current[world] = 0.0
            except Exception:  # ohne Welt-ETF weiterrechnen
                infos.pop(world, None)
        target, remaining = rb.closest_to_limits(current, infos, current_limits(), report.clusters)
        if remaining:
            st.warning(
                "Mit den vorhandenen Positionen lassen sich nicht alle Grenzen einhalten. Der Vorschlag kommt "
                "ihnen so nahe wie möglich, ohne neue Überschreitungen zu erzeugen. Verbleibender Überhang: "
                + ", ".join(f"{label} +{pct(v)}" for label, v in list(remaining.items())[:4])
                + ". Abhilfe: Grenzen lockern, den Welt-ETF als Ausgleich zulassen oder breiter gestreute "
                "Positionen aufnehmen."
            )
        return target, {"infos": infos, "prices": prices, "unreachable": bool(remaining)}
    if est is None:
        st.info("Für dieses Ziel werden mindestens zwei Positionen mit gemeinsamer Kurshistorie benötigt.")
        return None, {}
    own = ctx.own_weights(est.assets)
    if goal == "same_risk":
        w = opt.efficient_risk(est.mu, est.cov, opt.portfolio_stats(own, est.mu, est.cov)[1], bounds)
    elif goal == "gmv":
        w = opt.min_variance(est.cov, bounds)
    else:
        w = opt.max_sharpe(est.mu, est.cov, rf, bounds)
        if w is None:
            st.warning("Kein Portfolio erwartet eine Rendite über dem risikolosen Zins.")
            return None, {}
    if (w < -1e-9).any():
        st.warning("Die Zielgewichte enthalten Leerverkäufe. Für Umschichtungen bitte in der Seitenleiste "
                   "Leerverkäufe ausschalten.")
        return None, {}
    by_label = {label: s for s, label in ctx.labels.items()}
    universe = [by_label[a] for a in est.assets]
    # Positionen außerhalb der Analyse (mehr als ANALYSIS_LIMIT) behalten ihr Gewicht.
    target = ctx.weights.copy()
    target[universe] = w * ctx.weights[universe].sum()
    return target, {"infos": infos, "prices": prices}


def _rebalancing(ctx: PortfolioContext, report, est, rf, bounds, theme) -> None:
    goals = {
        "limits": "Klumpenrisiko begrenzen",
        "same_risk": "Effizient bei gleichem Risiko",
        "gmv": "Minimum-Varianz",
        "max_sharpe": "Max-Sharpe",
    }
    goal = st.radio("Ziel", list(goals), format_func=goals.get, horizontal=True, key="pf_goal")
    c1, c2, c3 = st.columns(3)
    use_world = c1.checkbox("Welt-ETF als Ausgleich zulassen", value=True, key="pf_use_world",
                            disabled=goal != "limits",
                            help="Erlaubt den Kauf eines breit gestreuten Welt-ETFs, wenn die Grenzen sonst "
                                 "nicht einzuhalten sind.")
    whole = c2.toggle("Ganze Stückzahlen", value=True, key="pf_whole")
    min_trade = c3.number_input("Kleinstbetrag je Transaktion (EUR)", 0, 100_000, 50, 25, key="pf_min_trade",
                                help="Kleinere Umschichtungen werden ausgelassen.")
    target, extra = _target_weights(ctx, goal, report, est, rf, bounds, use_world)
    if target is None:
        return
    infos, prices = extra["infos"], extra["prices"]
    tr = rb.trades(ctx.valued, target, prices, whole_shares=whole, min_trade=float(min_trade))
    buys, sells = tr.loc[tr["amount"] > 0, "amount"].sum(), -tr.loc[tr["amount"] < 0, "amount"].sum()
    realized = tr["realized_gain"].sum(min_count=1)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Käufe", f"{num(buys)} €", border=True)
    m2.metric("Verkäufe", f"{num(sells)} €", border=True)
    m3.metric("Restliquidität", f"{num(sells - buys)} €", border=True,
              help="Positiv: bleibt als Guthaben übrig (Rundung, ausgelassene Kleinbeträge). Negativ: wird zusätzlich benötigt.")
    m4.metric("Realisierte Gewinne", f"{num(realized)} €" if pd.notna(realized) else "–", border=True,
              help="Aus den Verkäufen, sofern Kaufkurse eingetragen sind. Gewinne unterliegen der Abgeltungsteuer.")

    active = tr[tr["action"] != "Halten"]
    if active.empty:
        st.success("Das Depot erfüllt das Ziel bereits – keine Umschichtung nötig.")
    else:
        table = pd.DataFrame({
            "Name": [infos[s].name if s in infos else s for s in active.index],
            "Aktion": active["action"],
            "Stück": active["shares_delta"].abs(),
            "Betrag (EUR)": active["amount"].abs(),
            "Gewicht vorher": active["weight_before"],
            "Gewicht nachher": active["weight_after"],
        })
        st.dataframe(styled(table, pct_cols=("Gewicht vorher", "Gewicht nachher"), num_cols=("Betrag (EUR)",))
                     .format(lambda v: num(v, 0 if whole else 2), subset=["Stück"]), hide_index=True)
    order = tr.sort_values("weight_before", ascending=False).index
    labels = [ctx.labels.get(s, infos[s].name if s in infos else s) for s in order]
    st.plotly_chart(charts.comparison_chart(labels, tr.loc[order, "weight_before"].to_numpy(),
                                            tr.loc[order, "weight_after"].to_numpy(), theme, "Gewicht"),
                    theme=None, config={"displaylogo": False})

    # Gewichte relativ zum Depotwert inklusive Restliquidität (nicht neu normieren)
    after = tr["weight_after"][tr["weight_after"] > 0]
    after_report = conc.analyze(after, infos, hg.weekly_returns(_prices_for(ctx, after.index, infos)),
                                current_limits())
    if goal == "limits":
        if after_report.exceeded:
            reason = ("nicht vollständig erreichbar, siehe oben" if extra.get("unreachable")
                      else "Rundung oder ausgelassene Kleinbeträge")
            st.info(f"Nach der Umschichtung noch über den Grenzen ({reason}): "
                    + ", ".join(f"{f.group} {pct(f.weight)}" for f in after_report.exceeded))
        else:
            st.success("Nach der Umschichtung liegen alle Konzentrationen innerhalb der Grenzen.")
    else:
        st.caption("Ziele aus der Optimierung beruhen auf geschätzten Renditen und Risiken (Einstellungen in der "
                   "Seitenleiste) – wie unsicher diese sind, zeigt der Tab **Schätzfehler**.")
    st.caption("Transaktionskosten und Steuern sind nicht berücksichtigt. Keine Anlageberatung.")


def _prices_for(ctx: PortfolioContext, symbols, infos) -> pd.DataFrame:
    have = [s for s in symbols if s in ctx.prices.columns]
    extra = [s for s in symbols if s not in ctx.prices.columns]
    if not extra:
        return ctx.prices[have]
    px = prices_eur(ctx.provider, tuple(extra), tuple(infos[s].currency for s in extra), ctx.start, ctx.end)
    return pd.concat([ctx.prices[have], px], axis=1)


# ---------------------------------------------------------------------------
# Einstieg
# ---------------------------------------------------------------------------


def render(ctx: PortfolioContext, est, rf, bounds, theme) -> None:
    _show_flash()
    _management(ctx)
    _search_box(ctx)
    if not ctx.portfolio.positions:
        st.info("Das Portfolio ist noch leer. Suche oben nach Aktien oder ETFs und füge sie mit Stückzahl und "
                "Kaufkurs hinzu." + (" Oder lade unter **Neu** das Beispieldepot." if ctx.provider == "demo" else ""))
        return
    _positions(ctx)
    if ctx.value <= 0 or len(ctx.weekly.dropna()) < 10:
        st.info("Für die Analysen werden Kurse mit etwas Historie benötigt.")
        return
    tabs = st.tabs(["Aufteilung", "Klumpenrisiko", "Absicherung", "Umschichtung"], key="pf_subtab",
                   on_change="rerun")
    report = None
    if tabs[0].open:
        with tabs[0]:
            _allocation(ctx, theme)
    if tabs[1].open:
        with tabs[1]:
            report = _concentration(ctx, theme)
    if report is None:
        report = conc.analyze(ctx.weights, ctx.infos, ctx.weekly, current_limits())
    if tabs[2].open:
        with tabs[2]:
            _hedges(ctx, report, theme)
    if tabs[3].open:
        with tabs[3]:
            _rebalancing(ctx, report, est, rf, bounds, theme)
