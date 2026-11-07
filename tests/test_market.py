import sys
import types
from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_optimizer import market


def test_currency_helpers():
    assert market.major_currency("GBp") == ("GBP", 100)
    assert market.major_currency("usd") == ("USD", 1.0)
    assert market.guess_currency("SAP.DE") == "EUR"
    assert market.guess_currency("AAPL") == "USD"
    assert market.guess_currency("HSBA.L") == "GBp"
    assert market.guess_currency("BTC-EUR") == "EUR"


def test_sector_and_country_names_are_translated():
    assert market.sector_de("Financial Services") == "Finanzen"
    assert market.sector_de("consumer_cyclical") == "Zyklischer Konsum"
    assert market.sector_de("realestate") == "Immobilien"
    assert market.sector_de(None) == market.UNKNOWN
    assert market.country_de("United States") == "USA"
    assert market.country_de("Atlantis") == "Atlantis"


def test_to_base_currency_handles_fx_and_minor_units():
    index = pd.bdate_range("2024-01-01", periods=3)
    prices = pd.DataFrame({"US": [110.0, 121.0, 132.0], "UK": [1000.0, 1000.0, 1000.0], "DE": [50.0, 51.0, 52.0]},
                          index=index)
    fx = pd.DataFrame({"USD": [1.10, 1.10, 1.20], "GBP": [0.80, 0.80, 0.80]}, index=index)
    eur = market.to_base_currency(prices, {"US": "USD", "UK": "GBp", "DE": "EUR"}, fx)
    np.testing.assert_allclose(eur["US"], [100.0, 110.0, 110.0])
    np.testing.assert_allclose(eur["UK"], 1000 / 100 / 0.80)
    np.testing.assert_allclose(eur["DE"], prices["DE"])


def test_to_base_currency_fills_fx_gaps():
    index = pd.bdate_range("2024-01-01", periods=4)
    prices = pd.DataFrame({"US": [100.0] * 4}, index=index)
    fx = pd.DataFrame({"USD": [2.0, np.nan, 4.0]}, index=index[1:])
    eur = market.to_base_currency(prices, {"US": "USD"}, fx)
    np.testing.assert_allclose(eur["US"], [50.0, 50.0, 50.0, 25.0])


def test_security_info_roundtrip_and_sector_exposure():
    info = market.SecurityInfo("X", "Fonds X", "ETF", sector_weights={"Technologie": 0.3, "Finanzen": 0.1})
    assert info.is_fund
    assert info.sector_exposure() == pytest.approx({"Technologie": 0.75, "Finanzen": 0.25})
    assert market.SecurityInfo.from_dict(info.to_dict()) == info
    stock = market.SecurityInfo("Y", "Aktie Y", sector="Energie")
    assert stock.sector_exposure() == {"Energie": 1.0}


def test_demo_provider_search_info_and_prices():
    provider = market.DemoMarketData(end=date(2025, 6, 30))
    hits = provider.search("technologie")
    assert {"NLS.DEMO", "PCH.DEMO", "LCL.DEMO", "DTEC.DEMO"} <= {h.symbol for h in hits}
    assert provider.search("   ") == []
    info = provider.info("ATI.DEMO")
    assert info.currency == "GBp" and info.country == "Vereinigtes Königreich"
    assert provider.info("DWLD.DEMO").sector_exposure()["Technologie"] == pytest.approx(0.25, abs=0.01)
    with pytest.raises(ValueError):
        provider.info("NOPE")
    prices = provider.prices(["NLS.DEMO", "ATI.DEMO"], date(2024, 1, 1), date(2025, 6, 30))
    assert list(prices.columns) == ["NLS.DEMO", "ATI.DEMO"] and (prices > 0).all().all()
    fx = provider.fx_rates(["USD", "GBP", "EUR"], date(2024, 1, 1), date(2025, 6, 30))
    assert list(fx.columns) == ["GBP", "USD"]
    # Alle Instrumente existieren im Katalog
    assert all(provider.info(i.symbol) for i in provider.instruments)


