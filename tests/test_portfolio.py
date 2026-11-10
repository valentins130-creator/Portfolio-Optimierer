import numpy as np
import pandas as pd
import pytest

from portfolio_optimizer.market import FUND_COUNTRY, SecurityInfo
from portfolio_optimizer.portfolio import (
    Portfolio,
    PortfolioStore,
    exposures,
    is_concentration_group,
    read_positions_csv,
    valuation,
)

APPLE = SecurityInfo("AAPL", "Apple", "Aktie", "USD", "Technologie", "USA")
SAP = SecurityInfo("SAP.DE", "SAP", "Aktie", "EUR", "Technologie", "Deutschland")
WORLD = SecurityInfo("EUNL.DE", "Welt-ETF", "ETF", "EUR", "Diversifiziert", FUND_COUNTRY,
                     {"Technologie": 0.25, "Finanzen": 0.15, "Gesundheit": 0.10})
BANK = SecurityInfo("BNK.L", "Bank", "Aktie", "GBp", "Finanzen", "Vereinigtes Königreich")


def test_add_merges_positions_with_average_purchase_price():
    pf = Portfolio("Test")
    pf.add(APPLE, 10, 100.0)
    pf.add(APPLE, 30, 140.0)
    assert len(pf.positions) == 1
    assert pf.get("AAPL").shares == 40
    assert pf.get("AAPL").purchase_price == pytest.approx(130.0)
    pf.add(APPLE, 10)  # ohne Kaufkurs ist der Einstand nicht mehr bestimmbar
    assert pf.get("AAPL").purchase_price is None
    with pytest.raises(ValueError):
        pf.add(SAP, 0)
    pf.remove("AAPL")
    assert pf.symbols == []


def test_json_roundtrip():
    pf = Portfolio("Mein Depot")
    pf.add(APPLE, 5, 150.0)
    pf.add(WORLD, 12.5)
    again = Portfolio.from_dict(__import__("json").loads(pf.to_json()))
    assert again.name == "Mein Depot"
    assert again.get("EUNL.DE").info == WORLD
    assert again.get("AAPL").purchase_price == 150.0
    assert again.get("EUNL.DE").purchase_price is None


def test_read_positions_csv_german_and_english():
    german = "Symbol;Name;Stück;Kaufkurs (EUR)\nAAPL;Apple;10;123,45\nsap.de;SAP;2,5;\n;leer;1;1\n"
    assert read_positions_csv(german.encode()) == [("AAPL", 10.0, 123.45), ("SAP.DE", 2.5, None)]
    english = "ticker,shares,price\nMSFT,3,250.5\n"
    assert read_positions_csv(english) == [("MSFT", 3.0, 250.5)]
    assert read_positions_csv(Portfolio("x").to_csv() + ";Kauf;AAPL;Apple;1;2\n") == [("AAPL", 1.0, 2.0)]
    with pytest.raises(ValueError):
        read_positions_csv("Name;Wert\nA;1\n")


def test_store_save_list_load_delete(tmp_path):
    store = PortfolioStore(tmp_path / "pf")
    assert store.names() == []
    pf = Portfolio("Altersvorsorge 2050")
    pf.add(SAP, 3, 180.0)
    store.save(pf)
    store.save(Portfolio("Alpha"))
    assert store.names() == ["Alpha", "Altersvorsorge 2050"]
    assert store.load("Altersvorsorge 2050").get("SAP.DE").shares == 3
    assert store.exists("Alpha")
    store.delete("Alpha")
    assert store.names() == ["Altersvorsorge 2050"]
    (tmp_path / "pf" / "kaputt.json").write_text("{nicht json", encoding="utf-8")
    assert store.names() == ["Altersvorsorge 2050"]


def test_deleted_portfolios_go_to_the_trash_and_can_be_restored(tmp_path):
    store = PortfolioStore(tmp_path / "pf")
    pf = Portfolio("Alpha")
    pf.add(SAP, 3, 180.0)
    store.save(pf)
    store.delete("Alpha")
    assert store.names() == [] and [item.name for item in store.trash()] == ["Alpha"]
    store.save(Portfolio("Alpha"))  # inzwischen gibt es wieder ein „Alpha“
    restored = store.restore(store.trash()[0])
    assert restored.name == "Alpha (2)" and restored.get("SAP.DE").shares == 3
    assert store.names() == ["Alpha", "Alpha (2)"] and store.trash() == []
    store.delete("Alpha")
    old = next(store.trash_folder.glob("*.json"))
    old.rename(old.with_name("alpha--20200101-000000-000000.json"))  # älter als 30 Tage
    assert store.trash() == [] and not any(store.trash_folder.glob("*.json"))


def test_valuation_values_pnl_and_weights():
    pf = Portfolio("Test")
    pf.add(APPLE, 10, 100.0)
    pf.add(SAP, 5)
    pf.add(BANK, 100, 4.0)
    prices = pd.Series({"AAPL": 150.0, "SAP.DE": 200.0})  # BANK ohne Kurs
    val = valuation(pf, prices)
    assert val.loc["AAPL", "value"] == 1500
    assert val.loc["AAPL", "pnl"] == 500
    assert val.loc["AAPL", "pnl_pct"] == pytest.approx(0.5)
    assert np.isnan(val.loc["SAP.DE", "pnl"])
    assert np.isnan(val.loc["BNK.L", "value"])
    assert val["weight"].sum() == pytest.approx(1.0)
    assert val.loc["AAPL", "weight"] == pytest.approx(1500 / 2500)


def test_exposures_look_through_funds():
    infos = {"AAPL": APPLE, "EUNL.DE": WORLD, "BNK.L": BANK}
    weights = pd.Series({"AAPL": 0.2, "EUNL.DE": 0.6, "BNK.L": 0.2})
    sectors = exposures(weights, infos, "sector")
    assert sectors["Technologie"] == pytest.approx(0.2 + 0.6 * 0.5)
    assert sectors["Finanzen"] == pytest.approx(0.2 + 0.6 * 0.3)
    assert sectors.sum() == pytest.approx(1.0)
    countries = exposures(weights, infos, "country")
    assert countries[FUND_COUNTRY] == pytest.approx(0.6)
    currencies = exposures(weights, infos, "currency")
    assert currencies.to_dict() == pytest.approx({"EUR": 0.6, "USD": 0.2, "GBP": 0.2})


def test_concentration_groups():
    assert not is_concentration_group("currency", "EUR")
    assert is_concentration_group("currency", "USD")
    assert not is_concentration_group("country", FUND_COUNTRY)
    assert not is_concentration_group("sector", "Anleihen")
    assert is_concentration_group("sector", "Technologie")
