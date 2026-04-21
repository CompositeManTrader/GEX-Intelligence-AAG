"""
Volatility analytics:
  - Close-to-close HV (legacy)
  - Parkinson (OHLC high-low)
  - Garman-Klass (OHLC)
  - Yang-Zhang (overnight + intraday + drift-free)
  - IV rank / percentile over persisted IV history (opt-in)
  - Volatility cone
  - Return distribution statistics
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from config import TRADING_DAYS


# ─────────────────────────────────────────────────────────────────────────────
#  Realized-volatility estimators — all annualized, in percent.
# ─────────────────────────────────────────────────────────────────────────────
def hv_close_to_close(closes: pd.Series, window: int) -> pd.Series:
    """Classic rolling stdev of log returns × sqrt(252) × 100."""
    lr = np.log(closes / closes.shift(1))
    return (lr.rolling(window).std() * np.sqrt(TRADING_DAYS) * 100).round(3)


def hv_parkinson(high: pd.Series, low: pd.Series, window: int) -> pd.Series:
    """Parkinson (1980). Uses only H/L — 5x more efficient than close-to-close
    when drift ~= 0 and no overnight gaps."""
    hl = np.log(high / low)
    factor = 1.0 / (4.0 * np.log(2.0))
    var = (hl * hl).rolling(window).mean() * factor
    return (np.sqrt(var * TRADING_DAYS) * 100).round(3)


def hv_garman_klass(open_: pd.Series, high: pd.Series,
                    low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    """Garman-Klass (1980). Uses full OHLC intraday, ignores overnight gaps."""
    hl = np.log(high / low)
    co = np.log(close / open_)
    term = 0.5 * hl * hl - (2.0 * np.log(2.0) - 1.0) * co * co
    var = term.rolling(window).mean()
    var = var.clip(lower=0)  # numerical floor
    return (np.sqrt(var * TRADING_DAYS) * 100).round(3)


def hv_yang_zhang(open_: pd.Series, high: pd.Series, low: pd.Series,
                  close: pd.Series, window: int) -> pd.Series:
    """Yang-Zhang (2000). Overnight + open-to-close + Rogers-Satchell. Drift-free,
    handles opening jumps. Most robust for equities."""
    ln_ho = np.log(high / open_)
    ln_lo = np.log(low / open_)
    ln_co = np.log(close / open_)
    ln_oc_prev = np.log(open_ / close.shift(1))
    ln_cc_prev = np.log(close / close.shift(1))

    n = window
    k = 0.34 / (1.34 + (n + 1) / (n - 1))

    var_overnight = ln_oc_prev.rolling(window).var()
    var_open_to_close = ln_cc_prev.rolling(window).var()
    rs = ln_ho * (ln_ho - ln_co) + ln_lo * (ln_lo - ln_co)
    var_rs = rs.rolling(window).mean()

    var_yz = var_overnight + k * var_open_to_close + (1 - k) * var_rs
    var_yz = var_yz.clip(lower=0)
    return (np.sqrt(var_yz * TRADING_DAYS) * 100).round(3)


# ─────────────────────────────────────────────────────────────────────────────
#  IV rank / percentile
# ─────────────────────────────────────────────────────────────────────────────
def iv_rank(current_iv: float, iv_history: Optional[pd.Series]) -> Optional[float]:
    """(current − min) / (max − min) × 100. Returns None if insufficient history.

    Pass a real IV history for a meaningful IV Rank — the legacy implementation
    reused HV30 as a proxy, which is conceptually wrong."""
    if current_iv is None or iv_history is None or len(iv_history.dropna()) < 20:
        return None
    h = iv_history.dropna().astype(float)
    lo, hi = float(h.min()), float(h.max())
    if hi <= lo:
        return None
    return round(max(0.0, min(100.0, (current_iv - lo) / (hi - lo) * 100.0)), 1)


def iv_percentile(current_iv: float, iv_history: Optional[pd.Series]) -> Optional[float]:
    """Fraction of observations strictly less than current IV, ×100."""
    if current_iv is None or iv_history is None or len(iv_history.dropna()) < 20:
        return None
    h = iv_history.dropna().astype(float)
    return round(float((h < current_iv).mean() * 100.0), 1)


# ─────────────────────────────────────────────────────────────────────────────
#  High-level analytics bundle consumed by UI
# ─────────────────────────────────────────────────────────────────────────────
def vol_analytics(price_df: pd.DataFrame, atm_iv: Optional[float],
                  iv_history: Optional[pd.Series] = None) -> dict:
    """Build a dict of analytics for the UI. Empty dict if inputs too small."""
    if price_df is None or price_df.empty or "close" not in price_df.columns:
        return {}
    closes = price_df["close"].dropna()
    if len(closes) < 30:
        return {}

    log_rets = np.log(closes / closes.shift(1)).dropna()

    # Multiple HV estimators
    hv20 = hv_close_to_close(closes, 20).dropna()
    hv30 = hv_close_to_close(closes, 30).dropna()
    hv60 = hv_close_to_close(closes, 60).dropna()
    hv90 = hv_close_to_close(closes, 90).dropna()

    has_ohlc = {"open", "high", "low"}.issubset(price_df.columns)
    hv30_pk = hv30_gk = hv30_yz = None
    if has_ohlc and len(closes) >= 30:
        try:
            hv30_pk = float(hv_parkinson(price_df["high"], price_df["low"], 30).dropna().iloc[-1])
            hv30_gk = float(hv_garman_klass(price_df["open"], price_df["high"],
                                            price_df["low"], price_df["close"], 30).dropna().iloc[-1])
            hv30_yz = float(hv_yang_zhang(price_df["open"], price_df["high"],
                                          price_df["low"], price_df["close"], 30).dropna().iloc[-1])
        except Exception:
            pass

    def _last(s):
        return round(float(np.asarray(s.iloc[-1]).flat[0]), 2) if len(s) > 0 else None

    hv20_v, hv30_v, hv60_v, hv90_v = _last(hv20), _last(hv30), _last(hv60), _last(hv90)

    iv_hv_ratio = round(atm_iv / (hv30_v + 1e-9), 2) if (atm_iv and hv30_v) else None
    iv_hv_spread = round(atm_iv - hv30_v, 2) if (atm_iv and hv30_v) else None

    # IV rank proper — requires persisted IV history
    iv_rank_v = iv_rank(atm_iv, iv_history) if atm_iv is not None else None
    iv_pct_v = iv_percentile(atm_iv, iv_history) if atm_iv is not None else None

    # Fallback: HV-based ranking (legacy), renamed to be honest about it
    hv_rank_v = None
    if len(hv30) >= 20 and atm_iv is not None:
        lo, hi = float(hv30.min()), float(hv30.max())
        if hi > lo:
            hv_rank_v = round(max(0.0, min(100.0, (atm_iv - lo) / (hi - lo) * 100)), 1)

    hv_pct_v = None
    if len(hv30) >= 20 and hv30_v is not None:
        hv_pct_v = round(float((hv30 < hv30_v).mean() * 100), 1)

    # Cone of HVs
    cone = {}
    for w, lbl in [(10, "HV10"), (20, "HV20"), (30, "HV30"), (60, "HV60"), (90, "HV90")]:
        s = hv_close_to_close(closes, w).dropna()
        if len(s) >= w:
            cone[lbl] = {
                "p10": round(float(s.quantile(0.10)), 2),
                "p25": round(float(s.quantile(0.25)), 2),
                "p50": round(float(s.quantile(0.50)), 2),
                "p75": round(float(s.quantile(0.75)), 2),
                "p90": round(float(s.quantile(0.90)), 2),
                "current": round(float(s.iloc[-1]), 2),
            }

    if iv_hv_ratio is not None:
        if iv_hv_ratio > 1.3:
            vol_regime = "IV CARA"
        elif iv_hv_ratio < 0.8:
            vol_regime = "IV BARATA"
        else:
            vol_regime = "IV NEUTRAL"
    else:
        vol_regime = "—"

    ann_ret = round(float(log_rets.mean() * TRADING_DAYS * 100), 2)
    skewness = round(float(log_rets.skew()), 3)
    kurt = round(float(log_rets.kurt()), 3)

    return {
        "hv20": hv20_v, "hv30": hv30_v, "hv60": hv60_v, "hv90": hv90_v,
        "hv30_parkinson": round(hv30_pk, 2) if hv30_pk else None,
        "hv30_garman_klass": round(hv30_gk, 2) if hv30_gk else None,
        "hv30_yang_zhang": round(hv30_yz, 2) if hv30_yz else None,
        "iv_hv_ratio": iv_hv_ratio,
        "iv_hv_spread": iv_hv_spread,
        "hv_percentile": hv_pct_v,
        "iv_rank": iv_rank_v,
        "iv_percentile": iv_pct_v,
        "hv_rank": hv_rank_v,  # legacy "IV rank over HV"
        "vol_regime": vol_regime,
        "cone": cone,
        "hv20_series": hv20, "hv30_series": hv30,
        "hv60_series": hv60, "log_returns": log_rets,
        "closes": closes, "ann_ret": ann_ret,
        "skewness": skewness, "kurtosis": kurt, "dates": price_df["date"],
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Back-compat
# ─────────────────────────────────────────────────────────────────────────────
def calc_hv(closes: pd.Series, window: int) -> pd.Series:
    return hv_close_to_close(closes, window)


def calc_vol_analytics(price_df: pd.DataFrame, atm_iv: float) -> dict:
    return vol_analytics(price_df, atm_iv)
