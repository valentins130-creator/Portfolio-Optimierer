"""Wertentwicklung des eigenen Depots aus der Transaktionsliste.

* Depotwert und eingezahltes Kapital je Tag,
* zeitgewichtete Rendite (unabhängig davon, wann wie viel investiert wurde)
  zum Vergleich mit einem Index,
* persönliche Rendite p. a. (interner Zinsfuß, berücksichtigt Zeitpunkt und
  Höhe der Ein- und Auszahlungen),
* Gewinn/Verlust je Position im Zeitverlauf.

Transaktionen ohne Datum oder Kurs lassen sich zeitlich nicht einordnen und
werden übersprungen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .portfolio import BUY, Portfolio


@dataclass(frozen=True)
class Performance:
    value: pd.Series  # Depotwert je Tag (Euro)
    invested: pd.Series  # kumulierte Nettoeinzahlungen (Käufe minus Verkaufserlöse)
    flows: pd.Series  # Nettoeinzahlung je Tag
    twr: pd.Series  # zeitgewichtete Wertentwicklung, Start = 100
    position_value: pd.DataFrame  # Wert je Position und Tag
    position_pnl: pd.DataFrame  # Gewinn/Verlust je Position (realisiert + unrealisiert)
    irr: float | None  # persönliche Rendite p. a.
    skipped: int  # Transaktionen ohne Datum, Kurs oder Kursdaten

    @property
    def twr_annual(self) -> float | None:
        days = (self.twr.index[-1] - self.twr.index[0]).days
        return float((self.twr.iloc[-1] / 100) ** (365.25 / days) - 1) if days >= 30 else None

    @property
    def gain(self) -> float:
        return float(self.value.iloc[-1] - self.invested.iloc[-1])


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Interner Zinsfuß p. a. für datierte Zahlungen (Auszahlungen an den Anleger positiv)."""
    amounts = np.array([c for _, c in cashflows], dtype=float)
    if not (amounts < 0).any() or not (amounts > 0).any():
        return None
    start = min(d for d, _ in cashflows)
    years = np.array([(d - start).days / 365.25 for d, _ in cashflows])

    def npv(rate: float) -> float:
        return float((amounts / (1 + rate) ** years).sum())

    try:
        return float(brentq(npv, -0.9999, 100.0, maxiter=500))
    except ValueError:  # keine Nullstelle im Suchbereich
        return None


def _trade_day(index: pd.DatetimeIndex, when: date) -> pd.Timestamp:
    """Erster Handelstag ab ``when`` (Wochenenden und Feiertage auf den nächsten Handelstag)."""
    pos = index.searchsorted(pd.Timestamp(when))
    return index[min(pos, len(index) - 1)]


def compute(portfolio: Portfolio, prices: pd.DataFrame) -> Performance | None:
    """Wertentwicklung aus Transaktionen und Tageskursen in Euro (Spalten = Symbole)."""
    usable = [t for t in portfolio.transactions
              if t.date and t.price and t.symbol in prices.columns and prices[t.symbol].notna().any()]
    if not usable:
        return None
    start = pd.Timestamp(min(t.date for t in usable))
    px = prices[sorted({t.symbol for t in usable})].ffill()
    px = px.loc[px.index >= start]  # ab dem ersten Handelstag mit Transaktion
    if px.empty:
        return None
    index = px.index
    holdings = pd.DataFrame(0.0, index=index, columns=px.columns)
    flows = pd.DataFrame(0.0, index=index, columns=px.columns)
    for t in sorted(usable, key=lambda t: t.date):
        day = _trade_day(index, t.date)
        sign = 1.0 if t.kind == BUY else -1.0
        holdings.loc[day:, t.symbol] += sign * t.shares
        flows.loc[day, t.symbol] += sign * t.amount
    position_value = (holdings * px).where(holdings.abs() > 1e-12, 0.0).fillna(0.0)
    value = position_value.sum(axis=1)
    flow = flows.sum(axis=1)

    # Zeitgewichtete Rendite: Zahlungen fließen zu Tagesbeginn zum Transaktionskurs ein.
    # Start = 100 zum Schlusskurs des ersten Handelstags, damit Depot und Index vergleichbar starten.
    previous = value.shift(1).fillna(0.0)
    base = previous + flow
    daily = ((value - previous - flow) / base.where(base > 1e-9, 1.0)).where(base > 1e-9, 0.0)
    daily.iloc[0] = 0.0
    twr = 100 * (1 + daily).cumprod()

    cashflows = [(t.date, -t.amount if t.kind == BUY else t.amount) for t in usable]
    cashflows.append((index[-1].date(), float(value.iloc[-1])))
    return Performance(
        value=value,
        invested=flow.cumsum(),
        flows=flow,
        twr=twr,
        position_value=position_value,
        position_pnl=position_value - flows.cumsum(),
        irr=xirr(cashflows),
        skipped=len(portfolio.transactions) - len(usable),
    )


def benchmark(perf: Performance, prices: pd.Series) -> tuple[pd.Series, float]:
    """Index im Vergleich: Wertentwicklung (Start 100) und Endwert bei identischen Ein- und Auszahlungen."""
    b = prices.reindex(perf.value.index.union(prices.index)).ffill().reindex(perf.value.index).bfill()
    indexed = 100 * b / b.iloc[0]
    units = (perf.flows / b).cumsum()
    return indexed, float(units.iloc[-1] * b.iloc[-1])
