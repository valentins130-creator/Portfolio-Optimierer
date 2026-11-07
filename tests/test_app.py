"""Rauchtests der Streamlit-Oberfläche mit ``streamlit.testing``.

Die App hat drei Ebenen (Portfolio, Analysen, Lösungen) mit aufklappbaren Abschnitten,
die erst rechnen, wenn sie geöffnet sind. Die Tests öffnen sie über ihre Schlüssel.
"""

import json
import sys
import types
import zlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from portfolio_optimizer.formatting import num

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PAGES = {
    "portfolio": ("views/portfolio.py", ("sec_add", "sec_positions", "sec_transactions", "sec_performance",
                                         "sec_market", "sec_allocation")),
    "analysen": ("views/analysen.py", ("sec_cluster", "sec_frontier", "sec_mc", "sec_error")),
    "loesungen": ("views/loesungen.py", ("sec_rebalance", "sec_hedge")),
}


def _assert_clean(at):
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _open(at, page, sections=None):
    """Seite wählen und ihre Abschnitte aufklappen."""
    path, keys = PAGES[page]
    at.switch_page(path)
    for key in keys if sections is None else sections:
        at.session_state[key] = True
    return at.run()


def _saved(tmp_path, name="mein-depot", provider="demo"):
    folder = tmp_path / "demo" if provider == "demo" else tmp_path
    return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    """App mit der Offline-Demo; Portfolios landen in einem temporären Ordner."""
    monkeypatch.setenv("PORTFOLIO_DIR", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=240)
    at.session_state["set_provider"] = "demo"
    return at.run()


@pytest.fixture
def example_app(demo_app):
    _button(demo_app, "Beispieldepot laden").click().run()
    _assert_clean(demo_app)
    return demo_app


# ---------------------------------------------------------------------------
# Ebene 1: Portfolio
# ---------------------------------------------------------------------------


def test_empty_portfolio_shows_onboarding_on_every_level(demo_app):
    at = demo_app
    _assert_clean(at)
    assert any("Das Portfolio ist noch leer" in i.value for i in at.info)
    assert [e.label for e in at.expander] == ["Transaktion erfassen"]
    for page in ("analysen", "loesungen"):
        _open(at, page)
        _assert_clean(at)
        assert any("Lege sie unter **Portfolio** an" in i.value for i in at.info)


def test_record_buy_and_sell_with_dates(demo_app, tmp_path):
    at = demo_app
    bought = date.today() - timedelta(days=400)
    at.text_input(key="tx_query").set_value("Nordlicht").run()
    at.date_input(key="tx_date").set_value(bought)
    at.number_input(key="tx_shares").set_value(12.0)
    at.number_input(key="tx_price").set_value(100.0)
    _button(at, "Erfassen").click().run()
    _assert_clean(at)
    tx = _saved(tmp_path)["transactions"]
    assert [(t["symbol"], t["kind"], t["shares"], t["price"], t["date"]) for t in tx] == [
        ("NLS.DEMO", "Kauf", 12.0, 100.0, bought.isoformat())]
    assert at.session_state["tx_query"] == ""  # Suche geleert, Auswahl wechselt auf „Aus dem Depot“
    assert at.segmented_control(key="tx_mode").value == "Aus dem Depot"

    # Verkauf über den Bestand hinaus wird abgelehnt
    at.segmented_control(key="tx_kind").set_value("Verkauf")
    at.date_input(key="tx_date").set_value(date.today() - timedelta(days=100))
    at.number_input(key="tx_shares").set_value(20.0)
    at.number_input(key="tx_price").set_value(150.0)
    _button(at, "Erfassen").click().run()
    assert any("übersteigt den Bestand" in t.value for t in at.toast)
    assert len(_saved(tmp_path)["transactions"]) == 1

    at.number_input(key="tx_shares").set_value(2.0)
    _button(at, "Erfassen").click().run()
    _assert_clean(at)
    assert len(_saved(tmp_path)["transactions"]) == 2
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Realisierte Gewinne"] == "100 €"  # 2 Stück × (150 − 100) €


