"""Schätzer für erwartete Renditen und Kovarianzmatrizen.

Alle Funktionen arbeiten auf einer Matrix periodischer (meist täglicher)
einfacher Renditen der Form ``(T, N)``: T Beobachtungen, N Assets.
``estimate`` liefert die Parameter annualisiert zurück.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252

MEAN_ESTIMATORS = {
    "sample": "Historischer Mittelwert",
    "bayes_stein": "Bayes-Stein-Shrinkage (Jorion)",
}

COV_ESTIMATORS = {
    "sample": "Stichproben-Kovarianz",
    "ledoit_wolf": "Ledoit-Wolf-Shrinkage (konstante Korrelation)",
}


@dataclass(frozen=True)
class Estimates:
    """Annualisierte Schätzungen für eine Menge von Assets."""

    assets: list[str]
    mu: np.ndarray
    cov: np.ndarray
    n_obs: int
    periods_per_year: int = TRADING_DAYS
    mean_method: str = "sample"
    cov_method: str = "sample"
    mean_shrinkage: float | None = None
    cov_shrinkage: float | None = None

    @property
    def vol(self) -> np.ndarray:
        return np.sqrt(np.diag(self.cov))

    @property
    def corr(self) -> np.ndarray:
        vol = self.vol
        return self.cov / np.outer(vol, vol)

    @property
    def years(self) -> float:
        return self.n_obs / self.periods_per_year


def _as_array(returns: pd.DataFrame | np.ndarray) -> np.ndarray:
    x = np.asarray(returns, dtype=float)
    if x.ndim != 2:
        raise ValueError("Renditen müssen als Matrix (Beobachtungen x Assets) vorliegen.")
    if not np.isfinite(x).all():
        raise ValueError("Renditen enthalten fehlende oder unendliche Werte.")
    return x


def sample_mean(returns: pd.DataFrame | np.ndarray) -> np.ndarray:
    return _as_array(returns).mean(axis=0)


def sample_cov(returns: pd.DataFrame | np.ndarray) -> np.ndarray:
    x = _as_array(returns)
    return np.atleast_2d(np.cov(x, rowvar=False, ddof=1))


def ledoit_wolf_cov(returns: pd.DataFrame | np.ndarray) -> tuple[np.ndarray, float]:
    """Shrinkage zur Matrix mit konstanter Korrelation.

    Ledoit & Wolf (2004): "Honey, I Shrunk the Sample Covariance Matrix".
    Die Varianzen bleiben erhalten, die Korrelationen werden in Richtung
    der durchschnittlichen Korrelation gezogen. Rückgabe: (Kovarianz, Intensität).
    """
    x = _as_array(returns)
    t, n = x.shape
    if n == 1:
        return sample_cov(x), 0.0
    x = x - x.mean(axis=0)
    sample = x.T @ x / t
    var = np.diag(sample)
    std = np.sqrt(var)
    corr = sample / np.outer(std, std)
    r_bar = (corr.sum() - n) / (n * (n - 1))
    prior = r_bar * np.outer(std, std)
    np.fill_diagonal(prior, var)

    # pi-hat: Summe der asymptotischen Varianzen der Stichproben-Kovarianzen
    y = x**2
    pi_mat = y.T @ y / t - sample**2
    pi_hat = pi_mat.sum()

    # rho-hat: asymptotische Kovarianzen zwischen Ziel und Stichprobe
    theta = (x**3).T @ x / t - var[:, None] * sample
    np.fill_diagonal(theta, 0.0)
    rho_hat = np.trace(pi_mat) + r_bar * (np.outer(1 / std, std) * theta).sum()

    # gamma-hat: Abstand zwischen Ziel und Stichprobe
    gamma_hat = np.linalg.norm(sample - prior, "fro") ** 2
    if gamma_hat <= 0:
        return sample, 1.0
    kappa = (pi_hat - rho_hat) / gamma_hat
    shrinkage = float(np.clip(kappa / t, 0.0, 1.0))
    return shrinkage * prior + (1 - shrinkage) * sample, shrinkage


def bayes_stein_mean(returns: pd.DataFrame | np.ndarray) -> tuple[np.ndarray, float]:
    """Bayes-Stein-Schätzer nach Jorion (1986).

    Zieht die Mittelwerte in Richtung der Rendite des Minimum-Varianz-
    Portfolios. Rückgabe: (Mittelwerte, Shrinkage-Gewicht).
    """
    x = _as_array(returns)
    t, n = x.shape
    mu = x.mean(axis=0)
    if n == 1 or t <= n + 2:
        return mu, 0.0
    cov = sample_cov(x) * (t - 1) / (t - n - 2)
    ones = np.ones(n)
    inv_ones = np.linalg.solve(cov, ones)
    mu0 = inv_ones @ mu / (inv_ones @ ones)
    diff = mu - mu0
    dist = t * diff @ np.linalg.solve(cov, diff)
    phi = float((n + 2) / ((n + 2) + dist))
    return (1 - phi) * mu + phi * mu0, phi


def estimate(
    returns: pd.DataFrame | np.ndarray,
    mean_method: str = "sample",
    cov_method: str = "sample",
    periods_per_year: int = TRADING_DAYS,
    assets: list[str] | None = None,
) -> Estimates:
    """Schätzt annualisierte erwartete Renditen und Kovarianzen."""
    if mean_method not in MEAN_ESTIMATORS:
        raise ValueError(f"Unbekannter Mittelwert-Schätzer: {mean_method}")
    if cov_method not in COV_ESTIMATORS:
        raise ValueError(f"Unbekannter Kovarianz-Schätzer: {cov_method}")
    x = _as_array(returns)
    if assets is None:
        assets = (
            [str(c) for c in returns.columns]
            if isinstance(returns, pd.DataFrame)
            else [f"Asset {i + 1}" for i in range(x.shape[1])]
        )

    mean_shrinkage = None
    if mean_method == "bayes_stein":
        mu, mean_shrinkage = bayes_stein_mean(x)
    else:
        mu = sample_mean(x)

    cov_shrinkage = None
    if cov_method == "ledoit_wolf":
        cov, cov_shrinkage = ledoit_wolf_cov(x)
    else:
        cov = sample_cov(x)

    return Estimates(
        assets=list(assets),
        mu=mu * periods_per_year,
        cov=cov * periods_per_year,
        n_obs=x.shape[0],
        periods_per_year=periods_per_year,
        mean_method=mean_method,
        cov_method=cov_method,
        mean_shrinkage=mean_shrinkage,
        cov_shrinkage=cov_shrinkage,
    )
