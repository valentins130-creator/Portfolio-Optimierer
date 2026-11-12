"""Rauchtests der Streamlit-Oberfläche mit ``streamlit.testing``.

Die App öffnet mit der Startseite; dahinter liegen drei Ebenen (Portfolio, Analysen, Lösungen)
mit aufklappbaren Abschnitten, die erst rechnen, wenn sie geöffnet sind. Die Tests öffnen sie
über ihre Schlüssel.
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
    "start": ("views/start.py", ()),
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


def _hero(at) -> str:
    """HTML der Depotwert-Zeile oben auf der Portfolio-Seite."""
    return next((e.proto.body for e in at.html if "po-hero" in e.proto.body and "<style>" not in e.proto.body), "")


def _start_card(at) -> str:
    """HTML der Karte „Klumpenrisiko“ auf der Startseite (Kennzahlen, Balken, Vorschlag)."""
    return "".join(b for b in (e.proto.body for e in at.html)
                   if ("po-stats" in b or "po-xray" in b) and "<style>" not in b)


def _app(tmp_path, monkeypatch, provider: str, page: str = "portfolio") -> AppTest:
    """App mit Portfolios in einem temporären Ordner, geöffnet auf der gewünschten Seite."""
    monkeypatch.setenv("PORTFOLIO_DIR", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=240)
    at.session_state["set_provider"] = provider
    if page != "start":  # die Startseite ist die Standardseite
        at.switch_page(PAGES[page][0])
    return at.run()


def _saved(tmp_path, name="mein-depot", provider="demo"):
    folder = tmp_path / "demo" if provider == "demo" else tmp_path
    return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    """App mit der Offline-Demo auf der Ebene Portfolio; Portfolios landen in einem temporären Ordner."""
    return _app(tmp_path, monkeypatch, "demo")


@pytest.fixture
def example_app(demo_app):
    _button(demo_app, "Beispieldepot laden").click().run()
    _assert_clean(demo_app)
    return demo_app


# ---------------------------------------------------------------------------
# Startseite
# ---------------------------------------------------------------------------


def test_start_page_opens_first_and_shows_the_example_while_the_depot_is_empty(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch, "demo", page="start")
    _assert_clean(at)
    assert any("Sieh, wo dein Depot wirklich Risiko trägt." in e.proto.body for e in at.html)
    card = _start_card(at)
    assert "Beispieldepot" in card and "Dein Depot ist noch leer." in card
    assert "<dt>Grenzen überschritten</dt><dd>4</dd>" in card  # Technologie und drei Einzelwerte
    assert {"Depot erfassen", "Beispieldepot laden"} <= {b.label for b in at.button}
    at.segmented_control(key="start_view").set_value("Nach Umschichtung").run()
    _assert_clean(at)
    card = _start_card(at)
    assert "<dt>Grenzen überschritten</dt><dd>0</dd>" in card
    assert "Danach hält das Depot alle Grenzen ein." in card


def test_start_page_analyses_the_own_depot_and_leads_to_the_analysis(example_app):
    at = _open(example_app, "start")
    _assert_clean(at)
    card = _start_card(at)
    assert "noch leer" not in card and "fiktive Werte" not in card and "10 Positionen" in card
    _button(at, "Depot prüfen").click().run()
    _assert_clean(at)
    assert at.session_state["sec_cluster"] is True
    assert any(":red-badge[Sektor] **Technologie**" in m.value for m in at.markdown)


def test_offline_demo_can_be_tried_from_the_start_page(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch, "yahoo", page="start")
    _button(at, "Offline-Demo ausprobieren").click().run()
    _assert_clean(at)
    assert at.session_state["set_provider"] == "demo"
    at = _open(at, "analysen")
    _assert_clean(at)
    assert at.session_state["set_provider"] == "demo"  # bleibt beim Seitenwechsel
    assert any(":red-badge[Sektor] **Technologie**" in m.value for m in at.markdown)


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
    at.date_input(key="tx_date").set_value(bought).run()
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
    at.date_input(key="tx_date").set_value(date.today() - timedelta(days=100)).run()
    at.number_input(key="tx_shares").set_value(20.0)
    at.number_input(key="tx_price").set_value(150.0)
    _button(at, "Erfassen").click().run()
    assert any("übersteigt den Bestand" in t.value for t in at.toast)
    assert len(_saved(tmp_path)["transactions"]) == 1

    at.number_input(key="tx_shares").set_value(2.0)
    _button(at, "Erfassen").click().run()
    _assert_clean(at)
    assert len(_saved(tmp_path)["transactions"]) == 2
    assert "+100 € realisiert" in _hero(at)  # 2 Stück × (150 − 100) €


def test_closing_price_is_filled_in_for_the_chosen_day(demo_app):
    at = demo_app
    at.text_input(key="tx_query").set_value("Nordlicht").run()
    at.date_input(key="tx_date").set_value(date.today() - timedelta(days=30)).run()
    price = at.number_input(key="tx_price").value
    assert price > 0 and any(f"{num(price, 2)} €" in c.value for c in at.caption)
    at.number_input(key="tx_price").set_value(1.0).run()  # eigener Kurs bleibt stehen
    assert at.number_input(key="tx_price").value == 1.0
    assert any(b.label == "Schlusskurs einsetzen" for b in at.button)
    at.date_input(key="tx_date").set_value(date(1995, 1, 2)).run()  # vor den Demo-Kursen: Feld geleert
    assert at.number_input(key="tx_price").value == 0.0
    _assert_clean(at)


def test_transactions_are_deleted_only_after_marking_and_can_be_restored(example_app, tmp_path):
    at = _open(example_app, "portfolio", sections=["sec_transactions"])
    count = len(_saved(tmp_path, "beispieldepot")["transactions"])
    assert all("Symbol" not in d.value.columns for d in at.dataframe if "Typ" in d.value.columns)
    at.session_state["tx_marked"] = {0, 1}  # zwei Käufe markiert (in der Tabelle per Häkchen)
    at.run()
    assert len(_saved(tmp_path, "beispieldepot")["transactions"]) == count  # Markieren löscht nichts
    _button(at, "2 markierte löschen").click().run()
    _assert_clean(at)
    assert len(_saved(tmp_path, "beispieldepot")["transactions"]) == count - 2
    _button(at, "Löschen rückgängig machen (2)").click().run()
    assert len(_saved(tmp_path, "beispieldepot")["transactions"]) == count
    at.session_state["tx_marked"] = {10, 11}  # Käufe der Brückenbank, deren Teilverkauf sie braucht
    at.run()
    _button(at, "2 markierte löschen").click().run()
    assert any("übersteigt den Bestand" in t.value for t in at.toast)
    assert len(_saved(tmp_path, "beispieldepot")["transactions"]) == count


def test_example_portfolio_level_portfolio(example_app):
    at = _open(example_app, "portfolio")
    _assert_clean(at)
    assert [e.label for e in at.expander][:3] == ["Transaktion erfassen", "Positionen", "Transaktionen"]
    assert "Depotwert" in _hero(at) and "10 Positionen" in _hero(at)
    labels = {m.label for m in at.metric}
    assert {"Persönliche Rendite p. a.", "Zeitgewichtete Rendite p. a.", "Eingezahlt (netto)"} <= labels
    assert any(m.value == "**Vergleich mit einem Index**" for m in at.markdown)
    positions = next(d.value for d in at.dataframe if "Stand" in d.value.columns)
    assert positions["Stand"].str.startswith("Schluss").all()  # die Demo hat keine Live-Kurse


def test_example_portfolio_level_analyses(example_app):
    at = _open(example_app, "analysen")
    _assert_clean(at)
    assert any(":red-badge[Sektor] **Technologie**" in m.value for m in at.markdown)
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
    assert [t.label for t in at.tabs][-3:] == ["Markt-Hedge (Beta)", "Beimischung", "Klumpenrisiko absichern"]
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


def test_deleted_portfolio_goes_to_trash_and_can_be_restored(demo_app, tmp_path):
    at = demo_app
    at.text_input(key="pf_new_name").set_value("Sparplan")
    _button(at, "Anlegen").click().run()
    assert at.selectbox(key="pf_select_demo").value == "Sparplan"
    saved = tmp_path / "demo" / "sparplan.json"
    _button(at, "In den Papierkorb verschieben").click().run()
    _assert_clean(at)
    assert not saved.exists() and any((tmp_path / "demo" / "papierkorb").glob("sparplan--*.json"))
    assert at.selectbox(key="pf_select_demo").value != "Sparplan"
    _button(at, "Wiederherstellen").click().run()
    _assert_clean(at)
    assert saved.exists() and at.selectbox(key="pf_select_demo").value == "Sparplan"


# ---------------------------------------------------------------------------
# Yahoo-Pfad mit nachgebildetem yfinance (kein Netzwerk in Tests)
# ---------------------------------------------------------------------------

YAHOO = {
    "AAPL": {"longName": "Apple Inc.", "quoteType": "EQUITY", "currency": "USD", "sector": "Technology",
             "country": "United States"},
    "SAP.DE": {"longName": "SAP SE", "quoteType": "EQUITY", "currency": "EUR", "sector": "Technology",
               "country": "Germany"},
}


SPLIT_DAYS_AGO = 200  # Apple hatte in der Nachbildung vor 200 Tagen einen Split 4:1


def _price(ticker: str, index: pd.DatetimeIndex) -> np.ndarray:
    """Splitbereinigter Kurs je Tag – unabhängig vom angefragten Zeitraum."""
    days = (pd.DatetimeIndex(index).tz_localize(None).normalize() - pd.Timestamp("2000-01-01")).days.to_numpy()
    level = 1.1 if ticker.endswith("=X") else 100.0
    return level * np.exp(0.00002 * days + 0.08 * np.sin(days / 37 + zlib.crc32(ticker.encode()) % 100))


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

    def download(tickers, start=None, end=None, interval="1d", auto_adjust=True, actions=False, **kwargs):
        tickers = [tickers] if isinstance(tickers, str) else list(tickers)
        if interval == "1m":  # Live-Kurse: letzte Handelsminuten von heute (UTC)
            index = pd.date_range(pd.Timestamp(date.today()) + pd.Timedelta(hours=9), periods=30, freq="min",
                                  tz="UTC")
        else:
            index = pd.bdate_range(start, pd.Timestamp(end) - pd.Timedelta(days=1))
        close = pd.DataFrame({t: _price(t, index) for t in tickers}, index=index)
        # Dividendenbereinigte Kurse liegen in der Vergangenheit unter den tatsächlichen
        adjusted = close * [1.0 if t.endswith("=X") else 0.8 for t in tickers]
        frames = {"Close": adjusted} if auto_adjust else {"Close": close, "Adj Close": adjusted}
        if actions:
            splits = pd.DataFrame(0.0, index=index, columns=tickers)
            split_day = pd.bdate_range(end=pd.Timestamp(date.today() - timedelta(days=SPLIT_DAYS_AGO)), periods=1)[0]
            if "AAPL" in tickers and split_day in index:
                splits.at[split_day, "AAPL"] = 4.0
            frames["Stock Splits"] = splits
        return pd.concat(frames, axis=1)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Search=Search, Ticker=Ticker,
                                                                       download=download))


def test_yahoo_portfolio_uses_live_prices(fake_yfinance, tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch, "yahoo")
    for i, (query, shares) in enumerate([("Apple", 10.0), ("SAP", 20.0)]):
        if i:
            at.segmented_control(key="tx_mode").set_value("Suchen").run()
        at.text_input(key="tx_query").set_value(query).run()
        at.date_input(key="tx_date").set_value(date.today() - timedelta(days=500)).run()
        at.number_input(key="tx_shares").set_value(shares)
        at.number_input(key="tx_price").set_value(100.0)
        _button(at, "Erfassen").click().run()
        _assert_clean(at)
    assert [t["symbol"] for t in _saved(tmp_path, provider="yahoo")["transactions"]] == ["AAPL", "SAP.DE"]
    positions = next(d.value for d in at.dataframe if "Stand" in d.value.columns).set_index("Symbol")
    assert positions["Stand"].str.startswith("live").all()
    # Apple wurde vor dem Split 4:1 gekauft: 10 Stück zu 100 € werden 40 Stück zu 25 €
    assert positions.at["AAPL", "Stück"] == pytest.approx(40.0)
    assert positions.at["AAPL", "Ø Kaufkurs"] == pytest.approx(25.0)
    assert positions.at["SAP.DE", "Stück"] == pytest.approx(20.0)
    assert any("4:1" in c.value for c in at.caption)
    for page in ("analysen", "loesungen", "start"):
        _open(at, page)
        _assert_clean(at)
    assert "Grenzen überschritten" in _start_card(at) and "Beispieldepot" not in _start_card(at)


def test_yahoo_suggests_actual_close_not_dividend_adjusted(fake_yfinance, tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch, "yahoo")
    when = date.today() - timedelta(days=500)
    at.text_input(key="tx_query").set_value("SAP").run()
    at.date_input(key="tx_date").set_value(when).run()
    _assert_clean(at)
    day = pd.bdate_range(end=pd.Timestamp(when), periods=1)
    expected = f"Schlusskurs {day[0]:%d.%m.%Y}: {num(_price('SAP.DE', day)[0], 2)} €"
    assert any(expected in c.value for c in at.caption), [c.value for c in at.caption]
    # Vor dem Split: Kurs in der damaligen Stückelung, wie in der Abrechnung (4 × splitbereinigter Kurs)
    at.segmented_control(key="tx_mode").set_value("Suchen") if any(
        w.key == "tx_mode" for w in at.segmented_control) else None
    at.text_input(key="tx_query").set_value("Apple").run()
    usd = _price("AAPL", day)[0] / _price("EURUSD=X", day)[0]
    assert at.number_input(key="tx_price").value == pytest.approx(round(4 * usd, 2))
