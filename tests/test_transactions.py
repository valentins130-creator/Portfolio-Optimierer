from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_optimizer.market import SecurityInfo
from portfolio_optimizer.performance import benchmark, compute, xirr
from portfolio_optimizer.portfolio import BUY, SELL, Portfolio, Transaction, fifo, read_transactions_csv, sale_gain

A = SecurityInfo("A", "Aktie A")
B = SecurityInfo("B", "Aktie B")


def _portfolio():
    pf = Portfolio("Test")
    pf.add_transaction(A, BUY, 10, 100.0, date(2024, 1, 2))
    pf.add_transaction(A, BUY, 10, 120.0, date(2024, 6, 3))
    pf.add_transaction(A, SELL, 15, 150.0, date(2024, 9, 2))
    pf.add_transaction(B, BUY, 5, 50.0, date(2024, 3, 1))
    return pf


def test_fifo_holdings_cost_and_realized_gain():
    pf = _portfolio()
    a = pf.get("A")
    assert a.shares == 5 and a.purchase_price == pytest.approx(120.0)  # die ersten 10 + 5 Stück sind verkauft
    assert a.realized == pytest.approx(10 * 50 + 5 * 30)
    assert a.first_date == date(2024, 1, 2)
    assert pf.realized_gains() == pytest.approx(650.0)
    assert fifo([Transaction("X", BUY, 3, None)]) == (3, None, 0.0)


def test_planned_sale_gain_uses_oldest_lots_first():
    pf = Portfolio("Test")
    pf.add_transaction(A, BUY, 10, 100.0, date(2023, 1, 2))
    pf.add_transaction(A, BUY, 10, 200.0, date(2024, 1, 2))
    assert pf.sale_gain("A", 5, 300.0) == pytest.approx(5 * 200)  # FIFO, nicht Ø-Kurs 150
    assert pf.sale_gain("A", 15, 300.0) == pytest.approx(10 * 200 + 5 * 100)
    pf.add_transaction(A, SELL, 10, 150.0, date(2024, 6, 3))  # erste Tranche ist weg
    assert pf.sale_gain("A", 5, 300.0) == pytest.approx(5 * 100)
    assert sale_gain([Transaction("X", BUY, 3, None)], 1, 10.0) is None  # ohne Kaufkurs kein Gewinn


def test_sells_cannot_exceed_holdings():
    pf = _portfolio()
    with pytest.raises(ValueError, match="übersteigt den Bestand"):
        pf.add_transaction(A, SELL, 6, 150.0, date(2024, 10, 1))
    assert len(pf.transactions) == 4  # ungültige Transaktion wurde nicht übernommen
    with pytest.raises(ValueError):
        pf.add_transaction(A, SELL, 1, 150.0, date(2023, 12, 1))  # vor dem ersten Kauf
    with pytest.raises(ValueError):
        pf.remove_transaction(0)  # ohne den ersten Kauf wäre der Verkauf ungedeckt
    with pytest.raises(ValueError):
        pf.update_transaction(2, shares=30.0)
    assert pf.transactions[2].shares == 15  # zurückgenommen


def test_fully_sold_position_disappears_but_keeps_history():
    pf = Portfolio("Test")
    pf.add_transaction(A, BUY, 4, 10.0, date(2024, 1, 2))
    pf.add_transaction(A, SELL, 4, 12.0, date(2024, 2, 1))
    assert pf.positions == [] and pf.symbols == []
    assert pf.realized_gains() == pytest.approx(8.0)
    pf.remove("A")
    assert pf.transactions == [] and pf.securities == {}


def test_json_roundtrip_and_old_format_migration():
    pf = _portfolio()
    again = Portfolio.from_dict(__import__("json").loads(pf.to_json()))
    assert again.transactions == pf.transactions and again.securities == pf.securities
    old = {"name": "Alt", "positions": [{"symbol": "A", "name": "Aktie A", "shares": 7, "purchase_price": 99.5}]}
    migrated = Portfolio.from_dict(old)
    assert migrated.transactions == [Transaction("A", BUY, 7.0, 99.5, None)]
    assert migrated.get("A").shares == 7


