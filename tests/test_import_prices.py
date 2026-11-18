"""CSV-Import: leere Kurse werden mit dem Schlusskurs des Tages gefüllt."""

from datetime import date

import pandas as pd
import pytest
import streamlit as st

from portfolio_optimizer.market import SecurityInfo
from ui import header
from ui.state import HistoryEUR, close_from


def _hist():
    index = pd.bdate_range("2024-06-03", "2024-06-14")
    close = pd.DataFrame({"NVDA": [100.0 + i for i in range(len(index))], "SAP.DE": 180.0}, index=index)
    splits = {"NVDA": [(date(2024, 6, 10), 10.0)]}  # 10:1 ab dem 10.06.
    return HistoryEUR(close, close, splits, [], {})


def test_close_from_uses_the_day_or_the_last_trading_day_before_in_old_units():
    hist = _hist()
    assert close_from(hist, "SAP.DE", date(2024, 6, 12)) == (180.0, date(2024, 6, 12))
    price, day = close_from(hist, "SAP.DE", date(2024, 6, 9))  # Sonntag: Freitag davor
    assert day == date(2024, 6, 7)
    price, day = close_from(hist, "NVDA", date(2024, 6, 4))  # vor dem Split: damalige Stückelung
    assert price == pytest.approx(101.0 * 10)
    assert close_from(hist, "NVDA", date(2024, 6, 11))[0] == pytest.approx(106.0)
    assert close_from(hist, "NVDA", date(2024, 5, 1)) is None  # keine Kurse rund um das Datum
    assert close_from(hist, "XXX", date(2024, 6, 12)) is None


class _Upload:
    name = "beispiel.csv"

    def __init__(self, text):
        self._data = text.encode("utf-8")

    def getvalue(self):
        return self._data


def test_csv_import_fills_empty_prices(monkeypatch):
    saved, messages = {}, []
    infos = {"SAP.DE": SecurityInfo("SAP.DE", "SAP SE"), "NVDA": SecurityInfo("NVDA", "NVIDIA", currency="USD")}
    monkeypatch.setattr(header, "security_info", lambda provider, symbol: infos[symbol])
    monkeypatch.setattr(header, "history_eur", lambda *args: _hist())
    monkeypatch.setattr(header, "unique_name", lambda provider, name: name)
    monkeypatch.setattr(header, "set_portfolio", lambda provider, pf: saved.setdefault("pf", pf))
    monkeypatch.setattr(header, "_show_entry", lambda open_: None)
    monkeypatch.setattr(header, "flash", lambda text, kind="success": messages.append((text, kind)))
    csv = ("Datum;Typ;Symbol;Stück;Kurs\n"
           "04.06.2024;Kauf;NVDA;2;\n"          # vor dem Split, Kurs leer
           "12.06.2024;Kauf;SAP.DE;5;170,00\n"  # eigener Kurs bleibt
           "13.06.2024;Kauf;SAP.DE;1;\n")
    monkeypatch.setitem(st.session_state, "pf_upload", _Upload(csv))
    header.import_upload("yahoo")
    prices = {(t.symbol, t.date): t.price for t in saved["pf"].transactions}
    assert prices[("NVDA", date(2024, 6, 4))] == pytest.approx(1010.0)
    assert prices[("SAP.DE", date(2024, 6, 12))] == pytest.approx(170.0)
    assert prices[("SAP.DE", date(2024, 6, 13))] == pytest.approx(180.0)
    assert "Bei 2 Transaktionen ohne Kurs gilt der Schlusskurs des Tages." in messages[-1][0]
