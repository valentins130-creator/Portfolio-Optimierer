"""Daten der Oberfläche: Einstellungen, zwischengespeicherte Marktdaten, gespeicherte
Portfolios und der Kontext, den alle Seiten nutzen."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from portfolio_optimizer import charts, data, hedging as hg, optimization as opt
from portfolio_optimizer import concentration as conc
from portfolio_optimizer.estimators import Estimates, estimate
from portfolio_optimizer.market import (
    BASE_CURRENCY,
    DEMO_EXAMPLE,
    SearchHit,
    SecurityInfo,
    fx_ticker,
    get_provider,
    major_currency,
    price_in_euro,
    to_base_currency,
)
from portfolio_optimizer.data import split_events
from portfolio_optimizer.portfolio import BUY, SELL, Portfolio, PortfolioStore, split_factor, valuation
from portfolio_optimizer.price_store import PriceStore

PROVIDERS = {"yahoo": "Yahoo Finance (live)", "demo": "Offline-Demo"}
DEFAULT_NAME = "Mein Depot"
ANALYSIS_LIMIT = 24  # so viele Positionen nutzen die Analysen höchstens


def _root() -> Path:
    """Ablageort der Portfolios und Kurse.

    Vorrang hat die Umgebungsvariable ``PORTFOLIO_DIR``. Auf Railway nimmt die App das angehängte
    Volume (Railway setzt ``RAILWAY_VOLUME_MOUNT_PATH``), damit die Depots einen Neustart überstehen.
    Sonst der Ordner ``portfolios`` neben der App.
    """
    folder = os.environ.get("PORTFOLIO_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    return Path(folder) if folder else Path(__file__).resolve().parents[1] / "portfolios"


def user_root(account) -> Path:
    """Eigener Ordner eines Kontos; die Kennung ist eine zufällige Hex-Zeichenfolge."""
    return _root() / "nutzer" / account.id


def data_root() -> Path:
    """Ablage der Depots: mit Konten der Ordner des angemeldeten Nutzers, sonst der gemeinsame Ordner."""
    account = st.session_state.get("user")
    return user_root(account) if account is not None else _root()


def store(provider: str) -> PortfolioStore:
    """Echte und Demo-Portfolios liegen getrennt, weil die Symbole nicht zusammenpassen."""
    return PortfolioStore(data_root() if provider == "yahoo" else data_root() / "demo")


def price_store() -> PriceStore:
    """Zuletzt erfolgreich geladene Yahoo-Kurse (Rückfall, wenn Yahoo zeitweise nichts liefert)."""
    return PriceStore(_root() / "kurse")


# ---------------------------------------------------------------------------
# Marktdaten
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def search(provider: str, query: str) -> list[SearchHit]:
    return get_provider(provider).search(query)


@st.cache_data(ttl=86400, show_spinner=False)
def security_info(provider: str, symbol: str) -> SecurityInfo:
    return get_provider(provider).info(symbol)


@dataclass(frozen=True)
class HistoryEUR:
    close: pd.DataFrame  # tatsächliche Schlusskurse in Euro (splitbereinigt)
    adjusted: pd.DataFrame  # zusätzlich dividendenbereinigt, für Renditen und Risiko
    splits: dict[str, list[tuple[date, float]]]  # Symbol -> [(Ex-Tag, Verhältnis)]
    missing: list[str]  # Symbole ohne Kurse
    stale: dict[str, date]  # Symbole mit Kursen aus dem lokalen Speicher -> letzter Kurstag


def _load_history(provider: str, symbols: tuple[str, ...], currencies: tuple[str, ...], start: date,
                  end: date) -> HistoryEUR:
    majors = sorted({major_currency(c)[0] for c in currencies} - {BASE_CURRENCY})
    fx_tickers = {fx_ticker(c): c for c in majors}
    hist = get_provider(provider).history([*symbols, *fx_tickers], start, end)  # ein Abruf samt Devisen
    stale: dict[str, date] = {}
    if provider == "yahoo":
        hist, stale = price_store().complete(hist, start, end)
    fx = hist.close[[t for t in fx_tickers if t in hist.close.columns]].rename(columns=fx_tickers)
    have = [s for s in symbols if s in hist.close.columns]
    currency = dict(zip(symbols, currencies))
    close = to_base_currency(hist.close[have], {s: currency[s] for s in have}, fx).dropna(how="all")
    adjusted = to_base_currency(hist.adj_close.reindex(columns=have), {s: currency[s] for s in have},
                                fx).dropna(how="all")
    have = [s for s in have if s in close.columns and close[s].notna().any()]  # ohne Wechselkurs kein Euro-Wert
    # Kurse aus dem Speicher gelten als veraltet, ebenso alle, deren Wechselkurs von dort stammt
    fx_stale = {fx_tickers[t] for t in stale if t in fx_tickers}
    stale_symbols = {s: d for s, d in stale.items() if s in have}
    for s in have:
        if s not in stale_symbols and major_currency(currency[s])[0] in fx_stale:
            stale_symbols[s] = min(d for t, d in stale.items() if t in fx_tickers)
    return HistoryEUR(close[have], adjusted.reindex(columns=have), split_events(hist.splits.reindex(columns=have)),
                      [s for s in symbols if s not in have], stale_symbols)


class _Incomplete(Exception):
    def __init__(self, result: HistoryEUR):
        super().__init__("unvollständige Kursdaten")
        self.result = result


@st.cache_data(ttl=3600, show_spinner="Lade Kurse …", max_entries=300)
def _history_cached(provider: str, symbols: tuple[str, ...], currencies: tuple[str, ...], start: date,
                    end: date) -> HistoryEUR:
    result = _load_history(provider, symbols, currencies, start, end)
    if result.missing or result.stale:
        raise _Incomplete(result)  # Lücken nicht eine Stunde lang festhalten
    return result


_RECENT_GAPS: dict[tuple, tuple[float, HistoryEUR]] = {}
GAP_RETRY_SECONDS = 120  # so lange gilt ein lückenhaftes Ergebnis, bevor Yahoo erneut gefragt wird


def history_eur(provider: str, symbols: tuple[str, ...], currencies: tuple[str, ...], start: date,
                end: date) -> HistoryEUR:
    """Kurse in Euro samt Splits. Vollständige Ergebnisse bleiben eine Stunde im Zwischenspeicher;
    lückenhafte (Yahoo drosselt) nur zwei Minuten, damit nicht jeder Klick neu anfragt."""
    key = (provider, tuple(symbols), tuple(currencies), start, end)
    recent = _RECENT_GAPS.get(key)
    if recent and time.monotonic() - recent[0] < GAP_RETRY_SECONDS:
        return recent[1]
    try:
        result = _history_cached(*key)
    except _Incomplete as exc:
        _RECENT_GAPS[key] = (time.monotonic(), exc.result)
        return exc.result
    _RECENT_GAPS.pop(key, None)
    return result


def prices_eur(provider: str, symbols: tuple[str, ...], currencies: tuple[str, ...], start: date, end: date,
               adjusted: bool = True) -> pd.DataFrame:
    """Tägliche Schlusskurse in Euro; Spalten ohne Daten fehlen.

    ``adjusted``: dividendenbereinigt für Renditen und Risiko; sonst die tatsächlichen
    Schlusskurse für Bewertung, Wertentwicklung und Kursvorschläge.
    """
    hist = history_eur(provider, tuple(symbols), tuple(currencies), start, end)
    return (hist.adjusted if adjusted else hist.close).dropna(how="all")


@st.cache_data(ttl=60, show_spinner=False)
def live_quotes(provider: str, tickers: tuple[str, ...]) -> pd.DataFrame:
    """Letzte Minutenkurse (Yahoo, verzögert); leer, wenn keine vorliegen."""
    try:
        return get_provider(provider).live_prices(list(tickers))
    except Exception:  # Live-Kurse sind eine Ergänzung; ohne sie gelten die Schlusskurse
        return pd.DataFrame(columns=["price", "time"])


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


def close_on(provider: str, info: SecurityInfo, when: date) -> tuple[float, date] | None:
    """Tatsächlicher Schlusskurs in Euro am Datum oder am letzten Handelstag davor.

    Liegt danach ein Aktiensplit, gilt der Kurs in der damaligen Stückelung – so wie in der
    Abrechnung. Geladen wird ab Jahresbeginn, damit weitere Daten im selben Jahr keinen neuen
    Abruf brauchen.
    """
    try:
        hist = history_eur(provider, (info.symbol,), (info.currency,),
                           date(when.year, 1, 1) - timedelta(days=10), date.today())
    except Exception:  # Netzwerkfehler: ohne Vorschlag weiter
        return None
    if info.symbol not in hist.close.columns:
        return None
    series = hist.close[info.symbol].loc[:pd.Timestamp(when)].dropna()
    if series.empty:
        return None
    day = series.index[-1].date()
    return float(series.iloc[-1]) * split_factor(hist.splits.get(info.symbol, []), day), day


# ---------------------------------------------------------------------------
# Einstellungen und Klumpenrisiko-Grenzen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    provider: str = "yahoo"
    years: int = 5
    mean_method: str = "sample"
    cov_method: str = "sample"
    rf: float = 0.02
    bounds: tuple[float, float] | None = (0.0, 1.0)

    @property
    def end(self) -> date:
        return date.today()

    @property
    def start(self) -> date:
        return (pd.Timestamp(self.end) - pd.DateOffset(years=self.years)).date()


def current_limits() -> conc.Limits:
    return st.session_state.get("pf_limits", conc.Limits())


# ---------------------------------------------------------------------------
# Gespeicherte Portfolios in der Sitzung
# ---------------------------------------------------------------------------


def _session_key(provider: str) -> str:
    return f"portfolio_{provider}"


def current_portfolio(provider: str) -> Portfolio:
    key = _session_key(provider)
    if key not in st.session_state:
        names = store(provider).names()
        st.session_state[key] = store(provider).load(names[0]) if names else Portfolio(DEFAULT_NAME)
    return st.session_state[key]


# Eingaben, deren Voreinstellung vom Depot abhängt (Zielrisiko = Risiko des Depots, Anfangskapital =
# Depotwert, auffälligstes Asset): beim Wechsel des Portfolios neu bestimmen
PORTFOLIO_INPUTS = ("frontier_target", "frontier_target_widget", "mc_initial", "sens_asset", "tx_marked",
                    "tx_undo")


def reset_portfolio_inputs() -> None:
    for key in PORTFOLIO_INPUTS:
        st.session_state.pop(key, None)


def set_portfolio(provider: str, portfolio: Portfolio, save: bool = True) -> None:
    reset_portfolio_inputs()
    st.session_state[_session_key(provider)] = portfolio
    st.session_state[f"pf_select_{provider}"] = portfolio.name
    if save:
        store(provider).save(portfolio)
    bump_editor()


def save(provider: str) -> None:
    store(provider).save(current_portfolio(provider))


def bump_editor() -> None:
    """Neuer Schlüssel für die Transaktionstabelle, damit sie die geänderten Daten frisch zeigt."""
    st.session_state["tx_editor_version"] = st.session_state.get("tx_editor_version", 0) + 1


def unique_name(provider: str, name: str) -> str:
    candidate, i = name, 2
    while store(provider).exists(candidate):
        candidate, i = f"{name} ({i})", i + 1
    return candidate


def example_portfolio(provider: str) -> Portfolio:
    """Fiktives Beispieldepot mit Käufen vor drei und einem Jahr und einem Teilverkauf.

    Käufe vor einem Aktiensplit stehen wie in der Abrechnung: weniger Stücke zum damaligen Kurs.
    """
    source = get_provider(provider)
    end = getattr(source, "end", date.today())
    infos = {s: source.info(s) for s in DEMO_EXAMPLE}
    hist = history_eur(provider, tuple(infos), tuple(i.currency for i in infos.values()),
                       (pd.Timestamp(end) - pd.DateOffset(years=4)).date(), end)
    px = hist.close
    last = px.index[-1]
    first, second, sale = (px.index[px.index.searchsorted(last - offset)]
                           for offset in (pd.DateOffset(years=3), pd.DateOffset(years=1), pd.DateOffset(months=6)))
    portfolio = Portfolio(unique_name(provider, "Beispieldepot"), splits=hist.splits)

    def buy(symbol: str, shares: float, day: pd.Timestamp) -> None:
        factor = split_factor(hist.splits.get(symbol, []), day.date())  # damalige Stückelung
        portfolio.add_transaction(infos[symbol], BUY, round(shares / factor, 2),
                                  round(float(px.at[day, symbol]) * factor, 2), day.date())

    for symbol, amount in DEMO_EXAMPLE.items():
        total = amount / float(px[symbol].iloc[-1])
        buy(symbol, total * 0.6, first)
        buy(symbol, total * 0.4, second)
    bank = "BRB.DEMO"
    portfolio.add_transaction(infos[bank], SELL, round(portfolio.get(bank).shares * 0.25, 2),
                              round(float(px.at[sale, bank]), 2), sale.date())
    return portfolio


# ---------------------------------------------------------------------------
# Portfolio-Kontext: Bestände, Kurse, Bewertung
# ---------------------------------------------------------------------------


@dataclass
class PortfolioContext:
    provider: str
    start: date  # Beginn des Analysezeitraums
    end: date
    portfolio: Portfolio
    prices: pd.DataFrame  # tatsächliche tägliche Schlusskurse in Euro je Symbol, ab dem ersten Kauf
    quotes: pd.DataFrame  # je gehaltenem Symbol: price (Euro), stand (Text), live (bool)
    valuation: pd.DataFrame
    missing: list[str] = field(default_factory=list)
    adjusted: pd.DataFrame = field(default_factory=pd.DataFrame)  # dividendenbereinigt, Analysezeitraum
    stale: dict[str, date] = field(default_factory=dict)  # Kurse aus dem lokalen Speicher -> letzter Kurstag

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
    def window(self) -> pd.DataFrame:
        """Dividendenbereinigte Tageskurse der bewerteten Positionen im Analysezeitraum (für Renditen
        und Risiko); fehlen bereinigte Kurse, gelten die tatsächlichen Schlusskurse."""
        symbols = list(self.weights.index)
        source = self.adjusted if set(symbols) <= set(self.adjusted.columns) else self.prices
        if source.empty:
            return pd.DataFrame()
        return source.loc[source.index >= pd.Timestamp(self.start), symbols]

    @property
    def weekly(self) -> pd.DataFrame:
        window = self.window
        return hg.weekly_returns(window) if not window.empty else pd.DataFrame()

    @property
    def labels(self) -> dict[str, str]:
        """Kurze, eindeutige Namen für Diagramme (auch für verkaufte Positionen)."""
        out, seen = {}, set()
        for symbol, info in self.portfolio.securities.items():
            label = info.name if len(info.name) <= 26 else info.name[:25].rstrip() + "…"
            if label in seen:
                label = f"{label} ({symbol})"
            seen.add(label)
            out[symbol] = label
        return out

    def analysis_symbols(self) -> list[str]:
        return list(self.weights.sort_values(ascending=False).index[:ANALYSIS_LIMIT])

    def analysis_prices(self) -> pd.DataFrame:
        return self.window[self.analysis_symbols()].rename(columns=self.labels)

    def own_weights(self, assets: list[str]) -> np.ndarray:
        """Eigene Gewichte in der Reihenfolge der Analyse-Assets (Namen), normiert."""
        by_label = {self.labels[s]: w for s, w in self.weights.items()}
        w = np.array([by_label.get(a, 0.0) for a in assets])
        return w / w.sum()


def _quotes(provider: str, held: dict[str, SecurityInfo], prices: pd.DataFrame) -> pd.DataFrame:
    """Aktueller Kurs je Position: tagsüber der letzte (verzögerte) Live-Kurs, sonst der letzte Schlusskurs."""
    rows = {}
    for symbol in held:
        if symbol in prices.columns and prices[symbol].notna().any():
            series = prices[symbol].dropna()
            rows[symbol] = {"price": float(series.iloc[-1]), "stand": f"Schluss {series.index[-1]:%d.%m.%Y}",
                            "live": False, "time": pd.NaT, "day": series.index[-1].date()}
    if not rows:
        return pd.DataFrame(columns=["price", "stand", "live", "time"])
    majors = sorted({major_currency(held[s].currency)[0] for s in rows} - {BASE_CURRENCY})
    live = live_quotes(provider, tuple(sorted(rows)) + tuple(fx_ticker(c) for c in majors))
    if not live.empty:
        fx = {c: float(live.at[fx_ticker(c), "price"]) for c in majors if fx_ticker(c) in live.index}
        today = date.today()
        for symbol, row in rows.items():
            if symbol not in live.index:
                continue
            when = pd.Timestamp(live.at[symbol, "time"])
            price = price_in_euro(float(live.at[symbol, "price"]), held[symbol].currency, fx)
            if np.isfinite(price) and when.date() >= row["day"]:
                stamp = f"live {when:%H:%M}" if when.date() == today else f"{when:%d.%m. %H:%M}"
                rows[symbol].update(price=price, stand=stamp, live=True, time=when)
    return pd.DataFrame.from_dict(rows, orient="index")[["price", "stand", "live", "time"]]


def load_context(settings: Settings, portfolio: Portfolio | None = None) -> PortfolioContext:
    """Bestände, Kurse und Bewertung des gewählten Portfolios (oder eines übergebenen, etwa des Beispieldepots)."""
    provider = settings.provider
    portfolio = current_portfolio(provider) if portfolio is None else portfolio
    securities = portfolio.securities
    dated = [t.date for t in portfolio.transactions if t.date]
    history_start = min([settings.start, *dated])
    prices = adjusted = pd.DataFrame()
    stale: dict[str, date] = {}
    if securities:
        try:
            hist = history_eur(provider, tuple(securities), tuple(i.currency for i in securities.values()),
                               history_start, settings.end)
        except Exception as exc:  # Netzwerkfehler von yfinance sind nicht einheitlich typisiert
            st.error(f"Kurse konnten nicht geladen werden: {exc}")
        else:
            prices, adjusted, stale = hist.close, hist.adjusted, hist.stale
            portfolio.splits = hist.splits  # vor allen Beständen setzen: Splits ändern Stückzahlen
    held = {p.symbol: p.info for p in portfolio.positions}
    quotes = _quotes(provider, held, prices)
    missing = [s for s in held if s not in quotes.index]
    price = quotes["price"] if not quotes.empty else pd.Series(dtype=float)
    return PortfolioContext(provider, settings.start, settings.end, portfolio, prices, quotes,
                            valuation(portfolio, price), missing, adjusted, stale)


# ---------------------------------------------------------------------------
# Alles, was die Seiten eines Durchlaufs brauchen
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    settings: Settings
    ctx: PortfolioContext
    theme: charts.Theme
    prices: pd.DataFrame | None = None  # Analysekurse (Spalten = kurze Namen)
    returns: pd.DataFrame | None = None
    est: Estimates | None = None
    bounds: tuple[float, float] | None = (0.0, 1.0)
    bounds_error: str | None = None


def build_run(settings: Settings, ctx: PortfolioContext, th: charts.Theme) -> RunState:
    run = RunState(settings, ctx, th, bounds=settings.bounds)
    if len(ctx.weights) < 2:
        return run
    try:
        prices = data.clean_prices(ctx.analysis_prices())
    except data.DataError:
        return run
    run.prices = prices
    run.returns = data.simple_returns(prices)
    run.est = estimate(run.returns, settings.mean_method, settings.cov_method)
    try:
        opt.validate_bounds(prices.shape[1], settings.bounds)
    except ValueError as exc:
        run.bounds_error = f"{exc} Für die Berechnungen gilt deshalb vorerst „ohne Leerverkäufe, bis 100 %“."
        run.bounds = (0.0, 1.0)
    return run


def current_run() -> RunState:
    return st.session_state["_run"]