def test_csv_with_dates_and_sells_roundtrip():
    pf = _portfolio()
    rows = read_transactions_csv(pf.to_csv())
    assert rows[0] == ("A", BUY, 10.0, 100.0, date(2024, 1, 2))
    assert ("A", SELL, 15.0, 150.0, date(2024, 9, 2)) in rows
    english = "date,type,ticker,shares,price\n2024-05-02,sell,MSFT,1,400.5\n"
    assert read_transactions_csv(english) == [("MSFT", SELL, 1.0, 400.5, date(2024, 5, 2))]
    with pytest.raises(ValueError, match="Ungültiges Datum"):
        read_transactions_csv("Datum;Symbol;Stück\n31.02.2024;A;1\n")


def test_xirr_matches_simple_cases():
    assert xirr([(date(2021, 1, 1), -100), (date(2022, 1, 1), 110)]) == pytest.approx(0.1, abs=1e-3)
    assert xirr([(date(2021, 1, 1), -100)]) is None
    flows = [(date(2020, 1, 1), -100), (date(2021, 1, 1), -100), (date(2022, 1, 1), 231)]
    rate = xirr(flows)
    assert -100 * (1 + rate) ** 2 - 100 * (1 + rate) + 231 == pytest.approx(0, abs=0.5)


def test_performance_value_invested_and_twr():
    pf = _portfolio()
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    prices = pd.DataFrame({"A": np.linspace(100, 160, len(idx)), "B": 50.0}, index=idx)
    perf = compute(pf, prices)
    assert perf.value.index[0] == pd.Timestamp("2024-01-02")
    assert perf.value.iloc[-1] == pytest.approx(5 * 160 + 5 * 50)
    assert perf.invested.iloc[-1] == pytest.approx(1000 + 1200 + 250 - 2250)
    assert perf.gain == pytest.approx(650 + 5 * 40)  # realisiert + unrealisiert
    assert perf.position_pnl.iloc[-1].to_dict() == pytest.approx({"A": 850.0, "B": 0.0})
    assert perf.twr.iloc[0] == 100 and perf.irr > 0
    indexed, same_flows = benchmark(perf, prices["B"])  # konstanter Index: Wert = Nettoeinzahlung
    assert indexed.iloc[-1] == pytest.approx(100)
    assert same_flows == pytest.approx(perf.invested.iloc[-1])


def test_twr_ignores_timing_of_deposits():
    """Steigt der einzige Wert um 10 %, beträgt die zeitgewichtete Rendite 10 % – egal wann nachgekauft wird."""
    idx = pd.bdate_range("2024-01-01", periods=3)
    prices = pd.DataFrame({"A": [100.0, 100.0, 110.0]}, index=idx)
    pf = Portfolio("Test")
    pf.add_transaction(A, BUY, 1, 100.0, date(2024, 1, 1))
    pf.add_transaction(A, BUY, 9, 100.0, date(2024, 1, 2))
    perf = compute(pf, prices)
    assert perf.twr.iloc[-1] == pytest.approx(110.0)
    assert perf.value.iloc[-1] == pytest.approx(1100.0)


def test_performance_skips_undated_transactions():
    pf = Portfolio("Test")
    pf.add(A, 5, 100.0)  # ohne Datum
    assert compute(pf, pd.DataFrame({"A": [1.0]}, index=pd.bdate_range("2024-01-01", periods=1))) is None
    pf.add_transaction(A, BUY, 1, 100.0, date(2024, 1, 1))
    perf = compute(pf, pd.DataFrame({"A": [100.0, 101.0]}, index=pd.bdate_range("2024-01-01", periods=2)))
    assert perf.skipped == 1
