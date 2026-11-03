"""Das eigene Portfolio: Positionen, Speichern/Laden, Bewertung und Aufteilung."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .data import _parse_number_column
from .market import BASE_CURRENCY, DIVERSIFIED, FUND_COUNTRY, UNKNOWN, SecurityInfo, major_currency


@dataclass
class Position:
    info: SecurityInfo
    shares: float
    purchase_price: float | None = None  # Einstandskurs je Stück in Euro

    @property
    def symbol(self) -> str:
        return self.info.symbol

    def to_dict(self) -> dict:
        return {"shares": self.shares, "purchase_price": self.purchase_price, **self.info.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> Position:
        price = data.get("purchase_price")
        return cls(
            info=SecurityInfo.from_dict(data),
            shares=float(data.get("shares", 0)),
            purchase_price=float(price) if price not in (None, "") else None,
        )


@dataclass
class Portfolio:
    name: str
    positions: list[Position] = field(default_factory=list)

    @property
    def symbols(self) -> list[str]:
        return [p.symbol for p in self.positions]

    def get(self, symbol: str) -> Position | None:
        return next((p for p in self.positions if p.symbol == symbol), None)

    def add(self, info: SecurityInfo, shares: float, purchase_price: float | None = None) -> None:
        """Fügt eine Position hinzu oder stockt eine bestehende auf (Einstandskurs gemittelt)."""
        if shares <= 0:
            raise ValueError("Die Stückzahl muss größer als null sein.")
        price = purchase_price if purchase_price else None
        existing = self.get(info.symbol)
        if existing is None:
            self.positions.append(Position(info, float(shares), price))
            return
        total = existing.shares + shares
        if existing.purchase_price is not None and price is not None:
            existing.purchase_price = (existing.shares * existing.purchase_price + shares * price) / total
        else:
            existing.purchase_price = None  # Einstandskurs nicht mehr bestimmbar
        existing.shares = total
        existing.info = info

    def remove(self, symbol: str) -> None:
        self.positions = [p for p in self.positions if p.symbol != symbol]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base_currency": BASE_CURRENCY,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "positions": [p.to_dict() for p in self.positions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Portfolio:
        return cls(name=str(data.get("name") or "Portfolio"),
                   positions=[Position.from_dict(p) for p in data.get("positions", [])])

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_csv(self) -> str:
        rows = [{"Symbol": p.symbol, "Name": p.info.name, "Stück": p.shares, "Kaufkurs": p.purchase_price}
                for p in self.positions]
        return pd.DataFrame(rows, columns=["Symbol", "Name", "Stück", "Kaufkurs"]).to_csv(
            index=False, sep=";", decimal=","
        )


_CSV_COLUMNS = {
    "symbol": {"symbol", "ticker", "kürzel", "wertpapier"},
    "shares": {"stück", "stueck", "anzahl", "menge", "shares", "quantity", "bestand"},
    "price": {"kaufkurs", "einstandskurs", "einstand", "kurs", "price", "purchase_price"},
}


def read_positions_csv(source: bytes | str) -> list[tuple[str, float, float | None]]:
    """Liest (Symbol, Stück, Kaufkurs) aus einer CSV-Datei mit deutschen oder englischen Spaltennamen."""
    text = source.decode("utf-8-sig") if isinstance(source, bytes) else source
    try:
        df = pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str)
    except Exception as exc:  # pandas wirft je nach Fehler unterschiedliche Typen
        raise ValueError(f"Die CSV-Datei konnte nicht gelesen werden: {exc}") from exc
    found = {}
    for col in df.columns:
        key = col.strip().lower().replace(" (eur)", "").replace(" in eur", "")
        for target, names in _CSV_COLUMNS.items():
            if key in names and target not in found:
                found[target] = col
    if "symbol" not in found or "shares" not in found:
        raise ValueError("Die CSV-Datei braucht mindestens die Spalten „Symbol“ und „Stück“.")
    shares = _parse_number_column(df[found["shares"]])
    prices = _parse_number_column(df[found["price"]]) if "price" in found else pd.Series(np.nan, index=df.index)
    rows = []
    for symbol, n, price in zip(df[found["symbol"]], shares, prices):
        if isinstance(symbol, str) and symbol.strip() and pd.notna(n) and n > 0:
            rows.append((symbol.strip().upper(), float(n), float(price) if pd.notna(price) and price > 0 else None))
    if not rows:
        raise ValueError("In der CSV-Datei wurden keine Positionen gefunden.")
    return rows


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9äöüß]+", "-", name.lower()).strip("-")
    return slug or "portfolio"


class PortfolioStore:
    """Speichert Portfolios als JSON-Dateien in einem Ordner."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _path(self, name: str) -> Path:
        return self.folder / f"{_slug(name)}.json"

    def names(self) -> list[str]:
        if not self.folder.is_dir():
            return []
        names = []
        for path in sorted(self.folder.glob("*.json")):
            try:
                names.append(json.loads(path.read_text(encoding="utf-8"))["name"])
            except (OSError, ValueError, KeyError):
                continue
        return sorted(names, key=str.lower)

    def load(self, name: str) -> Portfolio:
        return Portfolio.from_dict(json.loads(self._path(name).read_text(encoding="utf-8")))

    def save(self, portfolio: Portfolio) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._path(portfolio.name).write_text(portfolio.to_json(), encoding="utf-8")

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def exists(self, name: str) -> bool:
        return self._path(name).exists()


