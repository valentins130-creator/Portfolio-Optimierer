import sys
import types
from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_optimizer import data
from portfolio_optimizer.data import History, split_events
from portfolio_optimizer.price_store import PriceStore


def _history(tickers, index, scale=1.0, missing=()):
    close = pd.DataFrame({t: np.linspace(100, 110, len(index)) * scale for t in tickers}, index=index)
    splits = pd.DataFrame(0.0, index=index, columns=tickers)
    return History(close, close * 0.9, splits, list(missing))


def _yahoo(frames: dict) -> pd.DataFrame:
    return pd.concat(frames, axis=1)


def test_fetch_history_retries_missing_tickers_once(monkeypatch):
    index = pd.bdate_range("2026-01-05", periods=5)
    calls = []

    def download(tickers, **kwargs):
        calls.append((list(tickers), kwargs["threads"], kwargs["auto_adjust"], kwargs["actions"]))
        close = pd.DataFrame({t: 100.0 for t in tickers}, index=index)
        if len(calls) == 1:  # erster Abruf: SAP.DE gedrosselt
            close["SAP.DE"] = np.nan
        splits = pd.DataFrame(0.0, index=index, columns=tickers)
        if "SAP.DE" in tickers:
            splits.loc[index[2], "SAP.DE"] = 2.0
        return _yahoo({"Close": close, "Adj Close": close * 0.9, "Stock Splits": splits})

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=download))
    monkeypatch.setattr(data, "RETRY_DELAY", 0)
    hist = data.fetch_history(["AAPL", "SAP.DE"], date(2026, 1, 5), date(2026, 1, 9))
    assert hist.missing == [] and set(hist.close.columns) == {"AAPL", "SAP.DE"}
    assert calls[0][1:] == (True, False, True)  # ein Abruf: tatsächliche + bereinigte Kurse, Splits
    assert calls[1][:2] == (["SAP.DE"], False)  # zweiter Versuch einzeln, ohne Parallelität
    assert hist.adj_close.at[index[0], "AAPL"] == pytest.approx(90.0)
    assert split_events(hist.splits) == {"SAP.DE": [(index[2].date(), 2.0)]}


def test_price_store_fills_gaps_with_last_saved_prices(tmp_path):
    store = PriceStore(tmp_path)
    index = pd.bdate_range("2026-01-05", periods=10)
    store.complete(_history(["SAP.DE", "EURUSD=X"], index), index[0].date(), index[-1].date())
    later = pd.bdate_range("2026-01-05", periods=12)
    gap = _history(["AAPL"], later, missing=["SAP.DE", "EURUSD=X", "XXX"])
    hist, stale = store.complete(gap, later[0].date(), later[-1].date())
    assert hist.missing == ["XXX"]
    assert stale == {"SAP.DE": index[-1].date(), "EURUSD=X": index[-1].date()}
    assert hist.close["SAP.DE"].dropna().iloc[-1] == pytest.approx(110.0)
    assert (tmp_path / "EURUSD_X.csv").exists()


def test_price_store_rescales_old_history_after_a_split(tmp_path):
    store = PriceStore(tmp_path)
    index = pd.bdate_range("2026-01-05", periods=10)
    store.save(_history(["NVDA"], index[:6]))
    store.save(_history(["NVDA"], index[3:], scale=0.25))  # danach 4:1 gesplittet: Yahoo bereinigt alles
    saved = store.load("NVDA")
    assert len(saved) == 10
    # alte Tage auf die neue Skala gebracht: kein Sprung um Faktor 4 zwischen alten und neuen Werten
    assert saved["close"].iloc[2] / saved["close"].iloc[3] == pytest.approx(
        np.linspace(100, 110, 6)[2] / np.linspace(100, 110, 6)[3], rel=0.05)
