"""
Expected-move analyzer — multi-sigma bands, probability of touch, and
iron condor strike suggestions, with proper 0DTE fractional-T support.

The legacy `quant.levels.expected_move` returns just the 1σ band. For
0DTE iron condor traders that's not enough: they need (a) bands at
multiple sigmas to size short/long strikes, (b) skew-adjusted bands
(put-side wider than call-side under normal RR25), and (c) probability
metrics for picking strikes that target a specific prob-of-profit.

This module is independent of the legacy helper and focuses on the
0DTE / weekly use case. It uses fractional time-to-expiry via
`quant.bs.time_to_expiry_years` so the bands have realistic width even
mid-session on expiry day.

Public API
----------
    Band                       — dataclass: one (sigma, low, high, width, pot, p_inside)
    EMAnalysis                 — dataclass: full bundle of bands + metadata
    compute_em_bands(...)      — main entry point
    suggest_iron_condor(...)   — strike picker for a target prob-of-profit
    prob_of_touch(...)         — risk-neutral touch probability under GBM
    prob_inside(...)           — probability spot ends in [low, high] at T
"""
from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
from scipy.stats import norm

from quant import bs


# ─────────────────────────────────────────────────────────────────────────────
#  Dataclasses
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Band:
    sigma: float           # multiple of 1σ (e.g. 1.0, 1.5, 2.0)
    low: float             # spot − sigma·σ_move (or skew-adjusted)
    high: float            # spot + sigma·σ_move (or skew-adjusted)
    width: float           # high − low
    width_pct: float       # width / spot × 100
    p_inside: float        # P(low ≤ S_T ≤ high) — risk-neutral
    p_touch_low: float     # P(spot touches `low` before T) — Bachelier approx
    p_touch_high: float    # P(spot touches `high` before T)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EMAnalysis:
    spot: float
    T: float                              # time in years (annualized)
    minutes_to_close: float               # convenience
    iv_call: Optional[float]              # IV near ATM, calls (%)
    iv_put: Optional[float]               # IV near ATM, puts (%)
    iv_blend: Optional[float]             # average — used for symmetric bands
    skew_adjusted: bool                   # True if iv_call != iv_put applied
    sigma_move_dollars: float             # 1σ move in dollar terms
    bands: list[Band] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bands"] = [b.to_dict() for b in self.bands]
        return d


# ─────────────────────────────────────────────────────────────────────────────
#  Probability helpers (risk-neutral, lognormal GBM)
# ─────────────────────────────────────────────────────────────────────────────
def prob_inside(spot: float, low: float, high: float,
                iv_pct: float, T: float, r: float = 0.045,
                q: float = 0.0) -> float:
    """P(low ≤ S_T ≤ high) under risk-neutral lognormal dynamics.

    S_T = spot · exp((r − q − ½σ²)T + σ√T · Z), Z ~ N(0,1).
    So ln(S_T/spot) ~ N((r−q−½σ²)T, σ²T).
    """
    if T <= 0 or spot <= 0 or low <= 0 or high <= low or iv_pct is None:
        return 0.0
    sigma = float(iv_pct) / 100.0
    if sigma <= 0:
        return 0.0
    mu = (r - q - 0.5 * sigma * sigma) * T
    sd = sigma * np.sqrt(T)
    z_lo = (np.log(low / spot) - mu) / sd
    z_hi = (np.log(high / spot) - mu) / sd
    return float(norm.cdf(z_hi) - norm.cdf(z_lo))


def prob_of_touch(spot: float, strike: float, iv_pct: float, T: float,
                  r: float = 0.045, q: float = 0.0) -> float:
    """Probability the underlying touches `strike` before expiry, under
    GBM with continuous monitoring. Classic result:

        P(touch) ≈ 2 · P(S_T ends past the barrier)

    The factor of 2 is the reflection principle limit, exact for a
    barrier above starting point under driftless Brownian motion. Close
    enough for trading-day approximations where T is small and (r−q)·T
    is tiny vs σ√T (always true for 0DTE).
    """
    if T <= 0 or spot <= 0 or strike <= 0 or iv_pct is None:
        return 0.0
    sigma = float(iv_pct) / 100.0
    if sigma <= 0:
        return 0.0
    mu = (r - q - 0.5 * sigma * sigma) * T
    sd = sigma * np.sqrt(T)
    z = (np.log(strike / spot) - mu) / sd
    # P(S_T crosses) ≈ 1 - Φ(|z|) for one side; doubled by reflection.
    one_side = float(norm.sf(abs(z)))
    return float(min(1.0, 2.0 * one_side))