# ---------------------------------------------------------------------------
# Bewertung und Aufteilung
# ---------------------------------------------------------------------------


def valuation(portfolio: Portfolio, prices_eur: pd.Series) -> pd.DataFrame:
    """Aktueller Wert, Einstandswert und Gewinn/Verlust je Position (in Euro).

    Positionen ohne Kurs bleiben mit fehlenden Werten in der Tabelle, gehen
    aber nicht in Summen und Gewichte ein.
    """
    rows = []
    for p in portfolio.positions:
        price = float(prices_eur.get(p.symbol, np.nan))
        value = p.shares * price
        cost = p.shares * p.purchase_price if p.purchase_price else np.nan
        rows.append({
            "symbol": p.symbol, "name": p.info.name, "type": p.info.quote_type, "shares": p.shares,
            "price": price, "value": value, "purchase_price": p.purchase_price or np.nan, "cost": cost,
            "pnl": value - cost, "pnl_pct": value / cost - 1 if cost and cost > 0 else np.nan,
        })
    df = pd.DataFrame(rows, columns=["symbol", "name", "type", "shares", "price", "value", "purchase_price",
                                     "cost", "pnl", "pnl_pct"])
    total = df["value"].sum(min_count=1)
    df["weight"] = df["value"] / total if total and total > 0 else np.nan
    return df.set_index("symbol")


def exposure_matrix(infos: dict[str, SecurityInfo], by: str) -> pd.DataFrame:
    """Matrix Gruppen x Positionen: Anteil jeder Position an jeder Gruppe.

    ``by``: ``"sector"`` (Fonds über ihre Sektorgewichte), ``"country"`` oder
    ``"currency"`` (Handelswährung, Untereinheiten zusammengefasst).
    """
    columns = {}
    for symbol, info in infos.items():
        if by == "sector":
            columns[symbol] = info.sector_exposure()
        elif by == "country":
            columns[symbol] = {info.country: 1.0}
        elif by == "currency":
            columns[symbol] = {major_currency(info.currency)[0]: 1.0}
        else:
            raise ValueError(f"Unbekannte Aufteilung: {by}")
    return pd.DataFrame(columns).fillna(0.0)


def exposures(weights: pd.Series, infos: dict[str, SecurityInfo], by: str) -> pd.Series:
    """Gewicht je Sektor, Land oder Währung, absteigend sortiert."""
    matrix = exposure_matrix({s: infos[s] for s in weights.index}, by)
    return (matrix @ weights.reindex(matrix.columns).fillna(0.0)).sort_values(ascending=False)


NON_SECTOR_GROUPS = {"Anleihen", "Geldmarkt", DIVERSIFIED, UNKNOWN}


def is_concentration_group(by: str, group: str) -> bool:
    """Gruppen, für die eine Obergrenze sinnvoll ist.

    Ausgenommen sind der Euro (kein Währungsrisiko), Fonds ohne Länderangabe sowie
    Anleihen, Geldmarkt und nicht aufschlüsselbare Fonds bei den Sektoren.
    """
    if by == "sector":
        return group not in NON_SECTOR_GROUPS
    if by == "country":
        return group not in (FUND_COUNTRY, UNKNOWN)
    if by == "currency":
        return group != BASE_CURRENCY
    return True
