"""Streamlit-Oberfläche des Portfolio-Optimierers.

Start: ``streamlit run app.py``
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from portfolio_optimizer import charts, data, monte_carlo as mc, optimization as opt
from portfolio_optimizer import instability as ins
from portfolio_optimizer.estimators import COV_ESTIMATORS, MEAN_ESTIMATORS, estimate
from portfolio_optimizer.formatting import num, pct, ratio, styled

st.set_page_config(page_title="Portfolio-Optimierer", page_icon="📈", layout="wide")

CUSTOM_PRESET = "Eigene Auswahl"


# ---------------------------------------------------------------------------
# Zwischengespeicherte Berechnungen
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner="Lade Kurse von Yahoo Finance …")
def load_yahoo(tickers: tuple[str, ...], start: date, end: date):
    return data.fetch_prices(list(tickers), start, end)


@st.cache_data(show_spinner=False)
def load_csv(content: bytes) -> pd.DataFrame:
    return data.load_prices_csv(content)


@st.cache_data(show_spinner=False)
def load_demo(years: int, seed: int) -> pd.DataFrame:
    return data.synthetic_prices(years, seed)


@st.cache_data(show_spinner="Simuliere Pfade …", max_entries=20)
def run_simulation(method, weights, mu, cov, returns, years, n_paths, initial, contribution, seed):
    if method == "gbm":
        return mc.simulate_gbm(weights, mu, cov, years, n_paths, initial, contribution, seed=seed)
    return mc.simulate_bootstrap(weights, returns, years, n_paths, initial, contribution, seed=seed)


@st.cache_data(show_spinner=False, max_entries=10)
def run_frontier_experiment(assets, mu, cov, n_obs, bounds, seed):
    model = ins.Model(list(assets), mu, cov)
    return ins.frontier_experiment(model, n_obs, n_trials=20, bounds=bounds, seed=seed)


@st.cache_data(show_spinner=False, max_entries=10)
def run_strategy_experiment(assets, mu, cov, n_obs, n_trials, rf, bounds, strategies, seed):
    model = ins.Model(list(assets), mu, cov)
    return ins.strategy_experiment(
        model, n_obs, n_trials, rf, bounds, strategies=strategies, n_resamples=20, seed=seed
    )


def sensitivity_turnovers(est, rf, bounds, delta) -> np.ndarray:
    """Umschichtung des Max-Sharpe-Portfolios, wenn jeweils ein Asset um ``delta`` geändert wird."""
    out = np.full(len(est.assets), np.nan)
    for i in range(len(est.assets)):
        before, after = ins.perturbed_weights(est.mu, est.cov, rf, bounds, i, delta)
        if before is not None and after is not None:
            out[i] = ins.turnover(before, after)
    return out


def current_theme() -> charts.Theme:
    try:
        dark = st.context.theme.type == "dark"
    except AttributeError:
        dark = False
    return charts.get_theme(dark)


def show_chart(fig) -> None:
    st.plotly_chart(fig, theme=None, config={"displaylogo": False})


# ---------------------------------------------------------------------------
# Seitenleiste
# ---------------------------------------------------------------------------


def _apply_preset() -> None:
    preset = st.session_state["preset"]
    if preset in data.PRESETS:
        st.session_state["tickers"] = ", ".join(data.PRESETS[preset])


def _mark_custom() -> None:
    st.session_state["preset"] = CUSTOM_PRESET


def sidebar_data() -> tuple[pd.DataFrame, str] | None:
    sb = st.sidebar
    sb.header("1 · Daten")
    source = sb.radio(
        "Datenquelle",
        ["Yahoo Finance", "CSV-Datei", "Demo-Daten"],
        help="Demo-Daten sind simulierte Kurse fiktiver Assetklassen – praktisch zum Ausprobieren ohne Internet.",
    )

    if source == "Yahoo Finance":
        first = next(iter(data.PRESETS))
        st.session_state.setdefault("preset", first)
        st.session_state.setdefault("tickers", ", ".join(data.PRESETS[first]))
        sb.selectbox("Vorlage", [*data.PRESETS, CUSTOM_PRESET], key="preset", on_change=_apply_preset)
        sb.text_area(
            "Ticker",
            key="tickers",
            height=90,
            on_change=_mark_custom,
            help="Symbole wie bei Yahoo Finance, durch Komma getrennt. Deutsche Werte mit Börsenkürzel, "
            "z. B. SAP.DE (Xetra) oder EUNL.DE (iShares Core MSCI World).",
        )
        today = date.today()
        c1, c2 = sb.columns(2)
        ten_years_ago = (pd.Timestamp(today) - pd.DateOffset(years=10)).date()
        start = c1.date_input("Von", value=ten_years_ago, max_value=today, format="DD.MM.YYYY")
        end = c2.date_input("Bis", value=today, max_value=today, format="DD.MM.YYYY")
        sb.caption("Kurse in Handelswährung, dividendenbereinigt. Wechselkurse werden nicht umgerechnet.")

        tickers = data.parse_tickers(st.session_state["tickers"])
        if len(tickers) < 2:
            st.info("Bitte in der Seitenleiste mindestens zwei Ticker eingeben.")
            return None
        if len(tickers) > data.MAX_ASSETS:
            st.error(f"Bitte höchstens {data.MAX_ASSETS} Ticker auswählen.")
            return None
        if start >= end:
            st.error("Das Startdatum muss vor dem Enddatum liegen.")
            return None
        try:
            prices, missing = load_yahoo(tuple(tickers), start, end)
        except Exception as exc:  # Netzwerk- und API-Fehler von yfinance sind nicht einheitlich typisiert
            st.error(
                f"Der Abruf bei Yahoo Finance ist fehlgeschlagen ({exc}). "
                "Bitte Internetverbindung prüfen oder eine CSV-Datei bzw. die Demo-Daten verwenden."
            )
            return None
        if len(missing) == len(tickers):
            st.error(
                "Yahoo Finance hat für keinen der Ticker Daten geliefert. Bitte Schreibweise und "
                "Internetverbindung prüfen – oder eine CSV-Datei bzw. die Demo-Daten verwenden."
            )
            return None
        if missing:
            st.warning(f"Keine Kursdaten gefunden für: {', '.join(missing)}")
        if prices.shape[1] < 2:
            st.error("Für mindestens zwei Ticker werden Kursdaten benötigt.")
            return None
        label = "Yahoo Finance"

    elif source == "CSV-Datei":
        upload = sb.file_uploader(
            "Kursdatei (CSV)",
            type=["csv", "txt"],
            help="Erste Spalte: Datum. Danach eine Spalte je Asset mit Kursen. "
            "Komma, Semikolon und deutsches Zahlenformat werden erkannt.",
        )
        if upload is None:
            st.info(
                "Lade eine CSV-Datei mit einer Datumsspalte und einer Kursspalte je Asset hoch, zum Beispiel:\n\n"
                "```\nDatum;Aktie A;Aktie B\n02.01.2024;101,20;55,10\n03.01.2024;102,05;54,80\n```"
            )
            return None
        try:
            prices = load_csv(upload.getvalue())
        except data.DataError as exc:
            st.error(str(exc))
            return None
        label = f"CSV-Datei „{upload.name}“"

    else:
        years = sb.slider("Länge der Historie (Jahre)", 3, 30, 10)
        seed = sb.number_input("Zufallszahl (Seed)", 0, 10_000, 42)
        prices = load_demo(years, int(seed))
        label = "Synthetische Demo-Daten (fiktive Assetklassen)"

    try:
        prices = data.clean_prices(prices)
    except data.DataError as exc:
        st.error(str(exc))
        return None
    return prices, label


def sidebar_settings(n_assets: int):
    sb = st.sidebar
    sb.header("2 · Schätzung")
    mean_method = sb.selectbox(
        "Erwartete Renditen",
        list(MEAN_ESTIMATORS),
        format_func=MEAN_ESTIMATORS.get,
        help="Bayes-Stein zieht die historischen Mittelwerte in Richtung eines gemeinsamen Werts "
        "und dämpft so Ausreißer der Schätzung.",
    )
    cov_method = sb.selectbox(
        "Kovarianzen",
        list(COV_ESTIMATORS),
        format_func=COV_ESTIMATORS.get,
        help="Ledoit-Wolf zieht die Korrelationen in Richtung ihres Durchschnitts. "
        "Das stabilisiert die Matrix, besonders bei vielen Assets und kurzer Historie.",
    )
    rf = sb.number_input("Risikoloser Zins p. a. (%)", -2.0, 10.0, 2.0, 0.25, format="%.2f") / 100

    sb.header("3 · Gewichtsgrenzen")
    allow_short = sb.toggle("Leerverkäufe erlauben", value=False)
    unbounded = allow_short and sb.checkbox(
        "Ohne Grenzen (klassischer Markowitz)",
        help="Analytische Lösung ohne jede Gewichtsgrenze – zeigt die extremen Positionen des Originalmodells.",
    )
    if unbounded:
        bounds = None
    else:
        lo = sb.slider("Mindestgewicht je Titel", -100, 0, -30, 5, format="%d %%") / 100 if allow_short else 0.0
        hi = sb.slider("Höchstgewicht je Titel", 5, 200 if allow_short else 100, 100, 5, format="%d %%") / 100
        bounds = (lo, hi)
    try:
        opt.validate_bounds(n_assets, bounds)
    except ValueError as exc:
        sb.error(str(exc))
        st.stop()
    return mean_method, cov_method, rf, bounds


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------


def tab_data(prices, returns, est, rf, source_label, theme) -> None:
    st.caption(
        f"{source_label} · {prices.index[0]:%d.%m.%Y} – {prices.index[-1]:%d.%m.%Y} · "
        f"{num(len(returns))} Renditetage ({num(est.years, 1)} Jahre) · {len(est.assets)} Assets"
    )
    st.subheader("Wertentwicklung")
    show_chart(charts.price_chart(prices, theme))

    st.subheader("Kennzahlen je Asset")
    years = est.years
    table = pd.DataFrame(
        {
            "Erwartete Rendite p. a.": est.mu,
            "CAGR": (prices.iloc[-1] / prices.iloc[0]).to_numpy() ** (1 / years) - 1,
            "Volatilität p. a.": est.vol,
            "Sharpe-Ratio": (est.mu - rf) / est.vol,
            "Max. Drawdown": data.max_drawdown(prices).to_numpy(),
        },
        index=est.assets,
    )
    st.dataframe(
        styled(table, pct_cols=("Erwartete Rendite p. a.", "CAGR", "Volatilität p. a.", "Max. Drawdown"),
               ratio_cols=("Sharpe-Ratio",))
    )
    st.caption(
        "Erwartete Rendite: annualisierter arithmetischer Mittelwert der Tagesrenditen "
        f"({MEAN_ESTIMATORS[est.mean_method]}) – diese Größe nutzt die Optimierung. "
        "CAGR: tatsächliche jährliche Wachstumsrate im Zeitraum."
    )

    st.subheader("Korrelationen")
    corr = pd.DataFrame(est.corr, index=est.assets, columns=est.assets)
    show_chart(charts.correlation_heatmap(corr, theme))
    if est.cov_shrinkage is not None:
        st.caption(f"Ledoit-Wolf-Shrinkage-Intensität: {pct(est.cov_shrinkage)}")
    with st.expander("Korrelationsmatrix als Tabelle"):
        st.dataframe(corr.style.format(lambda v: ratio(v)))


def tab_frontier(est, rf, bounds, theme):
    """Zeigt den effizienten Rand und gibt die Portfolios für die anderen Tabs zurück."""
    n = len(est.assets)
    frontier = opt.efficient_frontier(est.mu, est.cov, bounds, n_points=60)
    w_gmv = opt.min_variance(est.cov, bounds)
    w_ms = opt.max_sharpe(est.mu, est.cov, rf, bounds)
    vol_gmv = opt.portfolio_stats(w_gmv, est.mu, est.cov)[1]
    vol_max = float(frontier.vols.max())

    if w_ms is None:
        st.warning(
            "Kein zulässiges Portfolio erwartet eine Rendite über dem risikolosen Zins – "
            "das Max-Sharpe-Portfolio existiert daher nicht."
        )

    if vol_max - vol_gmv > 0.002:
        # Raster in Schritten von 0,1 Prozentpunkten zwischen Minimum-Varianz und oberem Ende
        options = [round(v, 3) for v in np.arange(np.ceil(vol_gmv * 1000), np.floor(vol_max * 1000) + 1) / 1000]
        default = opt.portfolio_stats(w_ms, est.mu, est.cov)[1] if w_ms is not None else (vol_gmv + vol_max) / 2
        target = st.select_slider(
            "Zielvolatilität des ausgewählten Portfolios",
            options=options,
            value=min(options, key=lambda v: abs(v - default)),
            format_func=pct,
            help="Wählt das effiziente Portfolio mit der höchsten erwarteten Rendite bei dieser Volatilität. "
            "Voreingestellt ist die Volatilität des Max-Sharpe-Portfolios.",
        )
        w_sel = opt.efficient_risk(est.mu, est.cov, target, bounds)
    else:
        w_sel = w_gmv

    ret_sel, vol_sel, sharpe_sel = opt.portfolio_stats(w_sel, est.mu, est.cov, rf)
    c1, c2, c3 = st.columns(3)
    c1.metric("Erwartete Rendite p. a.", pct(ret_sel), border=True)
    c2.metric("Volatilität p. a.", pct(vol_sel), border=True)
    c3.metric("Sharpe-Ratio", ratio(sharpe_sel), border=True)

    named = {"Ausgewählt": w_sel, "Max-Sharpe": w_ms, "Minimum-Varianz": w_gmv}
    named = {k: v for k, v in named.items() if v is not None}
    points = {k: opt.portfolio_stats(w, est.mu, est.cov)[1::-1] for k, w in named.items()}
    cloud = opt.random_portfolios(est.mu, est.cov, 3000, seed=1, bounds=bounds)
    show_chart(
        charts.frontier_chart(
            frontier, est.assets, est.vol, est.mu, points, theme,
            rf=rf if w_ms is not None else None, cloud=cloud,
        )
    )
    st.caption(
        "Grau: zufällig gemischte Portfolios ohne Leerverkäufe. Gestrichelt: Kapitalmarktlinie "
        "vom risikolosen Zins durch das Max-Sharpe-Portfolio (Tangentialportfolio)."
    )

    left, right = st.columns(2)
    weights = pd.DataFrame(named, index=est.assets)
    with left:
        st.subheader("Gewichte")
        show_chart(charts.weights_chart(weights, theme))
    with right:
        st.subheader("Gewichte entlang der Frontier")
        show_chart(charts.transition_chart(frontier, est.assets, theme))

    w_eq = np.full(n, 1 / n)
    all_named = named | {"Gleichgewichtet (1/N)": w_eq}
    with st.expander("Gewichte und Kennzahlen als Tabelle"):
        st.dataframe(styled(pd.DataFrame(all_named, index=est.assets), pct_cols=tuple(all_named)))
        stats = pd.DataFrame(
            [opt.portfolio_stats(w, est.mu, est.cov, rf) for w in all_named.values()],
            index=list(all_named),
            columns=["Rendite p. a.", "Volatilität p. a.", "Sharpe-Ratio"],
        )
        st.dataframe(styled(stats, pct_cols=("Rendite p. a.", "Volatilität p. a."), ratio_cols=("Sharpe-Ratio",)))
        rc = pd.DataFrame(
            {"Gewicht": w_sel, "Risikobeitrag": opt.risk_contributions(w_sel, est.cov)}, index=est.assets
        )
        st.markdown("**Risikobeiträge des ausgewählten Portfolios** (Anteil an der Portfoliovarianz)")
        st.dataframe(styled(rc, pct_cols=("Gewicht", "Risikobeitrag")))

    with st.expander("Methodik"):
        st.markdown(
            "Für jede Zielrendite $r^*$ löst der Optimierer das Markowitz-Problem"
        )
        st.latex(r"\min_w \; w^\top \Sigma w \quad \text{u. d. N.} \quad w^\top \mu = r^*,\; \mathbf{1}^\top w = 1,\; l \le w_i \le u")
        st.markdown(
            "Das **Max-Sharpe-Portfolio** maximiert $(w^\\top\\mu - r_f)/\\sqrt{w^\\top\\Sigma w}$. "
            "Ohne Gewichtsgrenzen gibt es geschlossene Lösungen, sonst wird numerisch (SLSQP) optimiert. "
            "$\\mu$ und $\\Sigma$ werden aus Tagesrenditen geschätzt und mit 252 Handelstagen annualisiert."
        )
    return all_named


def tab_monte_carlo(portfolios, est, returns, theme) -> None:
    labels = {
        "Ausgewählt": "Ausgewähltes Frontier-Portfolio",
        "Max-Sharpe": "Max-Sharpe-Portfolio",
        "Minimum-Varianz": "Minimum-Varianz-Portfolio",
        "Gleichgewichtet (1/N)": "Gleichgewichtet (1/N)",
    }
    c1, c2 = st.columns(2)
    choice = c1.selectbox("Portfolio", list(portfolios), format_func=labels.get)
    method = c2.radio(
        "Verfahren",
        ["gbm", "bootstrap"],
        format_func={"gbm": "Parametrisch (GBM)", "bootstrap": "Historisches Bootstrap"}.get,
        horizontal=True,
        help="Parametrisch: korrelierte geometrische Brownsche Bewegung mit den geschätzten Parametern. "
        "Bootstrap: zieht zufällige Monatsblöcke aus den tatsächlichen Tagesrenditen (erhält Fat Tails).",
    )
    c3, c4, c5, c6 = st.columns(4)
    initial = c3.number_input("Anfangskapital", 0, 100_000_000, 10_000, 1_000)
    contribution = c4.number_input("Sparrate pro Monat", 0, 1_000_000, 0, 50)
    years = c5.slider("Anlagehorizont (Jahre)", 1, 40, 10)
    n_paths = c6.select_slider("Anzahl Pfade", [500, 1_000, 2_000, 5_000, 10_000], value=2_000)
    with st.expander("Weitere Einstellungen"):
        e1, e2 = st.columns(2)
        target = e1.number_input("Zielvermögen (0 = ohne)", 0, 1_000_000_000, 0, 1_000)
        seed = e2.number_input("Zufallszahl (Seed)", 0, 10_000, 7)
    if initial == 0 and contribution == 0:
        st.info("Bitte ein Anfangskapital oder eine Sparrate angeben.")
        return

    weights = portfolios[choice]
    sim = run_simulation(
        method, weights, est.mu, est.cov, returns.to_numpy(), years, n_paths,
        float(initial), float(contribution), int(seed),
    )
    s = sim.summary(target=float(target) if target > 0 else None)

    cols = st.columns(5 if target > 0 else 4)
    cols[0].metric("Median-Endvermögen", num(s["median"]), help=f"Eingezahlt: {num(s['invested'])}", border=True)
    cols[1].metric("Ungünstig (5-%-Quantil)", num(s["p5"]),
                   help=f"In 5 % der Pfade endet das Vermögen darunter. Mittel dieser Pfade (CVaR): {num(s['cvar5'])}",
                   border=True)
    cols[2].metric("Verlustwahrscheinlichkeit", pct(s["prob_loss"]),
                   help="Anteil der Pfade, die unter dem eingezahlten Kapital enden.", border=True)
    cols[3].metric("Rendite p. a. (Median)", pct(s["cagr_median"]),
                   help=f"Zeitgewichtet, ohne Einfluss der Sparrate. Typischer maximaler Drawdown: {pct(s['max_dd_median'])}",
                   border=True)
    if target > 0:
        cols[4].metric("Ziel erreicht", pct(s["prob_target"]), help=f"Anteil der Pfade mit mindestens {num(target)}",
                       border=True)

    st.subheader("Mögliche Vermögensentwicklungen")
    show_chart(charts.fan_chart(sim, theme))
    left, right = st.columns(2)
    with left:
        st.subheader("Verteilung des Endvermögens")
        show_chart(charts.final_wealth_histogram(sim, theme))
        st.caption("Darstellung bis zum 99,5-%-Quantil.")
    with right:
        st.subheader("Perzentile")
        marks = sorted({y for y in (1, 3, 5, 10, 15, 20, 25, 30, 40) if y < years} | {years})
        q = sim.percentiles().loc[[float(y) for y in marks]]
        q.insert(0, "Eingezahlt", sim.invested[[int(y * 12) for y in marks]])
        q.index = [f"{y} J." for y in marks]
        st.dataframe(styled(q, num_cols=tuple(q.columns)))
        st.caption(
            f"Maximaler Drawdown: Median {pct(s['max_dd_median'])}, in 5 % der Pfade über {pct(s['max_dd_p95'])} "
            "(auf Monatsbasis)."
        )

    st.info(
        "Die Simulation behandelt die geschätzten Renditen und Risiken als bekannt. "
        "Gerade die erwarteten Renditen sind aber sehr unsicher – wie stark, zeigt der Tab **Schätzfehler**."
        if method == "gbm"
        else "Das Bootstrap wiederholt die Vergangenheit in zufälliger Reihenfolge: Die historische "
        "Durchschnittsrendite (samt Schätzfehler) steckt damit in jedem Pfad – mehr dazu im Tab **Schätzfehler**."
    )


def tab_estimation_error(returns, est, rf, bounds, theme) -> None:
    st.markdown(
        "Die Optimierung behandelt Schätzungen als exakt. Sie bevorzugt daher systematisch Assets, "
        "deren Rendite zufällig **überschätzt** und deren Risiko **unterschätzt** wurde. Michaud (1989) "
        "nannte Mean-Variance-Optimierer deshalb „Fehlermaximierer“. Die folgenden drei Analysen zeigen, warum."
    )

    # 1 · Schätzunsicherheit -------------------------------------------------
    st.subheader("1 · Wie genau sind die Schätzungen?")
    err = ins.estimation_error_table(returns)
    err.index = est.assets
    left, right = st.columns([3, 2])
    with left:
        show_chart(charts.confidence_chart(err, theme))
    with right:
        typical_vol = float(err["vol"].median())
        st.metric("Datenhistorie", f"{num(est.years, 1)} Jahre", border=True)
        st.metric("Ø Breite des 95-%-Intervalls", pct((err["ci_high"] - err["ci_low"]).mean()), border=True)
        st.markdown(
            f"Bei einer typischen Volatilität von **{pct(typical_vol)}** wären rund "
            f"**{num((typical_vol / 0.01) ** 2)} Jahre** Daten nötig, damit der Standardfehler der "
            "erwarteten Rendite auf **1 Prozentpunkt** sinkt. Mehr Datenpunkte pro Jahr (z. B. Tages- statt "
            "Monatsdaten) helfen beim Mittelwert nicht – nur ein längerer Zeitraum. Volatilitäten und "
            "Korrelationen lassen sich dagegen deutlich genauer schätzen."
        )
    with st.expander("Tabelle: Schätzung und Standardfehler"):
        table = err.rename(
            columns={
                "mu": "Mittelwert p. a.", "vol": "Volatilität p. a.", "se": "Standardfehler",
                "ci_low": "95 %: von", "ci_high": "95 %: bis", "years_needed": "Jahre für ±1 Pp.",
            }
        )
        st.dataframe(
            styled(table, pct_cols=("Mittelwert p. a.", "Volatilität p. a.", "Standardfehler", "95 %: von", "95 %: bis"),
                   num_cols=("Jahre für ±1 Pp.",))
        )

    # 2 · Sensitivität -------------------------------------------------------
    st.subheader("2 · Kleine Änderung, große Wirkung")
    st.markdown(
        "Ändere die erwartete Rendite **eines** Assets um einen Bruchteil seiner Schätzunsicherheit und "
        "beobachte, wie stark sich das Max-Sharpe-Portfolio umbaut (Best & Grauer 1991)."
    )
    c1, c2 = st.columns(2)
    delta = c2.slider("Änderung der erwarteten Rendite (Prozentpunkte)", -3.0, 3.0, 1.0, 0.25, format="%+.2f")
    turnovers = sensitivity_turnovers(est, rf, bounds, delta / 100)
    if st.session_state.get("sens_asset") not in est.assets:
        best = int(np.nanargmax(turnovers)) if np.isfinite(turnovers).any() else 0
        st.session_state["sens_asset"] = est.assets[best]
    asset = c1.selectbox("Asset", est.assets, key="sens_asset",
                         help="Voreingestellt ist das Asset, auf dessen Änderung das Portfolio am stärksten reagiert.")
    idx = est.assets.index(asset)
    before, after = ins.perturbed_weights(est.mu, est.cov, rf, bounds, idx, delta / 100)
    if before is None or after is None:
        st.warning("Für diese Einstellung existiert kein Max-Sharpe-Portfolio (keine Rendite über dem risikolosen Zins).")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Umschichtung", pct(ins.turnover(before, after)),
                  help="Anteil des Portfolios, der umgeschichtet werden muss: ½ · Σ |Δw|", border=True)
        m2.metric("Ø Umschichtung über alle Assets", pct(float(np.nanmean(turnovers))),
                  help="Mittlere Umschichtung, wenn man nacheinander jedes Asset um denselben Betrag ändert.",
                  border=True)
        m3.metric("Standardfehler der Schätzung", pct(err["se"].iloc[idx]),
                  help=f"Standardfehler der erwarteten Rendite von {asset}. Die Änderung liegt typischerweise "
                  "innerhalb dieser statistischen Unsicherheit.", border=True)
        show_chart(charts.sensitivity_chart(est.assets, before, after, theme))

    # 3 · Simulationsexperiment ---------------------------------------------
    st.subheader("3 · Simulationsexperiment: geschätzt vs. tatsächlich")
    st.markdown(
        "Wir tun so, als kennten wir die **wahren** Parameter. Daraus simulieren wir viele alternative "
        "Kurshistorien, schätzen auf jeder neu, optimieren – und bewerten das Ergebnis mit den wahren "
        "Parametern. So wird sichtbar, was der Optimierer *verspricht* und was er *liefert*."
    )
    st.caption(
        "Tipp: Im Szenario „Identische Assets“ ist das wahre Optimum 1/N – jede Abweichung davon ist reines "
        "Schätzrauschen."
    )
    with st.form("experiment"):
        scenario = st.radio(
            "Wahres Modell",
            ["data", "identical"],
            format_func={"data": "Aktuelle Schätzungen der Daten", "identical": "Identische Assets (Optimum = 1/N)"}.get,
            horizontal=True,
        )
        f1, f2, f3 = st.columns(3)
        hist_years = f1.slider("Länge jeder simulierten Historie (Jahre)", 1, 30, int(np.clip(round(est.years), 1, 30)))
        n_trials = f2.select_slider("Anzahl Durchläufe", [50, 100, 200, 300], value=100)
        seed = f3.number_input("Zufallszahl (Seed)", 0, 10_000, 1)
        with st.expander("Parameter für „Identische Assets“"):
            g1, g2, g3, g4 = st.columns(4)
            id_n = g1.number_input("Anzahl Assets", 2, data.MAX_ASSETS, max(2, len(est.assets)))
            id_mu = g2.number_input("Rendite p. a. (%)", -5.0, 30.0, 7.0, 0.5)
            id_vol = g3.number_input("Volatilität p. a. (%)", 1.0, 80.0, 20.0, 1.0)
            id_corr = g4.number_input("Korrelation", -0.2, 0.95, 0.3, 0.05)
        submitted = st.form_submit_button("Experiment starten", type="primary")

    if submitted:
        if scenario == "data":
            model = ins.model_from_estimates(est)
        else:
            try:
                model = ins.identical_assets_model(int(id_n), id_mu / 100, id_vol / 100, float(id_corr))
            except ValueError as exc:
                st.error(str(exc))
                return
        try:
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
        render_experiment(params, est, rf, bounds, theme)

    # 4 · Gegenmittel -------------------------------------------------------
    st.subheader("Was hilft?")
    st.markdown(
        """
