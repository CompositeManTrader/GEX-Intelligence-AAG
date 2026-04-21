"""
Black-Scholes-Merton core — vectorized, supports continuous dividend yield q,
fractional T (intraday tail for 0DTE), and returns NaN on invalid inputs.

All functions accept scalars or arrays (broadcasting). Never raise; invalid
rows propagate as NaN/0.0 downstream.

Reference: Hull 11e, Ch 19.
"""
from __future__ import annotations

import datetime
from typing import Union

import numpy as np
from scipy.stats import norm

from config import CALENDAR_DAYS, MARKET_CLOSE_ET, RATE_CURVE_DEFAULT

ArrayLike = Union[float, np.ndarray]

_EPS = 1e-12


# ─────────────────────────────────────────────────────────────────────────────
#  Time helpers — 0DTE requires fractional day (hours to close)
# ─────────────────────────────────────────────────────────────────────────────
def time_to_expiry_years(
    dte: ArrayLike,
    now: datetime.datetime | None = None,
) -> np.ndarray:
    """Convert DTE (calendar days integer) to T in years.

    For DTE == 0 (0DTE) uses remaining hours until 16:00 ET as a fraction of
    a trading day. Minimum floor of ~2 minutes to keep BS numerically stable.
    """
    dte = np.asarray(dte, dtype=float)
    T = dte / float(CALENDAR_DAYS)

    zero_mask = dte == 0
    if np.any(zero_mask):
        # Work in Eastern Time — crude (no DST adjustment) but sufficient intraday.
        now = now or datetime.datetime.utcnow()
        et_now = now - datetime.timedelta(hours=4)  # approx ET (EDT)
        close = datetime.datetime.combine(et_now.date(), MARKET_CLOSE_ET)
        secs_to_close = max((close - et_now).total_seconds(), 120.0)
        frac_day = secs_to_close / 86400.0
        # T for 0DTE = fraction of one calendar day
        T = np.where(zero_mask, frac_day / CALENDAR_DAYS, T)

    # Final floor to prevent divide-by-zero in sigma*sqrt(T)
    return np.maximum(T, 2.0 / (86400.0 * CALENDAR_DAYS))


def rate_for_dte(dte: ArrayLike,
                 curve: dict[int, float] | None = None) -> np.ndarray:
    """Linear interpolation of the risk-free curve for the given DTEs."""
    curve = curve or RATE_CURVE_DEFAULT
    tenors = np.asarray(sorted(curve.keys()), dtype=float)
    rates = np.asarray([curve[int(t)] for t in tenors], dtype=float)
    dte_arr = np.asarray(dte, dtype=float)
    return np.interp(dte_arr, tenors, rates, left=rates[0], right=rates[-1])


# ─────────────────────────────────────────────────────────────────────────────
#  d1, d2 — with dividend yield q
# ─────────────────────────────────────────────────────────────────────────────
def d1(S: ArrayLike, K: ArrayLike, T: ArrayLike,
       sigma: ArrayLike, r: ArrayLike, q: ArrayLike = 0.0) -> np.ndarray:
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    r = np.asarray(r, dtype=float)
    q = np.asarray(q, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (np.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * np.sqrt(T))
    valid = (T > 0) & (sigma > 0) & (S > 0) & (K > 0)
    return np.where(valid, out, np.nan)


def d2(d1_val: ArrayLike, sigma: ArrayLike, T: ArrayLike) -> np.ndarray:
    sigma = np.asarray(sigma, dtype=float)
    T = np.asarray(T, dtype=float)
    return d1_val - sigma * np.sqrt(T)


# ─────────────────────────────────────────────────────────────────────────────
#  First-order greeks — useful for sanity check vs API
# ─────────────────────────────────────────────────────────────────────────────
def delta(S, K, T, sigma, r, q=0.0, side: str = "call") -> np.ndarray:
    v1 = d1(S, K, T, sigma, r, q)
    disc = np.exp(-np.asarray(q) * np.asarray(T))
    if side == "call":
        out = disc * norm.cdf(v1)
    else:
        out = disc * (norm.cdf(v1) - 1.0)
    return np.where(np.isfinite(out), out, np.nan)


def gamma(S, K, T, sigma, r, q=0.0) -> np.ndarray:
    """Gamma is identical for call and put (q>=0)."""
    S = np.asarray(S, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    q = np.asarray(q, dtype=float)
    v1 = d1(S, K, T, sigma, r, q)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.exp(-q * T) * norm.pdf(v1) / (S * sigma * np.sqrt(T))
    return np.where(np.isfinite(out), out, 0.0)


def vanna(S, K, T, sigma, r, q=0.0) -> np.ndarray:
    """Vanna = ∂Δ/∂σ = e^(-qT) · φ(d1) · (−d2 / σ).

    Same for calls and puts (q>=0)."""
    S = np.asarray(S, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    q = np.asarray(q, dtype=float)
    v1 = d1(S, K, T, sigma, r, q)
    v2 = d2(v1, sigma, T)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.exp(-q * T) * norm.pdf(v1) * (-v2 / sigma)
    return np.where(np.isfinite(out), out, 0.0)


def charm(S, K, T, sigma, r, q=0.0, per: str = "day") -> np.ndarray:
    """Charm (∂Δ/∂t). Returned per calendar day by default.

    Hull 19.12 (with continuous dividend q):
      Charm_call_year = q·e^(-qT)·N(d1)
          − e^(-qT)·φ(d1)·[ 2(r-q)T − d2·σ√T ] / (2T·σ√T)
    For put: Charm_put = Charm_call − q·e^(-qT) (parity in Δ).
    We use the call form here; since downstream GEX/VEX/CEX use `charm`
    identically for both sides under q=0 this equals the legacy behaviour.
    For q>0 callers should pass `side` if they care about the put/call split.
    """
    S = np.asarray(S, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    r = np.asarray(r, dtype=float)
    q = np.asarray(q, dtype=float)

    v1 = d1(S, K, T, sigma, r, q)
    v2 = d2(v1, sigma, T)
    with np.errstate(divide="ignore", invalid="ignore"):
        term_q = q * np.exp(-q * T) * norm.cdf(v1)
        num = np.exp(-q * T) * norm.pdf(v1) * (2.0 * (r - q) * T - v2 * sigma * np.sqrt(T))
        den = 2.0 * T * sigma * np.sqrt(T)
        charm_year = term_q - num / den
    if per == "day":
        charm_year = charm_year / float(CALENDAR_DAYS)
    return np.where(np.isfinite(charm_year), charm_year, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
#  Back-compat shims used by legacy callers
# ─────────────────────────────────────────────────────────────────────────────
def bs_d1(S, K, T, sigma, r, q=0.0):
    return d1(S, K, T, sigma, r, q)


def bs_d2(d1_val, sigma, T):
    return d2(d1_val, sigma, T)


def bs_vanna_vec(S, K, T, sigma, r, q=0.0):
    return vanna(S, K, T, sigma, r, q)


def bs_charm_vec(S, K, T, sigma, r, q=0.0):
    return charm(S, K, T, sigma, r, q, per="day")


def bs_gamma_vec(S, K, T, sigma, r, q=0.0):
    return gamma(S, K, T, sigma, r, q)
