"""Import Trade Republic transactions and dated net-worth statements.

No personal statement content is written to the repository or a server file.
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd


CATEGORIES = ("Aktien", "Aktien-ETFs/Fonds", "Anleihen", "Anleihen-ETFs/Fonds", "Krypto", "Derivate/Leveraged", "Cash", "Sonstige")
POSITION_EVENTS = {"BUY": 1, "SELL": -1}
# Corporate actions need individual assessment; never implicitly become purchases.
REVIEW_EVENTS = {"FREE_RECEIPT", "SPLIT", "MERGER", "STOCKPERK", "WARRANT_EXERCISE", "FINAL_MATURITY", "FULL_CALL", "TILG"}
ISIN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")
DE_NUMBER = r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?"


def number(value: object) -> float:
    if value is None or pd.isna(value):
        return 0.0
    text = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text) if text else 0.0


def category(name: str, asset_class: str = "", section: str = "") -> str:
    name_lower = name.lower()
    if section == "CRYPTO WALLET" or asset_class == "CRYPTO":
        return "Krypto"
    if section == "CASH":
        return "Cash"
    if "leveraged" in name_lower or re.search(r"\b[2-9]x\b", name_lower) or asset_class == "DERIVATIVE":
        return "Derivate/Leveraged"
    if section == "ZINSPRODUKTE" or asset_class == "BOND":
        return "Anleihen"
    if asset_class == "STOCK":
        return "Aktien"
    if asset_class == "FUND" or any(word in name_lower for word in ("msci", "ftse", "s&p 500", "etf", "ucits")):
        if any(word in name_lower for word in ("bond", "treasury", "government bond", "aggregate bonds")):
            return "Anleihen-ETFs/Fonds"
        return "Aktien-ETFs/Fonds"
    if section == "BROKERAGE":
        return "Sonstige"  # Unbekannte Brokerage-Produkte erst nach Prüfung einordnen
    return "Sonstige"


@dataclass
class Statement:
    positions: pd.DataFrame
    as_of: str
    expected_total: float
    warnings: list[str]


def parse_statement_pdf(content: bytes) -> Statement:
    try:
        import pdfplumber
    except ImportError as exc:  # z. B. lokal ohne "pip install -r requirements.txt"
        raise ValueError("Für den PDF-Import fehlt das Paket pdfplumber. Bitte "
                         "„python -m pip install -r requirements.txt“ ausführen.") from exc

    if not content.startswith(b"%PDF"):
        raise ValueError("Die Datei ist kein PDF.")
    rows: list[dict] = []
    section = ""
    as_of = ""
    expected_total = None
    for_page = []
    with pdfplumber.open(io.BytesIO(content)) as document:
        for page in document.pages:
            for_page.extend((page.extract_text() or "").splitlines())
    if not any("VERMÖGENSÜBERSICHT" in line for line in for_page):
        raise ValueError("Keine unterstützte Trade-Republic-Vermögensübersicht gefunden.")
    for line in for_page:
        date_match = re.search(r"\bzum\s+(\d{2}\.\d{2}\.\d{4})", line)
        if date_match and not as_of:
            as_of = date_match.group(1)
        total_match = re.match(rf"^GESAMT\s+({DE_NUMBER})\s+EUR\b", line)
        if total_match:
            expected_total = number(total_match.group(1))
        stripped = line.strip()
        if stripped in ("BROKERAGE", "ZINSPRODUKTE", "CRYPTO WALLET", "CASH"):
            section = stripped
            continue
        if stripped.startswith("Aufstellung über das Cash") or stripped.startswith("PRODUKT"):
            section = "CASH"
        if section in ("BROKERAGE", "ZINSPRODUKTE", "CRYPTO WALLET"):
            # Positions are uniquely identified by a quantity (including fractional pieces)
            # at the start of their line, followed by the product and two euro figures.
            match = re.match(rf"^({DE_NUMBER})(?:\s+USD)?\s+Stk\.\s+(.+?)\s+({DE_NUMBER})\s+({DE_NUMBER})$", stripped)
            bond_match = None if match else re.match(rf"^({DE_NUMBER})\s+USD\s+(.+?)\s+({DE_NUMBER})\s+({DE_NUMBER})$", stripped)
            match = match or bond_match
            if match:
                qty, name, price, value = match.groups()
                rows.append({"Name": name.strip(), "ISIN/Symbol": "", "Anteile": number(qty),
                             "Kurs (Beleg)": number(price), "Wert EUR": number(value),
                             "Anlageklasse": category(name, section=section), "Bereich": section})
                continue
            if rows and rows[-1]["Bereich"] == section:
                identifier = re.search(r"ISIN:\s*([A-Z0-9]{12})", stripped)
                if identifier:
                    rows[-1]["ISIN/Symbol"] = identifier.group(1)
                elif section == "CRYPTO WALLET":
                    ticker = re.match(r"^(BTC|ETH|SOL|XRP|ADA|DOT)\s+\d{2}\.\d{2}\.\d{4}", stripped)
                    if ticker:
                        rows[-1]["ISIN/Symbol"] = ticker.group(1)
        if section == "CASH":
            cash_match = re.match(rf"^Cashkonto\s+({DE_NUMBER})\s+EUR?$", stripped)
            if cash_match:
                rows.append({"Name": "Cashkonto", "ISIN/Symbol": "EUR", "Anteile": number(cash_match.group(1)),
                             "Kurs (Beleg)": 1.0, "Wert EUR": number(cash_match.group(1)),
                             "Anlageklasse": "Cash", "Bereich": "CASH"})
    if expected_total is None or not rows:
        raise ValueError("Positionen oder Gesamtwert nicht lesbar. Bitte PDF-Format prüfen.")
    frame = pd.DataFrame(rows)
    warnings = []
    difference = round(float(frame["Wert EUR"].sum()) - expected_total, 2)
    if abs(difference) > 0.05:
        warnings.append(f"Die extrahierten Positionen weichen um {difference:+.2f} EUR vom Beleg-Gesamtwert ab.")
    if frame["ISIN/Symbol"].eq("").any():
        warnings.append("Nicht alle ISINs/Symbole wurden erkannt; bitte die Tabelle kontrollieren.")
    if not as_of:
        warnings.append("Der Stichtag konnte nicht erkannt werden.")
    frame["Prüfhinweis"] = "; ".join(warnings) if warnings else "Bestand und Anlageklasse bestätigen"
    frame["Bestätigt"] = False
    return Statement(frame, as_of, expected_total, warnings)


def parse_broker_csv(content: bytes) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return provisional holdings, an auditable event table, and type counts.

    Only validated BUY/SELL events contribute to provisional holdings.
    Cashflows, dividends, interest, taxes and unreviewed corporate actions do not.
    No claim of current portfolio valuation is made from historical trade prices.
    """
    df = pd.read_csv(io.BytesIO(content), sep=None, engine="python", dtype=str, encoding="utf-8-sig")
    df.columns = df.columns.str.strip().str.lower()
    if "date" not in df.columns and "datetime" in df.columns:
        df = df.rename(columns={"datetime": "date"})
    required = {"date", "type", "symbol", "shares"}
    if not required.issubset(df.columns):
        raise ValueError("CSV enthält nicht die erwarteten Broker-Spalten: " + ", ".join(sorted(required - set(df.columns))))
    df["type"] = df["type"].fillna("").astype(str).str.upper().str.strip()
    types = df["type"].value_counts().to_dict()
    events = []
    for index, row in df.iterrows():
        kind = row["type"]
        symbol = str(row.get("symbol") or "").strip()
        if symbol.lower() == "nan":
            symbol = ""
        try:
            shares = number(row.get("shares"))
        except (ValueError, TypeError):
            shares = float("nan")
        price = _price(row, shares)
        action = "Ignoriert (keine Bestandsänderung)"
        delta = 0.0
        if kind in POSITION_EVENTS:
            if symbol and math.isfinite(shares) and shares != 0 and not (kind == "BUY" and shares < 0) and pd.notna(pd.to_datetime(row.get("date"), errors="coerce")):
                delta = abs(shares) * POSITION_EVENTS[kind]
                action = "Bestandsänderung"
            else:
                action = "Prüfen (Symbol, Stückzahl oder Datum ungültig)"
        elif kind in REVIEW_EVENTS:
            action = "Manuell prüfen (Kapitalmaßnahme)"
        elif kind not in {"DIVIDEND", "DISTRIBUTION", "INTEREST", "INTEREST_PAYMENT", "DEPOSIT", "WITHDRAWAL", "TAX", "FEE", "TRANSFER_IN", "TRANSFER_OUT", "CARD_TRANSACTION", "CARD_TRANSACTION_INTERNATIONAL", "CARD_ORDERING_FEE", "CUSTOMER_INPAYMENT", "CUSTOMER_INBOUND", "CUSTOMER_OUTBOUND_REQUEST", "TRANSFER_INBOUND", "TRANSFER_OUTBOUND", "TRANSFER_INSTANT_INBOUND", "TRANSFER_INSTANT_OUTBOUND", "TRANSFER_DIRECT_DEBIT_INBOUND", "BENEFITS_SAVEBACK", "TAX_OPTIMIZATION", "PRE_DETERMINED_TAX_BASE"}:
            action = "Manuell prüfen (unbekannter Buchungstyp)"
        events.append({"Zeile": index + 2, "Datum": row.get("date"), "Typ": kind,
                           "Name": row.get("name") if pd.notna(row.get("name")) else "",
                           "ISIN/Symbol": symbol, "Anlageklasse": row.get("asset_class") if pd.notna(row.get("asset_class")) else "",
                           "Anteile": shares, "Bestandsänderung": delta, "Kurs": price, "Status": action})
    audit = pd.DataFrame(events, columns=["Zeile", "Datum", "Typ", "Name", "ISIN/Symbol", "Anlageklasse",
                                          "Anteile", "Bestandsänderung", "Kurs", "Status"])
    positive = audit[(audit["Status"] == "Bestandsänderung") & audit["ISIN/Symbol"].ne("")]
    holdings = []
    for symbol, group in positive.groupby("ISIN/Symbol", sort=False):
        shares = float(group["Bestandsänderung"].sum())
        if abs(shares) <= 1e-9:
            continue
        name = next((str(x) for x in group["Name"].iloc[::-1] if str(x).strip()), symbol)
        asset_class = next((str(x) for x in group["Anlageklasse"].iloc[::-1] if str(x).strip()), "")
        holdings.append({"Name": name, "ISIN/Symbol": symbol, "Anteile": shares,
                         "Anlageklasse": category(name, asset_class), "Status": "Vorläufig; mit Depotauszug abgleichen"})
    frame = pd.DataFrame(holdings, columns=["Name", "ISIN/Symbol", "Anteile", "Anlageklasse", "Status"])
    frame["Prüfhinweis"] = "Historie vollständig? Stückzahl und Anlageklasse bestätigen"
    affected = set(audit.loc[audit["Status"].str.contains("prüfen|Prüfen"), "ISIN/Symbol"])
    frame.loc[frame["ISIN/Symbol"].isin(affected), "Prüfhinweis"] = "Ungeklärte Buchungen: Gesamtbestand abgleichen und ggf. korrigieren"
    frame["Bestätigt"] = False
    return frame, audit, types


