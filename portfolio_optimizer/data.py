"""Kursdaten laden: Yahoo Finance, CSV-Dateien oder synthetische Demo-Daten."""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from .estimators import TRADING_DAYS

MAX_ASSETS = 16
MIN_OBSERVATIONS = 60

PRESETS = {
    "US-ETFs (Assetklassen)": ["SPY", "EFA", "EEM", "AGG", "TLT", "GLD", "VNQ"],
    "Xetra-ETFs (EUR)": ["EUNL.DE", "IS3N.DE", "SXR8.DE", "EXS1.DE", "4GLD.DE"],
    "DAX-Aktien": ["SAP.DE", "SIE.DE", "ALV.DE", "DTE.DE", "MUV2.DE", "BAS.DE", "IFX.DE"],
    "US-Aktien": ["AAPL", "MSFT", "AMZN", "JPM", "JNJ", "XOM", "KO"],
}

# Fiktive Assetklassen für den Offline-Betrieb: (Rendite p. a., Volatilität p. a.)
DEMO_ASSETS = {
    "Aktien Welt": (0.07, 0.15),
    "Aktien Schwellenländer": (0.08, 0.21),
    "Staatsanleihen": (0.025, 0.05),
    "Unternehmensanleihen": (0.035, 0.07),
    "Gold": (0.04, 0.15),
    "Immobilien": (0.06, 0.19),
}
DEMO_CORR = np.array(
    [
        [1.00, 0.75, -0.10, 0.30, 0.05, 0.70],
        [0.75, 1.00, -0.05, 0.30, 0.15, 0.60],
        [-0.10, -0.05, 1.00, 0.65, 0.25, 0.05],
        [0.30, 0.30, 0.65, 1.00, 0.20, 0.35],
        [0.05, 0.15, 0.25, 0.20, 1.00, 0.10],
        [0.70, 0.60, 0.05, 0.35, 0.10, 1.00],
    ]
)


class DataError(ValueError):
    """Die Kursdaten sind unbrauchbar (zu kurz, leer, fehlerhaft)."""


def parse_tickers(text: str) -> list[str]:
    """Zerlegt eine Eingabe wie ``"aapl, msft; SAP.DE"`` in eindeutige Ticker."""
    seen: dict[str, None] = {}
    for token in re.split(r"[\s,;]+", text.strip()):
        if token:
            seen.setdefault(token.upper(), None)
    return list(seen)


def _extract_close(raw: pd.DataFrame, tickers: Sequence[str]) -> pd.DataFrame:
    """Holt die Schlusskurse aus dem Ergebnis von ``yfinance.download``."""
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw["Close"]
        else:  # group_by="ticker": (Ticker, Feld)
            close = raw.xs("Close", axis=1, level=1)
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
    close = close.copy()
    close.columns = [str(c) for c in close.columns]
    close.index = pd.DatetimeIndex(close.index)
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    return close[[t for t in tickers if t in close.columns]]