def test_example_portfolio_level_portfolio(example_app):
    at = _open(example_app, "portfolio")
    _assert_clean(at)
    assert [e.label for e in at.expander][:3] == ["Transaktion erfassen", "Positionen", "Transaktionen"]
    labels = {m.label for m in at.metric}
    assert {"Depotwert", "Persönliche Rendite p. a.", "Zeitgewichtete Rendite p. a.", "Eingezahlt (netto)"} <= labels
    assert any(m.value == "**Vergleich mit einem Index**" for m in at.markdown)
    positions = next(d.value for d in at.dataframe if "Stand" in d.value.columns)
    assert positions["Stand"].str.startswith("Schluss").all()  # die Demo hat keine Live-Kurse


def test_example_portfolio_level_analyses(example_app):
    at = _open(example_app, "analysen")
    _assert_clean(at)
    assert any("Sektor Technologie" in m.value for m in at.markdown)
    labels = {m.label for m in at.metric}
    assert {"Effektive Anzahl Positionen", "Sharpe-Ratio", "Median-Endvermögen"} <= labels
    # Voreingestellt ist das effiziente Portfolio mit dem Risiko des eigenen Depots
    vol = next(m for m in at.metric if m.label == "Volatilität p. a.")
    assert vol.delta.startswith("±")
    assert any("**Zusammensetzung der effizienten Portfolios je Risikoniveau**" == m.value for m in at.markdown)


def test_example_portfolio_level_solutions(example_app):
    at = _open(example_app, "loesungen")
    _assert_clean(at)
    assert any("innerhalb der Grenzen" in s.value for s in at.success)
    assert [t.label for t in at.tabs] == ["Markt-Hedge (Beta)", "Beimischung", "Klumpenrisiko absichern"]
    assert any(m.value.startswith("Am besten erklärt") for m in at.markdown)
    assert any(m.value.startswith("**Absichern:**") for m in at.markdown)


def test_open_sections_survive_page_changes(example_app):
    at = _open(example_app, "analysen", sections=["sec_frontier"])
    assert any(s.label == "Zielrisiko (Volatilität)" for s in at.select_slider)
    _open(at, "loesungen", sections=[])
    _open(at, "analysen", sections=[])
    _assert_clean(at)
    assert any(s.label == "Zielrisiko (Volatilität)" for s in at.select_slider)


def test_target_risk_follows_the_selected_portfolio(example_app):
    at = _open(example_app, "analysen", sections=["sec_frontier"])
    slider = next(s for s in at.select_slider if s.label == "Zielrisiko (Volatilität)")
    slider.set_value(round(at.session_state["frontier_target_widget"] + 0.05, 3)).run()  # mehr Risiko
    assert not next(m for m in at.metric if m.label == "Volatilität p. a.").delta.startswith("±")
    _button(at, "Beispieldepot laden").click().run()  # anderes Portfolio: Zielrisiko = Depotrisiko
    _assert_clean(at)
    assert next(m for m in at.metric if m.label == "Volatilität p. a.").delta.startswith("±")


def test_estimation_error_experiment(example_app):
    at = _open(example_app, "analysen", sections=["sec_error"])
    next(s for s in at.select_slider if s.label == "Anzahl Durchläufe").set_value(50)
    _button(at, "Experiment starten").click().run()
    _assert_clean(at)
    assert any("Ergebnis aus 50 simulierten Historien" in m.value for m in at.markdown)


def test_unconstrained_markowitz_with_short_selling(example_app):
    at = example_app
    at.session_state["set_short"] = True
    at.session_state["set_unbounded"] = True
    _open(at, "analysen")
    _assert_clean(at)
    _open(at, "loesungen", sections=[])
    at.radio(key="rb_goal").set_value("same_risk").run()
    assert any("Leerverkäufe" in w.value for w in at.warning)


def test_infeasible_weight_cap_falls_back_with_warning(example_app):
    at = example_app
    at.session_state["set_hi"] = 5  # 10 Positionen × 5 % < 100 %
    _open(at, "analysen")
    _assert_clean(at)
    assert any("vorerst" in w.value for w in at.warning)


def test_create_and_delete_portfolio(demo_app, tmp_path):
    at = demo_app
    at.text_input(key="pf_new_name").set_value("Sparplan")
    _button(at, "Anlegen").click().run()
    assert at.selectbox(key="pf_select_demo").value == "Sparplan"
    assert (tmp_path / "demo" / "sparplan.json").exists()
    _button(at, "Ja, löschen").click().run()
    _assert_clean(at)
    assert not (tmp_path / "demo" / "sparplan.json").exists()


