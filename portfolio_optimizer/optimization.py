"""Mittelwert-Varianz-Optimierung nach Markowitz.

Gewichtsgrenzen werden als ``bounds = (untergrenze, obergrenze)`` für alle
Assets angegeben, z. B. ``(0.0, 1.0)`` für long-only. ``bounds=None`` steht
für den klassischen, unbeschränkten Fall (beliebige Leerverkäufe); dann
werden die geschlossenen Lösungen verwendet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

Bounds = tuple[float, float] | None

_TOL = 1e-6


class OptimizationError(RuntimeError):
    """Der Optimierer hat keine zulässige Lösung gefunden."""


@dataclass(frozen=True)
class Frontier:
    """Punkte auf dem effizienten Rand (aufsteigend nach Rendite)."""

    returns: np.ndarray
    vols: np.ndarray
    weights: np.ndarray  # Form (Punkte, Assets)


def portfolio_stats(
    weights: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float = 0.0
) -> tuple[float, float, float]:
    """Erwartete Rendite, Volatilität und Sharpe-Ratio eines Portfolios."""
    ret = float(weights @ mu)
    vol = float(np.sqrt(max(weights @ cov @ weights, 0.0)))
    sharpe = (ret - rf) / vol if vol > 0 else float("nan")
    return ret, vol, sharpe


def risk_contributions(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Anteil jedes Assets an der Portfoliovarianz (summiert sich zu 1)."""
    marginal = cov @ weights
    total = weights @ marginal
    return weights * marginal / total


def validate_bounds(n_assets: int, bounds: Bounds) -> None:
    if bounds is None:
        return
    lo, hi = bounds
    if lo > hi:
        raise ValueError("Die Untergrenze der Gewichte liegt über der Obergrenze.")
    if n_assets * hi < 1 - 1e-12:
        raise ValueError(
            f"Mit höchstens {hi:.0%} je Titel und {n_assets} Titeln lässt sich "
            "kein voll investiertes Portfolio bilden."
        )
    if n_assets * lo > 1 + 1e-12:
        raise ValueError(
            f"Mit mindestens {lo:.0%} je Titel und {n_assets} Titeln summieren "
            "sich die Gewichte auf über 100 %."
        )


def _clean(weights: np.ndarray, bounds: Bounds) -> np.ndarray:
    """Entfernt numerisches Rauschen (Grenzen, Summe = 1)."""
    if bounds is not None:
        weights = np.clip(weights, *bounds)
    return weights / weights.sum()


def _feasible(weights: np.ndarray, bounds: Bounds, tol: float = _TOL) -> bool:
    if not np.isfinite(weights).all() or abs(weights.sum() - 1) > tol:
        return False
    if bounds is None:
        return True
    lo, hi = bounds
    return bool((weights >= lo - tol).all() and (weights <= hi + tol).all())


def _slsqp(fun, jac, x0, bounds_list, constraints):
    return minimize(
        fun,
        x0,
        jac=jac,
        method="SLSQP",
        bounds=bounds_list,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )


# ---------------------------------------------------------------------------
# Geschlossene Lösungen für den unbeschränkten Fall
# ---------------------------------------------------------------------------


def _frontier_constants(mu: np.ndarray, cov: np.ndarray):
    ones = np.ones(len(mu))
    a = np.linalg.solve(cov, ones)
    b = np.linalg.solve(cov, mu)
    A, B, C = ones @ a, ones @ b, mu @ b
    return a, b, A, B, C, A * C - B**2


def _analytic_efficient_return(mu, cov, targets) -> np.ndarray:
    a, b, A, B, C, D = _frontier_constants(mu, cov)
    targets = np.atleast_1d(targets)
    if D <= 1e-14 * max(A * C, 1e-300):
        # Alle erwarteten Renditen gleich: nur das Minimum-Varianz-Portfolio ist effizient.
        return np.tile(a / A, (len(targets), 1))
    return (np.outer(C - targets * B, a) + np.outer(targets * A - B, b)) / D


# ---------------------------------------------------------------------------
# Öffentliche Optimierer
# ---------------------------------------------------------------------------


def min_variance(cov: np.ndarray, bounds: Bounds = (0.0, 1.0)) -> np.ndarray:
    """Globales Minimum-Varianz-Portfolio (benötigt keine Renditeschätzung)."""
    n = len(cov)
    validate_bounds(n, bounds)
    if bounds is None:
        z = np.linalg.solve(cov, np.ones(n))
        return z / z.sum()
    res = _slsqp(
        lambda w: w @ cov @ w,
        lambda w: 2 * cov @ w,
        np.full(n, 1 / n),
        [bounds] * n,
        [{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(n)}],
    )
    if not _feasible(res.x, bounds):
        raise OptimizationError(f"Minimum-Varianz-Optimierung fehlgeschlagen: {res.message}")
    return _clean(res.x, bounds)


