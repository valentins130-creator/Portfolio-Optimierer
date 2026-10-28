import sys
import types
from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_optimizer import data


def test_parse_tickers():
    assert data.parse_tickers(" aapl, msft;SAP.de  aapl\nEUNL.DE ") == ["AAPL", "MSFT", "SAP.DE", "EUNL.DE"]
    assert data.parse_tickers("") == []


def _yahoo_frame(tickers, layout="column"):
    index = pd.date_range("2024-01-01", periods=5, freq="B", tz="America/New_York")
    fields = ["Close", "High", "Low", "Open", "Volume"]
    if layout == "column":
        columns = pd.MultiIndex.from_product([fields, tickers], names=["Price", "Ticker"])
    else:
        columns = pd.MultiIndex.from_product([tickers, fields], names=["Ticker", "Price"])
    values = np.arange(len(index) * len(columns), dtype=float).reshape(len(index), -1) + 1
    return pd.DataFrame(values, index=index, columns=columns)


@pytest.mark.parametrize("layout", ["column", "ticker"])
def test_extract_close_handles_multiindex_layouts(layout):
    raw = _yahoo_frame(["SPY", "AGG"], layout)
    close = data._extract_close(raw, ["SPY", "AGG"])
    assert list(close.columns) == ["SPY", "AGG"]
    assert close.index.tz is None
    expected = raw["Close"] if layout == "column" else raw.xs("Close", axis=1, level=1)
    np.testing.assert_allclose(close.to_numpy(), expected.to_numpy())


def test_extract_close_single_level_columns():
    raw = pd.DataFrame({"Close": [1.0, 2.0], "Open": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))
    close = data._extract_close(raw, ["SAP.DE"])
    assert list(close.columns) == ["SAP.DE"]


def test_fetch_prices_reports_missing_tickers(monkeypatch):
    raw = _yahoo_frame(["SPY", "XXXX"])
    raw.loc[:, ("Close", "XXXX")] = np.nan
    calls = {}

    def fake_download(tickers, **kwargs):
        calls.update(kwargs, tickers=tickers)
        return raw

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=fake_download))
    prices, missing = data.fetch_prices(["SPY", "XXXX"], date(2024, 1, 1), date(2024, 1, 31))
    assert list(prices.columns) == ["SPY"]
    assert missing == ["XXXX"]
    assert calls["auto_adjust"] is True
    assert calls["end"] == pd.Timestamp("2024-02-01")  # Enddatum inklusive


def test_load_csv_german_format():
    content = "Datum;Aktie A;Aktie B\n02.01.2024;1.101,20;55,10\n03.01.2024;1.102,05;54,80\n".encode()
    prices = data.load_prices_csv(content)
    assert list(prices.columns) == ["Aktie A", "Aktie B"]
    assert prices.index[0] == pd.Timestamp("2024-01-02")
    assert prices.iloc[0, 0] == pytest.approx(1101.20)
    assert prices.iloc[1, 1] == pytest.approx(54.80)


def test_load_csv_english_format():
    content = b"Date,SPY,AGG\n2024-01-02,470.5,98.1\n2024-01-03,468.2,98.3\n"
    prices = data.load_prices_csv(content)
    assert prices.index[1] == pd.Timestamp("2024-01-03")
    assert prices.loc["2024-01-02", "SPY"] == pytest.approx(470.5)


def test_load_csv_rejects_bad_files():
    with pytest.raises(data.DataError):
        data.load_prices_csv(b"nur eine Spalte\n1\n2\n")
    with pytest.raises(data.DataError):
        data.load_prices_csv(b"Datum,A\nkein Datum,1\nauch nicht,2\n")


def test_clean_prices_fills_short_gaps_and_aligns():
    index = pd.bdate_range("2024-01-01", periods=100)
    prices = pd.DataFrame({"A": np.linspace(100, 110, 100), "B": np.linspace(50, 55, 100)}, index=index)
    prices.iloc[10:12, 0] = np.nan  # Feiertag an einer Börse
    prices.iloc[:5, 1] = np.nan  # B startet später
    clean = data.clean_prices(prices.iloc[::-1])
    assert clean.index.is_monotonic_increasing
    assert clean.index[0] == index[5]
    assert clean.notna().all().all()
    assert clean.loc[index[10], "A"] == prices.loc[index[9], "A"]


def test_clean_prices_validation():
    index = pd.bdate_range("2024-01-01", periods=30)
    with pytest.raises(data.DataError):
        data.clean_prices(pd.DataFrame({"A": np.ones(30)}, index=index))
    index = pd.bdate_range("2024-01-01", periods=100)
    with pytest.raises(data.DataError):
        data.clean_prices(pd.DataFrame({"A": np.zeros(100)}, index=index))
    wide = pd.DataFrame(np.ones((100, data.MAX_ASSETS + 1)), index=index)
    with pytest.raises(data.DataError):
        data.clean_prices(wide)
    empty = pd.DataFrame({"A": np.full(100, np.nan)}, index=index)
    with pytest.raises(data.DataError, match="keine Kursspalten"):
        data.clean_prices(empty)


def test_clean_prices_drops_text_columns():
    content = "Datum;Fonds;Kommentar\n" + "".join(
        f"{d:%d.%m.%Y};{100 + i},5;ok\n" for i, d in enumerate(pd.bdate_range("2024-01-01", periods=80))
    )
    clean = data.clean_prices(data.load_prices_csv(content.encode()))
    assert list(clean.columns) == ["Fonds"]
    assert len(clean) == 80


def test_synthetic_prices_are_reproducible():
    a = data.synthetic_prices(years=2, seed=1)
    b = data.synthetic_prices(years=2, seed=1)
    pd.testing.assert_frame_equal(a, b)
    assert a.shape == (2 * 252 + 1, len(data.DEMO_ASSETS))
    assert (a > 0).all().all()
    np.testing.assert_allclose(a.iloc[0], 100)


def test_simple_returns_and_drawdown():
    prices = pd.DataFrame({"A": [100.0, 110.0, 99.0, 120.0]})
    r = data.simple_returns(prices)
    np.testing.assert_allclose(r["A"], [0.1, -0.1, 120 / 99 - 1])
    assert data.max_drawdown(prices)["A"] == pytest.approx(0.1)