def fetch_prices(
    tickers: Sequence[str], start: date, end: date
) -> tuple[pd.DataFrame, list[str]]:
    """Lädt dividendenbereinigte Schlusskurse von Yahoo Finance.

    Rückgabe: (Kurse, Ticker ohne Daten).
    """
    import yfinance as yf

    tickers = list(tickers)
    raw = yf.download(
        tickers,
        start=pd.Timestamp(start),
        end=pd.Timestamp(end) + pd.Timedelta(days=1),  # Enddatum ist bei yfinance exklusiv
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    close = _extract_close(raw, tickers)
    missing = [t for t in tickers if t not in close.columns or close[t].dropna().empty]
    return close.drop(columns=[t for t in missing if t in close.columns]), missing


def _parse_dates(values: pd.Series) -> pd.DatetimeIndex:
    text = values.astype(str).str.strip()
    if text.str.match(r"^\d{1,2}\.\d{1,2}\.\d{4}").all():
        return pd.DatetimeIndex(pd.to_datetime(text, format="%d.%m.%Y"))
    if text.str.match(r"^\d{4}-\d{2}-\d{2}").all():
        return pd.DatetimeIndex(pd.to_datetime(text, format="ISO8601"))
    return pd.DatetimeIndex(pd.to_datetime(text, format="mixed", dayfirst=True))


def _parse_number_column(col: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(col):
        return col.astype(float)
    text = col.astype(str).str.strip().replace({"": np.nan, "nan": np.nan, "-": np.nan})
    if text.str.contains(",", na=False).any():
        # Deutsches Format: Tausenderpunkt entfernen, Dezimalkomma ersetzen
        text = text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(text, errors="coerce")


def load_prices_csv(source: str | bytes | io.IOBase) -> pd.DataFrame:
    """Liest Kurse aus einer CSV-Datei: erste Spalte Datum, danach eine Spalte je Asset.

    Trennzeichen (Komma, Semikolon, Tab) und deutsches Zahlenformat werden erkannt.
    """
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        df = pd.read_csv(source, sep=None, engine="python", encoding="utf-8-sig")
    except Exception as exc:  # pandas wirft je nach Fehler unterschiedliche Typen
        raise DataError(f"Die CSV-Datei konnte nicht gelesen werden: {exc}") from exc
    if df.shape[1] < 2:
        raise DataError("Die CSV-Datei braucht eine Datumsspalte und mindestens eine Kursspalte.")
    try:
        index = _parse_dates(df.iloc[:, 0])
    except (ValueError, TypeError) as exc:
        raise DataError("Die erste Spalte enthält kein gültiges Datum.") from exc
    prices = pd.DataFrame(
        {str(c).strip(): _parse_number_column(df[c]).to_numpy() for c in df.columns[1:]},
        index=index,
    )
    prices.index.name = "Datum"
    return prices


def clean_prices(prices: pd.DataFrame, max_fill: int = 5) -> pd.DataFrame:
    """Sortiert, füllt kurze Lücken (z. B. abweichende Feiertage verschiedener Börsen)
    und schneidet auf den gemeinsamen Zeitraum aller Assets zu."""
    if prices.empty:
        raise DataError("Es liegen keine Kursdaten vor.")
    if prices.shape[1] > MAX_ASSETS:
        raise DataError(f"Bitte höchstens {MAX_ASSETS} Assets auswählen.")
    p = prices.sort_index().dropna(axis=1, how="all")  # z. B. Textspalten in einer CSV-Datei
    if p.shape[1] == 0:
        raise DataError("Es wurden keine Kursspalten mit Zahlen gefunden.")
    p = p[~p.index.duplicated(keep="last")]
    p = p.dropna(how="all").ffill(limit=max_fill).dropna()
    if len(p) < MIN_OBSERVATIONS:
        raise DataError(
            f"Der gemeinsame Zeitraum umfasst nur {len(p)} Kurstage; "
            f"benötigt werden mindestens {MIN_OBSERVATIONS}."
        )
    if (p <= 0).any().any():
        raise DataError("Die Kursdaten enthalten Werte kleiner oder gleich null.")
    return p


def simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().iloc[1:]


def synthetic_prices(years: int = 10, seed: int = 42) -> pd.DataFrame:
    """Simulierte Tageskurse für fiktive Assetklassen (geometrische Brownsche Bewegung)."""
    rng = np.random.default_rng(seed)
    mu = np.array([m for m, _ in DEMO_ASSETS.values()])
    vol = np.array([v for _, v in DEMO_ASSETS.values()])
    cov = DEMO_CORR * np.outer(vol, vol)
    n = years * TRADING_DAYS
    dt = 1 / TRADING_DAYS
    log_returns = rng.multivariate_normal((mu - vol**2 / 2) * dt, cov * dt, size=n)
    prices = 100 * np.exp(np.vstack([np.zeros(len(mu)), np.cumsum(log_returns, axis=0)]))
    index = pd.bdate_range(end="2025-12-31", periods=n + 1, name="Datum")
    return pd.DataFrame(prices, index=index, columns=list(DEMO_ASSETS))


def max_drawdown(prices: pd.Series | pd.DataFrame):
    return (1 - prices / prices.cummax()).max()
