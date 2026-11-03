"""Absicherungsvorschläge für das eigene Portfolio.

* **Markt-Hedge (Beta):** Wie stark schwankt das Depot mit einem Index? Eine
  Short-Position von Beta x Depotwert (z. B. über Future oder Short-ETF)
  neutralisiert diesen Teil des Risikos.
* **Diversifizierende Beimischung:** Wie verändern Volatilität und Drawdown,
  wenn ein Teil des Depots in eine wenig korrelierte Anlage fließt?
* **Klumpenrisiko absichern:** Für jede Konzentration über der Grenze das
  Instrument, das den Überhang am besten abbildet, samt Absicherungsbetrag.

Alle Rechnungen nutzen Wochenrenditen in Euro. Wochendaten mildern Verzerrungen
durch unterschiedliche Handelszeiten (Xetra schließt vor der Wall Street).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .concentration import PERIODS_PER_YEAR, Finding
from .market import Instrument

MIN_OBSERVATIONS = 26  # ein halbes Jahr Wochendaten


def weekly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.resample("W-FRI").last().pct_change(fill_method=None).iloc[1:]


def portfolio_returns(weights: pd.Series, returns: pd.DataFrame) -> pd.Series:
    """Renditen bei konstanten Gewichten (wöchentlich neu gewichtet)."""
    r = returns.reindex(columns=weights.index).dropna()
    return r @ (weights / weights.sum())


def annual_vol(r: pd.Series) -> float:
    return float(r.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR))


def annual_return(r: pd.Series) -> float:
    return float((1 + r).prod() ** (PERIODS_PER_YEAR / len(r)) - 1) if len(r) else float("nan")


def max_drawdown(r: pd.Series) -> float:
    wealth = np.concatenate([[1.0], (1 + r.to_numpy()).cumprod()])
    return float((1 - wealth / np.maximum.accumulate(wealth)).max())


def _aligned(*series: pd.Series) -> list[pd.Series]:
    df = pd.concat(series, axis=1).dropna()
    return [df.iloc[:, i] for i in range(df.shape[1])]


def _unique(instruments, kinds) -> list[Instrument]:
    seen, out = set(), []
    for inst in instruments:
        if inst.kind in kinds and inst.symbol not in seen:
            seen.add(inst.symbol)
            out.append(inst)
    return out


@dataclass(frozen=True)
class BetaHedge:
    instrument: Instrument
    beta: float
    r2: float
    notional: float  # Euro, als Short-Position
    vol_before: float
    vol_after: float
    mdd_before: float
    mdd_after: float
    ret_before: float
    ret_after: float


def beta_hedges(
    port_ret: pd.Series,
    inst_ret: pd.DataFrame,
    instruments,
    value: float,
    ratio: float = 1.0,
) -> list[BetaHedge]:
    """Beta-Hedge gegen jeden Marktindex, sortiert nach Erklärungskraft (R²)."""
    out = []
    for inst in _unique(instruments, {"market"}):
        if inst.symbol not in inst_ret:
            continue
        p, m = _aligned(port_ret, inst_ret[inst.symbol])
        if len(p) < MIN_OBSERVATIONS or m.var() <= 0:
            continue
        beta = float(p.cov(m) / m.var())
        hedged = p - ratio * beta * m
        out.append(BetaHedge(
            inst, beta, float(p.corr(m) ** 2), ratio * beta * value,
            annual_vol(p), annual_vol(hedged), max_drawdown(p), max_drawdown(hedged),
            annual_return(p), annual_return(hedged),
        ))
    return sorted(out, key=lambda h: h.r2, reverse=True)


@dataclass(frozen=True)
class Diversifier:
    instrument: Instrument
    corr: float
    vol: float
    share: float  # betrachteter Anteil der Beimischung
    share_min_var: float  # Anteil, bei dem die Volatilität minimal wird
    vol_before: float
    vol_after: float
    mdd_before: float
    mdd_after: float
    ret_before: float
    ret_after: float


def min_variance_share(p: pd.Series, c: pd.Series, max_share: float = 0.6) -> float:
    """Anteil x, der Var((1 - x) p + x c) minimiert."""
    var_p, var_c, cov = p.var(), c.var(), p.cov(c)
    denom = var_p + var_c - 2 * cov
    x = (var_p - cov) / denom if denom > 0 else 0.0
    return float(np.clip(x, 0.0, max_share))


def diversifiers(
    port_ret: pd.Series,
    inst_ret: pd.DataFrame,
    instruments,
    share: float = 0.2,
    exclude: set[str] = frozenset(),
) -> list[Diversifier]:
    """Wirkung einer Beimischung von ``share`` je Kandidat, sortiert nach Volatilität danach."""
    out = []
    for inst in _unique(instruments, {"diversifier"}):
        if inst.symbol not in inst_ret or inst.symbol in exclude:
            continue
        p, c = _aligned(port_ret, inst_ret[inst.symbol])
        if len(p) < MIN_OBSERVATIONS:
            continue
        mix = (1 - share) * p + share * c
        out.append(Diversifier(
            inst, float(p.corr(c)), annual_vol(c), share, min_variance_share(p, c),
            annual_vol(p), annual_vol(mix), max_drawdown(p), max_drawdown(mix),
            annual_return(p), annual_return(mix),
        ))
    return sorted(out, key=lambda d: d.vol_after)


def mix_curve(port_ret: pd.Series, inst: pd.Series, shares: np.ndarray) -> pd.Series:
    """Volatilität p. a. in Abhängigkeit vom Anteil der Beimischung."""
    p, c = _aligned(port_ret, inst)
    return pd.Series([annual_vol((1 - x) * p + x * c) for x in shares], index=shares)


@dataclass(frozen=True)
class ConcentrationHedge:
    finding: Finding
    reduce_amount: float  # Euro, die verkauft werden müssten, um die Grenze einzuhalten
    instrument: Instrument | None
    beta: float
    r2: float
    notional: float  # Euro, als Short-Position (bei Währungen: Termingeschäft)
    vol_before: float
    vol_after: float


def concentration_hedges(
    findings: list[Finding],
    weights: pd.Series,
    asset_ret: pd.DataFrame,
    value: float,
    inst_ret: pd.DataFrame,
    instruments,
    fx_ret: pd.DataFrame,
) -> list[ConcentrationHedge]:
    """Absicherung des Überhangs jeder Konzentration über ihrer Grenze.

    Abgesichert wird nur der Teil oberhalb der Grenze: Bei 45 % Technologie und
    einer Grenze von 30 % also 15 % des Depots.
    """
    port = portfolio_returns(weights, asset_ret)
    candidates = _unique(instruments, {"sector", "market"})
    out = []
    for f in findings:
        if not f.exceeded:
            continue
        excess = f.excess
        members = pd.Series({s: weights.get(s, 0.0) * share for s, share in f.members.items()})
        members = members[members > 0]
        group = portfolio_returns(members, asset_ret) if len(members) else None
        best, best_r2, best_beta, hedge_ret = None, 0.0, 0.0, None
        if f.kind == "currency":
            if f.group in fx_ret:
                hedge_ret = fx_ret[f.group]
                best = Instrument(f"EUR{f.group}", f"Devisentermingeschäft {f.group}/EUR", "fx", f.group)
                best_beta = 1.0  # der Euro-Wert von Fremdwährungsanlagen bewegt sich 1:1 mit dem Kurs
                if group is not None:
                    g, h = _aligned(group, hedge_ret)
                    best_r2 = float(g.corr(h) ** 2) if len(g) > 2 else 0.0
        elif group is not None:
            for inst in candidates:
                if inst.symbol not in inst_ret or inst.symbol in f.members:
                    continue
                g, h = _aligned(group, inst_ret[inst.symbol])
                if len(g) < MIN_OBSERVATIONS or h.var() <= 0:
                    continue
                r2 = float(g.corr(h) ** 2)
                if r2 > best_r2:
                    best, best_r2, best_beta, hedge_ret = inst, r2, float(g.cov(h) / h.var()), inst_ret[inst.symbol]
        if best is None or hedge_ret is None:
            vol = annual_vol(port)
            out.append(ConcentrationHedge(f, excess * value, None, float("nan"), float("nan"), 0.0, vol, vol))
            continue
        p, h = _aligned(port, hedge_ret)
        hedged = p - excess * best_beta * h
        out.append(ConcentrationHedge(
            f, excess * value, best, best_beta, best_r2, excess * best_beta * value,
            annual_vol(p), annual_vol(hedged),
        ))
    return out
