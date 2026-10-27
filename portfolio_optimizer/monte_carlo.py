"""Monte-Carlo-Simulation der Vermögensentwicklung eines Portfolios.

Zwei Verfahren:

* **Parametrisch (GBM):** Die Assets folgen einer geometrischen Brownschen
  Bewegung mit den geschätzten annualisierten Parametern ``mu`` und ``cov``.
  Log-Renditen pro Schritt sind normalverteilt mit
  ``(mu - diag(cov) / 2) * dt`` und ``cov * dt``.
* **Historisches Bootstrap:** Pro Schritt wird ein zufälliger Block aus
  aufeinanderfolgenden historischen Tagesrenditen gezogen. Fat Tails und die
  Korrelationsstruktur der Daten bleiben so erhalten.

Das Portfolio wird zu jedem Schritt auf die Zielgewichte zurückgesetzt
(Rebalancing). Eine optionale Sparrate wird am Ende jedes Schritts eingezahlt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .estimators import TRADING_DAYS


@dataclass(frozen=True)
class SimulationResult:
    times: np.ndarray  # Zeitpunkte in Jahren, Länge Schritte + 1
    wealth: np.ndarray  # Vermögen inkl. Sparrate, Form (Pfade, Schritte + 1)
    index: np.ndarray  # zeitgewichteter Wertindex ohne Sparrate, Start = 1
    invested: np.ndarray  # kumuliert eingezahltes Kapital, Länge Schritte + 1

    @property
    def years(self) -> float:
        return float(self.times[-1])

    def percentiles(self, qs=(5, 25, 50, 75, 95)) -> pd.DataFrame:
        values = np.percentile(self.wealth, qs, axis=0).T
        return pd.DataFrame(values, index=self.times, columns=[f"P{q}" for q in qs])

    def max_drawdowns(self) -> np.ndarray:
        running_max = np.maximum.accumulate(self.index, axis=1)
        return (1 - self.index / running_max).max(axis=1)

    def summary(self, target: float | None = None) -> dict[str, float]:
        final = self.wealth[:, -1]
        p5 = float(np.percentile(final, 5))
        growth = np.maximum(self.index[:, -1], 0.0)
        drawdowns = self.max_drawdowns()
        out = {
            "invested": float(self.invested[-1]),
            "mean": float(final.mean()),
            "median": float(np.median(final)),
            "p5": p5,
            "p95": float(np.percentile(final, 95)),
            "cvar5": float(final[final <= p5].mean()),
            "prob_loss": float((final < self.invested[-1]).mean()),
            "cagr_median": float(np.median(growth ** (1 / self.years) - 1)),
            "max_dd_median": float(np.median(drawdowns)),
            "max_dd_p95": float(np.percentile(drawdowns, 95)),
        }
        if target is not None:
            out["prob_target"] = float((final >= target).mean())
        return out


def cov_factor(cov: np.ndarray) -> np.ndarray:
    """Matrix L mit L @ L.T == cov (Cholesky, für semidefinite Matrizen per Eigenzerlegung)."""
    try:
        return np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh(cov)
        return vecs * np.sqrt(np.clip(vals, 0.0, None))


def _accumulate(
    step_gross: Callable[[], np.ndarray],
    n_paths: int,
    n_steps: int,
    steps_per_year: int,
    initial: float,
    contribution: float,
) -> SimulationResult:
    wealth = np.empty((n_paths, n_steps + 1))
    index = np.empty((n_paths, n_steps + 1))
    wealth[:, 0] = initial
    index[:, 0] = 1.0
    for t in range(1, n_steps + 1):
        # Ein Bruttofaktor < 0 (nur mit Hebel/Leerverkäufen möglich) bedeutet Totalverlust.
        gross = np.maximum(step_gross(), 0.0)
        index[:, t] = index[:, t - 1] * gross
        wealth[:, t] = wealth[:, t - 1] * gross + contribution
    return SimulationResult(
        times=np.arange(n_steps + 1) / steps_per_year,
        wealth=wealth,
        index=index,
        invested=initial + contribution * np.arange(n_steps + 1),
    )


def _check_inputs(weights: np.ndarray, years: float, n_paths: int, steps_per_year: int) -> int:
    if abs(weights.sum() - 1) > 1e-6:
        raise ValueError("Die Portfoliogewichte müssen sich zu 1 summieren.")
    if n_paths < 1:
        raise ValueError("Es wird mindestens ein Pfad benötigt.")
    n_steps = int(round(years * steps_per_year))
    if n_steps < 1:
        raise ValueError("Der Anlagehorizont ist zu kurz.")
    return n_steps


def simulate_gbm(
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    years: float,
    n_paths: int = 2000,
    initial: float = 10_000.0,
    contribution: float = 0.0,
    steps_per_year: int = 12,
    seed: int | None = None,
) -> SimulationResult:
    """Parametrische Simulation mit korrelierter geometrischer Brownscher Bewegung."""
    weights = np.asarray(weights, dtype=float)
    n_steps = _check_inputs(weights, years, n_paths, steps_per_year)
    dt = 1 / steps_per_year
    drift = (np.asarray(mu) - 0.5 * np.diag(cov)) * dt
    factor = cov_factor(np.asarray(cov) * dt)
    rng = np.random.default_rng(seed)

    def step_gross() -> np.ndarray:
        z = rng.standard_normal((n_paths, len(weights)))
        return np.exp(drift + z @ factor.T) @ weights

    return _accumulate(step_gross, n_paths, n_steps, steps_per_year, initial, contribution)


def simulate_bootstrap(
    weights: np.ndarray,
    returns: pd.DataFrame | np.ndarray,
    years: float,
    n_paths: int = 2000,
    initial: float = 10_000.0,
    contribution: float = 0.0,
    steps_per_year: int = 12,
    periods_per_year: int = TRADING_DAYS,
    seed: int | None = None,
) -> SimulationResult:
    """Block-Bootstrap aus historischen (einfachen) Periodenrenditen."""
    weights = np.asarray(weights, dtype=float)
    n_steps = _check_inputs(weights, years, n_paths, steps_per_year)
    r = np.asarray(returns, dtype=float)
    if (r <= -1).any():
        raise ValueError("Renditen von -100 % oder weniger sind nicht zulässig.")
    block = max(1, int(round(periods_per_year / steps_per_year)))
    if block > len(r):
        raise ValueError("Zu wenige historische Renditen für einen Simulationsschritt.")
    # Kumulierte Log-Renditen: die Rendite eines Blocks ist eine Differenz zweier Zeilen.
    log_cum = np.vstack([np.zeros(r.shape[1]), np.cumsum(np.log1p(r), axis=0)])
    rng = np.random.default_rng(seed)

    def step_gross() -> np.ndarray:
        start = rng.integers(0, len(r) - block + 1, size=n_paths)
        return np.exp(log_cum[start + block] - log_cum[start]) @ weights

    return _accumulate(step_gross, n_paths, n_steps, steps_per_year, initial, contribution)
