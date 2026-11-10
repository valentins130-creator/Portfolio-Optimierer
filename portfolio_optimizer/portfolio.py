"""Das eigene Portfolio: Transaktionen, Bestände, Speichern/Laden, Bewertung und Aufteilung."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .data import _parse_number_column
from .market import BASE_CURRENCY, DIVERSIFIED, FUND_COUNTRY, UNKNOWN, SecurityInfo, major_currency


BUY, SELL = "Kauf", "Verkauf"


def parse_date(value) -> date | None:
    """Datum aus ISO (2024-03-01) oder deutschem Format (01.03.2024); leer -> None."""
    if value is None or (isinstance(value, float) and np.isnan(value)) or str(value).strip() in ("", "nan", "None"):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    fmt = "%d.%m.%Y" if re.match(r"^\d{1,2}\.\d{1,2}\.\d{4}$", text) else "%Y-%m-%d"
    try:
        return datetime.strptime(text[:10], fmt).date()
    except ValueError as exc:
        raise ValueError(f"Ungültiges Datum: {text}") from exc


@dataclass
class Transaction:
    """Ein Kauf oder Verkauf. Kurs je Stück in Euro, wie im Depotauszug."""

    symbol: str
    kind: str = BUY
    shares: float = 0.0
    price: float | None = None
    date: date | None = None

    @property
    def amount(self) -> float | None:
        return self.shares * self.price if self.price else None

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "kind": self.kind, "shares": self.shares, "price": self.price,
                "date": self.date.isoformat() if self.date else None}

    @classmethod
    def from_dict(cls, data: dict) -> Transaction:
        price = data.get("price")
        return cls(
            symbol=str(data["symbol"]),
            kind=SELL if data.get("kind") == SELL else BUY,
            shares=float(data.get("shares", 0)),
            price=float(price) if price not in (None, "") else None,
            date=parse_date(data.get("date")),
        )


def num_text(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _order(t: Transaction) -> tuple:
    # Ohne Datum zuerst (Altbestand); am selben Tag Käufe vor Verkäufen
    return (t.date or date.min, 0 if t.kind == BUY else 1)


def fifo(transactions: list[Transaction]) -> tuple[float, float | None, float | None]:
    """Bestand, Einstandswert der gehaltenen Stücke und realisierter Gewinn nach FIFO.

    Einstandswert bzw. Gewinn sind ``None``, wenn ein dafür nötiger Kurs fehlt.
    Wirft ``ValueError``, wenn mehr verkauft als gehalten wird.
    """
    lots, realized = _replay(transactions)
    shares = sum(lot[0] for lot in lots)
    cost = sum(lot[0] * lot[1] for lot in lots) if all(lot[1] is not None for lot in lots) else None
    return shares, cost, realized


def sale_gain(transactions: list[Transaction], shares: float, price: float) -> float | None:
    """Gewinn, wenn jetzt ``shares`` Stück zu ``price`` verkauft würden (FIFO: älteste Stücke zuerst)."""
    lots, _ = _replay(transactions)
    gain, remaining = 0.0, shares
    for lot_shares, lot_price in lots:
        if remaining <= 1e-9:
            break
        if lot_price is None:
            return None
        take = min(lot_shares, remaining)
        gain += take * (price - lot_price)
        remaining -= take
    return gain


def _replay(transactions: list[Transaction]) -> tuple[list[list], float | None]:
    """Spielt die Transaktionen ab: verbleibende Kauf-Tranchen [Stück, Kurs] und realisierter Gewinn."""
    lots: list[list] = []  # [Stück, Kurs]
    realized, known = 0.0, True
    for t in sorted(transactions, key=_order):
        if t.kind == BUY:
            lots.append([t.shares, t.price])
            continue
        remaining = t.shares
        while remaining > 1e-9:
            if not lots:
                when = f" am {t.date:%d.%m.%Y}" if t.date else ""
                raise ValueError(f"Der Verkauf von {num_text(t.shares)} Stück {t.symbol}{when} übersteigt den Bestand.")
            lot = lots[0]
            take = min(lot[0], remaining)
            if lot[1] is None or t.price is None:
                known = False
            else:
                realized += take * (t.price - lot[1])
            lot[0] -= take
            remaining -= take
            if lot[0] <= 1e-9:
                lots.pop(0)
    return lots, realized if known else None


@dataclass
class Position:
    """Aktueller Bestand eines Wertpapiers, abgeleitet aus seinen Transaktionen."""

    info: SecurityInfo
    shares: float
    purchase_price: float | None = None  # Ø Einstandskurs der gehaltenen Stücke (FIFO) in Euro
    realized: float | None = 0.0  # realisierter Gewinn aus Verkäufen
    first_date: date | None = None

    @property
    def symbol(self) -> str:
        return self.info.symbol


def split_factor(events: list[tuple[date, float]], when: date | None) -> float:
    """Produkt der Split-Verhältnisse nach ``when`` (Splits ab ihrem Ex-Tag)."""
    if when is None:
        return 1.0
    factor = 1.0
    for day, ratio in events:
        if day > when:
            factor *= ratio
    return factor


@dataclass
class Portfolio:
    """Wertpapiere und Transaktionen, so wie sie erfasst wurden.

    ``splits`` (Symbol -> [(Ex-Tag, Verhältnis)]) kommt aus den Marktdaten und wird nicht
    gespeichert: Transaktionen vor einem Split zählen mit entsprechend mehr Stücken zu
    einem entsprechend niedrigeren Kurs – passend zu den splitbereinigten Kursreihen.
    """

    name: str
    securities: dict[str, SecurityInfo] = field(default_factory=dict)
    transactions: list[Transaction] = field(default_factory=list)
    splits: dict[str, list[tuple[date, float]]] = field(default_factory=dict, repr=False, compare=False)

    def sale_gain(self, symbol: str, shares: float, price: float) -> float | None:
        """Gewinn eines gedachten Verkaufs heute nach FIFO; ``None`` ohne Kaufkurse."""
        return sale_gain(self.transactions_of(symbol), shares, price)

    def adjusted(self, t: Transaction) -> Transaction:
        """Transaktion in Stück und Kurs nach allen späteren Splits."""
        factor = split_factor(self.splits.get(t.symbol, []), t.date)
        if factor == 1.0:
            return t
        return Transaction(t.symbol, t.kind, t.shares * factor, t.price / factor if t.price else t.price, t.date)

    def effective_transactions(self) -> list[Transaction]:
        """Alle Transaktionen splitbereinigt (für Bestände, Gewinne und Wertentwicklung)."""
        return [self.adjusted(t) for t in self.transactions]

    def transactions_of(self, symbol: str) -> list[Transaction]:
        """Splitbereinigte Transaktionen eines Wertpapiers."""
        return [self.adjusted(t) for t in self.transactions if t.symbol == symbol]

    def applied_splits(self) -> list[tuple[str, date, float]]:
        """Splits, die erfasste Transaktionen betreffen: (Symbol, Ex-Tag, Verhältnis)."""
        out = []
        for symbol, events in self.splits.items():
            dates = [t.date for t in self.transactions if t.symbol == symbol and t.date]
            out += [(symbol, day, ratio) for day, ratio in events if dates and min(dates) < day]
        return sorted(out, key=lambda e: e[1])

    @property
    def positions(self) -> list[Position]:
        out = []
        for symbol, info in self.securities.items():
            txs = self.transactions_of(symbol)
            shares, cost, realized = fifo(txs)
            if shares <= 1e-9:
                continue
            dates = [t.date for t in txs if t.date]
            out.append(Position(info, shares, cost / shares if cost is not None else None, realized,
                                min(dates) if dates else None))
        return out

    @property
    def symbols(self) -> list[str]:
        return [p.symbol for p in self.positions]

    def get(self, symbol: str) -> Position | None:
        return next((p for p in self.positions if p.symbol == symbol), None)

    def realized_gains(self) -> float | None:
        values = [fifo(self.transactions_of(s))[2] for s in self.securities]
        return None if any(v is None for v in values) else float(sum(values))

    def _check(self, symbol: str) -> None:
        fifo(self.transactions_of(symbol))

    def add_transaction(self, info: SecurityInfo, kind: str, shares: float, price: float | None = None,
                        when: date | None = None) -> None:
        """Erfasst einen Kauf oder Verkauf; ein Verkauf darf den Bestand nicht übersteigen."""
        if shares <= 0:
            raise ValueError("Die Stückzahl muss größer als null sein.")
        if kind not in (BUY, SELL):
            raise ValueError(f"Unbekannte Transaktionsart: {kind}")
        self.securities[info.symbol] = info
        self.transactions.append(Transaction(info.symbol, kind, float(shares), price or None, when))
        try:
            self._check(info.symbol)
        except ValueError:
            self.transactions.pop()
            if not self.transactions_of(info.symbol):
                del self.securities[info.symbol]
            raise

    def add(self, info: SecurityInfo, shares: float, purchase_price: float | None = None,
            when: date | None = None) -> None:
        """Kauf erfassen (Kurzform)."""
        self.add_transaction(info, BUY, shares, purchase_price, when)

    def update_transaction(self, index: int, **changes) -> None:
        """Ändert eine Transaktion; ungültige Änderungen (z. B. Überverkauf) werden zurückgenommen."""
        tx = self.transactions[index]
        before = Transaction(**vars(tx))
        for key, value in changes.items():
            setattr(tx, key, value)
        try:
            if tx.shares <= 0:
                raise ValueError("Die Stückzahl muss größer als null sein.")
            self._check(tx.symbol)
        except ValueError:
            self.transactions[index] = before
            raise

    def remove_transaction(self, index: int) -> None:
        tx = self.transactions.pop(index)
        try:
            self._check(tx.symbol)
        except ValueError:
            self.transactions.insert(index, tx)
            raise
        if not self.transactions_of(tx.symbol):
            self.securities.pop(tx.symbol, None)

    def remove_transactions(self, indices) -> list[str]:
        """Löscht mehrere Transaktionen auf einmal – alle oder keine.

        Rückgabe: Fehlermeldungen, wenn danach ein Verkauf den Bestand übersteigen würde;
        dann bleibt alles unverändert.
        """
        drop = set(indices)
        symbols = {self.transactions[i].symbol for i in drop}
        before = self.transactions
        self.transactions = [t for i, t in enumerate(before) if i not in drop]
        errors = []
        for symbol in sorted(symbols):
            try:
                self._check(symbol)
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            self.transactions = before
            return errors
        for symbol in symbols:
            if not self.transactions_of(symbol):
                self.securities.pop(symbol, None)
        return []

    def remove(self, symbol: str) -> None:
        """Entfernt ein Wertpapier mit allen Transaktionen."""
        self.transactions = [t for t in self.transactions if t.symbol != symbol]
        self.securities.pop(symbol, None)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "format": 2,
            "base_currency": BASE_CURRENCY,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "securities": {s: info.to_dict() for s, info in self.securities.items()},
            "transactions": [t.to_dict() for t in self.transactions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Portfolio:
        pf = cls(name=str(data.get("name") or "Portfolio"))
        if "transactions" in data:
            pf.securities = {s: SecurityInfo.from_dict(info) for s, info in data.get("securities", {}).items()}
            pf.transactions = [Transaction.from_dict(t) for t in data["transactions"]]
        else:  # altes Format: Positionen mit Stückzahl und Kaufkurs, ohne Datum
            for item in data.get("positions", []):
                info = SecurityInfo.from_dict(item)
                price = item.get("purchase_price")
                pf.securities[info.symbol] = info
                pf.transactions.append(Transaction(info.symbol, BUY, float(item.get("shares", 0)),
                                                   float(price) if price not in (None, "") else None, None))
        return pf

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_csv(self) -> str:
        rows = [{"Datum": t.date.strftime("%d.%m.%Y") if t.date else "", "Typ": t.kind, "Symbol": t.symbol,
                 "Name": self.securities[t.symbol].name if t.symbol in self.securities else "",
                 "Stück": t.shares, "Kurs": t.price} for t in sorted(self.transactions, key=_order)]
        return pd.DataFrame(rows, columns=["Datum", "Typ", "Symbol", "Name", "Stück", "Kurs"]).to_csv(
            index=False, sep=";", decimal=","
        )


_CSV_COLUMNS = {
    "symbol": {"symbol", "ticker", "kürzel", "wertpapier"},
    "shares": {"stück", "stueck", "anzahl", "menge", "shares", "quantity", "bestand"},
    "price": {"kaufkurs", "einstandskurs", "einstand", "kurs", "price", "purchase_price"},
    "date": {"datum", "kaufdatum", "date", "handelstag", "ausführung"},
    "kind": {"typ", "art", "transaktion", "type", "side"},
}


def read_transactions_csv(source: bytes | str) -> list[tuple[str, str, float, float | None, date | None]]:
    """Liest (Symbol, Typ, Stück, Kurs, Datum) aus einer CSV-Datei mit deutschen oder englischen Spalten.

    Pflicht sind Symbol und Stück; ohne Typ-Spalte gilt jede Zeile als Kauf.
    """
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
    for i, (symbol, n, price) in enumerate(zip(df[found["symbol"]], shares, prices)):
        if not (isinstance(symbol, str) and symbol.strip() and pd.notna(n) and n > 0):
            continue
        kind_text = str(df[found["kind"]].iloc[i]).strip().lower() if "kind" in found else ""
        kind = SELL if kind_text in ("verkauf", "sell", "v", "s") else BUY
        when = parse_date(df[found["date"]].iloc[i]) if "date" in found else None
        rows.append((symbol.strip().upper(), kind, float(n), float(price) if pd.notna(price) and price > 0 else None,
                     when))
    if not rows:
        raise ValueError("In der CSV-Datei wurden keine Transaktionen gefunden.")
    return rows


def read_positions_csv(source: bytes | str) -> list[tuple[str, float, float | None]]:
    """Kurzform für Bestandslisten: (Symbol, Stück, Kaufkurs) aller Käufe."""
    return [(s, n, p) for s, kind, n, p, _ in read_transactions_csv(source) if kind == BUY]


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9äöüß]+", "-", name.lower()).strip("-")
    return slug or "portfolio"


TRASH_DAYS = 30


@dataclass(frozen=True)
class TrashItem:
    name: str
    deleted: datetime
    path: Path


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

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    # Papierkorb: Löschen verschiebt nur; nach TRASH_DAYS Tagen wird endgültig aufgeräumt

    @property
    def trash_folder(self) -> Path:
        return self.folder / "papierkorb"

    def delete(self, name: str) -> None:
        """Verschiebt das Portfolio in den Papierkorb."""
        source = self._path(name)
        if not source.exists():
            return
        self.trash_folder.mkdir(parents=True, exist_ok=True)
        source.replace(self.trash_folder / f"{source.stem}--{datetime.now():%Y%m%d-%H%M%S-%f}.json")

    def trash(self) -> list[TrashItem]:
        """Gelöschte Portfolios, neueste zuerst; abgelaufene Einträge werden dabei entfernt."""
        items = []
        if not self.trash_folder.is_dir():
            return items
        for path in self.trash_folder.glob("*--*.json"):
            try:
                deleted = datetime.strptime(path.stem.rsplit("--", 1)[1], "%Y%m%d-%H%M%S-%f")
                name = json.loads(path.read_text(encoding="utf-8"))["name"]
            except (OSError, ValueError, KeyError):
                continue
            if (datetime.now() - deleted).days >= TRASH_DAYS:
                path.unlink(missing_ok=True)
                continue
            items.append(TrashItem(name, deleted, path))
        return sorted(items, key=lambda item: item.deleted, reverse=True)

    def restore(self, item: TrashItem) -> Portfolio:
        """Holt ein Portfolio zurück; gibt es den Namen inzwischen, bekommt es einen Zusatz."""
        portfolio = Portfolio.from_dict(json.loads(item.path.read_text(encoding="utf-8")))
        base, i = portfolio.name, 2
        while self.exists(portfolio.name):
            portfolio.name, i = f"{base} ({i})", i + 1
        self.save(portfolio)
        item.path.unlink(missing_ok=True)
        return portfolio


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
            "realized": np.nan if p.realized is None else p.realized, "first_date": p.first_date,
        })
    df = pd.DataFrame(rows, columns=["symbol", "name", "type", "shares", "price", "value", "purchase_price",
                                     "cost", "pnl", "pnl_pct", "realized", "first_date"])
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
