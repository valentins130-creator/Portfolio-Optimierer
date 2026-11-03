"""Rauchtests der Streamlit-Oberfläche mit ``streamlit.testing``."""

import json
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


# ---------------------------------------------------------------------------
# Mein Portfolio (Offline-Demo, Ablage in einem temporären Ordner)
# ---------------------------------------------------------------------------


@pytest.fixture
def portfolio_app(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DIR", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=240)
    at.session_state["pf_provider"] = "demo"
    at.run()
    at.sidebar.radio[0].set_value("Mein Portfolio").run()
    return at


def test_empty_portfolio_shows_onboarding(portfolio_app):
    _assert_clean(portfolio_app)
    assert any("Das Portfolio ist noch leer" in i.value for i in portfolio_app.info)


def test_search_and_add_position_is_saved(portfolio_app, tmp_path):
    at = portfolio_app
    at.text_input(key="pf_query").set_value("Nordlicht").run()
    at.number_input(key="pf_shares").set_value(12.0)
    at.number_input(key="pf_price").set_value(100.0)
    next(b for b in at.button if b.label == "Hinzufügen").click().run()
    _assert_clean(at)
    saved = json.loads((tmp_path / "demo" / "mein-depot.json").read_text(encoding="utf-8"))
    assert saved["positions"][0]["symbol"] == "NLS.DEMO"
    assert saved["positions"][0]["shares"] == 12.0
    assert saved["positions"][0]["purchase_price"] == 100.0
    assert at.text_input(key="pf_query").value == ""


@pytest.mark.parametrize("subtab", ["Aufteilung", "Klumpenrisiko", "Absicherung", "Umschichtung"])
def test_example_portfolio_all_views(portfolio_app, subtab):
    at = portfolio_app
    next(b for b in at.button if b.label == "Beispieldepot laden").click().run()
    at.session_state["pf_subtab"] = subtab
    at.run()
    _assert_clean(at)
    assert [t.label for t in at.tabs][:1] == ["Mein Portfolio"]
    assert any(m.value.startswith("**Mein Portfolio:**") for m in at.markdown)  # Vergleich im Frontier-Tab
    if subtab == "Klumpenrisiko":
        assert any("Sektor Technologie" in m.value for m in at.markdown)
    if subtab == "Absicherung":
        assert [s.value for s in at.subheader][:3] == ["Markt-Hedge (Beta)", "Diversifizierende Beimischung",
                                                      "Klumpenrisiko absichern"]
    if subtab == "Umschichtung":
        assert any("innerhalb der Grenzen" in s.value for s in at.success)


def test_create_and_delete_portfolio(portfolio_app, tmp_path):
    at = portfolio_app
    at.text_input(key="pf_new_name").set_value("Sparplan")
    next(b for b in at.button if b.label == "Anlegen").click().run()
    assert at.selectbox(key="pf_select_demo").value == "Sparplan"
    assert (tmp_path / "demo" / "sparplan.json").exists()
    next(b for b in at.button if b.label == "Ja, löschen").click().run()
    _assert_clean(at)
    assert not (tmp_path / "demo" / "sparplan.json").exists()
