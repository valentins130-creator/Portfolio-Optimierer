"""Warum Markowitz-Optimierung mit geschätzten Parametern oft enttäuscht.

Der Optimierer behandelt die Schätzungen als exakt. Er bevorzugt deshalb
systematisch Assets, deren Rendite zufällig überschätzt und deren Risiko
unterschätzt wurde ("Error Maximization", Michaud 1989).

Die Experimente hier arbeiten mit einem bekannten "wahren" Modell: Aus ihm
werden Renditehistorien simuliert, auf jeder Historie wird geschätzt und
optimiert, und das Ergebnis wird mit den wahren Parametern bewertet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import wishart

from .estimators import TRADING_DAYS, Estimates, estimate
from .monte_carlo import cov_factor
from .optimization import (
    Bounds,
    Frontier,
    OptimizationError,
    efficient_frontier,
    max_sharpe,
    min_variance,
    portfolio_stats,
)

STRATEGIES = {
    "ms_sample": "Max-Sharpe (Stichprobe)",
    "ms_mu_only": "Max-Sharpe (nur μ geschätzt)",
    "ms_cov_only": "Max-Sharpe (nur Σ geschätzt)",
    "ms_shrink": "Max-Sharpe (Shrinkage)",
    "ms_resampled": "Max-Sharpe (Resampling)",
    "gmv": "Minimum-Varianz",
    "equal": "Gleichgewichtet (1/N)",
}


@dataclass(frozen=True)
class Model:
    """Bekannte "wahre" annualisierte Parameter."""

    assets: list[str]
    mu: np.ndarray
    cov: np.ndarray


def model_from_estimates(est: Estimates) -> Model:
    return Model(assets=list(est.assets), mu=est.mu.copy(), cov=est.cov.copy())


def identical_assets_model(n: int, mu: float, vol: float, corr: float) -> Model:
    """N gleichartige Assets: Das wahre Optimum ist immer 1/N."""
    if n < 2:
        raise ValueError("Es werden mindestens zwei Assets benötigt.")
    if not -1 / (n - 1) < corr < 1:
        raise ValueError("Die Korrelation muss zwischen -1/(N-1) und 1 liegen.")
    c = np.full((n, n), corr)
    np.fill_diagonal(c, 1.0)
    return Model(
        assets=[f"Asset {i + 1}" for i in range(n)],
        mu=np.full(n, mu),
        cov=c * vol**2,
    )


def simulate_returns(
    model: Model, n_obs: int, rng: np.random.Generator, periods_per_year: int = TRADING_DAYS
) -> np.ndarray:
    """Normalverteilte Periodenrenditen aus dem wahren Modell."""
    factor = cov_factor(model.cov / periods_per_year)
    z = rng.standard_normal((n_obs, len(model.mu)))
    return model.mu / periods_per_year + z @ factor.T


def estimation_error_table(
    returns: pd.DataFrame, periods_per_year: int = TRADING_DAYS, precision: float = 0.01
) -> pd.DataFrame:
    """Standardfehler und 95-%-Konfidenzintervalle der annualisierten Mittelwerte.

    ``years_needed`` ist die Länge der Historie, die nötig wäre, damit der
    Standardfehler auf ``precision`` (z. B. 1 Prozentpunkt) sinkt.
    """
    years = len(returns) / periods_per_year
    mu = returns.mean() * periods_per_year
    vol = returns.std() * np.sqrt(periods_per_year)
    se = vol / np.sqrt(years)
    return pd.DataFrame(
        {
            "mu": mu,
            "vol": vol,
            "se": se,
            "ci_low": mu - 1.96 * se,
            "ci_high": mu + 1.96 * se,
            "years_needed": (vol / precision) ** 2,
        }
    )


def turnover(w_old: np.ndarray, w_new: np.ndarray) -> float:
    """Anteil des Portfolios, der umgeschichtet werden muss (0 bis 1, ohne Hebel)."""
    return float(0.5 * np.abs(np.asarray(w_new) - np.asarray(w_old)).sum())


def perturbed_weights(
    mu: np.ndarray, cov: np.ndarray, rf: float, bounds: Bounds, asset: int, delta: float
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Max-Sharpe-Gewichte vor und nach einer Änderung von ``mu[asset]`` um ``delta``."""
    shifted = np.array(mu, dtype=float)
    shifted[asset] += delta
    return max_sharpe(mu, cov, rf, bounds), max_sharpe(shifted, cov, rf, bounds)


