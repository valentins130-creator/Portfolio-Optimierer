"""Ebene 1 – Portfolio: Transaktionen erfassen, Positionen, Wertentwicklung, Kursdaten, Aufteilung."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pandas as pd
import streamlit as st

from portfolio_optimizer import charts, data, performance
from portfolio_optimizer.estimators import MEAN_ESTIMATORS
from portfolio_optimizer.formatting import num, pct, ratio, styled
from portfolio_optimizer.market import get_provider
from portfolio_optimizer.portfolio import BUY, SELL, Portfolio, exposures, is_concentration_group, parse_date
from ui.common import flash, section, show_chart, show_flash
from ui.state import (
    PortfolioContext,
    RunState,
    bump_editor,
    close_on,
    current_limits,
    current_portfolio,
    prices_eur,
    save,
    search,
    security_info,
    set_portfolio,
)

DIMENSIONS = {"Sektoren": "sector", "Währungen": "currency"}


def render(run: RunState) -> None:
    ctx = run.ctx
    show_flash()
    if ctx.portfolio.positions:
        _hero(ctx)
    if box := section("Transaktion erfassen", "sec_add", expanded=not ctx.portfolio.securities,
                      icon=":material/add_circle:"):
        with box:
            _add_transaction(ctx)
    if not ctx.portfolio.securities:
        st.info("Das Portfolio ist noch leer. Erfasse oben deine Käufe mit Datum, Stückzahl und Kurs."
                + (" Oder lade über **Neu** das Beispieldepot." if ctx.provider == "demo" else ""))
        return
    if box := section("Positionen", "sec_positions", expanded=True, icon=":material/table_view:"):
        with box:
            _positions(ctx)
    if box := section("Transaktionen", "sec_transactions", icon=":material/receipt_long:"):
        with box:
            _transactions(ctx)
    if box := section("Wertentwicklung", "sec_performance", icon=":material/show_chart:"):
        with box:
            _performance(ctx, run.theme)
    if box := section("Kursdaten und Kennzahlen", "sec_market", icon=":material/query_stats:"):
        with box:
            _market_data(run)
    if box := section("Aufteilung nach Sektoren und Währungen", "sec_allocation",
                      icon=":material/donut_small:"):
        with box:
            _allocation(ctx, run.theme)


def _signed_eur(value: float) -> str:
    return f"{'+' if value > 0 else '−' if value < 0 else '±'}{num(abs(value))} €"


def _hero(ctx: PortfolioContext) -> None:
    """Depotwert groß, darunter Gewinne, Positionen und Kursstand in einer Zeile."""
    val = ctx.valuation
    parts = []
    known = val["cost"].notna()
    if known.any():
        cost, now = float(val.loc[known, "cost"].sum()), float(val.loc[known, "value"].sum())
        diff = now - cost
        tone = "po-up" if diff > 0 else "po-down" if diff < 0 else ""
        arrow = "▲ " if diff > 0 else "▼ " if diff < 0 else ""
        parts.append(f'<span><span class="{tone}">{arrow}{_signed_eur(diff)} ({pct(now / cost - 1, signed=True)})'
                     "</span> unrealisiert</span>")
    realized = ctx.portfolio.realized_gains()
    if realized:
        parts.append(f"<span>{_signed_eur(realized)} realisiert</span>")
    n = len(ctx.portfolio.positions)
    parts.append(f"<span>{n} {'Position' if n == 1 else 'Positionen'}</span>")
    if not ctx.quotes.empty:
        live = ctx.quotes[ctx.quotes["live"]]
        common = ctx.quotes["stand"].mode().iloc[0]  # Fonds hinken oft einen Tag hinterher
        stand = (f"Kurse live, {live['stand'].iloc[0].removeprefix('live ')} Uhr" if not live.empty
                 else "Schlusskurse vom " + common.removeprefix("Schluss "))
        parts.append(f"<span>{stand}</span>")
    st.html(f'<div class="po-hero"><div class="po-label">Depotwert</div>'
            f'<div class="po-value">{num(ctx.value)} €</div><div class="po-sub">{"".join(parts)}</div></div>')


# ---------------------------------------------------------------------------
# Transaktion erfassen
# ---------------------------------------------------------------------------


def _record(provider: str, symbol: str) -> None:
    portfolio = current_portfolio(provider)
    try:
        info = portfolio.securities.get(symbol) or security_info(provider, symbol)
    except Exception as exc:  # Netzwerk- oder Datenfehler
        flash(f"Stammdaten für {symbol} nicht abrufbar: {exc}", "error")
        return
    kind = st.session_state.get("tx_kind") or BUY
    shares = float(st.session_state.get("tx_shares") or 0)
    price = float(st.session_state.get("tx_price") or 0) or None
    when = st.session_state.get("tx_date") or date.today()
    try:
        portfolio.add_transaction(info, kind, shares, price, when)
    except ValueError as exc:
        flash(str(exc), "error")
        return
    save(provider)
    bump_editor()
    st.session_state["tx_query"] = ""
    st.session_state.pop("tx_undo", None)
    flash(f"{kind} von {num(shares, 2)} Stück {info.name} am {when:%d.%m.%Y} erfasst.")


def _use_price(value: float) -> None:
    st.session_state["tx_price"] = round(value, 2)


def _label(info) -> str:
    """Name und Symbol – das Symbol nur, wenn es nicht schon der Name ist (z. B. bei Fonds ohne Namen)."""
    return info.name if info.name == info.symbol else f"{info.name} · {info.symbol}"


def _pick_security(ctx: PortfolioContext):
    """Wertpapier aus dem Depot oder per Suche; Rückgabe: (Symbol, Stammdaten) oder None."""
    securities = ctx.portfolio.securities
    mode = "Suchen"
    if securities:
        mode = st.segmented_control("Wertpapier", ["Aus dem Depot", "Suchen"], default="Aus dem Depot",
                                    key="tx_mode", required=True) or "Aus dem Depot"
    if mode == "Aus dem Depot":
        symbol = st.selectbox("Wertpapier aus dem Depot", list(securities),
                              format_func=lambda s: _label(securities[s]), key="tx_symbol")
        return symbol, securities[symbol]
    placeholder = ("z. B. Nordlicht, Technologie, ETF" if ctx.provider == "demo"
                   else "Name, Ticker oder ISIN – z. B. Apple, SAP.DE oder IE00B4L5Y983")
    query = st.text_input("Wertpapier suchen", key="tx_query", placeholder=placeholder).strip()
    if not query:
        return None
    try:
        hits = search(ctx.provider, query)
    except Exception as exc:  # Netzwerkfehler
        st.error(f"Die Suche ist fehlgeschlagen ({exc}). Ist Yahoo Finance erreichbar?")
        return None
    if not hits:
        st.info("Keine passenden Wertpapiere gefunden. Versuche den Ticker (z. B. „SAP.DE“) oder die ISIN.")
        return None
    index = st.selectbox("Treffer", range(len(hits)), format_func=lambda i: hits[i].label, key=f"tx_hit_{query}")
    symbol = hits[index].symbol
    try:
        info = security_info(ctx.provider, symbol)
    except Exception as exc:  # Netzwerkfehler
        st.error(f"Stammdaten für {symbol} nicht abrufbar: {exc}")
        return None
    st.caption(f"{info.quote_type} · {info.sector} · Handelswährung {info.currency}")
    return symbol, info


def _add_transaction(ctx: PortfolioContext) -> None:
    picked = _pick_security(ctx)
    if picked is None:
        return
    symbol, info = picked
    c1, c2, c3, c4, c5 = st.columns([1.3, 1.3, 1, 1.3, 1], vertical_alignment="bottom")
    c1.segmented_control("Typ", [BUY, SELL], default=BUY, key="tx_kind", required=True)
    when = c2.date_input("Datum", value=date.today(), min_value=date(1970, 1, 1), max_value=date.today(),
                         format="DD.MM.YYYY", key="tx_date")  # ohne min_value nur die letzten zehn Jahre
    close = close_on(ctx.provider, info, when)
    if st.session_state.get("tx_price_for") != (ctx.provider, symbol, when):
        # Anderes Wertpapier oder Datum: Schlusskurs dieses Tages eintragen, sonst das Feld leeren
        st.session_state["tx_price"] = round(close[0], 2) if close else 0.0
        st.session_state["tx_price_for"] = (ctx.provider, symbol, when)
    c3.number_input("Stück", min_value=0.0, value=1.0, step=1.0, key="tx_shares")
    c4.number_input("Kurs je Stück (EUR)", min_value=0.0, step=0.01, format="%.2f", key="tx_price",
                    help="Vorbelegt mit dem Schlusskurs des Tages. Für genaue Gewinne den Ausführungskurs aus der "
                         "Abrechnung eintragen.")
    c5.button("Erfassen", type="primary", on_click=_record, args=(ctx.provider, symbol), width="stretch")
    held = ctx.portfolio.get(symbol)
    parts = [f"Im Depot: {num(held.shares, 2)} Stück"] if held else []
    if close:
        value, day = close
        parts.append(f"Schlusskurs {day:%d.%m.%Y}: {num(value, 2)} €")
    else:
        parts.append("Für dieses Datum liegt kein Schlusskurs vor – bitte den Kurs aus der Abrechnung eintragen")
    left, right = st.columns([3, 1], vertical_alignment="center")
    left.caption(" · ".join(parts))
    if close and abs(float(st.session_state.get("tx_price") or 0) - round(close[0], 2)) > 0.004:
        right.button("Schlusskurs einsetzen", on_click=_use_price, args=(close[0],), type="tertiary")


# ---------------------------------------------------------------------------
# Positionen und Transaktionen
# ---------------------------------------------------------------------------


def _ratio_text(ratio: float) -> str:
    """4.0 -> "4:1", 0.1 -> "1:10", 1.5 -> "3:2"."""
    frac = Fraction(ratio).limit_denominator(1000)
    return f"{frac.numerator}:{frac.denominator}"


def split_note(portfolio) -> str | None:
    splits = portfolio.applied_splits()
    if not splits:
        return None
    names = ", ".join(f"{portfolio.securities[s].name if s in portfolio.securities else s} {_ratio_text(r)} "
                      f"am {d:%d.%m.%Y}" for s, d, r in splits)
    return (f"Aktiensplit berücksichtigt: {names}. Frühere Transaktionen zählen mit der neuen Stückzahl zum "
            "entsprechend angepassten Kurs; erfasst bleiben sie wie in der Abrechnung.")


def _positions(ctx: PortfolioContext) -> None:
    if ctx.missing:
        st.warning(f"Keine Kurse für: {', '.join(ctx.missing)}. Diese Positionen fehlen in Wert und Analysen. "
                   "Yahoo drosselt häufige Abfragen – die App fragt in zwei Minuten erneut nach.")
    if ctx.stale:
        names = ", ".join(f"{ctx.portfolio.securities[s].name} (Stand {d:%d.%m.%Y})" for s, d in ctx.stale.items()
                          if s in ctx.portfolio.securities)
        st.info(f"Yahoo hat gerade nicht für alle Werte Kurse geliefert. Verwendet werden die zuletzt gespeicherten: "
                f"{names}. Die App fragt in zwei Minuten erneut nach.")
    val = ctx.valuation
    stand = ctx.quotes["stand"].reindex(val.index) if not ctx.quotes.empty else None
    table = pd.DataFrame({
        "Name": val["name"], "Symbol": val.index, "Stück": val["shares"], "Ø Kaufkurs": val["purchase_price"],
        "Kurs": val["price"], "Stand": stand, "Wert": val["value"], "G/V": val["pnl"], "G/V %": val["pnl_pct"],
        "Gewicht": val["weight"],
    })
    st.dataframe(table, hide_index=True, column_config={
        "Name": st.column_config.TextColumn(width=190),
        "Symbol": st.column_config.TextColumn(width=85),
        "Stück": st.column_config.NumberColumn(format="localized", width=70),
        "Ø Kaufkurs": st.column_config.NumberColumn("Ø Kaufkurs €", format="euro", width=95,
                                                    help="Durchschnittlicher Einstandskurs der gehaltenen Stücke (FIFO)"),
        "Kurs": st.column_config.NumberColumn("Kurs €", format="euro", width=90),
        "Stand": st.column_config.TextColumn(width=125, help="„live“: Yahoo-Kurs des laufenden Handelstags "
                                                             "(ca. 15 Min. verzögert); sonst letzter Schlusskurs"),
        "Wert": st.column_config.NumberColumn("Wert €", format="euro", width=100),
        "G/V": st.column_config.NumberColumn("G/V €", format="euro", width=90),
        "G/V %": st.column_config.NumberColumn(format="percent", width=70),
        "Gewicht": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent", width=100),
    })
    if note := split_note(ctx.portfolio):
        st.caption(note)


MARK = "Auswahl"


def _apply_tx_edits(provider: str, editor_key: str, order: list[int]) -> None:
    """Änderungen aus der Tabelle übernehmen; die Auswahl-Spalte markiert nur (gelöscht wird per Knopf)."""
    portfolio = current_portfolio(provider)
    state = st.session_state[editor_key]
    columns = {"Datum": "date", "Typ": "kind", "Stück": "shares", "Kurs": "price"}
    marked = set(st.session_state.get("tx_marked", set()))
    errors, changed = [], False
    for row, changes in state.get("edited_rows", {}).items():
        index = order[int(row)]
        if MARK in changes:
            (marked.add if changes[MARK] else marked.discard)(index)
        update = {}
        for column, field_name in columns.items():
            if column not in changes:
                continue
            value = changes[column]
            if field_name == "date":
                value = parse_date(value)
            elif field_name == "price":
                value = float(value) if value else None
            elif field_name == "shares":
                value = float(value or 0)
            update[field_name] = value
        if not update:
            continue
        try:
            portfolio.update_transaction(index, **update)
            changed = True
        except ValueError as exc:
            errors.append(str(exc))
    st.session_state["tx_marked"] = marked
    if changed:
        save(provider)
        st.session_state.pop("tx_undo", None)
    bump_editor()  # neue Tabelle mit den übernommenen Werten und Markierungen
    if errors:
        flash(" ".join(errors), "error")
    elif changed:
        flash("Transaktion geändert.")


def _delete_marked(provider: str) -> None:
    portfolio = current_portfolio(provider)
    marked = sorted(st.session_state.get("tx_marked", set()))
    snapshot = portfolio.to_dict()
    errors = portfolio.remove_transactions(marked)
    if errors:
        flash("Nicht gelöscht: " + " ".join(errors), "error")
        return
    save(provider)
    st.session_state["tx_marked"] = set()
    st.session_state["tx_undo"] = {"provider": provider, "name": portfolio.name, "data": snapshot,
                                   "count": len(marked)}
    bump_editor()
    flash(f"{len(marked)} Transaktion(en) gelöscht.")


def _clear_marks() -> None:
    st.session_state["tx_marked"] = set()
    bump_editor()


def _undo_delete(provider: str) -> None:
    undo = st.session_state.pop("tx_undo", None)
    if undo and undo["provider"] == provider:
        set_portfolio(provider, Portfolio.from_dict(undo["data"]))
        flash("Löschen rückgängig gemacht.")


def _transactions(ctx: PortfolioContext) -> None:
    portfolio = ctx.portfolio
    order = sorted(range(len(portfolio.transactions)),
                   key=lambda i: (portfolio.transactions[i].date or date.min), reverse=True)
    marked = st.session_state.get("tx_marked", set())
    rows = []
    for i in order:
        t = portfolio.transactions[i]
        info = portfolio.securities.get(t.symbol)
        rows.append({MARK: i in marked, "Datum": t.date, "Typ": t.kind, "Wertpapier": info.name if info else t.symbol,
                     "Stück": t.shares, "Kurs": t.price, "Betrag": t.amount})
    key = f"tx_editor_{st.session_state.get('tx_editor_version', 0)}"
    st.data_editor(
        pd.DataFrame(rows), key=key, hide_index=True, on_change=_apply_tx_edits, args=(ctx.provider, key, order),
        disabled=["Wertpapier", "Betrag"],
        column_config={
            MARK: st.column_config.CheckboxColumn("", help="Zum Löschen markieren", width=40),
            "Datum": st.column_config.DateColumn(format="DD.MM.YYYY", width=105),
            "Typ": st.column_config.SelectboxColumn(options=[BUY, SELL], required=True, width=90),
            "Wertpapier": st.column_config.TextColumn(width=260),
            "Stück": st.column_config.NumberColumn(min_value=0.0, format="localized", width=80),
            "Kurs": st.column_config.NumberColumn("Kurs €", min_value=0.0, format="euro", width=95),
            "Betrag": st.column_config.NumberColumn("Betrag €", format="euro", width=110),
        },
    )
    if marked:
        left, right, _ = st.columns([1.6, 1.4, 3], vertical_alignment="center")
        left.button(f"{len(marked)} markierte löschen", type="primary", icon=":material/delete:",
                    on_click=_delete_marked, args=(ctx.provider,))
        right.button("Markierung aufheben", type="tertiary", on_click=_clear_marks)
    undo = st.session_state.get("tx_undo")
    if undo and undo["provider"] == ctx.provider and undo["name"] == portfolio.name:
        st.button(f"Löschen rückgängig machen ({undo['count']})", type="tertiary", icon=":material/undo:",
                  on_click=_undo_delete, args=(ctx.provider,))
    undated = sum(1 for t in portfolio.transactions if t.date is None)
    st.caption("Werte direkt in der Tabelle ändern; zum Löschen Zeilen markieren."
               + (f" {undated} ohne Datum – bitte ergänzen, sonst fehlen sie in der Wertentwicklung." if undated
                  else ""))


# ---------------------------------------------------------------------------
# Wertentwicklung
# ---------------------------------------------------------------------------


def _performance(ctx: PortfolioContext, theme) -> None:
    perf = performance.compute(ctx.portfolio, ctx.prices) if not ctx.prices.empty else None
    if perf is None:
        st.info("Für die Wertentwicklung braucht es Transaktionen mit Datum und Kurs.")
        return
    if perf.skipped:
        st.caption(f"{perf.skipped} Transaktion(en) ohne Datum, Kurs oder Kursdaten sind nicht berücksichtigt.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Eingezahlt (netto)", f"{num(perf.invested.iloc[-1])} €",
              help="Summe der Käufe minus Verkaufserlöse.")
    c2.metric("Gewinn gesamt", f"{num(perf.gain)} €", help="Realisierte und unrealisierte Gewinne zusammen.")
    c3.metric("Persönliche Rendite p. a.", pct(perf.irr) if perf.irr is not None else "–",
              help="Interner Zinsfuß: berücksichtigt, wann wie viel investiert wurde.")
    c4.metric("Zeitgewichtete Rendite p. a.", pct(perf.twr_annual) if perf.twr_annual is not None else "–",
              help="Rendite unabhängig vom Zeitpunkt der Käufe – vergleichbar mit Fonds und Indizes.")

    st.markdown("**Depotwert und Einzahlungen**")
    show_chart(charts.value_chart(perf.value, perf.invested, theme))

    st.markdown("**Vergleich mit einem Index**", help="Beide Linien starten beim ersten Kauf mit 100 und zeigen die "
                "zeitgewichtete Kursentwicklung; ausgeschüttete Dividenden sind in beiden nicht enthalten.")
    markets = {i.symbol: i for i in get_provider(ctx.provider).instruments if i.kind == "market"}
    bench = st.selectbox("Index", list(markets), format_func=lambda s: markets[s].label, key="perf_bench",
                         label_visibility="collapsed", width=320)
    try:
        series = prices_eur(ctx.provider, (bench,), (markets[bench].currency,), perf.value.index[0].date(), ctx.end,
                            adjusted=False)
    except Exception as exc:  # Netzwerkfehler
        st.warning(f"Indexkurse nicht verfügbar: {exc}")
        series = pd.DataFrame()
    if bench in series:
        indexed, same_flows = performance.benchmark(perf, series[bench])
        show_chart(charts.benchmark_chart(perf.twr, indexed, markets[bench].label, theme))
        diff = perf.value.iloc[-1] - same_flows
        st.caption(f"Dieselben Ein- und Auszahlungen im {markets[bench].label} wären heute {num(same_flows)} € wert – "
                   f"dein Depot liegt {num(abs(diff))} € {'darüber' if diff >= 0 else 'darunter'}.")

    st.markdown("**Entwicklung je Position**", help="Gewinn oder Verlust seit dem ersten Kauf: aktueller Wert minus "
                "Einzahlungen plus Verkaufserlöse, also realisiert und unrealisiert.")
    labels = ctx.labels
    pnl = perf.position_pnl.rename(columns=labels)
    order = list(perf.position_value.iloc[-1].sort_values(ascending=False).rename(index=labels).index)
    chosen = st.multiselect("Positionen", order, default=order[:8], key="perf_positions",
                            label_visibility="collapsed")
    if chosen:
        show_chart(charts.position_pnl_chart(pnl[chosen], theme))


# ---------------------------------------------------------------------------
# Kursdaten und Aufteilung
# ---------------------------------------------------------------------------


def _market_data(run: RunState) -> None:
    if run.est is None:
        st.info("Kursdaten und Kennzahlen brauchen mindestens zwei Positionen mit gemeinsamer Kurshistorie.")
        return
    prices, est, theme = run.prices, run.est, run.theme
    st.caption(f"{prices.index[0]:%d.%m.%Y} – {prices.index[-1]:%d.%m.%Y}, dividendenbereinigt in Euro. Zeitraum "
               "unter Einstellungen.")
    show_chart(charts.price_chart(prices, theme))
    table = pd.DataFrame({
        "Erwartete Rendite p. a.": est.mu,
        "CAGR": (prices.iloc[-1] / prices.iloc[0]).to_numpy() ** (1 / est.years) - 1,
        "Volatilität p. a.": est.vol,
        "Sharpe-Ratio": (est.mu - run.settings.rf) / est.vol,
        "Max. Drawdown": data.max_drawdown(prices).to_numpy(),
    }, index=est.assets)
    st.dataframe(styled(table, pct_cols=("Erwartete Rendite p. a.", "CAGR", "Volatilität p. a.", "Max. Drawdown"),
                        ratio_cols=("Sharpe-Ratio",)))
    st.caption(f"Erwartete Rendite: {MEAN_ESTIMATORS[est.mean_method]} der Tagesrenditen, annualisiert – mit "
               "dieser Größe rechnet die Optimierung. CAGR: tatsächliches Wachstum p. a.")
    st.markdown("**Korrelationen**")
    corr = pd.DataFrame(est.corr, index=est.assets, columns=est.assets)
    show_chart(charts.correlation_heatmap(corr, theme))
    if st.toggle("Korrelationsmatrix als Tabelle", key="corr_table"):
        st.dataframe(corr.style.format(lambda v: ratio(v)))


def _allocation(ctx: PortfolioContext, theme) -> None:
    if ctx.value <= 0:
        st.info("Für die Aufteilung werden Kurse der Positionen benötigt.")
        return
    choice = st.segmented_control("Aufteilung nach", list(DIMENSIONS), default="Sektoren", key="pf_dim",
                                  required=True) or "Sektoren"
    by = DIMENSIONS[choice]
    shares = exposures(ctx.weights, ctx.infos, by)
    limits = current_limits()
    limited = {g for g in shares.index if is_concentration_group(by, g)}
    left, right = st.columns([3, 2])
    with left:
        show_chart(charts.exposure_chart(shares, theme, limits.for_kind(by), limited))
    with right:
        table = pd.DataFrame({"Anteil": shares, "Wert (EUR)": shares * ctx.value})
        table.index.name = {"sector": "Sektor", "currency": "Währung"}[by]
        st.dataframe(styled(table, pct_cols=("Anteil",), num_cols=("Wert (EUR)",)))
    notes = {
        "sector": "ETFs zählen mit ihren Sektorgewichten, soweit Yahoo sie liefert.",
        "currency": "Maßgeblich ist die Handelswährung – ein Welt-ETF in Euro enthält trotzdem Dollar-Risiko.",
    }
    st.caption(notes[by] + " Gestrichelt: Grenze aus dem Klumpenrisiko.")
