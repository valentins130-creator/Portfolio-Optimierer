"""Sparpläne: Termine, Ausführungen zum Schlusskurs, Ende, Löschen, Speichern."""

from datetime import date

import pandas as pd
import pytest

from portfolio_optimizer.market import FUND_COUNTRY, SecurityInfo
from portfolio_optimizer.portfolio import BUY, SELL, Portfolio, add_months

WORLD = SecurityInfo("EUNL.DE", "Welt-ETF", "ETF", "EUR", "Diversifiziert", FUND_COUNTRY)


def closes(start: str, end: str, price: float = 100.0, step: float = 0.0) -> pd.Series:
    """Schlusskurse an Werktagen (Mo–Fr), auf Wunsch steigend."""
    days = pd.bdate_range(start, end)
    return pd.Series([price + step * i for i in range(len(days))], index=days)


def test_add_months_keeps_the_day_or_takes_the_month_end():
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2024, 1, 31), 3) == date(2024, 4, 30)
    assert add_months(date(2024, 11, 15), 2) == date(2025, 1, 15)


def test_due_dates_follow_the_start_day_and_stop_at_the_end():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 1, 31), months=1, end=date(2024, 4, 30))
    assert plan.due_dates(date(2025, 1, 1)) == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31),
                                                date(2024, 4, 30)]
    quarterly = pf.add_plan(WORLD, 50, date(2024, 2, 15), months=3)
    assert quarterly.due_dates(date(2024, 12, 31)) == [date(2024, 2, 15), date(2024, 5, 15), date(2024, 8, 15),
                                                       date(2024, 11, 15)]
    assert quarterly.label == "50 € vierteljährlich" and plan.label == "100 € monatlich"


def test_executions_buy_for_the_rate_on_the_due_date_or_the_next_trading_day():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 3, 2))  # Samstag
    px = closes("2024-02-26", "2024-06-28", price=50.0, step=0.1)
    assert pf.run_plan(plan, px, today=date(2024, 6, 28)) == 4
    runs = sorted(pf.executions(plan.id), key=lambda t: t.date)
    assert [t.date for t in runs] == [date(2024, 3, 4), date(2024, 4, 2), date(2024, 5, 2), date(2024, 6, 3)]
    first = runs[0]
    assert first.kind == BUY and first.price == pytest.approx(float(px[pd.Timestamp("2024-03-04")]))
    assert first.amount == pytest.approx(100, abs=0.01)
    assert pf.get("EUNL.DE").shares == pytest.approx(sum(100 / t.price for t in runs), rel=1e-5)


def test_running_again_adds_only_new_dates_and_respects_deleted_executions():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 1, 10))
    px = closes("2024-01-01", "2024-12-31")
    assert pf.run_plan(plan, px, today=date(2024, 3, 20)) == 3
    assert pf.run_plan(plan, px, today=date(2024, 3, 20)) == 0
    pf.remove_transaction(pf.transactions.index(pf.executions(plan.id)[1]))  # eine Ausführung von Hand gelöscht
    assert pf.run_plan(plan, px, today=date(2024, 5, 20)) == 2  # April und Mai, der Februar kommt nicht wieder
    assert len(pf.executions(plan.id)) == 4


def test_without_a_close_yet_the_run_waits_and_continues_later():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 5, 15))
    assert pf.run_plan(plan, closes("2024-05-01", "2024-06-14"), today=date(2024, 6, 15)) == 1  # 15.06. ohne Kurs
    assert pf.run_plan(plan, closes("2024-05-01", "2024-06-21"), today=date(2024, 6, 21)) == 1


def test_a_long_gap_before_the_first_price_skips_the_date():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 1, 5))
    assert pf.run_plan(plan, closes("2024-03-01", "2024-04-30"), today=date(2024, 4, 30)) == 2  # März, April
    assert [t.date.month for t in pf.executions(plan.id)] == [3, 4]


