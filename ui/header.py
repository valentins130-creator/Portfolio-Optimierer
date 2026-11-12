"""Kopfzeile: Portfolio-Auswahl, Verwalten (Neu, Import/Export, Löschen, Papierkorb) und Einstellungen."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import streamlit as st

from portfolio_optimizer.estimators import COV_ESTIMATORS, MEAN_ESTIMATORS
from portfolio_optimizer.portfolio import BUY, TRASH_DAYS, Portfolio, read_transactions_csv
from ui.common import flash
from ui.state import (
    DEFAULT_NAME,
    PROVIDERS,
    Settings,
    current_portfolio,
    example_portfolio,
    history_eur,
    reset_portfolio_inputs,
    security_info,
    set_portfolio,
    store,
    unique_name,
)

YEARS = [1, 2, 3, 5, 10, 15, 20]


def _provider_changed(widget_key: str) -> None:
    st.session_state["set_provider"] = st.session_state[widget_key]
    reset_portfolio_inputs()


def use_provider(provider: str) -> None:
    """Marktdaten umschalten, ohne die Einstellungen zu öffnen (z. B. von der Startseite aus).

    Maßgeblich ist der Sitzungswert ``set_provider``. Der Schalter in den Einstellungen bekommt dabei
    einen neuen Schlüssel: Solange das Menü geschlossen ist, kennt der Browser den neuen Wert sonst
    nicht und schickte beim nächsten Seitenwechsel den alten zurück.
    """
    st.session_state["set_provider"] = provider
    st.session_state["set_provider_version"] = st.session_state.get("set_provider_version", 0) + 1
    reset_portfolio_inputs()


def _settings_popover() -> Settings:
    st.markdown("**Daten**")
    options = list(PROVIDERS)
    current = st.session_state.setdefault("set_provider", options[0])
    widget_key = f"set_provider_{st.session_state.get('set_provider_version', 0)}"
    st.radio("Marktdaten", options, index=options.index(current), format_func=PROVIDERS.get, key=widget_key,
             horizontal=True, on_change=_provider_changed, args=(widget_key,),
             help="Die Offline-Demo nutzt fiktive Wertpapiere mit simulierten Kursen – zum Ausprobieren "
                  "ohne Internet.")
    provider = st.session_state["set_provider"]
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
    flash(f"„{name}“ liegt im Papierkorb und lässt sich unter Verwalten → Papierkorb wiederherstellen.")


def _restore(provider: str, path: str) -> None:
    item = next((i for i in store(provider).trash() if str(i.path) == path), None)
    if item is None:
        flash("Dieser Eintrag ist nicht mehr im Papierkorb.", "error")
        return
    portfolio = store(provider).restore(item)
    set_portfolio(provider, portfolio, save=False)
    _show_entry(not portfolio.securities)
    flash(f"„{portfolio.name}“ wiederhergestellt.")


def load_example(provider: str) -> None:
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
            # zeitlich geordnet, damit jeder Verkauf auf die Käufe davor trifft
            rows = sorted(read_transactions_csv(content), key=lambda r: (r[4] or date.min, r[1] != BUY))
            infos = {}
            for symbol in dict.fromkeys(r[0] for r in rows):
                try:
                    infos[symbol] = security_info(provider, symbol)
                except Exception:  # unbekanntes Symbol oder Netzwerkfehler
                    failed.append(symbol)
            dated = [r[4] for r in rows if r[4]]
            if infos and dated:  # Splits vorab, damit Verkäufe nach einem Split gedeckt sind
                try:
                    portfolio.splits = history_eur(provider, tuple(infos), tuple(i.currency for i in infos.values()),
                                                   min(dated), date.today()).splits
                except Exception:  # ohne Splits weiter
                    pass
            for symbol, kind, shares, price, when in rows:
                if symbol not in infos:
                    continue
                try:
                    portfolio.add_transaction(infos[symbol], kind, shares, price, when)
                except ValueError:  # ungedeckter Verkauf
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


def _manage(provider: str, portfolio: Portfolio) -> None:
    trash = store(provider).trash()
    new, transfer, delete, bin_ = st.tabs(["Neu", "Import/Export", "Löschen",
                                           f"Papierkorb ({len(trash)})" if trash else "Papierkorb"])
    with new:
        st.text_input("Name des neuen Portfolios", key="pf_new_name")
        st.button("Anlegen", on_click=_create, args=(provider,), type="primary")
        if provider == "demo":
            st.divider()
            st.button("Beispieldepot laden", on_click=load_example, args=(provider,),
                      help="Fiktives Depot mit Käufen über drei Jahre, Tech-Übergewicht und hohem Dollar-Anteil.")
    with transfer:
        st.download_button("Als JSON exportieren", portfolio.to_json(), file_name=f"{portfolio.name}.json",
                           mime="application/json", width="stretch")
        st.download_button("Transaktionen als CSV (Excel)", portfolio.to_csv(), file_name=f"{portfolio.name}.csv",
                           mime="text/csv", width="stretch")
        st.divider()
        st.file_uploader("Importieren (JSON oder CSV)", type=["json", "csv"], key="pf_upload",
                         help="CSV mit den Spalten Symbol und Stück, optional Datum, Typ (Kauf/Verkauf) und Kurs "
                              "(EUR je Stück).")
        st.button("Importieren", on_click=_import, args=(provider,))
    with delete:
        n = len(portfolio.transactions)
        st.markdown(f"**{portfolio.name}** · {n} {'Transaktion' if n == 1 else 'Transaktionen'}")
        st.caption(f"Das Portfolio kommt in den Papierkorb und lässt sich dort {TRASH_DAYS} Tage lang "
                   "wiederherstellen.")
        st.button("In den Papierkorb verschieben", type="primary", icon=":material/delete:", on_click=_delete,
                  args=(provider,))
    with bin_:
        if not trash:
            st.caption("Der Papierkorb ist leer.")
        for item in trash:
            left, right = st.columns([3, 2], vertical_alignment="center")
            left.markdown(f"**{item.name}**  \n:gray[gelöscht {item.deleted:%d.%m.%Y, %H:%M}]")
            right.button("Wiederherstellen", key=f"restore_{item.path.name}", type="tertiary",
                         icon=":material/restore_from_trash:", on_click=_restore, args=(provider, str(item.path)))


def render() -> Settings:
    """Zeichnet die Kopfzeile und liefert die aktuellen Einstellungen."""
    provider = st.session_state.get("set_provider", next(iter(PROVIDERS)))
    portfolio = current_portfolio(provider)
    names = store(provider).names()
    if portfolio.name not in names:
        names = [portfolio.name, *names]
    st.session_state.setdefault(f"pf_select_{provider}", portfolio.name)
    with st.container(horizontal=True, vertical_alignment="center", gap="small", key="toolbar"):
        st.selectbox("Portfolio", names, key=f"pf_select_{provider}", on_change=_switch, args=(provider,),
                     label_visibility="collapsed", width=320)
        with st.popover("Verwalten", icon=":material/folder_open:"):
            _manage(provider, portfolio)
        st.space("stretch")
        with st.popover("Einstellungen", icon=":material/tune:"):
            settings = _settings_popover()
    return settings
