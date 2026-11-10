"""Lokaler Kursspeicher: die zuletzt erfolgreich geladenen Kurse je Ticker.

Yahoo drosselt häufige Abfragen und liefert dann für einzelne Ticker zeitweise nichts.
Damit Positionen nicht aus Bewertung und Analysen fallen, legt die App jede erfolgreich
geladene Kursreihe als CSV ab und greift bei Lücken darauf zurück.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .data import History

COLUMNS = ["close", "adj_close", "split"]


def _merge(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """Neue Werte haben Vorrang. Ältere Werte werden über die gemeinsamen Tage auf die neue
    Skala gebracht, weil Yahoo nach Splits und Dividenden die ganze Historie neu bereinigt."""
    if old is None or old.empty:
        return new.sort_index()
    old = old.copy()
    common = old.index.intersection(new.index)
    for column in ("close", "adj_close"):
        both = pd.concat([old.loc[common, column], new.loc[common, column]], axis=1).dropna()
        if not both.empty:
            ratio = float((both.iloc[:, 1] / both.iloc[:, 0]).median())
            if np.isfinite(ratio) and ratio > 0:
                old[column] = old[column] * ratio
    return new.combine_first(old)[COLUMNS].sort_index()


class PriceStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _path(self, ticker: str) -> Path:
        return self.folder / f"{re.sub(r'[^A-Za-z0-9._-]', '_', ticker)}.csv"

    def load(self, ticker: str) -> pd.DataFrame | None:
        path = self._path(ticker)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
        except (OSError, ValueError):
            return None
        return df.reindex(columns=COLUMNS) if not df.empty else None

    def save(self, hist: History) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        for ticker in hist.close.columns:
            new = pd.DataFrame({
                "close": hist.close[ticker],
                "adj_close": hist.adj_close[ticker] if ticker in hist.adj_close else np.nan,
                "split": hist.splits[ticker] if ticker in hist.splits else np.nan,
            }).dropna(subset=["close"])
            if new.empty:
                continue
            path = self._path(ticker)
            tmp = path.with_suffix(".tmp")
            _merge(self.load(ticker), new).to_csv(tmp)
            tmp.replace(path)

    def complete(self, hist: History, start: date, end: date) -> tuple[History, dict[str, date]]:
        """Speichert die geladenen Reihen und ergänzt fehlende Ticker aus dem Speicher.

        Rückgabe: ergänzte Kurse und je ergänztem Ticker der letzte gespeicherte Kurstag.
        """
        try:
            self.save(hist)
        except OSError:  # z. B. schreibgeschützter Ordner: dann eben ohne Speicher
            pass
        stale: dict[str, date] = {}
        close, adj, splits = {}, {}, {}
        for ticker in hist.missing:
            df = self.load(ticker)
            part = df.loc[pd.Timestamp(start):pd.Timestamp(end)] if df is not None else None
            if part is None or part["close"].dropna().empty:
                continue
            close[ticker] = part["close"]
            adj[ticker] = part["adj_close"].fillna(part["close"])
            splits[ticker] = part["split"].fillna(0.0)
            stale[ticker] = part["close"].dropna().index[-1].date()
        if not close:
            return hist, stale
        return History(
            pd.concat([hist.close, pd.DataFrame(close)], axis=1),
            pd.concat([hist.adj_close, pd.DataFrame(adj)], axis=1),
            pd.concat([hist.splits, pd.DataFrame(splits)], axis=1),
            [t for t in hist.missing if t not in close],
        ), stale
