import numpy as np
import pytest

from portfolio_optimizer import optimization as opt

LOOSE = (-50.0, 50.0)  # so weit, dass die Grenzen nie greifen


def test_two_uncorrelated_assets_min_variance_has_closed_form():
    cov = np.diag([0.04, 0.01])
    w = opt.min_variance(cov, (0, 1))
    assert w[0] == pytest.approx(0.01 / 0.05, abs=1e-6)


@pytest.mark.parametrize("rf", [0.0, 0.02])
def test_bounded_solvers_match_analytic_solutions(demo_model, rf):
    mu, cov = demo_model
    np.testing.assert_allclose(opt.min_variance(cov, LOOSE), opt.min_variance(cov, None), atol=1e-5)
    np.testing.assert_allclose(opt.max_sharpe(mu, cov, rf, LOOSE), opt.max_sharpe(mu, cov, rf, None), atol=1e-4)
    target = 0.06
    np.testing.assert_allclose(
        opt.efficient_return(mu, cov, target, LOOSE), opt.efficient_return(mu, cov, target, None), atol=1e-5
    )


def test_long_only_max_sharpe_beats_random_portfolios(demo_model, rng):
    mu, cov = demo_model
    rf = 0.02
    w = opt.max_sharpe(mu, cov, rf, (0, 1))
    assert w.sum() == pytest.approx(1)
    assert (w >= 0).all()
    best = opt.portfolio_stats(w, mu, cov, rf)[2]
    random_w = rng.dirichlet(np.ones(len(mu)), size=5000)
    random_sharpe = (random_w @ mu - rf) / np.sqrt(np.einsum("ij,jk,ik->i", random_w, cov, random_w))
    assert best >= random_sharpe.max() - 1e-9


@pytest.mark.parametrize("bounds", [(0.0, 0.3), (-0.2, 0.6), (0.05, 0.5)])
def test_weight_bounds_are_respected(demo_model, bounds):
    mu, cov = demo_model
    lo, hi = bounds
    for w in (opt.min_variance(cov, bounds), opt.max_sharpe(mu, cov, 0.02, bounds)):
        assert w.sum() == pytest.approx(1)
        assert w.min() >= lo - 1e-9
        assert w.max() <= hi + 1e-9


def test_max_sharpe_is_tangent_to_frontier(demo_model):
    mu, cov = demo_model
    rf = 0.02
    frontier = opt.efficient_frontier(mu, cov, (0, 1), n_points=80)
    w = opt.max_sharpe(mu, cov, rf, (0, 1))
    best = opt.portfolio_stats(w, mu, cov, rf)[2]
    assert best >= ((frontier.returns - rf) / frontier.vols).max() - 1e-9


def test_max_sharpe_without_excess_return_returns_none(demo_model):
    mu, cov = demo_model
    assert opt.max_sharpe(mu, cov, rf=0.5, bounds=(0, 1)) is None


def test_efficient_frontier_is_monotone_and_starts_at_gmv(demo_model):
    mu, cov = demo_model
    for bounds in [(0, 1), None]:
        frontier = opt.efficient_frontier(mu, cov, bounds, n_points=40)
        assert np.all(np.diff(frontier.returns) > 0)
        assert np.all(np.diff(frontier.vols) > -1e-9)
        np.testing.assert_allclose(frontier.weights[0], opt.min_variance(cov, bounds), atol=1e-6)
        np.testing.assert_allclose(frontier.weights.sum(axis=1), 1)


def test_efficient_return_hits_target(demo_model):
    mu, cov = demo_model
    w = opt.efficient_return(mu, cov, 0.05, (0, 1))
    assert w @ mu == pytest.approx(0.05, abs=1e-7)


@pytest.mark.parametrize("bounds", [(0, 1), None])
def test_efficient_risk_maximizes_return_for_given_volatility(demo_model, bounds):
    mu, cov = demo_model
    target = 0.10
    w = opt.efficient_risk(mu, cov, target, bounds)
    ret, vol, _ = opt.portfolio_stats(w, mu, cov)
    assert vol == pytest.approx(target, abs=1e-5)
    frontier = opt.efficient_frontier(mu, cov, bounds, n_points=200)
    assert ret >= frontier.returns[frontier.vols <= target].max() - 1e-6


def test_efficient_risk_clamps_to_frontier_ends(demo_model):
    mu, cov = demo_model
    np.testing.assert_allclose(opt.efficient_risk(mu, cov, 0.001, (0, 1)), opt.min_variance(cov, (0, 1)))
    np.testing.assert_allclose(opt.efficient_risk(mu, cov, 5.0, (0, 1)), opt.max_return_weights(mu, (0, 1)))


def test_max_return_weights_fills_best_assets_first():
    mu = np.array([0.10, 0.05, 0.20])
    np.testing.assert_allclose(opt.max_return_weights(mu, (0, 0.5)), [0.5, 0, 0.5])
    # Mit Leerverkäufen: alle starten bei -10 %, das Budget von 130 % geht an die besten Assets
    np.testing.assert_allclose(opt.max_return_weights(mu, (-0.1, 1.0)), [0.1, -0.1, 1.0])


def test_infeasible_bounds_raise():
    with pytest.raises(ValueError):
        opt.validate_bounds(4, (0, 0.2))  # 4 x 20 % < 100 %
    with pytest.raises(ValueError):
        opt.validate_bounds(4, (0.3, 1))  # 4 x 30 % > 100 %
    opt.validate_bounds(4, None)


def test_risk_contributions_sum_to_one(demo_model):
    _, cov = demo_model
    w = opt.min_variance(cov, (0, 1))
    rc = opt.risk_contributions(w, cov)
    assert rc.sum() == pytest.approx(1)


def test_random_portfolios_respect_bounds(demo_model):
    mu, cov = demo_model
    bounds = (0, 0.4)
    rets, vols = opt.random_portfolios(mu, cov, 2000, bounds=bounds)
    assert len(rets) > 0
    # Kein zulässiges Zufallsportfolio liegt oberhalb des effizienten Rands
    for ret, vol in list(zip(rets, vols))[:100]:
        assert ret <= opt.efficient_risk(mu, cov, vol, bounds) @ mu + 1e-6
