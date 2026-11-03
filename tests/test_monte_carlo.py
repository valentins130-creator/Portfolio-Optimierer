import numpy as np
import pytest

from portfolio_optimizer import monte_carlo as mc


def test_deterministic_growth_with_contributions():
    mu = np.array([0.06, 0.03])
    cov = np.zeros((2, 2))  # ohne Risiko ist jeder Pfad gleich
    w = np.array([0.5, 0.5])
    sim = mc.simulate_gbm(w, mu, cov, years=5, n_paths=3, initial=1000, contribution=100, seed=0)
    g = w @ np.exp(mu / 12)
    n = 60
    expected = 1000 * g**n + 100 * sum(g**k for k in range(n))
    np.testing.assert_allclose(sim.wealth[:, -1], expected)
    np.testing.assert_allclose(sim.index[:, -1], g**n)
    assert sim.invested[-1] == pytest.approx(1000 + 100 * n)
    assert sim.wealth.shape == (3, n + 1)
    assert sim.years == pytest.approx(5)


def test_gbm_mean_matches_theory(demo_model):
    mu, cov = demo_model
    w = np.full(len(mu), 1 / len(mu))
    sim = mc.simulate_gbm(w, mu, cov, years=10, n_paths=20_000, seed=1)
    expected = (w @ np.exp(mu / 12)) ** 120
    final = sim.index[:, -1]
    assert abs(final.mean() - expected) < 4 * final.std() / np.sqrt(len(final))


def test_bootstrap_with_constant_returns_is_deterministic():
    daily = np.full((300, 2), 0.001)
    w = np.array([0.3, 0.7])
    sim = mc.simulate_bootstrap(w, daily, years=2, n_paths=5, initial=100, seed=0)
    np.testing.assert_allclose(sim.wealth[:, -1], 100 * 1.001 ** (21 * 24))


def test_bootstrap_uses_historical_blocks(rng):
    daily = rng.normal(0.0004, 0.01, size=(2000, 3))
    w = np.array([0.2, 0.3, 0.5])
    sim = mc.simulate_bootstrap(w, daily, years=3, n_paths=4000, seed=2)
    # Alle möglichen Monatsblöcke aus 21 aufeinanderfolgenden Tagen
    blocks = np.array([np.prod(1 + daily[s : s + 21], axis=0) @ w for s in range(len(daily) - 20)])
    step_growth = sim.index[:, 1]
    assert set(np.round(step_growth[:50], 12)) <= set(np.round(blocks, 12))
    assert step_growth.mean() == pytest.approx(blocks.mean(), abs=4 * blocks.std() / np.sqrt(4000))


def test_summary_statistics_are_consistent(demo_model):
    mu, cov = demo_model
    w = np.full(len(mu), 1 / len(mu))
    sim = mc.simulate_gbm(w, mu, cov, years=10, n_paths=2000, initial=10_000, contribution=100, seed=3)
    s = sim.summary(target=25_000)
    assert s["p5"] <= s["median"] <= s["p95"]
    assert s["cvar5"] <= s["p5"]
    assert 0 <= s["prob_loss"] <= 1
    assert 0 <= s["prob_target"] <= 1
    assert 0 <= s["max_dd_median"] <= s["max_dd_p95"] <= 1
    q = sim.percentiles()
    assert list(q.columns) == ["P5", "P25", "P50", "P75", "P95"]
    assert (q.diff(axis=1).iloc[:, 1:] >= 0).all().all()


def test_leveraged_portfolio_cannot_go_below_zero():
    mu = np.array([0.0, 0.0])
    cov = np.array([[0.25, 0.0], [0.0, 0.25]])
    w = np.array([3.0, -2.0])
    sim = mc.simulate_gbm(w, mu, cov, years=5, n_paths=500, seed=4)
    assert (sim.wealth >= 0).all()


def test_invalid_inputs_raise(demo_model):
    mu, cov = demo_model
    with pytest.raises(ValueError):
        mc.simulate_gbm(np.full(len(mu), 0.5), mu, cov, years=1)
    with pytest.raises(ValueError):
        mc.simulate_bootstrap(np.array([0.5, 0.5]), np.full((10, 2), 0.01), years=1)