def test_executions_before_a_split_use_the_old_unit_like_the_statement():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 1, 2))
    px = closes("2024-01-01", "2024-02-29", price=25.0)  # splitbereinigt: vorher 100 € je alte Aktie
    splits = [(date(2024, 2, 15), 4.0)]
    pf.run_plan(plan, px, splits, today=date(2024, 2, 29))
    january, february = sorted(pf.executions(plan.id), key=lambda t: t.date)
    for run in (january, february):  # beide vor dem Split: 1 alte Aktie zu 100 €
        assert run.price == pytest.approx(100.0) and run.shares == pytest.approx(1.0)
    pf.splits = {"EUNL.DE": splits}
    assert pf.get("EUNL.DE").shares == pytest.approx(8.0)  # nach dem Split 4 neue je alte


def test_end_plan_removes_later_executions_and_stops():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 1, 10))
    px = closes("2024-01-01", "2024-12-31")
    pf.run_plan(plan, px, today=date(2024, 6, 30))
    assert pf.end_plan(plan.id, date(2024, 3, 31)) == 3
    assert len(pf.executions(plan.id)) == 3 and not plan.running(date(2024, 6, 30))
    assert pf.run_plan(plan, px, today=date(2024, 12, 31)) == 0


def test_end_plan_refuses_when_a_sale_would_exceed_the_holding():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 1, 10))
    pf.run_plan(plan, closes("2024-01-01", "2024-12-31"), today=date(2024, 6, 30))
    pf.add_transaction(WORLD, SELL, 5.5, 100.0, date(2024, 6, 28))
    with pytest.raises(ValueError, match="übersteigt den Bestand"):
        pf.end_plan(plan.id, date(2024, 2, 28))
    assert len(pf.executions(plan.id)) == 6 and plan.end is None


def test_delete_plan_keeps_or_removes_the_executions():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 100, date(2024, 1, 10))
    pf.run_plan(plan, closes("2024-01-01", "2024-12-31"), today=date(2024, 3, 31))
    assert pf.delete_plan(plan.id, keep_executions=True) == 0
    assert not pf.plans and len(pf.transactions) == 3 and all(t.plan is None for t in pf.transactions)

    other = pf.add_plan(WORLD, 50, date(2024, 4, 10))
    pf.run_plan(other, closes("2024-01-01", "2024-12-31"), today=date(2024, 5, 31))
    assert pf.delete_plan(other.id, keep_executions=False) == 2
    assert len(pf.transactions) == 3 and "EUNL.DE" in pf.securities


def test_a_plan_without_executions_keeps_its_security():
    pf = Portfolio("Test")
    pf.add_plan(WORLD, 100, date(2030, 1, 1))  # beginnt erst später
    assert "EUNL.DE" in pf.securities and pf.positions == []
    pf.delete_plan(pf.plans[0].id)
    assert "EUNL.DE" not in pf.securities


def test_plans_survive_saving_and_loading():
    pf = Portfolio("Test")
    plan = pf.add_plan(WORLD, 75.5, date(2024, 1, 10), months=3, end=date(2025, 1, 10))
    pf.run_plan(plan, closes("2024-01-01", "2024-12-31"), today=date(2024, 12, 31))
    loaded = Portfolio.from_dict(pf.to_dict())
    assert loaded.plans == pf.plans
    assert [t.plan for t in loaded.transactions] == [plan.id] * 4
    assert loaded.plans[0].label == "75,50 € vierteljährlich"


def test_invalid_plans_are_rejected():
    pf = Portfolio("Test")
    with pytest.raises(ValueError, match="Sparrate"):
        pf.add_plan(WORLD, 0, date(2024, 1, 1))
    with pytest.raises(ValueError, match="Ende"):
        pf.add_plan(WORLD, 100, date(2024, 5, 1), end=date(2024, 4, 1))
    assert not pf.plans and not pf.securities
