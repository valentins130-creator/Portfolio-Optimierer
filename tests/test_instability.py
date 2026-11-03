import numpy as np
import pandas as pd
import pytest

from portfolio_optimizer import instability as ins
from portfolio_optimizer.optimization import efficient_risk, max_sharpe


@pytest.fixture
def model(demo_model):
    mu, cov = demo_model
    return ins.Model([f"A{i}" for i in range(len(mu))], mu, cov)


def test_identical_assets_have_equal_weight_optimum():
    model = ins.identical_assets_model(5, 0.07, 0.2, 0.3)
    np.testing.assert_allclose(max_sharpe(model.mu, model.cov, 0.02, (0, 1)), 0.2, atol=1e-6)
    with pytest.raises(ValueError):
        ins.identical_assets_model(5, 0.07, 0.2, -0.5)


def test_simulated_returns_have_model_moments(model, rng):
    x = ins.simulate_returns(model, 200_000, rng)
    np.testing.assert_allclose(np.cov(x, rowvar=False) * 252, model.cov, atol=2e-3)


def test_estimation_error_table(rng):
    returns = pd.DataFrame(rng.normal(0.0004, 0.01, size=(1260, 2)), columns=["X", "Y"])
    table = ins.estimation_error_table(returns)
    np.testing.assert_allclose(table["se"], table["vol"] / np.sqrt(5))
    np.testing.assert_allclose(table["ci_high"] - table["ci_low"], 2 * 1.96 * table["se"])
    np.testing.assert_allclose(table["years_needed"], (table["vol"] / 0.01) ** 2)


def test_perturbation_and_turnover(model):
    before, after = ins.perturbed_weights(model.mu, model.cov, 0.02, (0, 1), asset=0, delta=0.0)
    np.testing.assert_allclose(before, after)
    assert ins.turnover(before, after) == pytest.approx(0, abs=1e-9)
    before, after = ins.perturbed_weights(model.mu, model.cov, 0.02, (0, 1), asset=0, delta=0.02)
    assert after[0] > before[0]
    assert ins.turnover([1, 0], [0, 1]) == 1


def test_strategy_experiment_shows_error_maximization(model):
    exp = ins.strategy_experiment(model, n_obs=5 * 252, n_trials=40, rf=0.02, bounds=(0, 1), n_resamples=5, seed=3)
    opt_sharpe = exp.optimal_stats[2]
    true_sharpe = exp.true_stats[:, :, 2]
    # Kein Portfolio kann mit den wahren Parametern das wahre Optimum übertreffen
    assert np.nanmax(true_sharpe) <= opt_sharpe + 1e-6
    summary = exp.summary().set_index("strategy")
    sample = summary.loc["ms_sample"]
    # Die Schätzung verspricht mehr, als das Portfolio liefert
    assert sample["sharpe_est_mean"] > sample["sharpe_true_mean"]
    # Fehler in den Mittelwerten wiegen schwerer als Fehler in den Kovarianzen
    assert summary.loc["ms_cov_only", "share_of_optimum"] > summary.loc["ms_mu_only", "share_of_optimum"]
    np.testing.assert_allclose(exp.weights[:, exp.strategies.index("equal")], 1 / len(model.mu))
    frame = exp.sharpe_frame()
    assert len(frame) == 40 * len(exp.strategies)


def test_strategy_experiment_counts_cash_trials():
    # Wahre Überrendite klein: in manchen Stichproben liegt keine Schätzung über rf
    model = ins.identical_assets_model(3, 0.025, 0.2, 0.2)
    exp = ins.strategy_experiment(model, n_obs=252, n_trials=30, rf=0.02, strategies=("ms_sample",), seed=0)
    cash = exp.in_cash[:, 0]
    assert cash.any()
    np.testing.assert_allclose(exp.true_stats[cash, 0, 2], 0.0)
    assert exp.summary().loc[0, "cash_share"] == pytest.approx(cash.mean())


def test_strategy_experiment_requires_positive_true_excess_return():
    model = ins.identical_assets_model(3, 0.01, 0.2, 0.2)
    with pytest.raises(ValueError):
        ins.strategy_experiment(model, n_obs=252, n_trials=2, rf=0.02)


def test_actual_frontiers_lie_below_true_frontier(model):
    exp = ins.frontier_experiment(model, n_obs=3 * 252, n_trials=6, bounds=(0, 1), n_points=10, seed=5)
    tf = exp.true_frontier
    assert len(exp.estimated) == len(exp.actual) == 6
    for fr in exp.actual:
        # Unterhalb der Minimum-Varianz-Volatilität gibt es keine zulässigen Portfolios
        assert (fr.vols >= tf.vols[0] - 1e-9).all()
        for vol, ret in zip(fr.vols, fr.returns):
            best = efficient_risk(model.mu, model.cov, vol, (0, 1)) @ model.mu
            assert ret <= best + 1e-6
