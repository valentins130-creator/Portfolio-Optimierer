"""Klumpenrisiko: Konzentration nach Einzelwerten, Sektoren, Währungen und Gruppen
stark korrelierter Positionen.

Länder bleiben außen vor: Für Fonds liefern die Datenquellen keine Länderaufteilung,
eine Länderkonzentration wäre deshalb irreführend.

Neben dem Gewicht zählt der Risikoanteil: Eine Position mit 10 % Gewicht kann
ein Drittel der Schwankung verursachen, wenn sie volatil ist und mit dem Rest
des Depots stark korreliert.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from .market import SecurityInfo
from .optimization import risk_contributions
from .portfolio import exposure_matrix, is_concentration_group

PERIODS_PER_YEAR = 52  # Wochenrenditen

KINDS = {"position": "Einzelwert", "sector": "Sektor", "currency": "Währung", "cluster": "Korrelations-Cluster"}
GROUPS = ("sector", "currency")  # Aufteilungen, für die Grenzen gelten


@dataclass(frozen=True)
class Limits:
    """Obergrenzen, ab denen eine Konzentration als Klumpenrisiko gilt."""

    position: float = 0.10  # einzelne Aktie (Fonds sind selbst gestreut)
    sector: float = 0.30
    currency: float = 0.50  # je Fremdwährung
    cluster: float = 0.40
    correlation: float = 0.70  # ab dieser Korrelation gelten Positionen als "ähnlich"

    def for_kind(self, kind: str) -> float:
        return getattr(self, kind)


@dataclass
class Finding:
    kind: str  # Schlüssel aus KINDS
    group: str
    weight: float
    limit: float
    risk_share: float
    members: dict[str, float] = field(default_factory=dict)  # Symbol -> Anteil der Position an der Gruppe

    @property
    def excess(self) -> float:
        return max(0.0, self.weight - self.limit)

    @property
    def exceeded(self) -> bool:
        return self.weight > self.limit + 1e-12

    @property
    def status(self) -> str:
        if self.exceeded:
            return "über Grenze"
        return "nahe Grenze" if self.weight >= 0.8 * self.limit else "ok"


@dataclass
class ConcentrationReport:
    findings: list[Finding]
    hhi: float  # Herfindahl-Index der Positionsgewichte
    top5: float
    diversification_ratio: float  # gewichtete Einzelvolatilitäten / Portfoliovolatilität
    risk_shares: pd.Series  # Risikoanteil je Position
    clusters: list[list[str]]

    @property
    def effective_positions(self) -> float:
        return 1 / self.hhi if self.hhi > 0 else float("nan")

    @property
    def exceeded(self) -> list[Finding]:
        return [f for f in self.findings if f.exceeded]

    def by_kind(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]


def hhi(weights: pd.Series | np.ndarray) -> float:
    w = np.asarray(weights, dtype=float)
    return float((w**2).sum())


def correlation_clusters(returns: pd.DataFrame, threshold: float) -> list[list[str]]:
    """Gruppen von Positionen, die im Mittel mindestens mit ``threshold`` korrelieren.

    Hierarchisches Clustering (Average Linkage) auf dem Abstand sqrt(2 (1 - rho)).
    """
    returns = returns.dropna(axis=1, how="all").dropna()
    if returns.shape[1] < 2 or len(returns) < 10:
        return []
    corr = returns.corr().to_numpy()
    dist = np.sqrt(np.clip(2 * (1 - corr), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    tree = linkage(squareform(dist, checks=False), method="average")
    labels = fcluster(tree, t=np.sqrt(2 * (1 - threshold)), criterion="distance")
    groups: dict[int, list[str]] = {}
    for symbol, label in zip(returns.columns, labels):
        groups.setdefault(label, []).append(symbol)
    return sorted((g for g in groups.values() if len(g) > 1), key=len, reverse=True)


def analyze(
    weights: pd.Series,
    infos: dict[str, SecurityInfo],
    returns: pd.DataFrame,
    limits: Limits = Limits(),
) -> ConcentrationReport:
    """Erstellt den Klumpenrisiko-Bericht.

    ``weights``: aktuelle Gewichte je Symbol (Summe 1). ``returns``: Wochenrenditen in
    Euro derselben Symbole.
    """
    weights = weights[weights > 0]
    symbols = list(weights.index)
    rets = returns.reindex(columns=symbols).dropna()
    cov = rets.cov().to_numpy() * PERIODS_PER_YEAR
    w = weights.to_numpy()
    rc = pd.Series(risk_contributions(w, cov), index=symbols) if len(rets) > 2 else weights * np.nan
    vols = np.sqrt(np.diag(cov))
    port_vol = float(np.sqrt(w @ cov @ w))
    findings: list[Finding] = []

    for symbol in symbols:
        if not infos[symbol].is_fund:
            findings.append(Finding("position", infos[symbol].name, float(weights[symbol]), limits.position,
                                    float(rc[symbol]), {symbol: 1.0}))

    for by in GROUPS:
        matrix = exposure_matrix({s: infos[s] for s in symbols}, by)
        group_weights = matrix @ weights.reindex(matrix.columns)
        group_risk = matrix @ rc.reindex(matrix.columns)
        for group in matrix.index:
            if not is_concentration_group(by, group) or group_weights[group] <= 0:
                continue
            members = {s: float(matrix.at[group, s]) for s in matrix.columns if matrix.at[group, s] > 0}
            findings.append(Finding(by, group, float(group_weights[group]), limits.for_kind(by),
                                    float(group_risk[group]), members))

    # Breit gestreute Fonds laufen naturgemäß mit dem Markt; Cluster sollen versteckte
    # Konzentration unter Einzelwerten zeigen.
    singles = [s for s in symbols if not infos[s].is_fund]
    clusters = correlation_clusters(rets[singles], limits.correlation)
    for members in clusters:
        names = ", ".join(infos[s].name for s in members[:3]) + (" …" if len(members) > 3 else "")
        findings.append(Finding("cluster", names, float(weights[members].sum()), limits.cluster,
                                float(rc[members].sum()), {s: 1.0 for s in members}))

    order = list(KINDS)
    findings.sort(key=lambda f: (not f.exceeded, order.index(f.kind), -f.weight))
    sorted_w = np.sort(w)[::-1]
    return ConcentrationReport(
        findings=findings,
        hhi=hhi(w),
        top5=float(sorted_w[:5].sum()),
        diversification_ratio=float(w @ vols / port_vol) if port_vol > 0 else float("nan"),
        risk_shares=rc,
        clusters=clusters,
    )