- **Weniger schätzen:** Das Minimum-Varianz-Portfolio braucht keine Renditeschätzungen, 1/N gar keine Schätzung.
  DeMiguel, Garlappi & Uppal (2009) fanden, dass viele optimierte Strategien 1/N außerhalb der Stichprobe nicht schlagen.
- **Shrinkage:** Bayes-Stein zieht die Renditen zum gemeinsamen Mittel, Ledoit-Wolf stabilisiert die
  Kovarianzmatrix – beides in der Seitenleiste wählbar.
- **Restriktionen:** Long-only und Höchstgewichte begrenzen den Schaden extremer Schätzungen
  (Jagannathan & Ma 2003). Vergleiche die Ergebnisse oben mit und ohne Gewichtsgrenzen.
- **Resampling:** Optimale Gewichte über viele plausible Parametersätze mitteln (Michaud 1998).
- **Gleichgewichtsrenditen:** Black-Litterman nimmt markt-implizite Renditen als Ausgangspunkt und
  mischt eigene Einschätzungen nur dosiert hinzu.
        """
    )
    with st.expander("Literatur"):
        st.markdown(
            """
- Best, M. J. & Grauer, R. R. (1991): *On the Sensitivity of Mean-Variance-Efficient Portfolios to Changes in Asset Means.* Review of Financial Studies 4(2).
- Broadie, M. (1993): *Computing Efficient Frontiers Using Estimated Parameters.* Annals of Operations Research 45.
- Chopra, V. K. & Ziemba, W. T. (1993): *The Effect of Errors in Means, Variances, and Covariances on Optimal Portfolio Choice.* Journal of Portfolio Management 19(2).
- DeMiguel, V., Garlappi, L. & Uppal, R. (2009): *Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy?* Review of Financial Studies 22(5).
- Jagannathan, R. & Ma, T. (2003): *Risk Reduction in Large Portfolios: Why Imposing the Wrong Constraints Helps.* Journal of Finance 58(4).
- Jorion, P. (1986): *Bayes-Stein Estimation for Portfolio Analysis.* Journal of Financial and Quantitative Analysis 21(3).
- Ledoit, O. & Wolf, M. (2004): *Honey, I Shrunk the Sample Covariance Matrix.* Journal of Portfolio Management 30(4).
- Markowitz, H. (1952): *Portfolio Selection.* Journal of Finance 7(1).
- Michaud, R. O. (1989): *The Markowitz Optimization Enigma: Is 'Optimized' Optimal?* Financial Analysts Journal 45(1).
- Michaud, R. O. (1998): *Efficient Asset Management.* Harvard Business School Press.
            """
        )


def experiment_findings(summary: pd.DataFrame, opt_sharpe: float, params: dict) -> str:
    """Fasst das Strategie-Experiment in Worten zusammen - passend zu den tatsächlichen Zahlen."""
    sample, equal = summary.loc["ms_sample"], summary.loc["equal"]
    lines = [
        f"**Ergebnis aus {params['n_trials']} simulierten Historien à {num(params['n_obs'] / 252, 0)} Jahren:**",
        "",
        f"- Das Max-Sharpe-Portfolio aus Stichprobenschätzern **verspricht** im Mittel eine Sharpe-Ratio von "
        f"**{ratio(sample['sharpe_est_mean'])}**, **liefert** aber nur **{ratio(sample['sharpe_true_mean'])}**. "
        f"Das wahre Optimum liegt bei **{ratio(opt_sharpe)}**.",
    ]
    if equal["sharpe_true_mean"] >= sample["sharpe_true_mean"]:
        lines.append(
            f"- Die gleichgewichtete Aufteilung (1/N) erreicht ohne jede Schätzung **{ratio(equal['sharpe_true_mean'])}** "
            "– mindestens so viel wie das optimierte Portfolio."
        )
    else:
        lines.append(
            f"- Zum Vergleich: 1/N erreicht ohne jede Schätzung **{ratio(equal['sharpe_true_mean'])}**. Die Optimierung "
            "lohnt sich hier, weil sich die wahren Sharpe-Ratios der Assets stark unterscheiden."
        )
    cov_only, mu_only = summary.loc["ms_cov_only", "share_of_optimum"], summary.loc["ms_mu_only", "share_of_optimum"]
    verdict = (
        "Die Fehler in den erwarteten Renditen richten also den größeren Schaden an (Chopra & Ziemba 1993)."
        if cov_only > mu_only
        else "In diesem Fall schaden die Kovarianzfehler mindestens ebenso."
    )
    lines.append(
        f"- Ist nur Σ geschätzt (μ bekannt), erreicht der Optimierer **{pct(cov_only, 0)}** der optimalen "
        f"Sharpe-Ratio, ist nur μ geschätzt, **{pct(mu_only, 0)}**. {verdict}"
    )
    return "\n".join(lines)


def render_experiment(params, est, rf, bounds, theme) -> None:
    stale = params["rf"] != rf or params["bounds"] != bounds or (
        params["scenario"] == "data"
        and (
            params["assets"] != tuple(est.assets)
            or not np.allclose(params["mu"], est.mu)
            or not np.allclose(params["cov"], est.cov)
        )
    )
    if stale:
        st.info("Daten oder Einstellungen haben sich seit dem letzten Start geändert – "
                "die Ergebnisse unten beziehen sich noch auf den alten Stand.")

    strategies = tuple(ins.STRATEGIES)
    with st.spinner("Simuliere Historien, schätze und optimiere …", show_time=True):
        try:
            fexp = run_frontier_experiment(
                params["assets"], params["mu"], params["cov"], params["n_obs"], params["bounds"], params["seed"]
            )
            sexp = run_strategy_experiment(
                params["assets"], params["mu"], params["cov"], params["n_obs"], params["n_trials"],
                params["rf"], params["bounds"], strategies, params["seed"],
            )
        except ValueError as exc:
            st.warning(str(exc))
            return

    summary = sexp.summary().set_index("strategy")
    st.markdown(experiment_findings(summary, sexp.optimal_stats[2], params))

    st.markdown("**Efficient Frontier: Versprechen und Wirklichkeit** (20 Durchläufe, nach Broadie 1993)")
    show_chart(charts.broadie_chart(fexp, theme))
    st.caption(
        "Blau: Rand, den der Optimierer aus der jeweiligen Stichprobe berechnet. Orange: dieselben Portfolios, "
        "bewertet mit den wahren Parametern. Schwarz: der wahre effiziente Rand. Die geschätzten Ränder liegen "
        "im Mittel darüber (zu optimistisch), die tatsächlichen können nie darüber liegen."
    )

    st.markdown("**Sharpe-Ratio je Strategie: erwartet vs. tatsächlich erreicht**")
    show_chart(charts.sharpe_chart(sexp, theme))

    columns = {
        "sharpe_est_mean": "Sharpe erwartet",
        "sharpe_true_mean": "Sharpe tatsächlich",
        "sharpe_true_p5": "Sharpe tats. P5",
        "share_of_optimum": "Anteil am Optimum",
        "distance_mean": "Abstand",
    }
    note = ""
    if summary["cash_share"].max() > 0:
        columns["cash_share"] = "Risikolos"
        note = (" Risikolos: Anteil der Läufe, in denen die Schätzung kein Portfolio über dem risikolosen "
                "Zins sah; der Anleger bleibt dann risikolos investiert (Sharpe-Ratio 0).")
    table = summary.set_index("label")[list(columns)].rename(columns=columns)
    table.index.name = None
    st.dataframe(
        styled(table, pct_cols=("Anteil am Optimum", "Abstand", "Risikolos"),
               ratio_cols=("Sharpe erwartet", "Sharpe tatsächlich", "Sharpe tats. P5"))
    )
    st.caption(
        "Mittelwerte über alle Durchläufe; P5: 5-%-Quantil. Abstand: Anteil des Portfolios, der im Mittel "
        "umgeschichtet werden müsste, um das wahre Optimum zu erreichen (½ · Σ |w − w*|). Resampling: Mittel "
        "der Max-Sharpe-Gewichte über 20 Parameterziehungen (Michaud)." + note
    )

    st.markdown("**Wie stark schwanken die optimalen Gewichte?**")
    chosen = st.multiselect(
        "Strategien",
        list(ins.STRATEGIES),
        default=["ms_sample", "ms_shrink"],
        format_func=ins.STRATEGIES.get,
        max_selections=3,
    )
    if chosen:
        show_chart(charts.weight_distribution_chart(sexp, chosen, theme))
        st.caption("Boxen: mittlere 50 % der Gewichte über alle Durchläufe, Antennen: kleinstes bis größtes Gewicht. "
                   "Raute: wahres Optimum.")


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------


def main() -> None:
    st.title("Portfolio-Optimierer")
    st.caption("Markowitz-Optimierung · Monte-Carlo-Simulation · Schätzfehler verstehen")

    loaded = sidebar_data()
    if loaded is None:
        st.stop()
    prices, source_label = loaded
    returns = data.simple_returns(prices)
    mean_method, cov_method, rf, bounds = sidebar_settings(prices.shape[1])
    est = estimate(returns, mean_method, cov_method)
    theme = current_theme()

    t_data, t_frontier, t_mc, t_err = st.tabs(["Daten", "Efficient Frontier", "Monte Carlo", "Schätzfehler"])
    with t_data:
        tab_data(prices, returns, est, rf, source_label, theme)
    with t_frontier:
        portfolios = tab_frontier(est, rf, bounds, theme)
    with t_mc:
        tab_monte_carlo(portfolios, est, returns, theme)
    with t_err:
        tab_estimation_error(returns, est, rf, bounds, theme)


main()
