"""Kopfzeile: Titel, Portfolio-Auswahl, Neu/Export/Import/Löschen und Einstellungen."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from portfolio_optimizer.estimators import COV_ESTIMATORS, MEAN_ESTIMATORS
from portfolio_optimizer.portfolio import Portfolio, read_transactions_csv
from ui.common import flash
from ui.state import (
    DEFAULT_NAME,
    PROVIDERS,
    Settings,
    current_portfolio,
    example_portfolio,
    reset_portfolio_inputs,
    security_info,
    set_portfolio,
    store,
    unique_name,
)

YEARS = [1, 2, 3, 5, 10, 15, 20]


def _settings_popover() -> Settings:
    st.markdown("**Daten**")
    provider = st.radio("Marktdaten", list(PROVIDERS), format_func=PROVIDERS.get, key="set_provider",
                        horizontal=True, on_change=reset_portfolio_inputs,
                        help="Die Offline-Demo nutzt fiktive Wertpapiere mit simulierten Kursen – zum Ausprobieren "
                             "ohne Internet.")
    years = st.select_slider("Historie für Analysen", YEARS, value=5, key="set_years",
                             format_func=lambda y: f"{y} Jahr" if y == 1 else f"{y} Jahre",
                             help="Zeitraum für Risiko-, Hedge- und Optimierungsrechnungen. Die Wertentwicklung "
                                  "des Depots reicht immer bis zum ersten Kauf zurück.")
    st.markdown("**Schätzung**")
    mean_method = st.selectbox("Erwartete Renditen", list(MEAN_ESTIMATORS), format_func=MEAN_ESTIMATORS.get,
                               key="set_mean",
                               help="Bayes-Stein zieht die historischen Mittelwerte in Richtung eines gemeinsamen "
                                    "Werts und dämpft so Ausreißer der Schätzung.")
    cov_method = st.selectbox("Kovarianzen", list(COV_ESTIMATORS), format_func=COV_ESTIMATORS.get, key="set_cov",
                              help="Ledoit-Wolf zieht die Korrelationen in Richtung ihres Durchschnitts und "
                                   "stabilisiert so die Matrix.")
    rf = st.number_input("Risikoloser Zins p. a. (%)", -2.0, 10.0, 2.0, 0.25, format="%.2f", key="set_rf") / 100
    st.markdown("**Gewichtsgrenzen** (Markowitz und Umschichtung)")
    allow_short = st.toggle("Leerverkäufe erlauben", value=False, key="set_short")
    unbounded = allow_short and st.checkbox(
        "Ohne Grenzen (klassischer Markowitz)", key="set_unbounded",
        help="Analytische Lösung ohne jede Gewichtsgrenze – zeigt die extremen Positionen des Originalmodells.")
    if unbounded:
        bounds = None
    else:
        lo = st.slider("Mindestgewicht je Titel", -100, 0, -30, 5, format="%d %%", key="set_lo") / 100 \
            if allow_short else 0.0
        hi = st.slider("Höchstgewicht je Titel", 5, 200 if allow_short else 100, 100, 5, format="%d %%",
                       key="set_hi") / 100
        bounds = (lo, hi)
    st.caption("Alle Werte in Euro; Fremdwährungen werden mit den Wechselkursen umgerechnet.")
    return Settings(provider, years, mean_method, cov_method, rf, bounds)


# ---------------------------------------------------------------------------
# Portfolio-Verwaltung (Callbacks laufen vor dem nächsten Durchlauf)
# ---------------------------------------------------------------------------


def _show_entry(open_: bool) -> None:
    """Erfassungsbereich auf- oder zuklappen: offen für ein leeres Depot, sonst stehen die Positionen oben."""
    st.session_state["sec_add"] = open_


def _switch(provider: str) -> None:
    set_portfolio(provider, store(provider).load(st.session_state[f"pf_select_{provider}"]), save=False)
    _show_entry(not current_portfolio(provider).securities)


def _create(provider: str) -> None:
    name = st.session_state.get("pf_new_name", "").strip()
    if not name:
        flash("Bitte einen Namen eingeben.", "error")
    elif store(provider).exists(name):
        flash(f"Ein Portfolio „{name}“ gibt es schon.", "error")
    else:
        set_portfolio(provider, Portfolio(name))
        st.session_state["pf_new_name"] = ""
        _show_entry(True)
        flash(f"Portfolio „{name}“ angelegt.")


def _delete(provider: str) -> None:
    name = current_portfolio(provider).name
    store(provider).delete(name)
    names = store(provider).names()
    set_portfolio(provider, store(provider).load(names[0]) if names else Portfolio(DEFAULT_NAME), save=False)
    _show_entry(not current_portfolio(provider).securities)
    flash(f"Portfolio „{name}“ gelöscht.")


def _load_example(provider: str) -> None:
    set_portfolio(provider, example_portfolio(provider))
    _show_entry(False)
    flash("Beispieldepot geladen.")


def _import(provider: str) -> None:
    upload = st.session_state.get("pf_upload")
    if upload is None:
        flash("Bitte zuerst eine Datei auswählen.", "error")
        return
    content = upload.getvalue()
    failed: list[str] = []
    try:
        if upload.name.lower().endswith(".json"):
            portfolio = Portfolio.from_dict(json.loads(content.decode("utf-8-sig")))
        else:
            portfolio = Portfolio(Path(upload.name).stem)
            for symbol, kind, shares, price, when in read_transactions_csv(content):
                try:
                    portfolio.add_transaction(security_info(provider, symbol), kind, shares, price, when)
                except Exception:  # unbekanntes Symbol, Netzwerkfehler oder ungedeckter Verkauf
                    failed.append(symbol)
    except (ValueError, KeyError, TypeError) as exc:
        flash(f"Import fehlgeschlagen: {exc}", "error")
        return
    portfolio.name = unique_name(provider, portfolio.name)
    set_portfolio(provider, portfolio)
    _show_entry(not portfolio.securities)
    note = f" Übersprungen: {', '.join(sorted(set(failed)))}." if failed else ""
    flash(f"Portfolio „{portfolio.name}“ mit {len(portfolio.transactions)} Transaktionen importiert.{note}",
          "error" if failed else "success")


def render() -> Settings:
    """Zeichnet die Kopfzeile und liefert die aktuellen Einstellungen."""
    title, select, new, transfer, delete, options = st.columns([2.9, 2.6, 1, 1.4, 1.1, 1.4],
                                                               vertical_alignment="center")
    with options.popover("Einstellungen", icon=":material/settings:", width="stretch"):
        settings = _settings_popover()
    provider = settings.provider
    portfolio = current_portfolio(provider)

    title.markdown("### 📈 Portfolio-Optimierer")
    names = store(provider).names()
    if portfolio.name not in names:
        names = [portfolio.name, *names]
    st.session_state.setdefault(f"pf_select_{provider}", portfolio.name)
    select.selectbox("Portfolio", names, key=f"pf_select_{provider}", on_change=_switch, args=(provider,),
                     label_visibility="collapsed")
    with new.popover("Neu", icon=":material/add:", width="stretch"):
        st.text_input("Name des neuen Portfolios", key="pf_new_name")
        st.button("Anlegen", on_click=_create, args=(provider,), type="primary")
        if provider == "demo":
            st.divider()
            st.button("Beispieldepot laden", on_click=_load_example, args=(provider,),
                      help="Fiktives Depot mit Käufen über drei Jahre, Tech-Übergewicht und hohem Dollar-Anteil.")
    with transfer.popover("Export/Import", icon=":material/swap_vert:", width="stretch"):
        st.download_button("Als JSON exportieren", portfolio.to_json(), file_name=f"{portfolio.name}.json",
                           mime="application/json", width="stretch")
        st.download_button("Transaktionen als CSV (Excel)", portfolio.to_csv(), file_name=f"{portfolio.name}.csv",
                           mime="text/csv", width="stretch")
        st.divider()
        st.file_uploader("Importieren (JSON oder CSV)", type=["json", "csv"], key="pf_upload",
                         help="CSV mit den Spalten Symbol und Stück, optional Datum, Typ (Kauf/Verkauf) und Kurs "
                              "(EUR je Stück).")
        st.button("Importieren", on_click=_import, args=(provider,))
    with delete.popover("Löschen", icon=":material/delete:", width="stretch"):
        st.write(f"Portfolio „{portfolio.name}“ endgültig löschen?")
        st.button("Ja, löschen", on_click=_delete, args=(provider,), type="primary")
    return settings
