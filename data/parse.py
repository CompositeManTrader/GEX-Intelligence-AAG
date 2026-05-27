"""
Schwab chain parsing + cleaning.

IV% ships as a decimal in the API and as a percentage in the cleaned dataframe.
All downstream consumers (quant/*) operate on the percentage.
"""
from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd


_REMAP = {
    "strikePrice": "Strike", "_exp": "Expiry", "_dte": "DTE",
    "bid": "Bid", "ask": "Ask", "mark": "Mark", "last": "Last",
    "totalVolume": "Volume", "openInterest": "OI",
    "volatility": "IV%",
    "impliedVolatility": "IV%_alt",
    "delta": "Delta", "gamma": "Gamma",
    "theta": "Theta", "vega": "Vega", "rho": "Rho",
    "inTheMoney": "ITM", "theoreticalOptionValue": "Theo",
}


def parse_chain(data: dict) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Parse Schwab chain JSON into (calls_df, puts_df, underlying_dict)."""
    if not isinstance(data, dict):
        return pd.DataFrame(), pd.DataFrame(), {}
    rows_c: list[dict] = []
    rows_p: list[dict] = []
    for rows, key in [(rows_c, "callExpDateMap"), (rows_p, "putExpDateMap")]:
        for exp_key, strikes in data.get(key, {}).items():
            try:
                exp, dte = exp_key.split(":")
                dte_i = int(dte)
            except (ValueError, AttributeError):
                continue
            for opts in strikes.values():
                for o in opts:
                    o["_exp"] = exp
                    o["_dte"] = dte_i
                    rows.append(o)
    c = pd.DataFrame(rows_c) if rows_c else pd.DataFrame()
    p = pd.DataFrame(rows_p) if rows_p else pd.DataFrame()
    return c, p, data.get("underlying", {}) or {}


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Rename + coerce columns. IV% is stored in percentage (0-200%)."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if "volatility" not in df.columns and "impliedVolatility" in df.columns:
        df["volatility"] = df["impliedVolatility"]
    elif "volatility" not in df.columns:
        df["volatility"] = float("nan")
    cols = {k: v for k, v in _REMAP.items() if k in df.columns}
    df = df[list(cols)].rename(columns=cols).copy()
    df.drop(columns=["IV%_alt"], errors="ignore", inplace=True)

    rounds = [("Bid", 2), ("Ask", 2), ("Mark", 2), ("Last", 2), ("Theo", 2),
              ("Delta", 3), ("Theta", 3), ("Gamma", 4), ("Vega", 4), ("Rho", 4),
              ("Strike", 2)]
    for col, dig in rounds:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(dig)

    # Schwab sometimes delivers IV as decimal (0.20 = 20%), sometimes as
    # percent (20.0 = 20%). Distinguish by the *max* value, not the median:
    # a chain with a few extreme tail strikes can have median IV<3 in
    # percent (low-vol calm names like utility ETFs) and would have been
    # mis-multiplied by 100 by the legacy heuristic. Real IV in decimal
    # almost never exceeds 3.0 (300% vol); seeing any value above that
    # means the data already arrived in percent.
    #
    # CRITICAL: Schwab uses sentinel values (typically -999) for "no IV
    # available" on illiquid contracts. These leak through to_numeric (they
    # ARE numeric, just garbage). If a chain has ONLY -999 values, the
    # legacy heuristic would see `max ≤ 3.0` → multiply by 100 → write
    # -99900 to every row. Pre-filter to a plausible IV range before
    # judging units, and require a minimum count of plausible values so a
    # broken chain doesn't pollute the decision.
    if "IV%" in df.columns:
        iv = pd.to_numeric(df["IV%"], errors="coerce")
        plausible = iv[(iv > 0) & (iv < 1000)]
        if len(plausible) >= 3 and float(plausible.max()) <= 3.0:
            iv = iv * 100.0
        # Replace sentinel-looking values with NaN explicitly so downstream
        # filters (e.g. quant.exposures.filter_chain min IV gate) drop them
        # cleanly rather than treating -99900 as a "real" extreme IV.
        iv = iv.where((iv > 0) & (iv < 1000))
        df["IV%"] = iv.round(2)

    if "OI" in df.columns:
        df["OI"] = pd.to_numeric(df["OI"], errors="coerce").fillna(0).astype(int)
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype(int)
    if "DTE" in df.columns:
        df["DTE"] = pd.to_numeric(df["DTE"], errors="coerce").fillna(0).astype(int)
    if "ITM" in df.columns:
        # Explicit truthy mapping. `astype(bool)` makes `bool(None) = False`
        # (silently misclassifying NULL Schwab fields as OTM) and
        # `bool("false") = True` (any non-empty string is truthy). Coerce
        # via an explicit dict so the only Trues come from real True
        # markers and the rest fall back to False.
        df["ITM"] = df["ITM"].map(
            {True: True, "true": True, "True": True, 1: True, "1": True}
        ).fillna(False).astype(bool)
    return df


def by_expiry(df: pd.DataFrame, exp) -> pd.DataFrame:
    """Filter `df` to rows whose `Expiry` matches `exp`.

    `Expiry` is stored as the stringified `YYYY-MM-DD` from Schwab's
    `key.split(":")` upstream. If a caller passes a `datetime`/`date`
    object the `==` comparison silently returns an empty DataFrame.
    Coerce `exp` to `str` so the filter works regardless of how the
    caller obtained the value.
    """
    if df is None or df.empty or "Expiry" not in df.columns or exp is None:
        return df if df is not None else pd.DataFrame()
    return df[df["Expiry"] == str(exp)].copy()