def _price(row: pd.Series, shares: float) -> float | None:
    """Kurs je Stück in Euro, falls der Export ihn (Spalte price) oder den Betrag (amount) enthält."""
    try:
        if "price" in row and pd.notna(row["price"]) and number(row["price"]) > 0:
            return number(row["price"])
        if "amount" in row and pd.notna(row["amount"]) and math.isfinite(shares) and shares:
            value = abs(number(row["amount"])) / abs(shares)
            return value if value > 0 else None
    except (ValueError, TypeError):
        pass
    return None


def confirmed_positions(frame: pd.DataFrame) -> pd.DataFrame:
    """Single gate for calculation/export: explicit confirmation plus valid position data."""
    if "Bestätigt" not in frame:
        return frame.iloc[:0].copy()
    valid = frame["Bestätigt"].map(lambda value: isinstance(value, (bool, np.bool_)) and bool(value))
    valid &= frame["ISIN/Symbol"].fillna("").astype(str).str.strip().ne("")
    valid &= frame["Anlageklasse"].isin(CATEGORIES)
    valid &= ~frame["ISIN/Symbol"].duplicated(keep=False)
    for column in ("Anteile", "Wert EUR", "Kurs (Beleg)"):
        if column in frame:
            values = pd.to_numeric(frame[column], errors="coerce")
            valid &= values.map(lambda value: pd.notna(value) and math.isfinite(value) and value > 0)
    return frame.loc[valid].copy()


def is_broker_csv(content: bytes) -> bool:
    """Detect broker/review exports by headers regardless of order, BOM or delimiter."""
    columns = pd.read_csv(io.BytesIO(content), sep=None, engine="python", nrows=0, encoding="utf-8-sig").columns
    names = {name.strip().lower() for name in columns}
    return ({"type", "symbol", "shares"}.issubset(names) and bool(names & {"transaction_id", "asset_class", "datetime", "account_type", "original_amount"})) or bool(names & {"bestätigt", "prüfhinweis", "bestandsänderung"})
