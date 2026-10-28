"""Plotly-Diagramme in einheitlichem Stil für helles und dunkles Theme.

Farbregeln: Kategorische Farben werden in fester Reihenfolge vergeben und
folgen der Entität (Asset bzw. Portfolio), nie dem Rang. Ab dem neunten Asset
kommt eine zweite Kodierung (gepunktete Linie bzw. Schraffur) hinzu, statt
weitere Farbtöne zu erfinden. Texte tragen nie die Datenfarbe.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .instability import STRATEGIES, FrontierExperiment, StrategyExperiment
from .monte_carlo import SimulationResult
from .optimization import Frontier


@dataclass(frozen=True)
class Theme:
    dark: bool
    series: tuple[str, ...]
    surface: str
    ink: str
    ink2: str
    muted: str
    grid: str
    axis: str
    neutral: str
    pos: tuple[str, str]  # Divergierende Skala: positive Seite (mittel, kräftig)
    neg: tuple[str, str]  # negative Seite (mittel, kräftig)


LIGHT = Theme(
    dark=False,
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
    surface="#fcfcfb",
    ink="#0b0b0b",
    ink2="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    neutral="#f0efec",
    pos=("#f0a09f", "#b8302f"),
    neg=("#86b6ef", "#184f95"),
)

DARK = Theme(
    dark=True,
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
    surface="#1a1a19",
    ink="#f0efec",
    ink2="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    neutral="#383835",
    pos=("#8f3534", "#e66767"),
    neg=("#1c5cab", "#5598e7"),
)

FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

# Feste Rollen der Portfolios über alle Diagramme hinweg
PORTFOLIO_SLOTS = {"Ausgewählt": 0, "Max-Sharpe": 1, "Minimum-Varianz": 2}


def get_theme(dark: bool) -> Theme:
    return DARK if dark else LIGHT


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def asset_color(theme: Theme, i: int) -> str:
    return theme.series[i % len(theme.series)]


def asset_dash(i: int) -> str:
    return "solid" if i < 8 else "dot"


def portfolio_color(theme: Theme, name: str) -> str:
    return theme.series[PORTFOLIO_SLOTS[name]]


def style(
    fig: go.Figure,
    theme: Theme,
    *,
    height: int = 420,
    x_title: str | None = None,
    y_title: str | None = None,
    x_format: str | None = None,
    y_format: str | None = None,
    legend: bool = True,
) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=16, t=48 if legend else 16, b=8),
        paper_bgcolor=theme.surface,
        plot_bgcolor=theme.surface,
        font=dict(family=FONT, color=theme.ink2, size=13),
        separators=",.",
        showlegend=legend,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            title=None,
            font=dict(color=theme.ink2),
            bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(bgcolor=theme.surface, bordercolor=theme.axis, font=dict(color=theme.ink, family=FONT)),
        barcornerradius=4,
    )
    axis = dict(
        gridcolor=theme.grid,
        gridwidth=1,
        zeroline=False,
        showline=True,
        linecolor=theme.axis,
        linewidth=1,
        tickfont=dict(color=theme.muted),
        title_font=dict(color=theme.ink2),
        automargin=True,
    )
    fig.update_xaxes(**axis, title_text=x_title, tickformat=x_format)
    fig.update_yaxes(**axis, title_text=y_title, tickformat=y_format)
    return fig


def _bar_height(n_categories: int, n_series: int, bar_px: int = 14, gap: float = 0.35) -> int:
    """Diagrammhöhe so wählen, dass jeder Balken etwa ``bar_px`` dick ist (höchstens 24 px)."""
    slot = n_series * bar_px / (1 - gap)
    return int(max(220, n_categories * slot + 110))


# ---------------------------------------------------------------------------
# Daten
# ---------------------------------------------------------------------------


def price_chart(prices: pd.DataFrame, theme: Theme) -> go.Figure:
    norm = prices / prices.iloc[0] * 100
    fig = go.Figure()
    for i, col in enumerate(norm.columns):
        fig.add_trace(
            go.Scatter(
                x=norm.index,
                y=norm[col],
                name=col,
                mode="lines",
                line=dict(color=asset_color(theme, i), width=2, dash=asset_dash(i)),
                hovertemplate="%{y:,.1f}<extra>" + col + "</extra>",
            )
        )
    _end_labels(fig, norm, theme)
    fig.update_layout(hovermode="x unified")
    return style(fig, theme, height=440, y_title="Wert (Start = 100)", y_format=",.0f")


def _end_labels(fig: go.Figure, norm: pd.DataFrame, theme: Theme) -> None:
    """Direkte Beschriftung am Linienende - nur bei wenigen, gut getrennten Linien."""
    if norm.shape[1] > 4:
        return
    ends = norm.iloc[-1].sort_values()
    span = norm.max().max() - norm.min().min()
    if len(ends) > 1 and np.diff(ends.to_numpy()).min() < 0.05 * span:
        return
    for name, value in ends.items():
        fig.add_annotation(
            x=norm.index[-1], y=value, text=str(name), showarrow=False,
            xanchor="left", xshift=6, font=dict(color=theme.ink2, size=12),
        )
    fig.update_layout(margin=dict(r=140))


def correlation_heatmap(corr: pd.DataFrame, theme: Theme) -> go.Figure:
    scale = [
        [0.0, theme.neg[1]],
        [0.25, theme.neg[0]],
        [0.5, theme.neutral],
        [0.75, theme.pos[0]],
        [1.0, theme.pos[1]],
    ]
    labels = list(corr.columns)
    fig = go.Figure(
        go.Heatmap(
            z=corr.to_numpy(),
            x=labels,
            y=labels,
            zmin=-1,
            zmax=1,
            colorscale=scale,
            xgap=2,
            ygap=2,
            colorbar=dict(title=None, tickformat=".1f", outlinewidth=0, tickfont=dict(color=theme.muted)),
            hovertemplate="%{y} / %{x}<br>Korrelation %{z:.2f}<extra></extra>",
        )
    )
    if len(labels) <= 10:
        for i, row in enumerate(labels):
            for j, col in enumerate(labels):
                value = corr.iloc[i, j]
                strong = abs(value) > 0.6
                color = "#ffffff" if strong and not theme.dark else theme.ink
                fig.add_annotation(
                    x=col, y=row, text=f"{value:.2f}".replace(".", ","), showarrow=False,
                    font=dict(color=color, size=11),
                )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False)
    size = max(320, 60 * len(labels) + 120)
    return style(fig, theme, height=size, legend=False)


# ---------------------------------------------------------------------------
# Efficient Frontier
# ---------------------------------------------------------------------------


def frontier_chart(
    frontier: Frontier,
    asset_names: list[str],
    asset_vols: np.ndarray,
    asset_rets: np.ndarray,
    portfolios: dict[str, tuple[float, float]],
    theme: Theme,
    rf: float | None = None,
    cloud: tuple[np.ndarray, np.ndarray] | None = None,
) -> go.Figure:
    """Effizienter Rand mit Einzelwerten, Kapitalmarktlinie und markierten Portfolios.

    ``portfolios`` bildet Namen aus ``PORTFOLIO_SLOTS`` auf (Volatilität, Rendite) ab.
    """
    fig = go.Figure()
    hover = "Volatilität %{x:.1%}<br>Rendite %{y:.1%}"
    if cloud is not None:
        fig.add_trace(
            go.Scattergl(
                x=cloud[1], y=cloud[0], mode="markers", name="Zufällige Long-only-Portfolios",
                marker=dict(color=rgba(theme.muted, 0.22), size=4), hoverinfo="skip",
            )
        )
    if rf is not None and "Max-Sharpe" in portfolios:
        vol_t, ret_t = portfolios["Max-Sharpe"]
        x_end = max(frontier.vols.max(), vol_t) * 1.05
        fig.add_trace(
            go.Scatter(
                x=[0, x_end], y=[rf, rf + (ret_t - rf) / vol_t * x_end], mode="lines",
                name="Kapitalmarktlinie", line=dict(color=theme.ink2, width=1.5, dash="dash"),
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=frontier.vols, y=frontier.returns, mode="lines", name="Efficient Frontier",
            line=dict(color=theme.ink, width=2.5), hovertemplate=hover + "<extra>Efficient Frontier</extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=asset_vols, y=asset_rets, mode="markers+text", name="Einzelwerte", text=asset_names,
            textposition=_label_positions(asset_vols), textfont=dict(color=theme.ink2, size=12),
            marker=dict(color=theme.muted, size=9, line=dict(color=theme.surface, width=2)),
            hovertemplate="<b>%{text}</b><br>" + hover + "<extra></extra>",
        )
    )
    symbols = {"Ausgewählt": "diamond", "Max-Sharpe": "star", "Minimum-Varianz": "circle"}
    # Das ausgewählte Portfolio zuletzt zeichnen: Es liegt oft genau auf dem Max-Sharpe-Stern.
    for name, (vol, ret) in sorted(portfolios.items(), key=lambda item: item[0] == "Ausgewählt"):
        fig.add_trace(
            go.Scatter(
                x=[vol], y=[ret], mode="markers", name=name,
                marker=dict(
                    color=portfolio_color(theme, name), size=16 if name == "Max-Sharpe" else 13,
                    symbol=symbols[name], line=dict(color=theme.surface, width=2),
                ),
                hovertemplate=hover + f"<extra>{name}</extra>",
            )
        )
    fig.update_xaxes(rangemode="tozero")
    return style(fig, theme, height=520, x_title="Volatilität p. a.", y_title="Erwartete Rendite p. a.",
                 x_format=".0%", y_format=".0%")


def _label_positions(vols: np.ndarray) -> list[str]:
    """Beschriftungen am rechten Rand nach links, am linken Rand nach links neben den Punkt."""
    vols = np.asarray(vols)
    right = vols.max() - 0.15 * np.ptp(vols)
    return [
        "middle left" if v == vols.min() else "top left" if v >= right else "top center" for v in vols
    ]


def weights_chart(weights: pd.DataFrame, theme: Theme) -> go.Figure:
    """Gruppierte horizontale Balken: Zeilen = Assets, Spalten = Portfolios."""
    fig = go.Figure()
    for name in weights.columns:
        fig.add_trace(
            go.Bar(
                y=weights.index, x=weights[name], name=name, orientation="h",
                marker=dict(color=portfolio_color(theme, name), line=dict(width=0)),
                hovertemplate="%{y}: %{x:.1%}<extra>" + name + "</extra>",
            )
        )
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    height = _bar_height(len(weights.index), len(weights.columns))
    return style(fig, theme, height=height, x_title="Gewicht", x_format=".0%")


def transition_chart(frontier: Frontier, asset_names: list[str], theme: Theme) -> go.Figure:
    """Gewichte entlang des effizienten Rands (Transition Map)."""
    fig = go.Figure()
    has_short = (frontier.weights < -1e-9).any()
    for i, name in enumerate(asset_names):
        color = asset_color(theme, i)
        common = dict(
            x=frontier.vols, y=frontier.weights[:, i], name=name,
            hovertemplate="%{y:.1%}<extra>" + name + "</extra>",
        )
        if has_short:
            fig.add_trace(go.Scatter(**common, mode="lines", line=dict(color=color, width=2, dash=asset_dash(i))))
        else:
            fig.add_trace(
                go.Scatter(
                    **common, mode="lines", stackgroup="w", line=dict(color=theme.surface, width=1.5),
                    fillcolor=rgba(color, 0.85),
                    fillpattern=dict(shape="/", fgcolor=theme.surface, solidity=0.3) if i >= 8 else None,
                )
            )
    fig.update_layout(hovermode="x unified")
    return style(fig, theme, height=420, x_title="Volatilität p. a.", y_title="Gewicht",
                 x_format=".0%", y_format=".0%")


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------


def fan_chart(sim: SimulationResult, theme: Theme, n_paths_shown: int = 25) -> go.Figure:
    q = sim.percentiles((5, 25, 50, 75, 95))
    t = sim.times
    blue = theme.series[0]
    fig = go.Figure()
    for k in range(min(n_paths_shown, sim.wealth.shape[0])):
        fig.add_trace(
            go.Scatter(
                x=t, y=sim.wealth[k], mode="lines", line=dict(color=rgba(theme.muted, 0.35), width=0.8),
                name="Beispielpfade", legendgroup="paths", showlegend=k == 0, hoverinfo="skip",
            )
        )
    band = dict(mode="lines", line=dict(width=0), hoverinfo="skip")
    fig.add_trace(go.Scatter(x=t, y=q["P5"], showlegend=False, **band))
    fig.add_trace(
        go.Scatter(x=t, y=q["P95"], fill="tonexty", fillcolor=rgba(blue, 0.12),
                   name="90-%-Band (P5–P95)", **band)
    )
    fig.add_trace(go.Scatter(x=t, y=q["P25"], showlegend=False, **band))
    fig.add_trace(
        go.Scatter(x=t, y=q["P75"], fill="tonexty", fillcolor=rgba(blue, 0.28),
                   name="50-%-Band (P25–P75)", **band)
    )
    fig.add_trace(
        go.Scatter(
            x=t, y=sim.invested, mode="lines", name="Eingezahltes Kapital",
            line=dict(color=theme.ink2, width=1.5, dash="dash"),
            hovertemplate="%{y:,.0f}<extra>Eingezahlt</extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=t, y=q["P50"], mode="lines", name="Median", line=dict(color=blue, width=2.5),
            customdata=q[["P5", "P95"]].to_numpy(),
            hovertemplate="Median %{y:,.0f}<br>P5 %{customdata[0]:,.0f} · P95 %{customdata[1]:,.0f}<extra></extra>",
        )
    )
    upper = float(np.percentile(sim.wealth[:, -1], 97))
    fig.update_yaxes(range=[0, max(upper, float(q["P95"].max())) * 1.05])
    fig.update_layout(hovermode="x unified")
    return style(fig, theme, height=460, x_title="Jahre", y_title="Vermögen", y_format=",.0f")


def final_wealth_histogram(sim: SimulationResult, theme: Theme) -> go.Figure:
    final = sim.wealth[:, -1]
    upper = float(np.percentile(final, 99.5))
    lower = float(final.min())
    fig = go.Figure(
        go.Histogram(
            x=final[final <= upper], nbinsx=60, marker=dict(color=theme.series[0], line=dict(color=theme.surface, width=1)),
            hovertemplate="%{x}<br>%{y} Pfade<extra></extra>", name="Endvermögen",
        )
    )
    for value, label, color in (
        (sim.invested[-1], "Eingezahlt", theme.ink2),
        (float(np.median(final)), "Median", theme.ink),
    ):
        fig.add_vline(x=value, line=dict(color=color, width=1.5, dash="dash" if label == "Eingezahlt" else "solid"))
        fig.add_annotation(
            x=value, y=1, yref="paper", text=label, showarrow=False, xanchor="left", xshift=4,
            yanchor="top", font=dict(color=theme.ink2, size=12),
        )
    fig.update_xaxes(range=[min(lower, sim.invested[-1]) * 0.95, upper])
    fig.update_layout(bargap=0.04)
    return style(fig, theme, height=360, x_title="Endvermögen", y_title="Anzahl Pfade", x_format=",.0f", legend=False)


# ---------------------------------------------------------------------------
# Schätzfehler
# ---------------------------------------------------------------------------


def confidence_chart(table: pd.DataFrame, theme: Theme) -> go.Figure:
    """Geschätzte Renditen mit 95-%-Konfidenzintervall (Punkt und Fehlerbalken)."""
    fig = go.Figure(
        go.Scatter(
            x=table["mu"], y=table.index, mode="markers",
            error_x=dict(type="data", symmetric=False, array=table["ci_high"] - table["mu"],
                         arrayminus=table["mu"] - table["ci_low"], color=theme.series[0], thickness=2, width=6),
            marker=dict(color=theme.series[0], size=10, line=dict(color=theme.surface, width=2)),
            customdata=table[["ci_low", "ci_high"]].to_numpy(),
            hovertemplate="%{y}<br>Schätzung %{x:.1%}<br>95-%-Intervall %{customdata[0]:.1%} bis %{customdata[1]:.1%}<extra></extra>",
        )
    )
    fig.add_vline(x=0, line=dict(color=theme.axis, width=1))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    height = max(240, 44 * len(table) + 100)
    return style(fig, theme, height=height, x_title="Erwartete Rendite p. a. (95-%-Konfidenzintervall)",
                 x_format=".0%", legend=False)


def sensitivity_chart(assets: list[str], before: np.ndarray, after: np.ndarray, theme: Theme) -> go.Figure:
    fig = go.Figure()
    for name, values, color in (("Vorher", before, theme.series[0]), ("Nachher", after, theme.series[1])):
        fig.add_trace(
            go.Bar(y=assets, x=values, name=name, orientation="h", marker=dict(color=color, line=dict(width=0)),
                   hovertemplate="%{y}: %{x:.1%}<extra>" + name + "</extra>")
        )
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return style(fig, theme, height=_bar_height(len(assets), 2), x_title="Gewicht im Max-Sharpe-Portfolio",
                 x_format=".0%")


def broadie_chart(exp: FrontierExperiment, theme: Theme) -> go.Figure:
    fig = go.Figure()
    groups = (
        ("Geschätzter Rand (Sicht des Optimierers)", exp.estimated, theme.series[0]),
        ("Tatsächlicher Rand (wahre Parameter)", exp.actual, theme.series[1]),
    )
    for label, frontiers, color in groups:
        for k, fr in enumerate(frontiers):
            fig.add_trace(
                go.Scatter(
                    x=fr.vols, y=fr.returns, mode="lines", name=label, legendgroup=label, showlegend=k == 0,
                    line=dict(color=rgba(color, 0.55), width=1.2),
                    hovertemplate="Volatilität %{x:.1%}<br>Rendite %{y:.1%}<extra>" + label + "</extra>",
                )
            )
    tf = exp.true_frontier
    # Haben alle Assets dieselbe erwartete Rendite, schrumpft der wahre Rand auf einen Punkt.
    single_point = np.ptp(tf.vols) < 1e-9 and np.ptp(tf.returns) < 1e-9
    fig.add_trace(
        go.Scatter(
            x=tf.vols, y=tf.returns, mode="markers" if single_point else "lines", name="Wahrer effizienter Rand",
            line=dict(color=theme.ink, width=3),
            marker=dict(color=theme.ink, size=12, line=dict(color=theme.surface, width=2)),
            hovertemplate="Volatilität %{x:.1%}<br>Rendite %{y:.1%}<extra>Wahrer Rand</extra>",
        )
    )
    return style(fig, theme, height=500, x_title="Volatilität p. a.", y_title="Rendite p. a.",
                 x_format=".0%", y_format=".0%")


def sharpe_chart(exp: StrategyExperiment, theme: Theme) -> go.Figure:
    """Verteilung der tatsächlich erreichten Sharpe-Ratios je Strategie."""
    df = exp.sharpe_frame().dropna(subset=["sharpe_true"])
    order = list(dict.fromkeys(df["label"]))
    fig = go.Figure()
    fig.add_trace(
        go.Box(
            x=df["sharpe_true"], y=df["label"], orientation="h", name="Tatsächlich erreicht",
            marker=dict(color=theme.series[0], size=4), line=dict(width=1.5), fillcolor=rgba(theme.series[0], 0.15),
            boxpoints=False, hovertemplate="%{x:.2f}<extra></extra>",
        )
    )
    est = df.groupby("label", sort=False)["sharpe_est"].mean().reindex(order)
    fig.add_trace(
        go.Scatter(
            x=est.to_numpy(), y=est.index, mode="markers", name="Erwartet laut Schätzung (Mittel)",
            marker=dict(color=theme.series[1], size=11, symbol="diamond", line=dict(color=theme.surface, width=2)),
            hovertemplate="Erwartet: %{x:.2f}<extra>%{y}</extra>",
        )
    )
    opt = exp.optimal_stats[2]
    optimum_line = dict(color=theme.ink, width=1.5, dash="dash")
    fig.add_vline(x=opt, line=optimum_line)
    # Leere Spur, damit die Linie einen Legendeneintrag bekommt
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", line=optimum_line, name="Wahres Optimum"))
    fig.update_yaxes(categoryorder="array", categoryarray=order[::-1], showgrid=False)
    height = max(320, 52 * len(order) + 120)
    return style(fig, theme, height=height, x_title="Sharpe-Ratio")


def weight_distribution_chart(exp: StrategyExperiment, strategy_keys: list[str], theme: Theme) -> go.Figure:
    """Streuung der Gewichte über die Simulationsläufe im Vergleich zum wahren Optimum."""
    fig = go.Figure()
    assets = exp.assets
    for k, key in enumerate(strategy_keys):
        j = exp.strategies.index(key)
        w = exp.weights[:, j, :]
        w = w[np.isfinite(w).all(axis=1)]
        fig.add_trace(
            go.Box(
                x=np.tile(assets, len(w)), y=w.ravel(), name=STRATEGIES[key], boxpoints=False,
                marker=dict(color=theme.series[k]), line=dict(width=1.5), fillcolor=rgba(theme.series[k], 0.15),
            )
        )
    fig.add_trace(
        go.Scatter(
            x=assets, y=exp.optimal_weights, mode="markers", name="Wahres Optimum",
            marker=dict(color=theme.ink, size=11, symbol="diamond", line=dict(color=theme.surface, width=2)),
            hovertemplate="%{x}: %{y:.1%}<extra>Wahres Optimum</extra>",
        )
    )
    fig.update_layout(boxmode="group")
    return style(fig, theme, height=440, y_title="Gewicht", y_format=".0%")
