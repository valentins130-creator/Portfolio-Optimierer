from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_optimizer import concentration as conc
from portfolio_optimizer import hedging as hg
from portfolio_optimizer import rebalancing as rb
from portfolio_optimizer.market import FUND_COUNTRY, DemoMarketData, Instrument, SecurityInfo, to_base_currency


def _info(symbol, sector="Technologie", country="USA", currency="USD", fund=False):
    return SecurityInfo(symbol, f"Name {symbol}", "ETF" if fund else "Aktie", currency, sector,
                        FUND_COUNTRY if fund else country)


@pytest.fixture
def returns():
    """Drei stark korrelierte Tech-Werte, ein unabhängiger Versorger, ein Index."""
    rng = np.random.default_rng(0)
    n = 260
    market = rng.normal(0.002, 0.02, n)
    tech = rng.normal(0, 0.02, n)
    data = {
        "T1": market + tech + rng.normal(0, 0.006, n),
        "T2": market + tech + rng.normal(0, 0.006, n),
        "T3": market + tech + rng.normal(0, 0.006, n),
        "U1": 0.3 * market + rng.normal(0, 0.01, n),
        "IDX": market,
        "TECHX": market + tech,
        "BOND": rng.normal(0.0005, 0.004, n),
    }
    return pd.DataFrame(data, index=pd.date_range("2020-01-03", periods=n, freq="W-FRI"))


def test_hhi_and_effective_positions():
    assert conc.hhi(np.full(4, 0.25)) == pytest.approx(0.25)
    assert conc.hhi([1.0]) == 1.0


def test_correlation_clusters_find_tech_group(returns):
    clusters = conc.correlation_clusters(returns[["T1", "T2", "T3", "U1"]], threshold=0.7)
    assert clusters == [["T1", "T2", "T3"]]
    assert conc.correlation_clusters(returns[["T1"]], 0.7) == []


def test_analyze_flags_concentrations(returns):
    infos = {"T1": _info("T1"), "T2": _info("T2"), "T3": _info("T3"),
             "U1": _info("U1", "Versorger", "Deutschland", "EUR")}
    weights = pd.Series({"T1": 0.3, "T2": 0.2, "T3": 0.2, "U1": 0.3})
    report = conc.analyze(weights, infos, returns, conc.Limits())
    exceeded = {(f.kind, f.group) for f in report.exceeded}
    assert ("position", "Name T1") in exceeded
    assert ("sector", "Technologie") in exceeded
    assert ("currency", "USD") in exceeded
    assert ("country", "USA") in exceeded
    assert any(kind == "cluster" for kind, _ in exceeded)
    assert report.risk_shares.sum() == pytest.approx(1.0)
    # Die Tech-Werte tragen mehr Risiko als Gewicht
    assert report.risk_shares[["T1", "T2", "T3"]].sum() > 0.7
    tech = next(f for f in report.findings if f.group == "Technologie")
    assert tech.excess == pytest.approx(0.4)
    assert report.effective_positions == pytest.approx(1 / (0.09 + 0.04 + 0.04 + 0.09))


def test_beta_hedge_recovers_beta_and_cuts_risk(returns):
    port = 0.8 * returns["IDX"] + pd.Series(np.random.default_rng(1).normal(0, 0.005, len(returns)),
                                            index=returns.index)
    instruments = [Instrument("IDX", "Index", "market")]
    (hedge,) = hg.beta_hedges(port, returns, instruments, value=100_000)
    assert hedge.beta == pytest.approx(0.8, abs=0.05)
    assert hedge.notional == pytest.approx(hedge.beta * 100_000)
    assert hedge.r2 > 0.9
    assert hedge.vol_after < 0.4 * hedge.vol_before
    (half,) = hg.beta_hedges(port, returns, instruments, value=100_000, ratio=0.5)
    assert hedge.vol_after < half.vol_after < half.vol_before