def test_demo_world_fund_moves_with_dollar():
    provider = market.DemoMarketData(end=date(2025, 6, 30))
    start, end = date(2016, 1, 1), date(2025, 6, 30)
    usd_in_eur = (1 / provider.fx_rates(["USD"], start, end)["USD"]).pct_change().dropna()
    world = provider.prices(["DWLD.DEMO"], start, end)["DWLD.DEMO"].pct_change().dropna()
    assert world.corr(usd_in_eur) > 0.2


@pytest.fixture
def fake_yfinance(monkeypatch):
    class Search:
        def __init__(self, query, **kwargs):
            self.quotes = [
                {"symbol": "AAPL", "longname": "Apple Inc.", "quoteType": "EQUITY", "exchDisp": "NASDAQ"},
                {"symbol": "^GSPC", "shortname": "S&P 500", "quoteType": "INDEX"},
                {"symbol": "EUNL.DE", "shortname": "iShares Core MSCI World", "quoteType": "ETF", "exchange": "GER"},
            ]

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol
            if symbol == "AAPL":
                self.info = {"longName": "Apple Inc.", "quoteType": "EQUITY", "currency": "USD",
                             "sector": "Technology", "country": "United States"}
            elif symbol == "EUNL.DE":
                self.info = {"longName": "iShares Core MSCI World", "quoteType": "ETF", "currency": "EUR"}
                self.funds_data = types.SimpleNamespace(sector_weightings={"technology": 0.26, "healthcare": 0.1})
            else:
                self.info = {"longName": "Euro Bonds", "quoteType": "ETF", "category": "EUR Government Bond"}

                class NoFunds:
                    @property
                    def sector_weightings(self):
                        raise RuntimeError("keine Fondsdaten")

                self.funds_data = NoFunds()

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Search=Search, Ticker=Ticker))


def test_yahoo_search_keeps_holdable_types(fake_yfinance):
    hits = market.YahooMarketData().search("apple")
    assert [h.symbol for h in hits] == ["AAPL", "EUNL.DE"]
    assert hits[0].label == "Apple Inc. · AAPL · NASDAQ · Aktie"


def test_yahoo_info_for_stock_and_funds(fake_yfinance):
    provider = market.YahooMarketData()
    apple = provider.info("AAPL")
    assert (apple.sector, apple.country, apple.currency, apple.quote_type) == ("Technologie", "USA", "USD", "Aktie")
    world = provider.info("EUNL.DE")
    assert world.is_fund and world.country == market.FUND_COUNTRY
    assert world.sector_weights == {"Technologie": 0.26, "Gesundheit": 0.1}
    bonds = provider.info("EUNH.DE")
    assert bonds.sector == "Anleihen" and bonds.sector_weights == {}
    assert bonds.currency == "EUR"  # aus der Börsenendung abgeleitet


def test_price_in_euro_and_fx_ticker():
    assert market.fx_ticker("USD") == "EURUSD=X"
    assert market.price_in_euro(110.0, "USD", {"USD": 1.1}) == pytest.approx(100.0)
    assert market.price_in_euro(1000.0, "GBp", {"GBP": 0.8}) == pytest.approx(12.5)
    assert market.price_in_euro(50.0, "EUR", {}) == 50.0
    assert np.isnan(market.price_in_euro(50.0, "CHF", {}))


def test_yahoo_live_prices_use_last_minute_in_berlin_time(monkeypatch):
    index = pd.date_range("2026-11-06 14:30", periods=3, freq="1min", tz="UTC")
    close = pd.DataFrame({"AAPL": [270.0, 271.0, np.nan], "EURUSD=X": [1.15, 1.16, 1.17]}, index=index)
    calls = {}

    def download(tickers, **kwargs):
        calls.update(kwargs, tickers=tickers)
        return pd.concat({"Close": close}, axis=1)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=download))
    quotes = market.YahooMarketData().live_prices(["AAPL", "EURUSD=X"])
    assert calls["interval"] == "1m" and calls["period"] == "1d"
    assert quotes.loc["AAPL", "price"] == 271.0
    assert quotes.loc["AAPL", "time"] == pd.Timestamp("2026-11-06 15:31")  # 14:31 UTC = 15:31 in Berlin
    assert quotes.loc["EURUSD=X", "price"] == 1.17


def test_demo_has_no_live_prices():
    assert market.DemoMarketData().live_prices(["NLS.DEMO"]).empty