# ---------------------------------------------------------------------------
# Experiment 1: geschätzte vs. tatsächliche Efficient Frontier (Broadie 1993)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrontierExperiment:
    true_frontier: Frontier
    estimated: list[Frontier]  # wie der Optimierer den Rand sieht
    actual: list[Frontier]  # dieselben Portfolios, bewertet mit den wahren Parametern


def frontier_experiment(
    model: Model,
    n_obs: int,
    n_trials: int = 20,
    bounds: Bounds = (0.0, 1.0),
    n_points: int = 25,
    seed: int = 0,
    periods_per_year: int = TRADING_DAYS,
) -> FrontierExperiment:
    rng = np.random.default_rng(seed)
    true_frontier = efficient_frontier(model.mu, model.cov, bounds, max(n_points, 60))
    estimated, actual = [], []
    for _ in range(n_trials):
        est = estimate(simulate_returns(model, n_obs, rng, periods_per_year), periods_per_year=periods_per_year)
        try:
            frontier = efficient_frontier(est.mu, est.cov, bounds, n_points)
        except (OptimizationError, np.linalg.LinAlgError):
            continue
        w = frontier.weights
        estimated.append(frontier)
        actual.append(
            Frontier(
                returns=w @ model.mu,
                vols=np.sqrt(np.einsum("ij,jk,ik->i", w, model.cov, w).clip(min=0)),
                weights=w,
            )
        )
    return FrontierExperiment(true_frontier=true_frontier, estimated=estimated, actual=actual)


# ---------------------------------------------------------------------------
# Experiment 2: Strategien im Vergleich
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyExperiment:
    assets: list[str]
    strategies: list[str]  # Schlüssel aus STRATEGIES
    weights: np.ndarray  # (Durchläufe, Strategien, Assets); NaN, wenn der Solver scheitert
    true_stats: np.ndarray  # (Durchläufe, Strategien, 3): Rendite, Vola, Sharpe (wahr)
    est_stats: np.ndarray  # dasselbe aus Sicht der Schätzung (in-sample)
    in_cash: np.ndarray  # (Durchläufe, Strategien): kein Portfolio schien besser als rf
    optimal_weights: np.ndarray
    optimal_stats: tuple[float, float, float]
    n_obs: int
    rf: float

    def summary(self) -> pd.DataFrame:
        rows = []
        opt_sharpe = self.optimal_stats[2]
        for j, key in enumerate(self.strategies):
            true_sharpe = self.true_stats[:, j, 2]
            est_sharpe = self.est_stats[:, j, 2]
            ok = np.isfinite(true_sharpe)
            dist = 0.5 * np.abs(self.weights[ok, j] - self.optimal_weights).sum(axis=1)
            rows.append(
                {
                    "strategy": key,
                    "label": STRATEGIES[key],
                    "sharpe_true_mean": np.nanmean(true_sharpe) if ok.any() else np.nan,
                    "sharpe_true_p5": np.nanpercentile(true_sharpe, 5) if ok.any() else np.nan,
                    "sharpe_est_mean": np.nanmean(est_sharpe) if ok.any() else np.nan,
                    "share_of_optimum": np.nanmean(true_sharpe) / opt_sharpe if ok.any() else np.nan,
                    "distance_mean": dist.mean() if ok.any() else np.nan,
                    "cash_share": float(self.in_cash[:, j].mean()),
                    "failures": int((~ok).sum()),
                }
            )
        return pd.DataFrame(rows)

    def sharpe_frame(self) -> pd.DataFrame:
        """Lange Tabelle: eine Zeile pro Durchlauf und Strategie."""
        n_trials = self.true_stats.shape[0]
        return pd.DataFrame(
            {
                "trial": np.repeat(np.arange(n_trials), len(self.strategies)),
                "strategy": np.tile(self.strategies, n_trials),
                "label": np.tile([STRATEGIES[s] for s in self.strategies], n_trials),
                "sharpe_true": self.true_stats[:, :, 2].ravel(),
                "sharpe_est": self.est_stats[:, :, 2].ravel(),
            }
        )


