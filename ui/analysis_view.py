"""Ebene 2 – Analysen: Klumpenrisiko, Markowitz, Monte Carlo, Schätzfehler."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from portfolio_optimizer import charts, concentration as conc, data, monte_carlo as mc, optimization as opt
from portfolio_optimizer import instability as ins
from portfolio_optimizer.formatting import num, pct, ratio, styled
from ui.common import delta, section, show_chart, show_flash
from ui.state import PortfolioContext, RunState, current_limits

TARGET = charts.TARGET_PORTFOLIO
OWN = charts.OWN_PORTFOLIO


def render(run: RunState) -> None:
    show_flash()
    ctx = run.ctx
    if ctx.value <= 0 or ctx.weekly.dropna().shape[0] < 10:
        st.info("Für die Analysen braucht das Portfolio Positionen mit Kursen und etwas Kurshistorie. "
                "Lege sie unter **Portfolio** an.")
        return
    if box := section("Klumpenrisiko", "sec_cluster", expanded=True, icon=":material/bubble_chart:"):
        with box:
            concentration(ctx, run.theme)
    if run.est is None:
        st.info("Markowitz, Monte Carlo und Schätzfehler brauchen mindestens zwei Positionen mit gemeinsamer "
                "Kurshistorie.")
        return
    if run.bounds_error:
        st.warning(run.bounds_error)
    if box := section("Markowitz – Efficient Frontier", "sec_frontier", icon=":material/stacked_line_chart:"):
        with box:
            frontier(run)
    if box := section("Monte Carlo", "sec_mc", icon=":material/ssid_chart:"):
        with box:
            monte_carlo(run)
    if box := section("Schätzfehler", "sec_error", icon=":material/troubleshoot:"):
        with box:
            estimation_error(run)


# ---------------------------------------------------------------------------
# Klumpenrisiko
# ---------------------------------------------------------------------------


def _limits_popover() -> conc.Limits:
    d = current_limits()
    with st.popover("Grenzen anpassen", icon=":material/tune:"):
        position = st.slider("Einzelaktie", 2, 50, int(d.position * 100), 1, format="%d %%", key="lim_position")
        sector = st.slider("Sektor", 10, 80, int(d.sector * 100), 5, format="%d %%", key="lim_sector")
        currency = st.slider("Fremdwährung (je Währung)", 10, 100, int(d.currency * 100), 5, format="%d %%",
                             key="lim_currency")
        cluster = st.slider("Korrelations-Cluster", 10, 100, int(d.cluster * 100), 5, format="%d %%",
                            key="lim_cluster")
        corr = st.slider("Korrelation ab", 0.5, 0.95, float(d.correlation), 0.05, key="lim_corr",
                         help="Einzelwerte, die im Mittel mindestens so stark korrelieren, bilden einen Cluster.")
        st.caption("Fonds und ETFs zählen nicht als Einzelaktie, weil sie selbst breit gestreut sind. Euro, "
                   "Anleihen und Geldmarkt sind von den Grenzen ausgenommen.")
    limits = conc.Limits(position=position / 100, sector=sector / 100, currency=currency / 100,
                         cluster=cluster / 100, correlation=corr)
    st.session_state["pf_limits"] = limits
    return limits


def concentration(ctx: PortfolioContext, theme) -> conc.ConcentrationReport:
    limits = _limits_popover()
    report = conc.analyze(ctx.weights, ctx.infos, ctx.weekly, limits)
    singles = [w for s, w in ctx.weights.items() if not ctx.infos[s].is_fund]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Effektive Anzahl Positionen", num(report.effective_positions, 1),
              help="1 / Herfindahl-Index: So viele gleich große Positionen hätten dieselbe Konzentration.")
    c2.metric("Top-5-Anteil", pct(report.top5))
    c3.metric("Größte Einzelaktie", pct(max(singles)) if singles else "–")
    c4.metric("Diversifikationsquote", ratio(report.diversification_ratio),
              help="Gewichtete Einzelvolatilitäten geteilt durch die Depotvolatilität. Je höher, desto mehr "
                   "gleichen sich die Positionen gegenseitig aus (1 = keine Streuungswirkung).")
    if report.exceeded:
        st.markdown("**Über den Grenzen**")
        st.markdown("  \n".join(
            f":red-badge[{conc.KINDS[f.kind]}] **{f.group}** – {pct(f.weight)} des Depots, Grenze {pct(f.limit, 0)}, "
            f"{pct(f.risk_share)} der Schwankung" for f in report.exceeded))
        st.caption("Vorschläge dazu unter Lösungen.")
    else:
        st.success("Keine Konzentration über den Grenzen.")
    near = [f for f in report.findings if f.status == "nahe Grenze"]
    if near:
        st.caption("Nahe an der Grenze: " + ", ".join(f"{f.group} ({pct(f.weight)})" for f in near))
    st.markdown("**Gewicht und Risikoanteil je Position**", help="Der Risikoanteil ist der Teil der "
                "Depotschwankung, der auf eine Position entfällt. Liegt er deutlich über dem Gewicht, ist die "
                "Position volatil oder läuft stark mit dem Rest des Depots.")
    order = ctx.weights.sort_values(ascending=False).index
    show_chart(charts.weight_risk_chart([ctx.labels[s] for s in order], ctx.weights[order].to_numpy(),
                                        report.risk_shares.reindex(order).to_numpy(), theme))
    if st.toggle("Alle Konzentrationen als Tabelle", key="cluster_table"):
        rows = [{"Art": conc.KINDS[f.kind], "Gruppe": f.group, "Gewicht": f.weight, "Risikoanteil": f.risk_share,
                 "Grenze": f.limit, "Status": f.status} for f in report.findings]
        st.dataframe(styled(pd.DataFrame(rows), pct_cols=("Gewicht", "Risikoanteil", "Grenze")), hide_index=True)
    return report


# ---------------------------------------------------------------------------
# Markowitz
# ---------------------------------------------------------------------------


def target_weights(run: RunState) -> tuple[np.ndarray, float]:
    """Effizientes Portfolio beim gewählten Zielrisiko (Standard: Risiko des eigenen Depots)."""
    est, bounds = run.est, run.bounds
    own = run.ctx.own_weights(est.assets)
    default = opt.portfolio_stats(own, est.mu, est.cov)[1]
    target = st.session_state.get("frontier_target", default)
    return opt.efficient_risk(est.mu, est.cov, target, bounds), target


def standard_portfolios(run: RunState) -> dict[str, np.ndarray]:
    est, bounds = run.est, run.bounds
    n = len(est.assets)
    named = {
        OWN: run.ctx.own_weights(est.assets),
        TARGET: target_weights(run)[0],
        "Max-Sharpe": opt.max_sharpe(est.mu, est.cov, run.settings.rf, bounds),
        "Minimum-Varianz": opt.min_variance(est.cov, bounds),
        "Gleichgewichtet (1/N)": np.full(n, 1 / n),
    }
    return {k: v for k, v in named.items() if v is not None}


def _keep_target() -> None:
    st.session_state["frontier_target"] = st.session_state["frontier_target_widget"]


def frontier(run: RunState) -> None:
    est, bounds, rf, theme = run.est, run.bounds, run.settings.rf, run.theme
    curve = opt.efficient_frontier(est.mu, est.cov, bounds, n_points=60)
    w_gmv = opt.min_variance(est.cov, bounds)
    w_ms = opt.max_sharpe(est.mu, est.cov, rf, bounds)
    own = run.ctx.own_weights(est.assets)
    vol_gmv = opt.portfolio_stats(w_gmv, est.mu, est.cov)[1]
    vol_max = float(curve.vols.max())
    if w_ms is None:
        st.warning("Kein zulässiges Portfolio erwartet eine Rendite über dem risikolosen Zins – das "
                   "Max-Sharpe-Portfolio existiert daher nicht.")

    target_vol = vol_gmv
    if vol_max - vol_gmv > 0.002:
        options = [round(v, 3) for v in np.arange(np.ceil(vol_gmv * 1000), np.floor(vol_max * 1000) + 1) / 1000]
        wanted = st.session_state.get("frontier_target", opt.portfolio_stats(own, est.mu, est.cov)[1])
        nearest = min(options, key=lambda v: abs(v - wanted))
        if st.session_state.get("frontier_target_widget") not in options:
            st.session_state["frontier_target_widget"] = nearest
        target_vol = st.select_slider(
            "Zielrisiko (Volatilität)", options=options, format_func=pct, key="frontier_target_widget",
            on_change=_keep_target,
            help="Wählt das effiziente Portfolio mit der höchsten erwarteten Rendite bei diesem Risiko. "
                 "Voreingestellt ist das Risiko deines Depots.",
        )
    w_target = opt.efficient_risk(est.mu, est.cov, target_vol, bounds)
    ret_t, vol_t, sharpe_t = opt.portfolio_stats(w_target, est.mu, est.cov, rf)
    ret_o, vol_o, sharpe_o = opt.portfolio_stats(own, est.mu, est.cov, rf)
    c1, c2, c3 = st.columns(3)
    c1.metric("Erwartete Rendite p. a.", pct(ret_t), **delta(ret_t - ret_o, pct(ret_t - ret_o, signed=True)
                                                              + " ggü. Depot"))
    c2.metric("Volatilität p. a.", pct(vol_t), **delta(vol_t - vol_o, pct(vol_t - vol_o, signed=True)
                                                       + " ggü. Depot", inverse=True))
    diff = sharpe_t - sharpe_o
    c3.metric("Sharpe-Ratio", ratio(sharpe_t), **delta(diff, ("+" if diff > 0 else "") + ratio(diff) + " ggü. Depot",
                                                       tol=0.005))
    st.caption(f"{TARGET} gegenüber deinem Depot (Rendite {pct(ret_o)}, Volatilität {pct(vol_o)}) – auf Basis "
               "geschätzter Renditen, siehe Schätzfehler.")

    named = {OWN: own, TARGET: w_target, "Max-Sharpe": w_ms, "Minimum-Varianz": w_gmv}
    named = {k: v for k, v in named.items() if v is not None}
    points = {k: opt.portfolio_stats(w, est.mu, est.cov)[1::-1] for k, w in named.items()}
    cloud = opt.random_portfolios(est.mu, est.cov, 3000, seed=1, bounds=bounds)
    show_chart(charts.frontier_chart(curve, est.assets, est.vol, est.mu, points, theme,
                                     rf=rf if w_ms is not None else None, cloud=cloud))
    st.caption("Grau: zufällige Mischungen. Gestrichelt: Kapitalmarktlinie durch das Max-Sharpe-Portfolio."
               + ("" if charts.labels_fit(est.assets) else " Namen der Einzelwerte beim Überfahren."))

    left, right = st.columns(2)
    with left:
        st.markdown("**Gewichte je Portfolio**")
        show_chart(charts.weights_chart(pd.DataFrame(named, index=est.assets), theme))
    with right:
        st.markdown("**Zusammensetzung der effizienten Portfolios je Risikoniveau**", help="Jeder senkrechte "
                    "Schnitt ist ein effizientes Portfolio; die Flächen zeigen seine Gewichte (zusammen 100 %). "
                    "Nach rechts steigen Risiko und erwartete Rendite. Gestrichelt: das gewählte Zielrisiko.")
        show_chart(charts.transition_chart(curve, est.assets, theme, marker=target_vol))

    if st.toggle("Gewichte und Kennzahlen als Tabelle", key="frontier_table"):
        all_named = named | {"Gleichgewichtet (1/N)": np.full(len(est.assets), 1 / len(est.assets))}
        st.dataframe(styled(pd.DataFrame(all_named, index=est.assets), pct_cols=tuple(all_named)))
        stats = pd.DataFrame([opt.portfolio_stats(w, est.mu, est.cov, rf) for w in all_named.values()],
                             index=list(all_named), columns=["Rendite p. a.", "Volatilität p. a.", "Sharpe-Ratio"])
        st.dataframe(styled(stats, pct_cols=("Rendite p. a.", "Volatilität p. a."), ratio_cols=("Sharpe-Ratio",)))
    with st.popover("Methodik", icon=":material/menu_book:"):
        st.markdown("Für jede Zielrendite $r^*$ löst der Optimierer das Markowitz-Problem")
        st.latex(r"\min_w \; w^\top \Sigma w \quad \text{u. d. N.} \quad w^\top \mu = r^*,\; "
                 r"\mathbf{1}^\top w = 1,\; l \le w_i \le u")
        st.markdown("Das **Max-Sharpe-Portfolio** maximiert $(w^\\top\\mu - r_f)/\\sqrt{w^\\top\\Sigma w}$. "
                    "Ohne Gewichtsgrenzen gibt es geschlossene Lösungen, sonst wird numerisch (SLSQP) optimiert. "
                    "$\\mu$ und $\\Sigma$ stammen aus Tagesrenditen in Euro, annualisiert mit 252 Handelstagen.")


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner="Simuliere Pfade…", max_entries=20)
def run_simulation(method, weights, mu, cov, returns, years, n_paths, initial, contribution, seed):
    if method == "gbm":
        return mc.simulate_gbm(weights, mu, cov, years, n_paths, initial, contribution, seed=seed)
    return mc.simulate_bootstrap(weights, returns, years, n_paths, initial, contribution, seed=seed)


def monte_carlo(run: RunState) -> None:
    est, theme = run.est, run.theme
    portfolios = standard_portfolios(run)
    if st.session_state.get("mc_portfolio") not in portfolios:
        st.session_state.pop("mc_portfolio", None)
    c1, c2 = st.columns(2)
    choice = c1.selectbox("Portfolio", list(portfolios), key="mc_portfolio",
                          format_func=lambda k: {OWN: "Mein Portfolio (aktuelle Gewichte)"}.get(k, k))
    method = c2.radio("Verfahren", ["gbm", "bootstrap"], horizontal=True, key="mc_method",
                      format_func={"gbm": "Parametrisch (GBM)", "bootstrap": "Historisches Bootstrap"}.get,
                      help="Parametrisch: korrelierte geometrische Brownsche Bewegung mit den geschätzten "
                           "Parametern. Bootstrap: zieht zufällige Monatsblöcke aus den tatsächlichen Tagesrenditen.")
    c3, c4, c5, c6 = st.columns(4)
    initial = c3.number_input("Anfangskapital", 0, 100_000_000, int(round(run.ctx.value)) or 10_000, 1_000,
                              key="mc_initial")
    contribution = c4.number_input("Sparrate pro Monat", 0, 1_000_000, 0, 50, key="mc_contribution")
    years = c5.slider("Anlagehorizont (Jahre)", 1, 40, 10, key="mc_years")
    n_paths = c6.select_slider("Anzahl Pfade", [500, 1_000, 2_000, 5_000, 10_000], value=2_000, key="mc_paths")
    with st.popover("Weitere Einstellungen", icon=":material/tune:"):
        target = st.number_input("Zielvermögen (0 = ohne)", 0, 1_000_000_000, 0, 1_000, key="mc_target")
        seed = st.number_input("Zufallszahl (Seed)", 0, 10_000, 7, key="mc_seed")
    if initial == 0 and contribution == 0:
        st.info("Bitte ein Anfangskapital oder eine Sparrate angeben.")
        return
    sim = run_simulation(method, portfolios[choice], est.mu, est.cov, run.returns.to_numpy(), years, n_paths,
                         float(initial), float(contribution), int(seed))
    s = sim.summary(target=float(target) if target > 0 else None)
    cols = st.columns(5 if target > 0 else 4)
    cols[0].metric("Median-Endvermögen", f"{num(s['median'])} €", help=f"Eingezahlt: {num(s['invested'])} €")
    cols[1].metric("Ungünstig (5-%-Quantil)", f"{num(s['p5'])} €",
                   help=f"In 5 % der Pfade endet das Vermögen darunter. Mittel dieser Pfade (CVaR): {num(s['cvar5'])} €")
    cols[2].metric("Verlustwahrscheinlichkeit", pct(s["prob_loss"]),
                   help="Anteil der Pfade, die unter dem eingezahlten Kapital enden.")
    cols[3].metric("Rendite p. a. (Median)", pct(s["cagr_median"]),
                   help=f"Zeitgewichtet, ohne Einfluss der Sparrate. Typischer maximaler Drawdown: "
                        f"{pct(s['max_dd_median'])}")
    if target > 0:
        cols[4].metric("Ziel erreicht", pct(s["prob_target"]), help=f"Anteil der Pfade mit mindestens {num(target)} €")
    st.markdown("**Mögliche Vermögensentwicklungen**")
    show_chart(charts.fan_chart(sim, theme))
    left, right = st.columns(2)
    with left:
        st.markdown("**Verteilung des Endvermögens**")
        show_chart(charts.final_wealth_histogram(sim, theme))
        st.caption("Darstellung bis zum 99,5-%-Quantil.")
    with right:
        st.markdown("**Perzentile**")
        marks = sorted({y for y in (1, 3, 5, 10, 15, 20, 25, 30, 40) if y < years} | {years})
        q = sim.percentiles().loc[[float(y) for y in marks]]
        q.insert(0, "Eingezahlt", sim.invested[[int(y * 12) for y in marks]])
        q.index = [f"{y} J." for y in marks]
        st.dataframe(styled(q, num_cols=tuple(q.columns)))
        st.caption(f"Maximaler Drawdown: Median {pct(s['max_dd_median'])}, in 5 % der Pfade über "
                   f"{pct(s['max_dd_p95'])} (auf Monatsbasis).")
    st.caption("Die Simulation behandelt die geschätzten Renditen als bekannt – wie unsicher sie sind, zeigt "
               "Schätzfehler." if method == "gbm" else
               "Das Bootstrap wiederholt die Vergangenheit in zufälliger Reihenfolge; ihre Durchschnittsrendite "
               "steckt in jedem Pfad – siehe Schätzfehler.")


# ---------------------------------------------------------------------------
# Schätzfehler
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False, max_entries=10)
def run_frontier_experiment(assets, mu, cov, n_obs, bounds, seed):
    return ins.frontier_experiment(ins.Model(list(assets), mu, cov), n_obs, n_trials=20, bounds=bounds, seed=seed)


@st.cache_data(show_spinner=False, max_entries=10)
def run_strategy_experiment(assets, mu, cov, n_obs, n_trials, rf, bounds, strategies, seed):
    return ins.strategy_experiment(ins.Model(list(assets), mu, cov), n_obs, n_trials, rf, bounds,
                                   strategies=strategies, n_resamples=20, seed=seed)


def sensitivity_turnovers(est, rf, bounds, shift) -> np.ndarray:
    """Umschichtung des Max-Sharpe-Portfolios, wenn jeweils ein Asset um ``shift`` geändert wird."""
    out = np.full(len(est.assets), np.nan)
    for i in range(len(est.assets)):
        before, after = ins.perturbed_weights(est.mu, est.cov, rf, bounds, i, shift)
        if before is not None and after is not None:
            out[i] = ins.turnover(before, after)
    return out


def estimation_error(run: RunState) -> None:
    est, rf, bounds, theme = run.est, run.settings.rf, run.bounds, run.theme
    st.markdown("Die Optimierung behandelt Schätzungen als exakt. Sie bevorzugt daher systematisch Assets, deren "
                "Rendite zufällig **überschätzt** und deren Risiko **unterschätzt** wurde. Michaud (1989) nannte "
                "Mean-Variance-Optimierer deshalb „Fehlermaximierer“.")

    st.markdown("#### 1 · Wie genau sind die Schätzungen?")
    err = ins.estimation_error_table(run.returns)
    err.index = est.assets
    left, right = st.columns([3, 2])
    with left:
        show_chart(charts.confidence_chart(err, theme))
    with right:
        typical_vol = float(err["vol"].median())
        st.metric("Datenhistorie", f"{num(est.years, 1)} Jahre")
        st.metric("Ø Breite des 95-%-Intervalls", pct((err["ci_high"] - err["ci_low"]).mean()))
        st.markdown(f"Bei einer typischen Volatilität von **{pct(typical_vol)}** wären rund "
                    f"**{num((typical_vol / 0.01) ** 2)} Jahre** Daten nötig, damit der Standardfehler der "
                    "erwarteten Rendite auf **1 Prozentpunkt** sinkt. Volatilitäten und Korrelationen lassen sich "
                    "dagegen deutlich genauer schätzen.")
    if st.toggle("Schätzung und Standardfehler als Tabelle", key="error_table"):
        table = err.rename(columns={"mu": "Mittelwert p. a.", "vol": "Volatilität p. a.", "se": "Standardfehler",
                                    "ci_low": "95 %: von", "ci_high": "95 %: bis", "years_needed": "Jahre für ±1 Pp."})
        st.dataframe(styled(table, pct_cols=("Mittelwert p. a.", "Volatilität p. a.", "Standardfehler",
                                             "95 %: von", "95 %: bis"), num_cols=("Jahre für ±1 Pp.",)))

    st.markdown("#### 2 · Kleine Änderung, große Wirkung")
    st.markdown("Ändere die erwartete Rendite **eines** Assets um einen Bruchteil seiner Schätzunsicherheit und "
                "beobachte, wie stark sich das Max-Sharpe-Portfolio umbaut (Best & Grauer 1991).")
    c1, c2 = st.columns(2)
    shift = c2.slider("Änderung der erwarteten Rendite (Prozentpunkte)", -3.0, 3.0, 1.0, 0.25, format="%+.2f",
                      key="sens_delta")
    turnovers = sensitivity_turnovers(est, rf, bounds, shift / 100)
    if st.session_state.get("sens_asset") not in est.assets:
        best = int(np.nanargmax(turnovers)) if np.isfinite(turnovers).any() else 0
        st.session_state["sens_asset"] = est.assets[best]
    asset = c1.selectbox("Asset", est.assets, key="sens_asset",
                         help="Voreingestellt ist das Asset, auf dessen Änderung das Portfolio am stärksten reagiert.")
    idx = est.assets.index(asset)
    before, after = ins.perturbed_weights(est.mu, est.cov, rf, bounds, idx, shift / 100)
    if before is None or after is None:
        st.warning("Für diese Einstellung existiert kein Max-Sharpe-Portfolio (keine Rendite über dem risikolosen Zins).")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Umschichtung", pct(ins.turnover(before, after)),
                  help="Anteil des Portfolios, der umgeschichtet werden muss: ½ · Σ |Δw|")
        m2.metric("Ø Umschichtung über alle Assets", pct(float(np.nanmean(turnovers))))
        m3.metric("Standardfehler der Schätzung", pct(err["se"].iloc[idx]),
                  help=f"Standardfehler der erwarteten Rendite von {asset}.")
        show_chart(charts.sensitivity_chart(est.assets, before, after, theme))

    st.markdown("#### 3 · Simulationsexperiment: geschätzt vs. tatsächlich")
    st.markdown("Wir tun so, als kennten wir die **wahren** Parameter, simulieren daraus viele alternative "
                "Kurshistorien, schätzen auf jeder neu, optimieren – und bewerten das Ergebnis mit den wahren "
                "Parametern. So wird sichtbar, was der Optimierer *verspricht* und was er *liefert*.")
    with st.form("experiment"):
        scenario = st.radio("Wahres Modell", ["data", "identical"], horizontal=True,
                            format_func={"data": "Aktuelle Schätzungen deines Depots",
                                         "identical": "Identische Assets (Optimum = 1/N)"}.get)
        f1, f2, f3 = st.columns(3)
        hist_years = f1.slider("Länge jeder simulierten Historie (Jahre)", 1, 30,
                               int(np.clip(round(est.years), 1, 30)))
        n_trials = f2.select_slider("Anzahl Durchläufe", [50, 100, 200, 300], value=100)
        seed = f3.number_input("Zufallszahl (Seed)", 0, 10_000, 1)
        st.caption("Nur für „Identische Assets“:")
        g1, g2, g3, g4 = st.columns(4)
        id_n = g1.number_input("Anzahl Assets", 2, data.MAX_ASSETS, max(2, len(est.assets)))
        id_mu = g2.number_input("Rendite p. a. (%)", -5.0, 30.0, 7.0, 0.5)
        id_vol = g3.number_input("Volatilität p. a. (%)", 1.0, 80.0, 20.0, 1.0)
        id_corr = g4.number_input("Korrelation", -0.2, 0.95, 0.3, 0.05)
        submitted = st.form_submit_button("Experiment starten", type="primary")
    if submitted:
        try:
            model = (ins.model_from_estimates(est) if scenario == "data"
                     else ins.identical_assets_model(int(id_n), id_mu / 100, id_vol / 100, float(id_corr)))
            opt.validate_bounds(len(model.mu), bounds)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state["experiment_params"] = {
            "assets": tuple(model.assets), "mu": model.mu, "cov": model.cov, "scenario": scenario,
            "n_obs": int(hist_years * 252), "n_trials": int(n_trials), "rf": rf, "bounds": bounds, "seed": int(seed),
        }
    params = st.session_state.get("experiment_params")
    if params is None:
        st.caption("Das Experiment rechnet je nach Einstellung einige Sekunden.")
    else:
        _render_experiment(params, est, rf, bounds, theme)

    st.markdown("#### Was hilft?")
    st.markdown(
        "- **Weniger schätzen:** Minimum-Varianz braucht keine Renditeschätzungen, 1/N gar keine Schätzung.\n"
        "- **Shrinkage:** Bayes-Stein und Ledoit-Wolf (unter **Einstellungen**) dämpfen Ausreißer der Schätzung.\n"
        "- **Restriktionen:** Long-only und Höchstgewichte begrenzen den Schaden extremer Schätzungen.\n"
        "- **Resampling:** Optimale Gewichte über viele plausible Parametersätze mitteln (Michaud).\n"
        "- **Gleichgewichtsrenditen:** Black-Litterman startet bei markt-impliziten Renditen."
    )
    with st.popover("Literatur", icon=":material/menu_book:"):
        st.markdown(
            "- Best & Grauer (1991), *Review of Financial Studies* 4(2)\n"
            "- Broadie (1993), *Annals of Operations Research* 45\n"
            "- Chopra & Ziemba (1993), *Journal of Portfolio Management* 19(2)\n"
            "- DeMiguel, Garlappi & Uppal (2009), *Review of Financial Studies* 22(5)\n"
            "- Jagannathan & Ma (2003), *Journal of Finance* 58(4)\n"
            "- Jorion (1986), *Journal of Financial and Quantitative Analysis* 21(3)\n"
            "- Ledoit & Wolf (2004), *Journal of Portfolio Management* 30(4)\n"
            "- Markowitz (1952), *Journal of Finance* 7(1)\n"
            "- Michaud (1989), *Financial Analysts Journal* 45(1); Michaud (1998), *Efficient Asset Management*"
        )


def _findings(summary: pd.DataFrame, opt_sharpe: float, params: dict) -> str:
    sample, equal = summary.loc["ms_sample"], summary.loc["equal"]
    lines = [
        f"**Ergebnis aus {params['n_trials']} simulierten Historien à {num(params['n_obs'] / 252, 0)} Jahren:**",
        "",
        f"- Das Max-Sharpe-Portfolio aus Stichprobenschätzern **verspricht** im Mittel eine Sharpe-Ratio von "
        f"**{ratio(sample['sharpe_est_mean'])}**, **liefert** aber nur **{ratio(sample['sharpe_true_mean'])}**. "
        f"Das wahre Optimum liegt bei **{ratio(opt_sharpe)}**.",
    ]
    if equal["sharpe_true_mean"] >= sample["sharpe_true_mean"]:
        lines.append(f"- Die gleichgewichtete Aufteilung (1/N) erreicht ohne jede Schätzung "
                     f"**{ratio(equal['sharpe_true_mean'])}** – mindestens so viel wie das optimierte Portfolio.")
    else:
        lines.append(f"- Zum Vergleich: 1/N erreicht ohne jede Schätzung **{ratio(equal['sharpe_true_mean'])}**. "
                     "Die Optimierung lohnt sich hier, weil sich die wahren Sharpe-Ratios stark unterscheiden.")
    cov_only, mu_only = summary.loc["ms_cov_only", "share_of_optimum"], summary.loc["ms_mu_only", "share_of_optimum"]
    verdict = ("Die Fehler in den erwarteten Renditen richten also den größeren Schaden an (Chopra & Ziemba 1993)."
               if cov_only > mu_only else "In diesem Fall schaden die Kovarianzfehler mindestens ebenso.")
    lines.append(f"- Ist nur Σ geschätzt (μ bekannt), erreicht der Optimierer **{pct(cov_only, 0)}** der optimalen "
                 f"Sharpe-Ratio, ist nur μ geschätzt, **{pct(mu_only, 0)}**. {verdict}")
    return "\n".join(lines)


def _render_experiment(params, est, rf, bounds, theme) -> None:
    stale = params["rf"] != rf or params["bounds"] != bounds or (
        params["scenario"] == "data" and (params["assets"] != tuple(est.assets)
                                          or not np.allclose(params["mu"], est.mu)
                                          or not np.allclose(params["cov"], est.cov)))
    if stale:
        st.info("Daten oder Einstellungen haben sich seit dem letzten Start geändert – die Ergebnisse unten "
                "beziehen sich noch auf den alten Stand.")
    strategies = tuple(ins.STRATEGIES)
    with st.spinner("Simuliere Historien, schätze und optimiere …", show_time=True):
        try:
            fexp = run_frontier_experiment(params["assets"], params["mu"], params["cov"], params["n_obs"],
                                           params["bounds"], params["seed"])
            sexp = run_strategy_experiment(params["assets"], params["mu"], params["cov"], params["n_obs"],
                                           params["n_trials"], params["rf"], params["bounds"], strategies,
                                           params["seed"])
        except ValueError as exc:
            st.warning(str(exc))
            return
    summary = sexp.summary().set_index("strategy")
    st.markdown(_findings(summary, sexp.optimal_stats[2], params))
    st.markdown("**Efficient Frontier: Versprechen und Wirklichkeit** (20 Durchläufe, nach Broadie 1993)")
    show_chart(charts.broadie_chart(fexp, theme))
    st.caption("Blau: Rand, den der Optimierer aus der jeweiligen Stichprobe berechnet. Orange: dieselben "
               "Portfolios, bewertet mit den wahren Parametern. Schwarz: der wahre effiziente Rand.")
    st.markdown("**Sharpe-Ratio je Strategie: erwartet vs. tatsächlich erreicht**")
    show_chart(charts.sharpe_chart(sexp, theme))
    columns = {"sharpe_est_mean": "Sharpe erwartet", "sharpe_true_mean": "Sharpe tatsächlich",
               "sharpe_true_p5": "Sharpe tats. P5", "share_of_optimum": "Anteil am Optimum", "distance_mean": "Abstand"}
    note = ""
    if summary["cash_share"].max() > 0:
        columns["cash_share"] = "Risikolos"
        note = (" Risikolos: Anteil der Läufe, in denen die Schätzung kein Portfolio über dem risikolosen Zins "
                "sah; der Anleger bleibt dann risikolos investiert (Sharpe-Ratio 0).")
    table = summary.set_index("label")[list(columns)].rename(columns=columns)
    table.index.name = None
    st.dataframe(styled(table, pct_cols=("Anteil am Optimum", "Abstand", "Risikolos"),
                        ratio_cols=("Sharpe erwartet", "Sharpe tatsächlich", "Sharpe tats. P5")))
    st.caption("Mittelwerte über alle Durchläufe; P5: 5-%-Quantil. Abstand: Anteil des Portfolios, der im Mittel "
               "umgeschichtet werden müsste, um das wahre Optimum zu erreichen (½ · Σ |w − w*|)." + note)
    st.markdown("**Wie stark schwanken die optimalen Gewichte?**")
    chosen = st.multiselect("Strategien", list(ins.STRATEGIES), default=["ms_sample", "ms_shrink"],
                            format_func=ins.STRATEGIES.get, max_selections=3, key="exp_strategies")
    if chosen:
        show_chart(charts.weight_distribution_chart(sexp, chosen, theme))
        st.caption("Boxen: mittlere 50 % der Gewichte über alle Durchläufe, Antennen: kleinstes bis größtes "
                   "Gewicht. Raute: wahres Optimum.")