def test_min_variance_share_matches_brute_force(returns):
    p, c = returns["T1"], returns["BOND"]
    x = hg.min_variance_share(p, c, max_share=1.0)
    grid = np.linspace(0, 1, 2001)
    best = grid[np.argmin([((1 - g) * p + g * c).var() for g in grid])]
    assert x == pytest.approx(best, abs=1e-3)


def test_diversifiers_rank_bonds_first(returns):
    port = returns[["T1", "T2", "T3"]].mean(axis=1)
    instruments = [Instrument("BOND", "Anleihen", "diversifier"), Instrument("TECHX", "Tech", "diversifier")]
    divs = hg.diversifiers(port, returns, instruments, share=0.3)
    assert [d.instrument.symbol for d in divs] == ["BOND", "TECHX"]
    assert divs[0].vol_after < divs[0].vol_before
    assert divs[0].mdd_after <= divs[0].mdd_before


def test_concentration_hedges_pick_matching_instrument(returns):
    infos = {"T1": _info("T1"), "T2": _info("T2"), "T3": _info("T3"),
             "U1": _info("U1", "Versorger", "Deutschland", "EUR")}
    weights = pd.Series({"T1": 0.3, "T2": 0.2, "T3": 0.2, "U1": 0.3})
    report = conc.analyze(weights, infos, returns)
    instruments = [Instrument("IDX", "Index", "market"), Instrument("TECHX", "Tech", "sector", sector="Technologie")]
    fx = pd.DataFrame({"USD": np.random.default_rng(2).normal(0, 0.01, len(returns))}, index=returns.index)
    items = hg.concentration_hedges(report.findings, weights, returns, 10_000, returns, instruments, fx)
    sector = next(i for i in items if i.finding.group == "Technologie")
    assert sector.instrument.symbol == "TECHX"
    assert sector.reduce_amount == pytest.approx(0.4 * 10_000)
    assert sector.vol_after < sector.vol_before
    usd = next(i for i in items if i.finding.kind == "currency")
    assert usd.instrument.kind == "fx" and usd.notional == pytest.approx(usd.finding.excess * 10_000)


def test_cap_concentrations_is_minimal_and_feasible(returns):
    infos = {"T1": _info("T1"), "T2": _info("T2"), "U1": _info("U1", "Versorger", "Deutschland", "EUR"),
             "W": SecurityInfo("W", "Welt", "ETF", "EUR", "Diversifiziert", FUND_COUNTRY,
                               {"Technologie": 0.25, "Versorger": 0.05, "Finanzen": 0.7})}
    current = pd.Series({"T1": 0.5, "T2": 0.3, "U1": 0.2, "W": 0.0})
    limits = conc.Limits(position=0.25, sector=0.5, country=1.0, currency=1.0, cluster=1.0)
    target = rb.cap_concentrations(current, infos, limits)
    assert target.sum() == pytest.approx(1.0)
    assert target[["T1", "T2", "U1"]].max() <= 0.25 + 1e-6
    tech = target["T1"] + target["T2"] + 0.25 * target["W"]
    assert tech <= 0.5 + 1e-6
    assert target["W"] > 0  # der Welt-ETF nimmt den Überhang auf
    with pytest.raises(rb.InfeasibleError):
        rb.cap_concentrations(current[["T1", "T2"]], infos, limits)