def max_return_weights(mu: np.ndarray, bounds: Bounds = (0.0, 1.0)) -> np.ndarray:
    """Portfolio mit der höchsten erwarteten Rendite unter den Gewichtsgrenzen."""
    if bounds is None:
        raise ValueError("Ohne Gewichtsgrenzen ist die erreichbare Rendite unbeschränkt.")
    n = len(mu)
    validate_bounds(n, bounds)
    lo, hi = bounds
    weights = np.full(n, lo, dtype=float)
    budget = 1 - n * lo
    for i in np.argsort(-mu, kind="stable"):
        add = min(hi - lo, budget)
        weights[i] += add
        budget -= add
        if budget <= 1e-15:
            break
    return weights


def efficient_return(
    mu: np.ndarray,
    cov: np.ndarray,
    target: float,
    bounds: Bounds = (0.0, 1.0),
    x0: np.ndarray | None = None,
) -> np.ndarray:
    """Portfolio mit minimaler Varianz für eine vorgegebene Zielrendite."""
    n = len(mu)
    validate_bounds(n, bounds)
    if bounds is None:
        return _analytic_efficient_return(mu, cov, target)[0]
    constraints = [
        {"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(n)},
        {"type": "eq", "fun": lambda w: w @ mu - target, "jac": lambda w: mu},
    ]
    res = _slsqp(
        lambda w: w @ cov @ w,
        lambda w: 2 * cov @ w,
        np.full(n, 1 / n) if x0 is None else x0,
        [bounds] * n,
        constraints,
    )
    if not _feasible(res.x, bounds) or abs(res.x @ mu - target) > _TOL:
        raise OptimizationError(f"Keine Lösung für Zielrendite {target:.2%}: {res.message}")
    return _clean(res.x, bounds)


def efficient_risk(
    mu: np.ndarray, cov: np.ndarray, target_vol: float, bounds: Bounds = (0.0, 1.0)
) -> np.ndarray:
    """Effizientes Portfolio mit der höchsten Rendite bei höchstens ``target_vol``."""
    n = len(mu)
    validate_bounds(n, bounds)
    w_gmv = min_variance(cov, bounds)
    if target_vol <= np.sqrt(w_gmv @ cov @ w_gmv):
        return w_gmv
    if bounds is None:
        _, _, A, B, C, D = _frontier_constants(mu, cov)
        if D <= 1e-14 * max(A * C, 1e-300):
            return w_gmv
        target = (B + np.sqrt(max(B**2 - A * (C - D * target_vol**2), 0.0))) / A
        return _analytic_efficient_return(mu, cov, target)[0]
    w_top = max_return_weights(mu, bounds)
    if np.sqrt(w_top @ cov @ w_top) <= target_vol:
        return w_top
    constraints = [
        {"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(n)},
        {
            "type": "ineq",
            "fun": lambda w: target_vol**2 - w @ cov @ w,
            "jac": lambda w: -2 * cov @ w,
        },
    ]
    res = _slsqp(lambda w: -(w @ mu), lambda w: -mu, w_gmv, [bounds] * n, constraints)
    if not _feasible(res.x, bounds) or res.x @ cov @ res.x > target_vol**2 * (1 + 1e-4):
        raise OptimizationError(f"Keine Lösung für Zielvolatilität {target_vol:.2%}: {res.message}")
    return _clean(res.x, bounds)


def max_sharpe(
    mu: np.ndarray, cov: np.ndarray, rf: float = 0.0, bounds: Bounds = (0.0, 1.0)
) -> np.ndarray | None:
    """Tangentialportfolio (maximale Sharpe-Ratio).

    Gibt ``None`` zurück, wenn kein zulässiges Portfolio eine Rendite über dem
    risikolosen Zins erwartet - dann ist die Sharpe-Ratio nicht sinnvoll maximierbar.

    Mit Gewichtsgrenzen wird das konvexe Ersatzproblem gelöst
    (Cornuéjols & Tütüncü): minimiere y'Σy unter (mu - rf)'y = 1;
    die Gewichte sind w = y / sum(y), die Grenzen werden in y linear.
    """
    n = len(mu)
    validate_bounds(n, bounds)
    excess = mu - rf
    if bounds is None:
        z = np.linalg.solve(cov, excess)
        if z.sum() <= 1e-12 * np.abs(z).sum():
            return None
        return z / z.sum()

    lo, hi = bounds
    w_top = max_return_weights(mu, bounds)
    if w_top @ excess <= 1e-12:
        return None
    scale = np.abs(excess).max()
    excess_s = excess / scale
    ones = np.ones(n)
    constraints = [{"type": "eq", "fun": lambda y: excess_s @ y - 1, "jac": lambda y: excess_s}]
    y_bounds = [(None, None)] * n
    if lo >= 0:
        y_bounds = [(0.0, None)] * n
    if lo != 0:
        a_lo = np.eye(n) - lo * np.outer(ones, ones)  # y_i - lo * sum(y) >= 0
        constraints.append({"type": "ineq", "fun": lambda y: a_lo @ y, "jac": lambda y: a_lo})
    if lo < 0:
        constraints.append({"type": "ineq", "fun": lambda y: y.sum(), "jac": lambda y: ones})
    if hi < 1 or lo < 0:
        a_hi = hi * np.outer(ones, ones) - np.eye(n)  # hi * sum(y) - y_i >= 0
        constraints.append({"type": "ineq", "fun": lambda y: a_hi @ y, "jac": lambda y: a_hi})

    res = _slsqp(
        lambda y: y @ cov @ y,
        lambda y: 2 * cov @ y,
        w_top / (w_top @ excess_s),
        y_bounds,
        constraints,
    )
    total = res.x.sum()
    if not np.isfinite(total) or total <= 1e-10:
        raise OptimizationError(f"Max-Sharpe-Optimierung fehlgeschlagen: {res.message}")
    weights = res.x / total
    if not _feasible(weights, bounds, tol=1e-5):
        raise OptimizationError(f"Max-Sharpe-Optimierung fehlgeschlagen: {res.message}")
    return _clean(weights, bounds)


def efficient_frontier(
    mu: np.ndarray, cov: np.ndarray, bounds: Bounds = (0.0, 1.0), n_points: int = 50
) -> Frontier:
    """Berechnet den effizienten Rand vom Minimum-Varianz-Portfolio aufwärts."""
    n = len(mu)
    validate_bounds(n, bounds)
    w_gmv = min_variance(cov, bounds)
    r_min = float(w_gmv @ mu)

    if bounds is None:
        # Ohne Grenzen ist der Rand nach oben offen; wir zeigen einen sinnvollen Ausschnitt.
        r_max = r_min + 1.5 * max(mu.max() - r_min, 0.0)
        targets = np.linspace(r_min, r_max, n_points) if r_max > r_min else np.array([r_min])
        weights = _analytic_efficient_return(mu, cov, targets)
    else:
        w_top = max_return_weights(mu, bounds)
        r_max = float(w_top @ mu)
        if r_max - r_min <= 1e-10:
            weights = w_gmv[None, :]
        else:
            targets = np.linspace(r_min, r_max, n_points)
            rows = [w_gmv]
            for target in targets[1:-1]:
                try:
                    rows.append(efficient_return(mu, cov, target, bounds, x0=rows[-1]))
                except OptimizationError:
                    continue
            rows.append(w_top)
            weights = np.array(rows)

    rets = weights @ mu
    vols = np.sqrt(np.einsum("ij,jk,ik->i", weights, cov, weights).clip(min=0))
    return Frontier(returns=rets, vols=vols, weights=weights)


def random_portfolios(
    mu: np.ndarray, cov: np.ndarray, n: int = 3000, seed: int = 0, bounds: Bounds = None
) -> tuple[np.ndarray, np.ndarray]:
    """Zufällige long-only-Portfolios zur Veranschaulichung der Menge aller Portfolios.

    Mit ``bounds`` bleiben nur Portfolios übrig, die die Grenzen einhalten - so
    liegt keines oberhalb des effizienten Rands.
    """
    rng = np.random.default_rng(seed)
    k = len(mu)
    # Eine Mischung aus gleichmäßigen und konzentrierten Gewichten füllt die Fläche besser.
    weights = np.vstack(
        [rng.dirichlet(np.ones(k), size=n // 2), rng.dirichlet(np.full(k, 0.2), size=n - n // 2)]
    )
    if bounds is not None:
        lo, hi = bounds
        weights = weights[((weights >= lo) & (weights <= hi)).all(axis=1)]
    rets = weights @ mu
    vols = np.sqrt(np.einsum("ij,jk,ik->i", weights, cov, weights))
    return rets, vols
