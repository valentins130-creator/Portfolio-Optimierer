"""Import Trade Republic transactions and dated net-worth statements.

No personal statement content is written to the repository or a server file.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

import pandas as pd


CATEGORIES = ("Aktien", "Aktien-ETFs/Fonds", "Anleihen", "Anleihen-ETFs/Fonds", "Krypto", "Derivate/Leveraged", "Cash", "Sonstige")
POSITION_EVENTS = {"BUY": 1, "SELL": -1, "FREE_RECEIPT": 1}
# Corporate actions need individual assessment; never implicitly become purchases.
REVIEW_EVENTS = {"SPLIT", "MERGER", "STOCKPERK", "WARRANT_EXERCISE", "FINAL_MATURITY", "FULL_CALL", "TILG"}
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
        return "Aktien"
    return "Sonstige"


@dataclass
class Statement:
    positions: pd.DataFrame
    as_of: str
    expected_total: float
    warnings: list[str]


def parse_statement_pdf(content: bytes) -> Statement:
    import pdfplumber

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
    return Statement(frame, as_of, expected_total, warnings)


def parse_broker_csv(content: bytes) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return provisional holdings, an auditable event table, and type counts.

    Only BUY/SELL/FREE_RECEIPT with positive valid quantities change holdings.
    Cashflows, dividends, interest, taxes and unreviewed corporate actions do not.
    No claim of current portfolio valuation is made from historical trade prices.
    """
    df = pd.read_csv(io.BytesIO(content), dtype={"symbol": str}, low_memory=False)
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
        shares = number(row.get("shares"))
        action = "Ignoriert (keine Bestandsänderung)"
        delta = 0.0
        if kind in POSITION_EVENTS:
            if symbol and shares:
                delta = abs(shares) * POSITION_EVENTS[kind]
                action = "Bestandsänderung"
            else:
                action = "Prüfen (Symbol/Stückzahl fehlt)"
        elif kind in REVIEW_EVENTS:
            action = "Manuell prüfen (Kapitalmaßnahme)"
        if kind in POSITION_EVENTS or kind in REVIEW_EVENTS:
            events.append({"Zeile": index + 2, "Datum": row.get("date"), "Typ": kind,
                           "Name": row.get("name") if pd.notna(row.get("name")) else "",
                           "ISIN/Symbol": symbol, "Anlageklasse": row.get("asset_class") if pd.notna(row.get("asset_class")) else "",
                           "Anteile": shares, "Bestandsänderung": delta, "Status": action})
    audit = pd.DataFrame(events, columns=["Zeile", "Datum", "Typ", "Name", "ISIN/Symbol", "Anlageklasse",
                                          "Anteile", "Bestandsänderung", "Status"])
    positive = audit[(audit["Status"] == "Bestandsänderung") & audit["ISIN/Symbol"].ne("")]
    holdings = []
    for symbol, group in positive.groupby("ISIN/Symbol", sort=False):
        shares = float(group["Bestandsänderung"].sum())
        if shares <= 1e-9:
            continue
        name = next((str(x) for x in group["Name"].iloc[::-1] if str(x).strip()), symbol)
        asset_class = next((str(x) for x in group["Anlageklasse"].iloc[::-1] if str(x).strip()), "")
        holdings.append({"Name": name, "ISIN/Symbol": symbol, "Anteile": shares,
                         "Anlageklasse": category(name, asset_class), "Status": "Vorläufig; mit Depotauszug abgleichen"})
    return pd.DataFrame(holdings, columns=["Name", "ISIN/Symbol", "Anteile", "Anlageklasse", "Status"]), audit, types