# ---------------------------------------------------------------------------
# Yahoo-Pfad mit nachgebildetem yfinance (kein Netzwerk in Tests)
# ---------------------------------------------------------------------------

YAHOO = {
    "AAPL": {"longName": "Apple Inc.", "quoteType": "EQUITY", "currency": "USD", "sector": "Technology",
             "country": "United States"},
    "SAP.DE": {"longName": "SAP SE", "quoteType": "EQUITY", "currency": "EUR", "sector": "Technology",
               "country": "Germany"},
}


def _series(ticker: str, n: int) -> np.ndarray:
    rng = np.random.default_rng(zlib.crc32(ticker.encode()))
    level = 1.1 if ticker.endswith("=X") else 100.0
    return level * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))


@pytest.fixture
def fake_yfinance(monkeypatch):
    class Search:
        def __init__(self, query, **kwargs):
            hits = [s for s, i in YAHOO.items() if query.lower() in i["longName"].lower()]
            self.quotes = [{"symbol": s, "longname": YAHOO[s]["longName"], "quoteType": YAHOO[s]["quoteType"],
                            "exchDisp": "Test"} for s in hits]

    class Ticker:
        def __init__(self, symbol):
            self.info = YAHOO.get(symbol, {"quoteType": "ETF", "longName": symbol})
            self.funds_data = types.SimpleNamespace(sector_weightings={})

    def download(tickers, start=None, end=None, interval="1d", auto_adjust=False, **kwargs):
        tickers = [tickers] if isinstance(tickers, str) else list(tickers)
        if interval == "1m":  # Live-Kurse: letzte Handelsminuten von heute (UTC)
            index = pd.date_range(pd.Timestamp(date.today()) + pd.Timedelta(hours=9), periods=30, freq="min",
                                  tz="UTC")
        else:
            index = pd.bdate_range(start, pd.Timestamp(end) - pd.Timedelta(days=1))
        # Dividendenbereinigte Kurse liegen in der Vergangenheit unter den tatsächlichen
        scale = {t: 0.8 if auto_adjust and not t.endswith("=X") else 1.0 for t in tickers}
        close = pd.DataFrame({t: _series(t, len(index)) * scale[t] for t in tickers}, index=index)
        return pd.concat({"Close": close}, axis=1)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Search=Search, Ticker=Ticker,
                                                                       download=download))


def test_yahoo_portfolio_uses_live_prices(fake_yfinance, tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DIR", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=240)
    at.session_state["set_provider"] = "yahoo"
    at.run()
    for i, (query, shares) in enumerate([("Apple", 10.0), ("SAP", 20.0)]):
        if i:
            at.segmented_control(key="tx_mode").set_value("Suchen").run()
        at.text_input(key="tx_query").set_value(query).run()
        at.date_input(key="tx_date").set_value(date.today() - timedelta(days=500))
        at.number_input(key="tx_shares").set_value(shares)
        at.number_input(key="tx_price").set_value(100.0)
        _button(at, "Erfassen").click().run()
        _assert_clean(at)
    assert [t["symbol"] for t in _saved(tmp_path, provider="yahoo")["transactions"]] == ["AAPL", "SAP.DE"]
    positions = next(d.value for d in at.dataframe if "Stand" in d.value.columns)
    assert positions["Stand"].str.startswith("live").all()
    for page in ("analysen", "loesungen"):
        _open(at, page)
        _assert_clean(at)


def test_yahoo_suggests_actual_close_not_dividend_adjusted(fake_yfinance, tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DIR", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=240)
    at.session_state["set_provider"] = "yahoo"
    at.run()
    when = date.today() - timedelta(days=500)
    at.text_input(key="tx_query").set_value("SAP").run()
    at.date_input(key="tx_date").set_value(when).run()
    _assert_clean(at)
    index = pd.bdate_range(pd.Timestamp(when) - pd.Timedelta(days=10), pd.Timestamp(when))
    expected = f"Schlusskurs am {index[-1]:%d.%m.%Y}: {num(_series('SAP.DE', len(index))[-1], 2)} €"
    assert any(expected in c.value for c in at.caption), [c.value for c in at.caption]