# ─────────────────────────────────────────────────────────────────────────────
#  Main entry — multi-sigma bands
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_SIGMAS = (0.5, 1.0, 1.5, 2.0)


def compute_em_bands(
    spot: float,
    iv_call_pct: Optional[float],
    iv_put_pct: Optional[float] = None,
    dte: int = 0,
    now: Optional[datetime.datetime] = None,
    sigmas: tuple[float, ...] = DEFAULT_SIGMAS,
    r: float = 0.045,
    q: float = 0.0,
    skew_adjust: bool = True,
) -> Optional[EMAnalysis]:
    """Compute multi-sigma expected-move bands.

    Parameters
    ----------
    spot : float
        Current underlying price.
    iv_call_pct, iv_put_pct : float (percent)
        ATM IV from each side of the chain (typically `_interp_iv_one_side`
        from `quant.levels`). If `iv_put_pct` is None the function uses
        `iv_call_pct` symmetrically. When both are present and
        `skew_adjust=True`, the upper band uses call-IV and the lower band
        uses put-IV — captures the realistic skew where downside moves
        price-in higher vol than upside.
    dte : int
        Days to expiry. For dte ≤ 0 the function delegates to
        `bs.time_to_expiry_years` for fractional hours-to-close.
    sigmas : iterable
        Sigma multiples to report bands for. Default (0.5, 1, 1.5, 2).
    r, q : float
        Risk-free rate and dividend yield for the lognormal model. Use
        `bs.rate_for_dte(dte)` and `config.dividend_yield_for(symbol)`
        upstream if you want symbol-specific values.
    skew_adjust : bool
        If True and both IVs are present, use side-specific IV. If
        False, always use the average (symmetric bands).
    """
    if not spot or spot <= 0 or iv_call_pct is None:
        return None

    # ── Time in years (fractional for 0DTE) ────────────────────────────
    if dte <= 0:
        T_arr = bs.time_to_expiry_years(np.array([0]), now=now)
        T = float(T_arr[0])
    else:
        T = float(max(dte, 0)) / 365.0
    if T <= 0:
        return None
    minutes_to_close = T * 365.0 * 24.0 * 60.0  # back-out for display

    iv_c = float(iv_call_pct)
    iv_p = float(iv_put_pct) if iv_put_pct is not None else iv_c
    iv_blend = (iv_c + iv_p) / 2.0
    is_skew_adj = skew_adjust and (abs(iv_c - iv_p) > 0.01)

    # 1σ move in dollars, based on the blended IV. This is the headline
    # number — what most platforms call "Expected Move".
    sigma_move_dollars = spot * (iv_blend / 100.0) * np.sqrt(T)

    bands: list[Band] = []
    for k in sigmas:
        # When skew-adjusted, the upper bound uses call IV (vol the
        # market is implying for upside moves) and the lower bound uses
        # put IV (downside vol — typically higher under normal skew).
        iv_up = iv_c if is_skew_adj else iv_blend
        iv_dn = iv_p if is_skew_adj else iv_blend
        move_up = spot * (iv_up / 100.0) * np.sqrt(T) * k
        move_dn = spot * (iv_dn / 100.0) * np.sqrt(T) * k
        low = spot - move_dn
        high = spot + move_up
        width = high - low
        p_in = prob_inside(spot, low, high, iv_blend, T, r=r, q=q)
        p_t_lo = prob_of_touch(spot, low, iv_dn, T, r=r, q=q)
        p_t_hi = prob_of_touch(spot, high, iv_up, T, r=r, q=q)
        bands.append(Band(
            sigma=float(k),
            low=round(float(low), 2),
            high=round(float(high), 2),
            width=round(float(width), 2),
            width_pct=round(float(width / spot * 100.0), 2),
            p_inside=round(float(p_in), 4),
            p_touch_low=round(float(p_t_lo), 4),
            p_touch_high=round(float(p_t_hi), 4),
        ))

    return EMAnalysis(
        spot=round(float(spot), 2),
        T=round(float(T), 8),
        minutes_to_close=round(float(minutes_to_close), 1),
        iv_call=round(float(iv_c), 2),
        iv_put=round(float(iv_p), 2),
        iv_blend=round(float(iv_blend), 2),
        skew_adjusted=is_skew_adj,
        sigma_move_dollars=round(float(sigma_move_dollars), 3),
        bands=bands,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Iron condor strike picker
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class IronCondorSuggestion:
    short_put: float
    long_put: float
    short_call: float
    long_call: float
    wing_width: float
    prob_of_profit: float       # P(S_T inside [short_put, short_call])
    p_touch_short_put: float
    p_touch_short_call: float
    max_loss_per_spread: float  # = wing_width (in points)
    target_pop: float           # what we asked for

    def to_dict(self) -> dict:
        return asdict(self)


def _snap_to_grid(price: float, grid: float = 1.0,
                  direction: str = "nearest") -> float:
    """Snap a price to a strike grid (default 1pt for SPX/SPY whole strikes).
    direction ∈ {"nearest", "down", "up"}."""
    if grid <= 0:
        return price
    if direction == "down":
        return float(np.floor(price / grid) * grid)
    if direction == "up":
        return float(np.ceil(price / grid) * grid)
    return float(round(price / grid) * grid)


def suggest_iron_condor(
    analysis: EMAnalysis,
    target_pop: float = 0.70,
    wing_width: float = 5.0,
    strike_grid: float = 1.0,
    r: float = 0.045,
    q: float = 0.0,
) -> Optional[IronCondorSuggestion]:
    """Pick short / long strikes for a 0DTE iron condor targeting a
    given probability of profit.

    Method
    ------
    1. Bisect the *short* strikes outward from spot until
       P(S_T ∈ [short_put, short_call]) ≈ target_pop.
    2. Long strikes = short ± wing_width (snapped to grid).
    3. Compute P-of-touch on the short legs for risk context.

    Uses the analysis's blended IV (symmetric search). Skew adjustment
    of the search is possible but adds little for the 0DTE case.

    Returns None if `analysis` is invalid or the search can't converge
    (e.g. spot too close to a grid point with absurd vol).
    """
    if analysis is None or analysis.T <= 0:
        return None
    iv = analysis.iv_blend
    if iv is None or iv <= 0:
        return None
    spot = analysis.spot
    T = analysis.T

    # Bisect over k (sigma multiple) for the symmetric short band.
    # P_inside is monotonically increasing in k, so this converges fast.
    lo, hi = 0.10, 4.0
    target = float(np.clip(target_pop, 0.05, 0.95))
    best_k: Optional[float] = None
    best_diff = float("inf")
    for _ in range(40):
        k = 0.5 * (lo + hi)
        move = spot * (iv / 100.0) * np.sqrt(T) * k
        p_in = prob_inside(spot, spot - move, spot + move, iv, T, r=r, q=q)
        diff = abs(p_in - target)
        if diff < best_diff:
            best_diff = diff
            best_k = k
        if p_in < target:
            lo = k
        else:
            hi = k
        if diff < 1e-4:
            break
    if best_k is None:
        return None

    move = spot * (iv / 100.0) * np.sqrt(T) * best_k
    # Short strikes — snap put DOWN (further OTM) and call UP (further OTM)
    # for a slightly more conservative band after snapping.
    short_put = _snap_to_grid(spot - move, strike_grid, direction="down")
    short_call = _snap_to_grid(spot + move, strike_grid, direction="up")
    long_put = _snap_to_grid(short_put - wing_width, strike_grid, "down")
    long_call = _snap_to_grid(short_call + wing_width, strike_grid, "up")

    # Recompute the realised P-of-profit with the snapped strikes.
    p_in_snapped = prob_inside(spot, short_put, short_call, iv, T, r=r, q=q)
    p_t_sp = prob_of_touch(spot, short_put, iv, T, r=r, q=q)
    p_t_sc = prob_of_touch(spot, short_call, iv, T, r=r, q=q)

    return IronCondorSuggestion(
        short_put=float(short_put),
        long_put=float(long_put),
        short_call=float(short_call),
        long_call=float(long_call),
        wing_width=float(wing_width),
        prob_of_profit=round(float(p_in_snapped), 4),
        p_touch_short_put=round(float(p_t_sp), 4),
        p_touch_short_call=round(float(p_t_sc), 4),
        max_loss_per_spread=float(wing_width),
        target_pop=float(target),
    )
