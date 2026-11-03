import numpy as np
import pandas as pd
import pytest

from portfolio_optimizer.estimators import (
    TRADING_DAYS,
    bayes_stein_mean,
    estimate,
    ledoit_wolf_cov,
    sample_cov,
)


def _returns(rng, n_obs, mu, cov):
    return rng.multivariate_normal(mu / TRADING_DAYS, cov / TRADING_DAYS, size=n_obs)


def _ledoit_wolf_reference(x):
    """Direkte Umsetzung der Formeln aus Ledoit & Wolf (2004) mit Schleifen."""
    t, n = x.shape
    y = x - x.mean(axis=0)
    s = y.T @ y / t
    sd = np.sqrt(np.diag(s))
    r_bar = sum(s[i, j] / (sd[i] * sd[j]) for i in range(n) for j in range(n) if i != j) / (n * (n - 1))
    f = np.array([[s[i, i] if i == j else r_bar * sd[i] * sd[j] for j in range(n)] for i in range(n)])
    pi = np.array([[np.mean((y[:, i] * y[:, j] - s[i, j]) ** 2) for j in range(n)] for i in range(n)])

    def theta(k, i, j):
        return np.mean((y[:, k] ** 2 - s[k, k]) * (y[:, i] * y[:, j] - s[i, j]))

    rho = np.trace(pi) + sum(
        r_bar / 2 * (sd[j] / sd[i] * theta(i, i, j) + sd[i] / sd[j] * theta(j, i, j))
        for i in range(n)
        for j in range(n)
        if i != j
    )
    gamma = ((f - s) ** 2).sum()
    delta = max(0.0, min(1.0, (pi.sum() - rho) / gamma / t))
    return delta * f + (1 - delta) * s, delta


def test_sample_estimates_are_annualized(rng, demo_model):
    x = _returns(rng, 500, *demo_model)
    est = estimate(pd.DataFrame(x, columns=list("ABCDEF")))
    assert est.assets == list("ABCDEF")
    np.testing.assert_allclose(est.mu, x.mean(axis=0) * TRADING_DAYS)
    np.testing.assert_allclose(est.cov, np.cov(x, rowvar=False) * TRADING_DAYS)
    assert est.years == pytest.approx(500 / TRADING_DAYS)


def test_ledoit_wolf_matches_reference_formula(rng, demo_model):
    x = _returns(rng, 80, *demo_model)
    cov, delta = ledoit_wolf_cov(x)
    ref_cov, ref_delta = _ledoit_wolf_reference(x)
    assert delta == pytest.approx(ref_delta)
    np.testing.assert_allclose(cov, ref_cov)


def test_ledoit_wolf_keeps_variances_and_shrinks_less_with_more_data(rng, demo_model):
    short = _returns(rng, 60, *demo_model)
    long = _returns(rng, 5000, *demo_model)
    cov_short, delta_short = ledoit_wolf_cov(short)
    _, delta_long = ledoit_wolf_cov(long)
    assert 0 <= delta_long < delta_short <= 1
    centered = short - short.mean(axis=0)
    np.testing.assert_allclose(np.diag(cov_short), (centered**2).mean(axis=0))
    assert np.linalg.eigvalsh(cov_short).min() > 0


def test_bayes_stein_pulls_means_together(rng):
    n = 5
    cov = 0.04 * (0.3 * np.ones((n, n)) + 0.7 * np.eye(n))
    x = _returns(rng, 750, np.full(n, 0.06), cov)
    mu_bs, phi = bayes_stein_mean(x)
    mu = x.mean(axis=0)
    assert 0 < phi <= 1
    assert np.ptp(mu_bs) < np.ptp(mu)
    # Konvexkombination: alle Werte liegen zwischen Mittelwert und gemeinsamem Ziel
    target = (mu_bs - (1 - phi) * mu) / phi
    np.testing.assert_allclose(target, target[0])


def test_bayes_stein_falls_back_with_too_few_observations(rng):
    x = rng.normal(size=(4, 3))
    mu, phi = bayes_stein_mean(x)
    assert phi == 0.0
    np.testing.assert_allclose(mu, x.mean(axis=0))


def test_estimate_rejects_unknown_methods(rng):
    x = rng.normal(size=(100, 2))
    with pytest.raises(ValueError):
        estimate(x, mean_method="magic")
    with pytest.raises(ValueError):
        estimate(x, cov_method="magic")


def test_estimate_rejects_missing_values():
    x = np.array([[0.01, np.nan], [0.02, 0.01]])
    with pytest.raises(ValueError):
        sample_cov(x)