def _resampled_max_sharpe(
    est: Estimates, rf: float, bounds: Bounds, n_resamples: int, rng: np.random.Generator
) -> np.ndarray | None:
    """Resampled Efficiency nach Michaud: Mittel der Max-Sharpe-Gewichte über
    Parameterziehungen, die zur Schätzunsicherheit der Stichprobe passen."""
    n_obs = est.n_obs
    rows = []
    for _ in range(n_resamples):
        mu = rng.multivariate_normal(est.mu, est.cov / est.years)
        cov = wishart.rvs(df=n_obs - 1, scale=est.cov / (n_obs - 1), random_state=rng)
        try:
            w = max_sharpe(mu, np.atleast_2d(cov), rf, bounds)
        except (OptimizationError, np.linalg.LinAlgError):
            w = None
        if w is not None:
            rows.append(w)
    if not rows:
        return None
    w = np.mean(rows, axis=0)
    return w / w.sum()


def _strategy_weights(
    key: str,
    returns: np.ndarray,
    est: Estimates,
    model: Model,
    rf: float,
    bounds: Bounds,
    n_resamples: int,
    rng: np.random.Generator,
    periods_per_year: int,
) -> np.ndarray | None:
    n = len(model.mu)
    if key == "ms_sample":
        return max_sharpe(est.mu, est.cov, rf, bounds)
    if key == "ms_mu_only":
        return max_sharpe(est.mu, model.cov, rf, bounds)
    if key == "ms_cov_only":
        return max_sharpe(model.mu, est.cov, rf, bounds)
    if key == "ms_shrink":
        shrunk = estimate(returns, "bayes_stein", "ledoit_wolf", periods_per_year)
        return max_sharpe(shrunk.mu, shrunk.cov, rf, bounds)
    if key == "ms_resampled":
        return _resampled_max_sharpe(est, rf, bounds, n_resamples, rng)
    if key == "gmv":
        return min_variance(est.cov, bounds)
    if key == "equal":
        return np.full(n, 1 / n)
    raise ValueError(f"Unbekannte Strategie: {key}")


def strategy_experiment(
    model: Model,
    n_obs: int,
    n_trials: int = 100,
    rf: float = 0.0,
    bounds: Bounds = (0.0, 1.0),
    strategies: tuple[str, ...] = tuple(STRATEGIES),
    n_resamples: int = 20,
    seed: int = 0,
    periods_per_year: int = TRADING_DAYS,
    progress: Callable[[float], None] | None = None,
) -> StrategyExperiment:
    """Simuliert ``n_trials`` Historien und vergleicht die Strategien mit dem wahren Optimum."""
    optimal = max_sharpe(model.mu, model.cov, rf, bounds)
    if optimal is None:
        raise ValueError(
            "Im wahren Modell erwartet kein Portfolio eine Rendite über dem risikolosen "
            "Zins - die Sharpe-Ratio lässt sich nicht maximieren."
        )
    n_assets = len(model.mu)
    rng = np.random.default_rng(seed)
    weights = np.full((n_trials, len(strategies), n_assets), np.nan)
    true_stats = np.full((n_trials, len(strategies), 3), np.nan)
    est_stats = np.full((n_trials, len(strategies), 3), np.nan)
    in_cash = np.zeros((n_trials, len(strategies)), dtype=bool)

    for i in range(n_trials):
        returns = simulate_returns(model, n_obs, rng, periods_per_year)
        est = estimate(returns, periods_per_year=periods_per_year)
        for j, key in enumerate(strategies):
            try:
                w = _strategy_weights(
                    key, returns, est, model, rf, bounds, n_resamples, rng, periods_per_year
                )
            except (OptimizationError, np.linalg.LinAlgError):
                continue
            if w is None:
                # Laut Schätzung schlägt kein Portfolio den risikolosen Zins:
                # Der Anleger bleibt risikolos investiert (Sharpe-Ratio 0).
                in_cash[i, j] = True
                weights[i, j] = 0.0
                true_stats[i, j] = est_stats[i, j] = (rf, 0.0, 0.0)
                continue
            weights[i, j] = w
            true_stats[i, j] = portfolio_stats(w, model.mu, model.cov, rf)
            est_stats[i, j] = portfolio_stats(w, est.mu, est.cov, rf)
        if progress is not None:
            progress((i + 1) / n_trials)

    return StrategyExperiment(
        assets=list(model.assets),
        strategies=list(strategies),
        weights=weights,
        true_stats=true_stats,
        est_stats=est_stats,
        in_cash=in_cash,
        optimal_weights=optimal,
        optimal_stats=portfolio_stats(optimal, model.mu, model.cov, rf),
        n_obs=n_obs,
        rf=rf,
    )
