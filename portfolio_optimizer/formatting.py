"""Zahlenformatierung im deutschen Stil (Dezimalkomma, Tausenderpunkt)."""

from __future__ import annotations

import math

import pandas as pd


def _german(text: str) -> str:
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _missing(x) -> bool:
    return x is None or (isinstance(x, float) and not math.isfinite(x))


def pct(x: float | None, digits: int = 1, signed: bool = False) -> str:
    """0.0734 -> '7,3 %'"""
    if _missing(x):
        return "–"
    sign = "+" if signed else ""
    return _german(f"{x * 100:{sign},.{digits}f}") + " %"


def num(x: float | None, digits: int = 0) -> str:
    """12345.6 -> '12.346'"""
    if _missing(x):
        return "–"
    return _german(f"{x:,.{digits}f}")


def ratio(x: float | None, digits: int = 2) -> str:
    """0.3721 -> '0,37'"""
    return num(x, digits)


def styled(
    df: pd.DataFrame,
    pct_cols: tuple[str, ...] = (),
    ratio_cols: tuple[str, ...] = (),
    num_cols: tuple[str, ...] = (),
    digits: int = 1,
):
    """Pandas-Styler mit deutschen Zahlenformaten für ``st.dataframe``."""
    formats = {c: (lambda v: pct(v, digits)) for c in pct_cols if c in df.columns}
    formats |= {c: ratio for c in ratio_cols if c in df.columns}
    formats |= {c: num for c in num_cols if c in df.columns}
    return df.style.format(formats)
