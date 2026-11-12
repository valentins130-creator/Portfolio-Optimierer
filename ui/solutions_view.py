"""Ebene 3 – Lösungen: Umschichtung und Absicherung."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from portfolio_optimizer import charts, concentration as conc, hedging as hg, optimization as opt
from portfolio_optimizer import rebalancing as rb
from portfolio_optimizer.formatting import num, pct, ratio, styled
from portfolio_optimizer.market import get_provider, major_currency
from ui.common import section, show_chart, show_flash
from ui.state import (
    PortfolioContext,
    RunState,
    current_limits,
    fx_weekly_returns,
    instrument_prices,
    prices_eur,
    security_info,
)


def render(run: RunState) -> None:
    show_flash()
    ctx = run.ctx
    if ctx.value <= 0 or ctx.weekly.dropna().shape[0] < 10:
        st.info("Für Lösungsvorschläge braucht das Portfolio Positionen mit Kursen und etwas Kurshistorie. "
                "Lege sie unter **Portfolio** an.")
        return
    report = conc.analyze(ctx.weights, ctx.infos, ctx.weekly, current_limits())
    if report.exceeded:
        n = len(report.exceeded)
        st.caption(f"{n} {'Konzentration' if n == 1 else 'Konzentrationen'} über den Grenzen – Details und Grenzen "
                   "unter Analysen → Klumpenrisiko.")
    if box := section("Umschichtung", "sec_rebalance", expanded=True, icon=":material/swap_horiz:"):
        with box:
            rebalancing(run, report)
    if box := section("Absicherung", "sec_hedge", icon=":material/shield:"):
        with box:
            hedges(ctx, report, run.theme)


# ---------------------------------------------------------------------------
# Umschichtung
# ---------------------------------------------------------------------------


def prices_for(ctx: PortfolioContext, symbols, infos) -> pd.DataFrame:
    """Kurse im Analysezeitraum, auch für Wertpapiere, die erst durch eine Umschichtung dazukommen."""
    have = [s for s in symbols if s in ctx.window.columns]
    extra = [s for s in symbols if s not in ctx.window.columns]
    if not extra:
        return ctx.window[have]
    px = prices_eur(ctx.provider, tuple(extra), tuple(infos[s].currency for s in extra), ctx.start, ctx.end)
    return pd.concat([ctx.window[have], px], axis=1)


def limits_plan(ctx: PortfolioContext, report: conc.ConcentrationReport, limits: conc.Limits,
                use_world: bool = True) -> tuple[pd.Series, dict, pd.Series, dict]:
    """Zielgewichte, die die Klumpenrisiko-Grenzen mit möglichst wenig Umschichtung einhalten.

    Liefert Zielgewichte, Stammdaten und Kurse (inklusive eines Welt-ETFs als Ausgleich, falls
    erlaubt) sowie den Überhang, der sich mit den vorhandenen Positionen nicht abbauen lässt.
    """
    infos = dict(ctx.infos)
    prices = ctx.quotes["price"].copy()
    current = ctx.weights.copy()
    world = get_provider(ctx.provider).world_fund
    if use_world and world not in current.index:
        try:
            infos[world] = security_info(ctx.provider, world)
            px = prices_eur(ctx.provider, (world,), (infos[world].currency,), ctx.start, ctx.end)
            prices[world] = float(px[world].dropna().iloc[-1])
            current[world] = 0.0
        except Exception:  # ohne Welt-ETF weiterrechnen
            infos.pop(world, None)
    target, remaining = rb.closest_to_limits(current, infos, limits, report.clusters)
    return target, infos, prices, remaining


def _target_weights(run: RunState, goal: str, report, use_world: bool) -> tuple[pd.Series | None, dict]:
    """Zielgewichte je Symbol und Zusatzinfos (Kurse, Stammdaten) für neue Positionen."""
    ctx, est, bounds = run.ctx, run.est, run.bounds
    infos = dict(ctx.infos)
    prices = ctx.quotes["price"].copy()
    if goal == "limits":
        target, infos, prices, remaining = limits_plan(ctx, report, current_limits(), use_world)
        if remaining:
            st.warning(
                "Mit den vorhandenen Positionen lassen sich nicht alle Grenzen einhalten. Der Vorschlag kommt ihnen "
                "so nahe wie möglich, ohne neue Überschreitungen zu erzeugen. Verbleibender Überhang: "
                + ", ".join(f"{label} +{pct(v)}" for label, v in list(remaining.items())[:4])
                + ". Abhilfe: Grenzen lockern, den Welt-ETF als Ausgleich zulassen oder breiter gestreute "
                "Positionen aufnehmen."
            )
        return target, {"infos": infos, "prices": prices, "unreachable": bool(remaining)}
    if est is None:
        st.info("Für dieses Ziel werden mindestens zwei Positionen mit gemeinsamer Kurshistorie benötigt.")
        return None, {}
    own = ctx.own_weights(est.assets)
    if goal == "same_risk":
        w = opt.efficient_risk(est.mu, est.cov, opt.portfolio_stats(own, est.mu, est.cov)[1], bounds)
    elif goal == "gmv":
        w = opt.min_variance(est.cov, bounds)
    else:
        w = opt.max_sharpe(est.mu, est.cov, run.settings.rf, bounds)
        if w is None:
            st.warning("Kein Portfolio erwartet eine Rendite über dem risikolosen Zins.")
            return None, {}
    if (w < -1e-9).any():
        st.warning("Die Zielgewichte enthalten Leerverkäufe. Für Umschichtungen bitte unter **Einstellungen** "
                   "Leerverkäufe ausschalten.")
        return None, {}
    by_label = {label: s for s, label in ctx.labels.items()}
    universe = [by_label[a] for a in est.assets]
    target = ctx.weights.copy()  # Positionen außerhalb der Analyse behalten ihr Gewicht
    target[universe] = w * ctx.weights[universe].sum()
    return target, {"infos": infos, "prices": prices}


def rebalancing(run: RunState, report: conc.ConcentrationReport) -> None:
    ctx, theme = run.ctx, run.theme
    goals = {"limits": "Klumpenrisiko begrenzen", "same_risk": "Effizient bei gleichem Risiko",
             "gmv": "Minimum-Varianz", "max_sharpe": "Max-Sharpe"}
    goal = st.radio("Ziel", list(goals), format_func=goals.get, horizontal=True, key="rb_goal")
    c1, c2, c3 = st.columns(3)
    use_world = c1.checkbox("Welt-ETF als Ausgleich zulassen", value=True, key="rb_world", disabled=goal != "limits",
                            help="Erlaubt den Kauf eines breit gestreuten Welt-ETFs, wenn die Grenzen sonst nicht "
                                 "einzuhalten sind.")
    whole = c2.toggle("Ganze Stückzahlen", value=True, key="rb_whole")
    min_trade = c3.number_input("Kleinstbetrag je Transaktion (EUR)", 0, 100_000, 50, 25, key="rb_min_trade",
                                help="Kleinere Umschichtungen werden ausgelassen.")
    target, extra = _target_weights(run, goal, report, use_world)
    if target is None:
        return
    infos, prices = extra["infos"], extra["prices"]
    tr = rb.trades(ctx.valued, target, prices, whole_shares=whole, min_trade=float(min_trade),
                   sale_gain=ctx.portfolio.sale_gain)
    buys, sells = tr.loc[tr["amount"] > 0, "amount"].sum(), -tr.loc[tr["amount"] < 0, "amount"].sum()
    realized = tr["realized_gain"].sum(min_count=1)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Käufe", f"{num(buys)} €")
    m2.metric("Verkäufe", f"{num(sells)} €")
    m3.metric("Restliquidität", f"{num(sells - buys)} €",
              help="Positiv: bleibt als Guthaben übrig (Rundung, ausgelassene Kleinbeträge). Negativ: wird "
                   "zusätzlich benötigt.")
    m4.metric("Realisierte Gewinne", f"{num(realized)} €" if pd.notna(realized) else "–",
              help="Aus den vorgeschlagenen Verkäufen nach FIFO (zuerst gekaufte Stücke zuerst), sofern "
                   "Kaufkurse erfasst sind. Gewinne unterliegen der Abgeltungsteuer.")
    active = tr[tr["action"] != "Halten"]
    if active.empty:
        st.success("Das Depot erfüllt das Ziel bereits – keine Umschichtung nötig.")
    else:
        table = pd.DataFrame({
            "Name": [infos[s].name if s in infos else s for s in active.index], "Aktion": active["action"],
            "Stück": active["shares_delta"].abs(), "Betrag (EUR)": active["amount"].abs(),
            "Gewicht vorher": active["weight_before"], "Gewicht nachher": active["weight_after"],
        })
        st.dataframe(styled(table, pct_cols=("Gewicht vorher", "Gewicht nachher"), num_cols=("Betrag (EUR)",))
                     .format(lambda v: num(v, 0 if whole else 2), subset=["Stück"]), hide_index=True)
    order = tr.sort_values("weight_before", ascending=False).index
    labels = [ctx.labels.get(s, infos[s].name if s in infos else s) for s in order]
    show_chart(charts.comparison_chart(labels, tr.loc[order, "weight_before"].to_numpy(),
                                       tr.loc[order, "weight_after"].to_numpy(), theme, "Gewicht"))
    after = tr["weight_after"][tr["weight_after"] > 0]  # bezogen auf den Depotwert inklusive Restliquidität
    after_report = conc.analyze(after, infos, hg.weekly_returns(prices_for(ctx, after.index, infos)),
                                current_limits())
    if goal == "limits":
        if after_report.exceeded:
            reason = ("nicht vollständig erreichbar, siehe oben" if extra.get("unreachable")
                      else "Rundung oder ausgelassene Kleinbeträge")
            st.info(f"Nach der Umschichtung noch über den Grenzen ({reason}): "
                    + ", ".join(f"{f.group} {pct(f.weight)}" for f in after_report.exceeded))
        else:
            st.success("Nach der Umschichtung liegen alle Konzentrationen innerhalb der Grenzen.")
    else:
        st.caption("Optimierte Ziele beruhen auf geschätzten Renditen – wie unsicher die sind, zeigt Analysen → "
                   "Schätzfehler.")
    st.caption("Ohne Transaktionskosten und Steuern. Keine Anlageberatung.")


# ---------------------------------------------------------------------------
# Absicherung
# ---------------------------------------------------------------------------


def hedges(ctx: PortfolioContext, report: conc.ConcentrationReport, theme) -> None:
    provider = get_provider(ctx.provider)
    try:
        inst_ret = hg.weekly_returns(instrument_prices(ctx.provider, ctx.start, ctx.end))
    except Exception as exc:  # Netzwerkfehler
        st.error(f"Kurse der Absicherungsinstrumente konnten nicht geladen werden: {exc}")
        return
    port = hg.portfolio_returns(ctx.weights, ctx.weekly)
    if len(port) < hg.MIN_OBSERVATIONS:
        st.info("Für Absicherungsvorschläge wird mindestens ein halbes Jahr gemeinsamer Kurshistorie benötigt.")
        return
    value = ctx.value
    tab_market, tab_mix, tab_cluster = st.tabs(["Markt-Hedge (Beta)", "Beimischung", "Klumpenrisiko absichern"])

    with tab_market:
        quote = st.slider("Absicherungsquote", 0, 100, 100, 10, format="%d %%", key="hedge_ratio",
                          help="Welcher Teil des Marktrisikos abgesichert werden soll.") / 100
        items = hg.beta_hedges(port, inst_ret, provider.instruments, value, quote)
        if items:
            best = items[0]
            st.markdown(
                f"Am besten erklärt **{best.instrument.label}** dein Depot (R² {ratio(best.r2)}, Beta "
                f"{ratio(best.beta)}). Eine Short-Position von **{num(best.notional)} €** senkt die Volatilität "
                f"von {pct(best.vol_before)} auf **{pct(best.vol_after)}** und den größten historischen Rückgang "
                f"von {pct(best.mdd_before)} auf {pct(best.mdd_after)}."
            )
            table = pd.DataFrame([{
                "Index": h.instrument.label, "Beta": h.beta, "R²": h.r2, "Short-Betrag (EUR)": h.notional,
                "Volatilität danach": h.vol_after, "Max. Rückgang danach": h.mdd_after,
                "Rendite p. a. danach": h.ret_after,
            } for h in items])
            st.dataframe(styled(table, pct_cols=("Volatilität danach", "Max. Rückgang danach", "Rendite p. a. danach"),
                                ratio_cols=("Beta", "R²"), num_cols=("Short-Betrag (EUR)",)), hide_index=True)
            st.caption("Umsetzung über Index-Futures, Short-ETFs oder Puts; mit dem Risiko sichert man auch die "
                       "Marktrendite ab. Werte historisch, ohne Kosten.")
        else:
            st.info("Für die Marktindizes liegen keine ausreichenden Kurse vor.")

    with tab_mix:
        share = st.slider("Anteil der Beimischung", 5, 50, 20, 5, format="%d %%", key="mix_share",
                          help="Welcher Teil des Depots in die Beimischung umgeschichtet würde.") / 100
        divs = hg.diversifiers(port, inst_ret, provider.instruments, share, exclude=set(ctx.weights.index))
        if divs:
            table = pd.DataFrame([{
                "Beimischung": d.instrument.label, "Korrelation": d.corr, "Eigene Volatilität": d.vol,
                "Depot-Volatilität danach": d.vol_after, "Max. Rückgang danach": d.mdd_after,
                "Rendite p. a. danach": d.ret_after,
            } for d in divs])
            st.dataframe(styled(table, pct_cols=("Eigene Volatilität", "Depot-Volatilität danach",
                                                 "Max. Rückgang danach", "Rendite p. a. danach"),
                                ratio_cols=("Korrelation",)), hide_index=True)
            st.caption(f"Ohne Beimischung: Volatilität {pct(divs[0].vol_before)}, größter Rückgang "
                       f"{pct(divs[0].mdd_before)}, Rendite p. a. {pct(divs[0].ret_before)} (historisch).")
            curves = {d.instrument.label: hg.mix_curve(port, inst_ret[d.instrument.symbol], np.linspace(0, 0.6, 25))
                      for d in divs[:3]}
            show_chart(charts.mix_curve_chart(curves, theme, share))

    with tab_cluster:
        currencies = tuple(sorted({major_currency(i.currency)[0] for i in ctx.infos.values()}))
        fx_ret = fx_weekly_returns(ctx.provider, currencies, ctx.start, ctx.end)
        items = hg.concentration_hedges(report.findings, ctx.weights, ctx.weekly, value, inst_ret,
                                        provider.instruments, fx_ret)
        if not items:
            st.success("Keine Konzentration über den Grenzen – hier gibt es nichts abzusichern.")
        for item in items:
            f = item.finding
            with st.container(border=True):
                st.markdown(f":red-badge[{conc.KINDS[f.kind]}] **{f.group}** – {pct(f.weight)} des Depots, Grenze "
                            f"{pct(f.limit, 0)}")
                left, right = st.columns(2)
                left.markdown(f"**Reduzieren:** {num(item.reduce_amount)} € verkaufen und breiter anlegen "
                              "(siehe **Umschichtung**).")
                if item.instrument is None:
                    right.markdown("**Absichern:** kein passendes Instrument mit ausreichender Historie gefunden.")
                elif f.kind == "currency":
                    right.markdown(f"**Absichern:** {f.group} im Wert von {num(item.notional)} € per "
                                   "Devisentermingeschäft verkaufen oder währungsgesicherte Anteilsklassen "
                                   f"(„EUR Hedged“) nutzen. Depot-Volatilität {pct(item.vol_before)} → "
                                   f"**{pct(item.vol_after)}**.")
                else:
                    right.markdown(f"**Absichern:** Short {num(item.notional)} € **{item.instrument.label}** "
                                   f"(Beta {ratio(item.beta)}, R² {ratio(item.r2)}). Depot-Volatilität "
                                   f"{pct(item.vol_before)} → **{pct(item.vol_after)}**.")
        st.caption("Abgesichert wird nur der Teil über der Grenze. Historische Wochenrenditen in Euro; keine "
                   "Anlageberatung.")
