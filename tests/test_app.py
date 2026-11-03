"""Rauchtests der Streamlit-Oberfläche mit ``streamlit.testing``."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from portfolio_optimizer import data

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def app():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    return at


def _assert_clean(at):
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


@pytest.fixture(autouse=True)
def fake_yahoo(monkeypatch):
    """Kein Netzwerk in Tests: Yahoo liefert synthetische Kurse für die angefragten Ticker."""

    def fetch(tickers, start, end):
        prices = data.synthetic_prices(years=5, seed=3).iloc[:, : len(tickers)]
        prices.columns = list(tickers)[: prices.shape[1]]
        return prices, list(tickers)[prices.shape[1]:]

    monkeypatch.setattr(data, "fetch_prices", fetch)


def test_yahoo_source_renders_all_tabs(app):
    _assert_clean(app)
    assert len(app.tabs) == 4
    labels = [m.label for m in app.metric]
    assert "Sharpe-Ratio" in labels and "Median-Endvermögen" in labels


def test_demo_data_and_experiment(app):
    app.sidebar.radio[0].set_value("Demo-Daten").run()
    _assert_clean(app)
    trials = next(s for s in app.select_slider if s.label == "Anzahl Durchläufe")
    trials.set_value(50)
    next(b for b in app.button if b.label == "Experiment starten").click().run()
    _assert_clean(app)
    assert any("Ergebnis aus 50 simulierten Historien" in m.value for m in app.markdown)


def test_unconstrained_markowitz_with_short_selling(app):
    app.sidebar.radio[0].set_value("Demo-Daten").run()
    app.sidebar.toggle[0].set_value(True).run()
    app.sidebar.checkbox[0].set_value(True).run()
    _assert_clean(app)


def test_infeasible_weight_cap_shows_error(app):
    app.sidebar.radio[0].set_value("Demo-Daten").run()
    cap = next(s for s in app.sidebar.slider if s.label == "Höchstgewicht je Titel")
    cap.set_value(10).run()  # 6 Assets x 10 % < 100 %
    assert any("kein voll investiertes Portfolio" in e.value for e in app.sidebar.error)
