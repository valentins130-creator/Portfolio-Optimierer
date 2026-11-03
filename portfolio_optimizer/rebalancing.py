"""Umschichtungsvorschläge: Zielgewichte und die dafür nötigen Käufe und Verkäufe."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .concentration import Limits
from .market import SecurityInfo
from .portfolio import exposure_matrix, is_concentration_group


class InfeasibleError(ValueError):
    """Die Grenzen lassen sich mit den verfügbaren Positionen nicht einhalten."""


def limit_constraints(
    symbols: list[str], infos: dict[str, SecurityInfo], limits: Limits, clusters: list[list[str]]
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Lineare Nebenbedingungen A w <= b für alle Klumpenrisiko-Grenzen."""
    rows, bounds, labels = [], [], []
    for i, symbol in enumerate(symbols):
        if not infos[symbol].is_fund:
            row = np.zeros(len(symbols))
            row[i] = 1.0
            rows.append(row)
            bounds.append(limits.position)
            labels.append(f"Einzelwert {infos[symbol].name}")
    for by, label in (("sector", "Sektor"), ("country", "Land"), ("currency", "Währung")):
        matrix = exposure_matrix({s: infos[s] for s in symbols}, by).reindex(columns=symbols).fillna(0.0)
        for group in matrix.index:
            if is_concentration_group(by, group):
                rows.append(matrix.loc[group].to_numpy())
                bounds.append(limits.for_kind(by))
                labels.append(f"{label} {group}")
    for k, members in enumerate(clusters, start=1):
        rows.append(np.array([1.0 if s in members else 0.0 for s in symbols]))
        bounds.append(limits.cluster)
        labels.append(f"Korrelations-Cluster {k}")
    if not rows:
        return np.zeros((0, len(symbols))), np.zeros(0), []
    return np.array(rows), np.array(bounds), labels


def cap_concentrations(
    current: pd.Series,
    infos: dict[str, SecurityInfo],
    limits: Limits,
    clusters: list[list[str]] = (),
) -> pd.Series:
    """Kleinste Umschichtung (quadratische Abweichung), mit der alle Grenzen eingehalten werden.

    ``current`` darf Symbole mit Gewicht 0 enthalten, z. B. einen breit gestreuten
    ETF, der als Ausgleich gekauft werden darf.
    """
    symbols = list(current.index)
    w0 = current.to_numpy(dtype=float)
    w0 = w0 / w0.sum()
    a, b, labels = limit_constraints(symbols, infos, limits, [c for c in clusters if set(c) <= set(symbols)])
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(len(w))}]
    if len(b):
        constraints.append({"type": "ineq", "fun": lambda w: b - a @ w, "jac": lambda w: -a})
    start = np.clip(w0, 0, None)
    res = minimize(
        lambda w: ((w - w0) ** 2).sum(), start, jac=lambda w: 2 * (w - w0), method="SLSQP",
        bounds=[(0.0, 1.0)] * len(symbols), constraints=constraints, options={"maxiter": 500, "ftol": 1e-12},
    )
    w = np.clip(res.x, 0.0, None)
    w = w / w.sum()
    violation = (a @ w - b).max() if len(b) else 0.0
    if not res.success and violation > 1e-6 or violation > 1e-5:
        broken = [labels[i] for i in np.where(a @ w - b > 1e-5)[0]]
        raise InfeasibleError(
            "Mit den vorhandenen Positionen lassen sich nicht alle Grenzen einhalten"
            + (f" ({', '.join(broken[:3])})" if broken else "") + "."
        )
    return pd.Series(w, index=symbols)


def trades(
    valuation: pd.DataFrame,
    target: pd.Series,
    prices: pd.Series,
    whole_shares: bool = True,
    min_trade: float = 0.0,
) -> pd.DataFrame:
    """Käufe und Verkäufe, um vom aktuellen Depot (``valuation``) zu ``target`` zu kommen.

    ``prices``: Kurse in Euro für alle Symbole in ``target`` (auch neue Positionen).
    Mit ``whole_shares`` werden Käufe ab- und Verkäufe aufgerundet: Keine Position
    landet über ihrem Zielgewicht, ein kleiner Rest bleibt als Liquidität.
    Gewichte nachher beziehen sich auf den Depotwert vorher (inklusive dieses Rests).
    Spalten: Stückänderung, Betrag (positiv = Kauf), Gewicht vorher/nachher,
    realisierter Gewinn bei Verkäufen (wenn der Kaufkurs bekannt ist).
    """
    total = float(valuation["value"].sum())
    symbols = list(dict.fromkeys([*valuation.index, *target.index]))
    rows = []
    for s in symbols:
        current = float(valuation["value"].get(s, 0.0)) if s in valuation.index else 0.0
        price = float(prices.get(s, np.nan))
        delta = float(target.get(s, 0.0)) * total - current
        shares = delta / price if price > 0 else 0.0
        if whole_shares:
            shares = float(np.floor(shares + 1e-9))
            if s in valuation.index:
                shares = max(shares, -float(valuation.at[s, "shares"]))
        amount = shares * price if price > 0 else 0.0
        if abs(amount) < min_trade:
            shares, amount = 0.0, 0.0
        purchase = valuation["purchase_price"].get(s, np.nan) if s in valuation.index else np.nan
        realized = -shares * (price - purchase) if shares < 0 and pd.notna(purchase) else np.nan
        rows.append({"symbol": s, "shares_delta": shares, "amount": amount, "value_before": current,
                     "value_after": current + amount, "realized_gain": realized})
    df = pd.DataFrame(rows).set_index("symbol")
    df["weight_before"] = df["value_before"] / total
    df["weight_after"] = df["value_after"] / total
    df["action"] = np.select([df["amount"] > 0, df["amount"] < 0], ["Kaufen", "Verkaufen"], "Halten")
    return df