def test_trades_round_conservatively_and_report_gains():
    val = pd.DataFrame({"shares": [10.0, 5.0], "value": [1000.0, 1000.0], "purchase_price": [80.0, np.nan],
                        "price": [100.0, 200.0]}, index=["A", "B"])
    target = pd.Series({"A": 0.255, "B": 0.5, "C": 0.245})
    prices = pd.Series({"A": 100.0, "B": 200.0, "C": 30.0})
    tr = rb.trades(val, target, prices, whole_shares=True, min_trade=0)
    assert tr.loc["A", "shares_delta"] == -5  # 4,9 Stück verkaufen -> 5
    assert tr.loc["A", "realized_gain"] == pytest.approx(5 * 20)
    assert tr.loc["C", "shares_delta"] == 16  # 16,3 Stück kaufen -> 16
    assert tr.loc["B", "action"] == "Halten"
    assert (tr["weight_after"] <= pd.Series({"A": 0.255, "B": 0.5, "C": 0.245}) + 1e-12).all()
    assert tr["value_after"].sum() <= 2000
    skipped = rb.trades(val, target, prices, whole_shares=False, min_trade=600)
    assert skipped.loc["A", "amount"] == 0 and skipped.loc["C", "amount"] == 0
    fifo = rb.trades(val, target, prices, whole_shares=True, sale_gain=lambda s, n, px: n * (px - 50.0))
    assert fifo.loc["A", "realized_gain"] == pytest.approx(5 * 50)  # Gewinn aus den Kauf-Tranchen


def test_demo_portfolio_end_to_end():
    provider = DemoMarketData(end=date(2025, 6, 30))
    symbols = ["NLS.DEMO", "PCH.DEMO", "LCL.DEMO", "ALP.DEMO", "DWLD.DEMO"]
    infos = {s: provider.info(s) for s in symbols}
    start, end = date(2021, 1, 1), date(2025, 6, 30)
    fx = provider.fx_rates(["USD", "CHF"], start, end)
    prices = to_base_currency(provider.prices(symbols, start, end), {s: i.currency for s, i in infos.items()}, fx)
    weights = pd.Series([0.25, 0.25, 0.2, 0.1, 0.2], index=symbols)
    weekly = hg.weekly_returns(prices)
    report = conc.analyze(weights, infos, weekly)
    assert report.clusters and set(report.clusters[0]) >= {"PCH.DEMO", "LCL.DEMO"}
    assert "DWLD.DEMO" not in {s for c in report.clusters for s in c}  # Fonds bilden keine Cluster
    target = rb.cap_concentrations(weights, infos, conc.Limits(), report.clusters)
    after = conc.analyze(target, infos, weekly)
    assert not [f for f in after.findings if f.exceeded and f.excess > 1e-4]


def test_closest_to_limits_when_limits_are_unreachable(returns):
    infos = {"T1": _info("T1"), "T2": _info("T2"), "U1": _info("U1", "Versorger", "Deutschland", "EUR")}
    current = pd.Series({"T1": 0.5, "T2": 0.3, "U1": 0.2})
    limits = conc.Limits(position=0.4, sector=0.3, country=1.0, currency=1.0, cluster=1.0)
    with pytest.raises(rb.InfeasibleError):
        rb.cap_concentrations(current, infos, limits)
    target, remaining = rb.closest_to_limits(current, infos, limits)
    # U1 ist der einzige Versorger und darf die 30-%-Sektorgrenze nicht neu überschreiten:
    # Technologie lässt sich daher nur auf 70 % drücken.
    assert target.sum() == pytest.approx(1.0)
    assert target["U1"] == pytest.approx(0.3, abs=1e-4)
    assert target["T1"] + target["T2"] == pytest.approx(0.7, abs=1e-4)
    assert max(target["T1"], target["T2"]) <= 0.4 + 1e-3  # die behebbare Einzelgrenze wird mit abgebaut
    assert list(remaining) == ["Sektor Technologie"]
    assert remaining["Sektor Technologie"] == pytest.approx(0.4, abs=1e-3)
    # Erreichbare Grenzen: dasselbe Ergebnis wie cap_concentrations
    easy = conc.Limits(position=0.6, sector=1.0, country=1.0, currency=1.0, cluster=1.0)
    target2, remaining2 = rb.closest_to_limits(current, infos, easy)
    assert remaining2 == {}
    pd.testing.assert_series_equal(target2, rb.cap_concentrations(current, infos, easy))
