"""Marktdaten für das eigene Portfolio: Suche, Stammdaten, Kurse und Wechselkurse.

Zwei Quellen mit derselben Schnittstelle:

* ``YahooMarketData``: Live-Daten über yfinance (Internetzugang nötig).
* ``DemoMarketData``: fiktive Wertpapiere mit simulierten Kursen, damit sich
  alles ohne Internet ausprobieren und testen lässt.

Kurse kommen in der Handelswährung (teils in Untereinheiten wie Pence);
``to_base_currency`` rechnet sie mit den Wechselkursen in Euro um.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

from .data import fetch_prices
from .estimators import TRADING_DAYS

BASE_CURRENCY = "EUR"
UNKNOWN = "Unbekannt"
FUND_COUNTRY = "Mehrere Länder (Fonds)"
DIVERSIFIED = "Diversifiziert"

FUND_TYPES = {"ETF", "Fonds"}
HOLDABLE_TYPES = {"EQUITY": "Aktie", "ETF": "ETF", "MUTUALFUND": "Fonds", "CRYPTOCURRENCY": "Krypto"}

# Untereinheiten: Kurs in Pence o. Ä. -> (Hauptwährung, Teiler)
MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}

SECTORS = {
    "technology": "Technologie",
    "financialservices": "Finanzen",
    "financial": "Finanzen",
    "healthcare": "Gesundheit",
    "consumercyclical": "Zyklischer Konsum",
    "consumerdefensive": "Basiskonsum",
    "industrials": "Industrie",
    "basicmaterials": "Grundstoffe",
    "energy": "Energie",
    "utilities": "Versorger",
    "realestate": "Immobilien",
    "communicationservices": "Kommunikation",
}

COUNTRIES = {
    "United States": "USA",
    "Germany": "Deutschland",
    "Switzerland": "Schweiz",
    "United Kingdom": "Vereinigtes Königreich",
    "France": "Frankreich",
    "Netherlands": "Niederlande",
    "Ireland": "Irland",
    "Italy": "Italien",
    "Spain": "Spanien",
    "Austria": "Österreich",
    "Belgium": "Belgien",
    "Denmark": "Dänemark",
    "Sweden": "Schweden",
    "Norway": "Norwegen",
    "Finland": "Finnland",
    "Luxembourg": "Luxemburg",
    "Japan": "Japan",
    "China": "China",
    "Hong Kong": "Hongkong",
    "Taiwan": "Taiwan",
    "South Korea": "Südkorea",
    "India": "Indien",
    "Canada": "Kanada",
    "Australia": "Australien",
    "Brazil": "Brasilien",
}

# Handelsplatz-Endungen bei Yahoo -> Handelswährung, falls die Stammdaten keine liefern
SUFFIX_CURRENCIES = {
    "DE": "EUR", "F": "EUR", "BE": "EUR", "DU": "EUR", "HM": "EUR", "MU": "EUR", "SG": "EUR",
    "PA": "EUR", "AS": "EUR", "MI": "EUR", "MC": "EUR", "BR": "EUR", "VI": "EUR", "HE": "EUR",
    "LS": "EUR", "IR": "EUR", "L": "GBp", "SW": "CHF", "TO": "CAD", "T": "JPY", "HK": "HKD",
    "AX": "AUD", "CO": "DKK", "ST": "SEK", "OL": "NOK",
}


def sector_de(name: str | None) -> str:
    """Yahoo-Sektorbezeichnung (z. B. "Financial Services", "financial_services") auf Deutsch."""
    if not name:
        return UNKNOWN
    return SECTORS.get(re.sub(r"[^a-z]", "", name.lower()), name)


def country_de(name: str | None) -> str:
    if not name:
        return UNKNOWN
    return COUNTRIES.get(name, name)


def major_currency(currency: str) -> tuple[str, float]:
    """``"GBp"`` -> ``("GBP", 100)``; ``"USD"`` -> ``("USD", 1)``."""
    return MINOR_UNITS.get(currency, (currency.upper(), 1.0))


def guess_currency(symbol: str) -> str:
    suffix = symbol.rsplit(".", 1)[1].upper() if "." in symbol else ""
    if symbol.endswith("-EUR"):
        return "EUR"
    return SUFFIX_CURRENCIES.get(suffix, "USD")


def _fund_category_sector(category: str | None) -> str:
    """Grobe Einordnung von Fonds ohne Sektordaten anhand ihrer Kategorie."""
    text = (category or "").lower()
    if any(word in text for word in ("bond", "anleihe", "treasury", "government", "fixed income")):
        return "Anleihen"
    if any(word in text for word in ("money market", "geldmarkt", "ultrashort", "overnight")):
        return "Geldmarkt"
    if any(word in text for word in ("commodit", "gold", "precious", "rohstoff")):
        return "Rohstoffe"
    if "real estate" in text or "property" in text:
        return "Immobilien"
    return DIVERSIFIED


@dataclass(frozen=True)
class SearchHit:
    symbol: str
    name: str
    quote_type: str
    exchange: str = ""

    @property
    def label(self) -> str:
        parts = [self.name, self.symbol, self.exchange, self.quote_type]
        return " · ".join(p for p in parts if p)


@dataclass
class SecurityInfo:
    """Stammdaten eines Wertpapiers."""

    symbol: str
    name: str
    quote_type: str = "Aktie"
    currency: str = BASE_CURRENCY  # Handelswährung, ggf. Untereinheit (GBp)
    sector: str = UNKNOWN
    country: str = UNKNOWN
    sector_weights: dict[str, float] = field(default_factory=dict)  # Durchschau bei Fonds

    @property
    def is_fund(self) -> bool:
        return self.quote_type in FUND_TYPES

    def sector_exposure(self) -> dict[str, float]:
        """Anteile je Sektor; bei Fonds über die Sektorgewichte des Fonds."""
        total = sum(v for v in self.sector_weights.values() if v > 0)
        if total > 0:
            return {k: v / total for k, v in self.sector_weights.items() if v > 0}
        return {self.sector: 1.0}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SecurityInfo:
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        known["sector_weights"] = {str(k): float(v) for k, v in (known.get("sector_weights") or {}).items()}
        return cls(**known)


@dataclass(frozen=True)
class Instrument:
    """Kandidat für Absicherungen und Beimischungen."""

    symbol: str
    label: str
    kind: str  # "market" | "sector" | "diversifier"
    currency: str = BASE_CURRENCY
    sector: str | None = None


def to_base_currency(prices: pd.DataFrame, currencies: dict[str, str], fx: pd.DataFrame) -> pd.DataFrame:
    """Rechnet Kurse in Euro um.

    ``fx`` enthält je Fremdwährung (Spaltenname, z. B. ``"USD"``) den Kurs
    "Einheiten Fremdwährung je 1 Euro", wie bei Yahoo ``EURUSD=X``.
    """
    out = {}
    for symbol in prices.columns:
        major, divisor = major_currency(currencies.get(symbol, BASE_CURRENCY))
        series = prices[symbol] / divisor
        if major != BASE_CURRENCY:
            if major not in fx.columns:
                continue
            rate = fx[major].reindex(prices.index.union(fx.index)).ffill().reindex(prices.index).bfill()
            series = series / rate
        out[symbol] = series
    return pd.DataFrame(out, index=prices.index)


# ---------------------------------------------------------------------------
# Yahoo Finance
# ---------------------------------------------------------------------------

YAHOO_INSTRUMENTS = (
    Instrument("EUNL.DE", "MSCI World", "market"),
    Instrument("SXR8.DE", "S&P 500", "market"),
    Instrument("EXS1.DE", "DAX", "market"),
    Instrument("EXW1.DE", "EURO STOXX 50", "market"),
    Instrument("IS3N.DE", "MSCI Emerging Markets IMI", "market"),
    Instrument("QQQ", "Nasdaq-100", "market", "USD"),
    Instrument("XLK", "Technologie (USA)", "sector", "USD", "Technologie"),
    Instrument("EXV3.DE", "Technologie (Europa)", "sector", "EUR", "Technologie"),
    Instrument("XLF", "Finanzen (USA)", "sector", "USD", "Finanzen"),
    Instrument("XLV", "Gesundheit (USA)", "sector", "USD", "Gesundheit"),
    Instrument("EXV4.DE", "Gesundheit (Europa)", "sector", "EUR", "Gesundheit"),
    Instrument("XLY", "Zyklischer Konsum (USA)", "sector", "USD", "Zyklischer Konsum"),
    Instrument("XLP", "Basiskonsum (USA)", "sector", "USD", "Basiskonsum"),
    Instrument("XLI", "Industrie (USA)", "sector", "USD", "Industrie"),
    Instrument("EXH4.DE", "Industrie (Europa)", "sector", "EUR", "Industrie"),
    Instrument("XLB", "Grundstoffe (USA)", "sector", "USD", "Grundstoffe"),
    Instrument("XLE", "Energie (USA)", "sector", "USD", "Energie"),
    Instrument("XLU", "Versorger (USA)", "sector", "USD", "Versorger"),
    Instrument("EXH9.DE", "Versorger (Europa)", "sector", "EUR", "Versorger"),
    Instrument("XLRE", "Immobilien (USA)", "sector", "USD", "Immobilien"),
    Instrument("XLC", "Kommunikation (USA)", "sector", "USD", "Kommunikation"),
    Instrument("EUNH.DE", "Euro-Staatsanleihen", "diversifier"),
    Instrument("XEON.DE", "Geldmarkt (€STR)", "diversifier"),
    Instrument("4GLD.DE", "Gold (Xetra-Gold)", "diversifier"),
    Instrument("IEF", "US-Staatsanleihen 7–10 J.", "diversifier", "USD"),
    Instrument("IUSN.DE", "Nebenwerte Welt", "diversifier"),
    Instrument("IS3N.DE", "Schwellenländer", "diversifier"),
    Instrument("EUNL.DE", "Aktien Welt (MSCI World)", "diversifier"),
)


class YahooMarketData:
    """Live-Daten von Yahoo Finance über yfinance."""

    key = "yahoo"
    label = "Yahoo Finance"
    instruments = YAHOO_INSTRUMENTS
    world_fund = "EUNL.DE"

    def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        import yfinance as yf

        quotes = yf.Search(
            query, max_results=limit, news_count=0, lists_count=0, recommended=0, include_cb=False
        ).quotes
        hits = []
        for quote in quotes:
            quote_type = HOLDABLE_TYPES.get(quote.get("quoteType", ""))
            if quote_type is None:
                continue
            name = quote.get("longname") or quote.get("shortname") or quote["symbol"]
            hits.append(SearchHit(quote["symbol"], name, quote_type, quote.get("exchDisp") or quote.get("exchange", "")))
        return hits

    def info(self, symbol: str) -> SecurityInfo:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        data = ticker.info or {}
        quote_type = HOLDABLE_TYPES.get(data.get("quoteType", ""), "Aktie")
        info = SecurityInfo(
            symbol=symbol,
            name=data.get("longName") or data.get("shortName") or symbol,
            quote_type=quote_type,
            currency=data.get("currency") or guess_currency(symbol),
        )
        if quote_type in FUND_TYPES:
            info.country = FUND_COUNTRY
            try:
                weights = ticker.funds_data.sector_weightings or {}
            except Exception:  # Fondsdaten fehlen bei vielen Produkten; dann ohne Durchschau
                weights = {}
            info.sector_weights = {sector_de(k): float(v) for k, v in weights.items() if v}
            info.sector = _fund_category_sector(data.get("category")) if not info.sector_weights else DIVERSIFIED
        elif quote_type == "Krypto":
            info.sector, info.country = "Krypto", "Ohne Land"
        else:
            fallback = _fund_category_sector(info.name)  # z. B. Gold-ETCs ohne Sektorangabe
            info.sector = sector_de(data.get("sector")) if data.get("sector") else (
                fallback if fallback != DIVERSIFIED else UNKNOWN
            )
            info.country = country_de(data.get("country"))
        return info

    def prices(self, symbols: list[str], start: date, end: date) -> pd.DataFrame:
        close, _ = fetch_prices(list(symbols), start, end)
        return close

    def fx_rates(self, currencies: list[str], start: date, end: date) -> pd.DataFrame:
        pairs = {f"EUR{c}=X": c for c in sorted(set(currencies)) if c != BASE_CURRENCY}
        if not pairs:
            return pd.DataFrame()
        close, _ = fetch_prices(list(pairs), start, end)
        return close.rename(columns=pairs)


# ---------------------------------------------------------------------------
# Offline-Demo: fiktive Wertpapiere aus einem Faktormodell
# ---------------------------------------------------------------------------

# Faktoren: (Volatilität p. a., Drift p. a.). FX-Faktoren sind Log-Renditen der
# Fremdwährung gegenüber dem Euro.
_FACTORS = {
    "MKT": (0.14, 0.06), "US": (0.05, 0.01), "EU": (0.05, 0.0), "CH": (0.05, 0.0),
    "UK": (0.05, -0.005), "JP": (0.06, 0.0), "EM": (0.09, 0.005), "TECH": (0.15, 0.02),
    "FIN": (0.10, 0.0), "HEALTH": (0.07, 0.005), "STAPLES": (0.06, 0.0), "CYCL": (0.09, 0.0),
    "IND": (0.07, 0.0), "ENERGY": (0.15, 0.0), "UTIL": (0.07, 0.0), "MAT": (0.09, 0.0),
    "REIT": (0.10, 0.0), "SMALL": (0.06, 0.005), "RATES": (0.05, 0.02), "GOLD": (0.14, 0.04),
    "CASH": (0.002, 0.025), "USD": (0.08, 0.0), "GBP": (0.07, 0.0), "CHF": (0.06, 0.01),
    "JPY": (0.10, -0.01),
}
_FX_START = {"USD": 1.10, "GBP": 0.86, "CHF": 0.95, "JPY": 160.0}

_WORLD_SECTORS = {
    "Technologie": 0.25, "Finanzen": 0.16, "Gesundheit": 0.11, "Industrie": 0.11,
    "Zyklischer Konsum": 0.10, "Kommunikation": 0.08, "Basiskonsum": 0.06, "Energie": 0.04,
    "Grundstoffe": 0.04, "Versorger": 0.03, "Immobilien": 0.02,
}
_EUROPE_SECTORS = {
    "Finanzen": 0.21, "Industrie": 0.17, "Gesundheit": 0.14, "Basiskonsum": 0.10,
    "Zyklischer Konsum": 0.09, "Technologie": 0.08, "Grundstoffe": 0.06, "Energie": 0.05,
    "Versorger": 0.05, "Kommunikation": 0.04, "Immobilien": 0.01,
}

# Symbol: (Name, Typ, Währung, Sektor, Land, Startkurs, Idiosynkratische Vola, Faktorladungen)
_DEMO_CATALOG = {
    "NLS.DEMO": ("Nordlicht Software AG", "Aktie", "EUR", "Technologie", "Deutschland", 120.0, 0.12,
                 {"MKT": 1.2, "EU": 1.0, "TECH": 1.0}),
    "BRB.DEMO": ("Brückenbank AG", "Aktie", "EUR", "Finanzen", "Deutschland", 18.0, 0.18,
                 {"MKT": 1.1, "EU": 1.0, "FIN": 1.0}),
    "RHC.DEMO": ("Rheinchemie SE", "Aktie", "EUR", "Grundstoffe", "Deutschland", 55.0, 0.16,
                 {"MKT": 1.0, "EU": 1.0, "MAT": 1.0}),
    "MWS.DEMO": ("Motorwerke Süd AG", "Aktie", "EUR", "Zyklischer Konsum", "Deutschland", 80.0, 0.20,
                 {"MKT": 1.2, "EU": 1.0, "CYCL": 1.0}),
    "HSV.DEMO": ("Hansa Versorgung AG", "Aktie", "EUR", "Versorger", "Deutschland", 30.0, 0.12,
                 {"MKT": 0.5, "EU": 0.8, "UTIL": 1.0}),
    "KBH.DEMO": ("Kornblume Lebensmittel AG", "Aktie", "EUR", "Basiskonsum", "Deutschland", 64.0, 0.13,
                 {"MKT": 0.6, "EU": 0.8, "STAPLES": 1.0}),
    "ALP.DEMO": ("Alpenpharma AG", "Aktie", "CHF", "Gesundheit", "Schweiz", 90.0, 0.14,
                 {"MKT": 0.7, "CH": 1.0, "HEALTH": 1.0}),
    "ATI.DEMO": ("Atlantic Insurance plc", "Aktie", "GBp", "Finanzen", "Vereinigtes Königreich", 1250.0,
                 0.15, {"MKT": 0.9, "UK": 1.0, "FIN": 0.8}),
    "PCH.DEMO": ("Pacific Chips Inc.", "Aktie", "USD", "Technologie", "USA", 140.0, 0.14,
                 {"MKT": 1.3, "US": 1.0, "TECH": 1.2}),
    "LCL.DEMO": ("Liberty Cloud Corp.", "Aktie", "USD", "Technologie", "USA", 210.0, 0.12,
                 {"MKT": 1.2, "US": 1.0, "TECH": 1.0}),
    "SPC.DEMO": ("Starport Communications Inc.", "Aktie", "USD", "Kommunikation", "USA", 75.0, 0.18,
                 {"MKT": 1.0, "US": 1.0, "TECH": 0.5}),
    "GLE.DEMO": ("Great Lakes Energy Inc.", "Aktie", "USD", "Energie", "USA", 60.0, 0.20,
                 {"MKT": 0.9, "US": 1.0, "ENERGY": 1.0}),
    "SKR.DEMO": ("Sakura Robotics K.K.", "Aktie", "JPY", "Industrie", "Japan", 4200.0, 0.18,
                 {"MKT": 1.0, "JP": 1.0, "IND": 1.0}),
    "DWLD.DEMO": ("Demo Aktien Welt ETF", "ETF", "EUR", DIVERSIFIED, FUND_COUNTRY, 80.0, 0.01,
                  {"MKT": 1.0, "US": 0.65, "EU": 0.2, "JP": 0.06, "TECH": 0.25, "USD": 0.65, "JPY": 0.06}),
    "DUS.DEMO": ("Demo USA-Index ETF", "ETF", "EUR", DIVERSIFIED, FUND_COUNTRY, 450.0, 0.01,
                 {"MKT": 1.0, "US": 1.0, "TECH": 0.3, "USD": 1.0}),
    "DEUR.DEMO": ("Demo Europa-Aktien ETF", "ETF", "EUR", DIVERSIFIED, FUND_COUNTRY, 40.0, 0.01,
                  {"MKT": 0.9, "EU": 1.0}),
    "DDE.DEMO": ("Demo Deutschland-Index ETF", "ETF", "EUR", DIVERSIFIED, FUND_COUNTRY, 150.0, 0.03,
                 {"MKT": 1.0, "EU": 1.1}),
    "DEM.DEMO": ("Demo Schwellenländer ETF", "ETF", "EUR", DIVERSIFIED, FUND_COUNTRY, 30.0, 0.02,
                 {"MKT": 1.0, "EM": 1.0, "USD": 0.5}),
    "DSMC.DEMO": ("Demo Nebenwerte Welt ETF", "ETF", "EUR", DIVERSIFIED, FUND_COUNTRY, 60.0, 0.02,
                  {"MKT": 1.1, "SMALL": 1.0, "US": 0.5, "USD": 0.6}),
    "DTEC.DEMO": ("Demo Technologie-Sektor ETF", "ETF", "EUR", "Technologie", FUND_COUNTRY, 100.0, 0.03,
                  {"MKT": 1.2, "TECH": 1.0, "US": 0.7, "USD": 0.7}),
    "DFIN.DEMO": ("Demo Finanz-Sektor ETF", "ETF", "EUR", "Finanzen", FUND_COUNTRY, 50.0, 0.03,
                  {"MKT": 1.0, "FIN": 1.0, "EU": 0.4, "US": 0.4, "USD": 0.4}),
    "DHLT.DEMO": ("Demo Gesundheit-Sektor ETF", "ETF", "EUR", "Gesundheit", FUND_COUNTRY, 70.0, 0.03,
                  {"MKT": 0.7, "HEALTH": 1.0, "US": 0.5, "USD": 0.5}),
    "DENR.DEMO": ("Demo Energie-Sektor ETF", "ETF", "EUR", "Energie", FUND_COUNTRY, 35.0, 0.03,
                  {"MKT": 0.9, "ENERGY": 1.0, "US": 0.5, "USD": 0.5}),
    "DIND.DEMO": ("Demo Industrie-Sektor ETF", "ETF", "EUR", "Industrie", FUND_COUNTRY, 65.0, 0.03,
                  {"MKT": 1.0, "IND": 1.0, "EU": 0.4, "US": 0.4, "USD": 0.4}),
    "DUTL.DEMO": ("Demo Versorger-Sektor ETF", "ETF", "EUR", "Versorger", FUND_COUNTRY, 45.0, 0.03,
                  {"MKT": 0.5, "UTIL": 1.0, "EU": 0.5}),
    "DBND.DEMO": ("Demo Euro-Staatsanleihen ETF", "ETF", "EUR", "Anleihen", FUND_COUNTRY, 100.0, 0.005,
                  {"RATES": 1.0, "MKT": -0.05}),
    "DCSH.DEMO": ("Demo Geldmarkt ETF", "ETF", "EUR", "Geldmarkt", FUND_COUNTRY, 100.0, 0.0005,
                  {"CASH": 1.0}),
    "DGLD.DEMO": ("Demo Gold ETC", "ETF", "EUR", "Rohstoffe", FUND_COUNTRY, 50.0, 0.01,
                  {"GOLD": 1.0, "USD": 0.8}),
}

_DEMO_FUND_SECTORS = {
    "DWLD.DEMO": _WORLD_SECTORS,
    "DUS.DEMO": {**_WORLD_SECTORS, "Technologie": 0.31, "Finanzen": 0.13},
    "DEUR.DEMO": _EUROPE_SECTORS,
    "DDE.DEMO": {**_EUROPE_SECTORS, "Industrie": 0.25, "Finanzen": 0.18},
    "DEM.DEMO": {**_WORLD_SECTORS, "Technologie": 0.22, "Finanzen": 0.22},
    "DSMC.DEMO": {**_WORLD_SECTORS, "Industrie": 0.18, "Technologie": 0.12},
}

DEMO_INSTRUMENTS = (
    Instrument("DWLD.DEMO", "Aktien Welt (Demo)", "market"),
    Instrument("DUS.DEMO", "USA-Index (Demo)", "market"),
    Instrument("DDE.DEMO", "Deutschland-Index (Demo)", "market"),
    Instrument("DEUR.DEMO", "Europa (Demo)", "market"),
    Instrument("DEM.DEMO", "Schwellenländer (Demo)", "market"),
    Instrument("DTEC.DEMO", "Technologie (Demo)", "sector", sector="Technologie"),
    Instrument("DFIN.DEMO", "Finanzen (Demo)", "sector", sector="Finanzen"),
    Instrument("DHLT.DEMO", "Gesundheit (Demo)", "sector", sector="Gesundheit"),
    Instrument("DENR.DEMO", "Energie (Demo)", "sector", sector="Energie"),
    Instrument("DIND.DEMO", "Industrie (Demo)", "sector", sector="Industrie"),
    Instrument("DUTL.DEMO", "Versorger (Demo)", "sector", sector="Versorger"),
    Instrument("DBND.DEMO", "Euro-Staatsanleihen (Demo)", "diversifier"),
    Instrument("DCSH.DEMO", "Geldmarkt (Demo)", "diversifier"),
    Instrument("DGLD.DEMO", "Gold (Demo)", "diversifier"),
    Instrument("DSMC.DEMO", "Nebenwerte Welt (Demo)", "diversifier"),
    Instrument("DEM.DEMO", "Schwellenländer (Demo)", "diversifier"),
    Instrument("DWLD.DEMO", "Aktien Welt (Demo)", "diversifier"),
)

# Beispieldepot: Symbol -> heutiger Wert in Euro (mit Tech-Übergewicht und hohem USD-Anteil)
DEMO_EXAMPLE = {
    "NLS.DEMO": 8000, "PCH.DEMO": 10000, "LCL.DEMO": 9000, "SPC.DEMO": 5000, "GLE.DEMO": 4000,
    "BRB.DEMO": 3000, "ALP.DEMO": 4000, "ATI.DEMO": 3000, "HSV.DEMO": 2000, "DWLD.DEMO": 10000,
}


@lru_cache(maxsize=4)
def _simulate_demo(end: date, years: int = 12, seed: int = 11) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulierte Kurse (Handelswährung) und Wechselkurse (Fremdwährung je Euro)."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(end=pd.Timestamp(end), periods=years * TRADING_DAYS, name="Datum")
    n, dt = len(index), 1 / TRADING_DAYS
    names = list(_FACTORS)
    vols = np.array([_FACTORS[f][0] for f in names])
    drifts = np.array([_FACTORS[f][1] for f in names])
    factors = pd.DataFrame(
        rng.standard_normal((n, len(names))) * vols * np.sqrt(dt) + (drifts - vols**2 / 2) * dt,
        index=index, columns=names,
    )
    prices = {}
    for symbol, (_, _, _, _, _, start, idio, loads) in _DEMO_CATALOG.items():
        log_ret = sum(weight * factors[f] for f, weight in loads.items())
        log_ret = log_ret + rng.standard_normal(n) * idio * np.sqrt(dt) - idio**2 / 2 * dt
        prices[symbol] = start * np.exp(np.cumsum(log_ret))
    fx = {cur: rate * np.exp(-np.cumsum(factors[cur])) for cur, rate in _FX_START.items()}
    return pd.DataFrame(prices, index=index), pd.DataFrame(fx, index=index)


class DemoMarketData:
    """Fiktive Wertpapiere mit simulierten Kursen (ohne Internet)."""

    key = "demo"
    label = "Offline-Demo"
    instruments = DEMO_INSTRUMENTS
    world_fund = "DWLD.DEMO"

    def __init__(self, end: date | None = None):
        self.end = end or date.today()

    def _data(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        return _simulate_demo(self.end)

    def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        q = query.strip().lower()
        if not q:
            return []
        hits = [
            SearchHit(symbol, entry[0], entry[1], "Demo")
            for symbol, entry in _DEMO_CATALOG.items()
            if q in symbol.lower() or q in entry[0].lower() or q in entry[3].lower()
        ]
        return hits[:limit]

    def info(self, symbol: str) -> SecurityInfo:
        if symbol not in _DEMO_CATALOG:
            raise ValueError(f"Unbekanntes Demo-Wertpapier: {symbol}")
        name, quote_type, currency, sector, country, *_ = _DEMO_CATALOG[symbol]
        return SecurityInfo(
            symbol=symbol, name=name, quote_type=quote_type, currency=currency, sector=sector,
            country=country, sector_weights=dict(_DEMO_FUND_SECTORS.get(symbol, {})),
        )

    def prices(self, symbols: list[str], start: date, end: date) -> pd.DataFrame:
        prices, _ = self._data()
        cols = [s for s in symbols if s in prices.columns]
        return prices.loc[pd.Timestamp(start) : pd.Timestamp(end), cols]

    def fx_rates(self, currencies: list[str], start: date, end: date) -> pd.DataFrame:
        _, fx = self._data()
        cols = [c for c in sorted(set(currencies)) if c in fx.columns]
        return fx.loc[pd.Timestamp(start) : pd.Timestamp(end), cols]


def get_provider(key: str):
    return YahooMarketData() if key == "yahoo" else DemoMarketData()
