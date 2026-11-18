"""Import: leere Kurse aus dem Schlusskurs des Tages, Broker-CSV und PDF-Vermögensübersicht im normalen Import."""

import sys
from datetime import date
from types import SimpleNamespace

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
    def __init__(self, text, name="beispiel.csv"):
        self._data = text.encode("utf-8") if isinstance(text, str) else text
        self.name = name

    def getvalue(self):
        return self._data


INFOS = {"SAP.DE": SecurityInfo("SAP.DE", "SAP SE"), "NVDA": SecurityInfo("NVDA", "NVIDIA", currency="USD")}


def _setup(monkeypatch):
    """Import ohne Netz: Stammdaten aus INFOS, eine ISIN findet die Suche (SAP)."""
    saved, messages = {}, []
    monkeypatch.setattr(header, "security_info", lambda provider, symbol: INFOS[symbol])
    monkeypatch.setattr(header, "search", lambda provider, query: [SimpleNamespace(symbol="SAP.DE")]
                        if query == "DE0007164600" else [])
    monkeypatch.setattr(header, "history_eur", lambda *args: _hist())
    monkeypatch.setattr(header, "unique_name", lambda provider, name: name)
    monkeypatch.setattr(header, "set_portfolio", lambda provider, pf: saved.setdefault("pf", pf))
    monkeypatch.setattr(header, "_show_entry", lambda open_: None)
    monkeypatch.setattr(header, "flash", lambda text, kind="success": messages.append((text, kind)))
    return saved, messages


def test_csv_import_fills_empty_prices(monkeypatch):
    saved, messages = _setup(monkeypatch)
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


def test_broker_csv_runs_through_the_normal_import(monkeypatch):
    saved, messages = _setup(monkeypatch)
    csv = ("datetime,type,symbol,shares,amount,name,asset_class\n"
           "2024-06-12T09:30:00Z,BUY,DE0007164600,5,-850,SAP,STOCK\n"
           "2024-06-13T09:30:00Z,BUY,DE0007164600,1,,SAP,STOCK\n"
           "2024-06-14T09:30:00Z,DIVIDEND,DE0007164600,6,12,SAP,STOCK\n"
           "2024-06-14T09:30:00Z,SPLIT,DE0007164600,2,,SAP,STOCK\n")
    monkeypatch.setitem(st.session_state, "pf_upload", _Upload(csv, "export.csv"))
    header.import_upload("yahoo")
    trades = [(t.symbol, t.date, t.shares, t.price) for t in saved["pf"].transactions]
    assert trades == [("SAP.DE", date(2024, 6, 12), 5, pytest.approx(170.0)),  # Betrag / Stück
                      ("SAP.DE", date(2024, 6, 13), 1, pytest.approx(180.0))]  # Schlusskurs des Tages
    text, kind = messages[-1]
    assert kind == "success" and "1 Buchung" in text  # die Kapitalmaßnahme bleibt zur Prüfung


def _fake_pdf(text):
    page = SimpleNamespace(extract_text=lambda: text)

    class Doc:
        pages = [page]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return SimpleNamespace(open=lambda _: Doc())


def test_pdf_statement_runs_through_the_normal_import(monkeypatch):
    saved, messages = _setup(monkeypatch)
    sample = ("VERMÖGENSÜBERSICHT\nzum 14.06.2024\nGESAMT 1.050,00 EUR\nBROKERAGE\n"
              "5 Stk. SAP SE 180,00 900,00\nISIN: DE0007164600\nCASH\nCashkonto 150,00 EUR\n")
    monkeypatch.setitem(sys.modules, "pdfplumber", _fake_pdf(sample))
    monkeypatch.setitem(st.session_state, "pf_upload", _Upload(b"%PDF-1.7 test", "Vermoegen.pdf"))
    header.import_upload("yahoo")
    [trade] = saved["pf"].transactions
    assert (trade.symbol, trade.date, trade.shares, trade.price) == ("SAP.DE", date(2024, 6, 14), 5, 180.0)
    assert "Bargeld wird nicht übernommen" in messages[-1][0]


def test_pdf_import_without_pdfplumber_explains_what_is_missing(monkeypatch):
    saved, messages = _setup(monkeypatch)
    monkeypatch.setitem(sys.modules, "pdfplumber", None)  # wie „No module named pdfplumber“
    monkeypatch.setitem(st.session_state, "pf_upload", _Upload(b"%PDF-1.7 test", "Vermoegen.pdf"))
    header.import_upload("yahoo")
    assert "pf" not in saved
    text, kind = messages[-1]
    assert kind == "error" and "pdfplumber" in text and "requirements.txt" in text
