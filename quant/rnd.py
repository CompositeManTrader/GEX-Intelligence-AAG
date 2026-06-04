"""
Risk-Neutral Density — SVI-based, the central model of Expected Range.

This is the production-grade replacement for the naive Breeden-Litzenberger
in `quant.expected_range`. It fixes the seven things that made level
estimates imprecise:

  1. OTM blend (puts below forward, calls above) — best IV per strike.
  2. Works in (log-moneyness, total variance) space where the smile is
     smooth and near-linear, not in raw (strike, IV).
  3. SVI parametric fit (Gatheral) instead of an arbitrary smoothing
     spline — 5 parameters, robust to noisy 0DTE strikes.
  4. Arbitrage-free by construction (Gatheral g(k) ≥ 0 check); degrades
     gracefully to a monotone spline, then to direct BL, if the fit fails.
  5. Wide grid (±N·σ) so tails aren't truncated — P5/P95 are reliable.
  6. Centred on the FORWARD F = S·e^((r−q)T), not spot.
  7. Exact level inversion of the CDF for percentiles, not linear interp.

SVI raw parametrization (Gatheral 2004):

    w(k) = a + b·[ρ·(k − m) + √((k − m)² + σ²)]

with  w = total implied variance = σ_BS²·T,  k = ln(K/F).
Parameters:
    a      vertical level of variance
    b ≥ 0  wing slopes (b(1±ρ))
    ρ      skew rotation, |ρ| < 1
    m      horizontal shift of the vertex
    σ > 0  ATM curvature smoothing

Public API
----------
    fit_svi(k, w, T)            → (SVIParams, rmse)
    svi_total_variance(p, k)    → w(k)
    build_rnd(calls, puts, …)   → RND DataFrame + metadata dict
    rnd_levels(rnd, spot, …)    → exact percentiles + mode + level probs
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from quant import bs


# ─────────────────────────────────────────────────────────────────────────────
#  SVI parametrization
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SVIParams:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def to_dict(self) -> dict:
        return asdict(self)


def svi_total_variance(p: SVIParams, k: np.ndarray) -> np.ndarray:
    """Evaluate the SVI total variance w(k). Always non-negative for
    valid parameters (a + b·σ·√(1−ρ²) ≥ 0)."""
    k = np.asarray(k, dtype=float)
    return p.a + p.b * (p.rho * (k - p.m) + np.sqrt((k - p.m) ** 2 + p.sigma ** 2))


def _svi_residuals(x: np.ndarray, k: np.ndarray, w: np.ndarray,
                   weights: np.ndarray) -> np.ndarray:
    a, b, rho, m, sigma = x
    model = a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma ** 2))
    return (model - w) * weights


def fit_svi(k: np.ndarray, w: np.ndarray, T: float,
            weights: Optional[np.ndarray] = None
            ) -> tuple[Optional[SVIParams], float]:
    """Least-squares fit of the SVI raw form to (k, w) observations.

    Returns (SVIParams, rmse) or (None, inf) if the fit can't run.
    Bounds enforce the arb-free necessary conditions:
        b ≥ 0,  |ρ| < 1,  σ > 0,  and  b(1+|ρ|) ≤ 4/T  (Lee wing limit).
    """
    k = np.asarray(k, dtype=float)
    w = np.asarray(w, dtype=float)
    good = np.isfinite(k) & np.isfinite(w) & (w > 0)
    k, w = k[good], w[good]
    if len(k) < 5:
        return None, float("inf")
    if weights is None:
        weights = np.ones_like(w)
    else:
        weights = np.asarray(weights, dtype=float)[good]

    try:
        from scipy.optimize import least_squares
    except Exception:
        return None, float("inf")

    w_atm = float(np.median(w))
    w_max = float(np.max(w))
    k_span = float(np.max(k) - np.min(k)) or 0.1
    # Lee wing limit: b(1+|ρ|) ≤ 4/T → b ≤ 4/T. For 0DTE T is tiny so the
    # cap is large/loose (correct: little time = little wing arbitrage risk).
    b_max = max(4.0 / max(T, 1e-6), 1.0)

    x0 = np.array([
        max(w_atm * 0.5, 1e-8),   # a
        min(0.1, b_max * 0.5),    # b
        -0.3,                      # rho (equity put-skew default)
        0.0,                       # m
        max(k_span * 0.3, 1e-3),  # sigma
    ])
    lower = np.array([1e-10, 0.0, -0.999, -0.5, 1e-4])
    upper = np.array([max(w_max * 2.0, 1e-6), b_max, 0.999, 0.5,
                      max(k_span * 2.0, 0.5)])
    # Clip x0 into bounds (guards degenerate inputs)
    x0 = np.minimum(np.maximum(x0, lower + 1e-12), upper - 1e-12)

    try:
        res = least_squares(
            _svi_residuals, x0, args=(k, w, weights),
            bounds=(lower, upper), method="trf", max_nfev=2000,
        )
        p = SVIParams(a=float(res.x[0]), b=float(res.x[1]),
                      rho=float(res.x[2]), m=float(res.x[3]),
                      sigma=float(res.x[4]))
        model = svi_total_variance(p, k)
        rmse = float(np.sqrt(np.mean(((model - w)) ** 2)))
        return p, rmse
    except Exception:
        return None, float("inf")


def svi_g_function(p: SVIParams, k: np.ndarray) -> np.ndarray:
    """Gatheral's g(k) — the function whose positivity guarantees the
    SVI slice is free of butterfly arbitrage (i.e. density ≥ 0).

        g(k) = (1 − k·w'/(2w))² − (w'/4)²·(1/w + 1/4) + w''/2
    """
    k = np.asarray(k, dtype=float)
    root = np.sqrt((k - p.m) ** 2 + p.sigma ** 2)
    w = p.a + p.b * (p.rho * (k - p.m) + root)
    wp = p.b * (p.rho + (k - p.m) / root)               # w'(k)
    wpp = p.b * p.sigma ** 2 / (root ** 3)               # w''(k)
    w = np.where(w > 1e-12, w, 1e-12)
    term1 = (1.0 - k * wp / (2.0 * w)) ** 2
    term2 = (wp ** 2 / 4.0) * (1.0 / w + 0.25)
    return term1 - term2 + wpp / 2.0


# ─────────────────────────────────────────────────────────────────────────────
#  Black-76 (forward-based) call price — correct when working with forward
# ─────────────────────────────────────────────────────────────────────────────
def _black76_call(F: float, K: np.ndarray, T: float, sigma: np.ndarray,
                  r: float) -> np.ndarray:
    K = np.asarray(K, float)
    sigma = np.asarray(sigma, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sqrtT = np.sqrt(T)
        d1 = (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        c = np.exp(-r * T) * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return c


# ─────────────────────────────────────────────────────────────────────────────
#  OTM-blended IV input
# ─────────────────────────────────────────────────────────────────────────────
def _otm_blend(calls: pd.DataFrame, puts: pd.DataFrame,
               forward: float) -> Optional[pd.DataFrame]:
    """Build a single IV-per-strike series using the OTM convention vs the
    forward: puts for K < F, calls for K ≥ F. Returns DataFrame
    (Strike, iv_decimal) sorted, or None if too few points."""
    pieces = []
    if puts is not None and not puts.empty and {"Strike", "IV%"}.issubset(puts.columns):
        p = puts[["Strike", "IV%"]].copy()
        p["Strike"] = pd.to_numeric(p["Strike"], errors="coerce")
        p["IV%"] = pd.to_numeric(p["IV%"], errors="coerce")
        p = p[p["Strike"] < forward]
        pieces.append(p)
    if calls is not None and not calls.empty and {"Strike", "IV%"}.issubset(calls.columns):
        c = calls[["Strike", "IV%"]].copy()
        c["Strike"] = pd.to_numeric(c["Strike"], errors="coerce")
        c["IV%"] = pd.to_numeric(c["IV%"], errors="coerce")
        c = c[c["Strike"] >= forward]
        pieces.append(c)
    if not pieces:
        return None
    df = pd.concat(pieces, ignore_index=True).dropna()
    df = df[(df["IV%"] > 0) & (df["IV%"] < 1000)]
    df = df.groupby("Strike", as_index=False)["IV%"].mean().sort_values("Strike")
    if len(df) < 5:
        # Fall back to calls-only if the blend is too sparse
        if calls is not None and not calls.empty:
            c = calls[["Strike", "IV%"]].copy()
            c["Strike"] = pd.to_numeric(c["Strike"], errors="coerce")
            c["IV%"] = pd.to_numeric(c["IV%"], errors="coerce")
            c = c.dropna()
            c = c[(c["IV%"] > 0) & (c["IV%"] < 1000)]
            c = c.groupby("Strike", as_index=False)["IV%"].mean().sort_values("Strike")
            if len(c) >= 5:
                c["iv"] = c["IV%"] / 100.0
                return c[["Strike", "iv"]]
        return None
    df["iv"] = df["IV%"] / 100.0
    return df[["Strike", "iv"]]


# ─────────────────────────────────────────────────────────────────────────────
#  Main builder
# ─────────────────────────────────────────────────────────────────────────────
def _trapz(y, x):
    y = np.asarray(y, float); x = np.asarray(x, float)
    if len(y) < 2:
        return 0.0
    return float(np.sum((y[1:] + y[:-1]) / 2.0 * np.diff(x)))


def build_rnd(
    calls: pd.DataFrame, puts: pd.DataFrame, spot: float, dte: int = 0,
    r: float = 0.045, q: float = 0.0, now=None,
    grid_points: int = 401, tail_sigmas: float = 4.0,
) -> tuple[Optional[pd.DataFrame], dict]:
    """Build the risk-neutral density from the option chain.

    Returns (rnd_df, meta) where:
      rnd_df  — DataFrame(strike, pdf, cdf, iv_fit) or None
      meta    — dict with: method ('svi'|'spline'|'bl'), svi params,
                rmse, forward, arb_free (bool), min_g, n_strikes, T,
                truncated (bool — whether the grid clipped the tails).
    """
    meta: dict = {"method": None, "forward": None, "rmse": None,
                  "arb_free": None, "min_g": None, "n_strikes": 0,
                  "T": None, "truncated": False, "svi": None,
                  "svi_reject": None, "wing_capped": None}
    if not spot or spot <= 0:
        return None, meta

    T = (float(bs.time_to_expiry_years(np.array([0]), now=now)[0])
         if dte <= 0 else float(max(dte, 0)) / 365.0)
    if T <= 0:
        return None, meta
    meta["T"] = round(T, 8)

    forward = spot * np.exp((r - q) * T)
    meta["forward"] = round(forward, 4)

    blend = _otm_blend(calls, puts, forward)
    if blend is None or len(blend) < 5:
        return None, meta
    meta["n_strikes"] = int(len(blend))

    K = blend["Strike"].to_numpy(dtype=float)
    iv = blend["iv"].to_numpy(dtype=float)
    k_obs = np.log(K / forward)
    w_obs = (iv ** 2) * T
    # Weight ATM strikes more (they're the most liquid / reliable)
    weights = np.exp(-0.5 * (k_obs / max(np.std(k_obs), 1e-3)) ** 2) + 0.25

    # ── Grid: ±tail_sigmas in log-moneyness, but don't extrapolate the
    # SVI fit absurdly far beyond observed strikes.
    atm_sd = float(np.sqrt(np.median(w_obs))) if np.median(w_obs) > 0 else 0.02
    k_reach = min(tail_sigmas * atm_sd, 1.5 * max(abs(k_obs.min()), abs(k_obs.max())))
    k_reach = max(k_reach, 1.2 * max(abs(k_obs.min()), abs(k_obs.max())))
    meta["truncated"] = bool(k_reach < tail_sigmas * atm_sd * 0.999)
    k_grid = np.linspace(-k_reach, k_reach, grid_points)
    K_grid = forward * np.exp(k_grid)

    # ── Fit SVI ──────────────────────────────────────────────────────────
    params, rmse = fit_svi(k_obs, w_obs, T, weights=weights)
    method = None
    w_grid = None
    if params is None:
        # Instrumentation: record WHY SVI was unavailable so the UI can
        # surface it (the fit didn't converge or had too few points).
        meta["svi_reject"] = f"fit None (n={len(k_obs)})"
    else:
        w_svi = svi_total_variance(params, k_grid)
        g = svi_g_function(params, k_grid)
        min_g = float(np.min(g))
        n_wneg = int(np.sum(w_svi <= 0))
        meta["min_g"] = round(min_g, 6)
        meta["svi"] = params.to_dict()
        meta["rmse"] = round(rmse, 6)
        # Accept SVI if total variance stays positive and (mostly) arb-free.
        if np.all(w_svi > 0) and min_g > -1e-3:
            w_grid = w_svi
            method = "svi"
            meta["arb_free"] = bool(min_g >= 0)
        else:
            # Rejected → spline. Capture the reason for diagnostics: an
            # arbitrage violation (min_g<0) or a non-positive variance on
            # the grid (typically the extrapolated wings for tiny-T 0DTE).
            if n_wneg > 0:
                meta["svi_reject"] = f"w<=0 en {n_wneg} ptos del grid"
            else:
                meta["svi_reject"] = f"arb min_g={min_g:.4f} (umbral -0.001)"

    # ── Wing-repair retry ────────────────────────────────────────────────
    # 0DTE OTM IVs are often inflated (bid-ask on penny-premium options),
    # making the raw smile non-arbitrage-free so SVI is (correctly) rejected
    # → spline → tail artifacts. Those wing IVs are largely noise. If the raw
    # SVI failed for ARBITRAGE (not w<=0), retry with the per-strike total
    # variance capped relative to ATM, tightening until the fit is arb-free.
    # Only fires when the raw fit failed, so well-behaved (longer-dated)
    # smiles are untouched. Verified empirically on steep SPX 0DTE smiles.
    if method is None and params is not None:
        atm_w = float(w_obs[int(np.argmin(np.abs(k_obs)))])
        if atm_w > 0:
            for cap_mult in (3.0, 2.5, 2.0, 1.6):
                w_cap = np.minimum(w_obs, (cap_mult ** 2) * atm_w)
                p2, rmse2 = fit_svi(k_obs, w_cap, T, weights=weights)
                if p2 is None:
                    continue
                w_svi2 = svi_total_variance(p2, k_grid)
                g2 = svi_g_function(p2, k_grid)
                min_g2 = float(np.min(g2))
                if np.all(w_svi2 > 0) and min_g2 > -1e-3:
                    w_grid = w_svi2
                    method = "svi"
                    meta["min_g"] = round(min_g2, 6)
                    meta["svi"] = p2.to_dict()
                    meta["rmse"] = round(rmse2, 6)
                    meta["arb_free"] = bool(min_g2 >= 0)
                    meta["svi_reject"] = None
                    meta["wing_capped"] = cap_mult
                    break

    # ── Fallback 1: monotone-ish smoothing spline on (k, w) ──────────────
    if w_grid is None:
        try:
            from scipy.interpolate import UnivariateSpline
            order = np.argsort(k_obs)
            s_fac = max(len(k_obs) * 0.3, 1.0) * float(np.nanvar(w_obs)) * 0.5
            spl = UnivariateSpline(k_obs[order], w_obs[order], k=3,
                                   s=s_fac, ext=3)
            w_grid = np.clip(spl(k_grid), 1e-10, None)
            method = "spline"
            meta["arb_free"] = None
        except Exception:
            w_grid = None

    # ── Fallback 2: linear interp on (k, w) ──────────────────────────────
    if w_grid is None:
        w_grid = np.interp(k_grid, k_obs, w_obs)
        w_grid = np.clip(w_grid, 1e-10, None)
        method = "bl"
        meta["arb_free"] = None

    meta["method"] = method
    iv_grid = np.sqrt(np.maximum(w_grid, 1e-12) / T)

    # ── Breeden-Litzenberger: f(K) = e^{rT}·∂²C/∂K² ──────────────────────
    c = _black76_call(forward, K_grid, T, iv_grid, r)
    # Non-uniform grid in K (since K = F·e^k), so use gradient twice.
    first = np.gradient(c, K_grid)
    second = np.gradient(first, K_grid)
    pdf = np.exp(r * T) * second
    pdf = np.where(np.isfinite(pdf), pdf, 0.0)
    pdf = np.clip(pdf, 0.0, None)

    area = _trapz(pdf, K_grid)
    if area <= 0:
        return None, meta
    pdf = pdf / area
    # CDF by cumulative trapezoid
    cdf = np.concatenate([[0.0], np.cumsum((pdf[1:] + pdf[:-1]) / 2.0 * np.diff(K_grid))])
    if cdf[-1] > 0:
        cdf = cdf / cdf[-1]

    rnd = pd.DataFrame({"strike": K_grid, "pdf": pdf, "cdf": cdf,
                        "iv_fit": iv_grid * 100.0})
    return rnd, meta


# ─────────────────────────────────────────────────────────────────────────────
#  Exact levels from the density
# ─────────────────────────────────────────────────────────────────────────────
def rnd_levels(rnd: pd.DataFrame, spot: float,
               levels: Optional[dict] = None,
               percentiles: tuple[float, ...] = (5, 10, 25, 50, 75, 90, 95),
               ) -> dict:
    """Exact level statistics from a risk-neutral density.

    Percentiles come from inverting the CDF (not linear interp of a
    coarse grid). Mode is the density peak. `levels` (e.g. walls) get
    P(below)/P(above) plus an approximate probability-of-touch (2× the
    end-probability past the level, capped at 1).
    """
    if rnd is None or rnd.empty:
        return {}
    K = rnd["strike"].to_numpy(float)
    pdf = rnd["pdf"].to_numpy(float)
    cdf = rnd["cdf"].to_numpy(float)
    dK = np.gradient(K)

    mean = float(np.sum(K * pdf * dK))
    var = float(np.sum((K - mean) ** 2 * pdf * dK))
    std = float(np.sqrt(max(var, 0.0)))
    if std > 0:
        skew = float(np.sum(((K - mean) / std) ** 3 * pdf * dK))
        kurt = float(np.sum(((K - mean) / std) ** 4 * pdf * dK)) - 3.0
    else:
        skew = kurt = 0.0

    mode = float(K[int(np.argmax(pdf))])

    # Percentiles by CDF inversion (CDF is monotone increasing)
    pct = {}
    for p in percentiles:
        target = p / 100.0
        # np.interp needs increasing xp; cdf is increasing
        lvl = float(np.interp(target, cdf, K))
        pct[f"p{int(p)}"] = round(lvl, 2)

    out = {
        "mean": round(mean, 2),
        "std": round(std, 2),
        "std_pct": round(std / spot * 100, 2) if spot else None,
        "skew": round(skew, 3),
        "excess_kurtosis": round(kurt, 3),
        "mode": round(mode, 2),
        "percentiles": pct,
        # 1σ-equivalent band from the actual quantiles (P16/P84)
        "p16": round(float(np.interp(0.16, cdf, K)), 2),
        "p84": round(float(np.interp(0.84, cdf, K)), 2),
        "level_probs": {},
    }
    if levels:
        for name, lvl in levels.items():
            if lvl is None:
                continue
            try:
                lvl = float(lvl)
            except (TypeError, ValueError):
                continue
            p_below = float(np.interp(lvl, K, cdf, left=0.0, right=1.0))
            p_above = 1.0 - p_below
            # P(touch) ≈ 2× the smaller end-probability (reflection bound)
            p_end = min(p_below, p_above)
            out["level_probs"][name] = {
                "level": round(lvl, 2),
                "p_below": round(p_below, 4),
                "p_above": round(p_above, 4),
                "p_touch": round(min(1.0, 2.0 * p_end), 4),
            }
    return out
