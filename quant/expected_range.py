"""
Expected-range analytics — multiple estimators of the session's likely
price range, plus the full risk-neutral density extracted from the chain.

Why five estimators
-------------------
The "expected move" most platforms show is a single number derived from
ATM IV under a Gaussian assumption. That hides three things a serious
trader needs:

  1. What the market actually CHARGES for the move (the straddle price),
     which can diverge from the Gaussian estimate when skew/kurtosis bite.
  2. What the underlying actually DELIVERED recently (realized vol),
     which tells you if IV is rich or cheap.
  3. The real shape of the implied distribution — fat tails and skew —
     not the symmetric bell the Gaussian assumes.

So this module computes:

  · iv_gaussian_em  — spot × IV × √T              (the classic baseline)
  · skew_em         — asymmetric, put-IV down / call-IV up
  · straddle_em     — derived from the actual ATM straddle MID price
  · realized_em     — spot × realized-vol × √T     (Yang-Zhang)
  · risk_neutral_density — Breeden-Litzenberger ∂²C/∂K² → full implied PDF

and a multi-expiration probability cone.

Conventions
-----------
  · 1σ expected move (dollars) = S · σ · √T, with σ the annualized IV in
    decimal and T the year-fraction to expiry. For 0DTE T comes from
    `bs.time_to_expiry_years` (fractional hours to 16:00 ET).
  · Straddle ↔ 1σ relationship: an ATM straddle pays E[|S_T − K|], which
    for a normal move equals σ_dollar · √(2/π) ≈ 0.7979 · σ_dollar.
    Therefore  1σ_dollar = straddle / 0.7979 = straddle · 1.2533.
    We report BOTH the raw straddle (= the literal "expected move",
    E[|move|]) and the implied 1σ (× 1.2533) so the two senses aren't
    conflated.
  · Risk-neutral density via Breeden-Litzenberger (1978):
        f(K) = e^{rT} · ∂²C/∂K²
    Computed by fitting a smooth IV(K) curve, pricing calls on a fine
    strike grid with Black-Scholes, then taking the discrete second
    difference. Negatives (numerical noise) are clipped and the result
    is normalised to integrate to 1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from quant import bs

# E[|X|] = σ·√(2/π) for X~N(0,σ²)  →  σ = E[|X|] · √(π/2)
_STRADDLE_TO_SIGMA = float(np.sqrt(np.pi / 2.0))   # ≈ 1.2533
_SIGMA_TO_STRADDLE = float(np.sqrt(2.0 / np.pi))   # ≈ 0.7979


def _trapz(y: np.ndarray, x: np.ndarray) -> float:
    """Trapezoidal integral, portable across numpy versions.
    `np.trapz` was removed/renamed to `np.trapezoid` in numpy 2.x, so we
    implement it directly to avoid version-coupling."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    if len(y) < 2:
        return 0.0
    return float(np.sum((y[1:] + y[:-1]) / 2.0 * np.diff(x)))


# ─────────────────────────────────────────────────────────────────────────────
#  Dataclass
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RangeEstimate:
    method: str
    low: float            # 1σ lower bound
    high: float           # 1σ upper bound
    em_dollars: float     # representative ±$ move (avg of up/down legs)
    em_pct: float         # em_dollars / spot × 100
    iv_used: Optional[float]   # IV (%) feeding this estimate, if any
    asymmetric: bool
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
#  Time helper
# ─────────────────────────────────────────────────────────────────────────────
def _years_to_expiry(dte: int, now=None) -> float:
    if dte <= 0:
        return float(bs.time_to_expiry_years(np.array([0]), now=now)[0])
    return float(max(dte, 0)) / 365.0


# ─────────────────────────────────────────────────────────────────────────────
#  Estimator 1 — IV Gaussian
# ─────────────────────────────────────────────────────────────────────────────
def iv_gaussian_em(spot: float, iv_pct: float, T: float) -> Optional[RangeEstimate]:
    if not spot or spot <= 0 or iv_pct is None or iv_pct <= 0 or T <= 0:
        return None
    em = spot * (iv_pct / 100.0) * np.sqrt(T)
    return RangeEstimate(
        method="IV Gaussian",
        low=round(spot - em, 2), high=round(spot + em, 2),
        em_dollars=round(em, 3), em_pct=round(em / spot * 100, 3),
        iv_used=round(iv_pct, 2), asymmetric=False,
        note="spot × IV × √T — modelo lognormal simétrico",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Estimator 2 — Skew-adjusted
# ─────────────────────────────────────────────────────────────────────────────
def skew_em(spot: float, iv_call_pct: float, iv_put_pct: float,
            T: float) -> Optional[RangeEstimate]:
    if (not spot or spot <= 0 or T <= 0
            or iv_call_pct is None or iv_put_pct is None
            or iv_call_pct <= 0 or iv_put_pct <= 0):
        return None
    up = spot * (iv_call_pct / 100.0) * np.sqrt(T)
    dn = spot * (iv_put_pct / 100.0) * np.sqrt(T)
    return RangeEstimate(
        method="Skew-adjusted",
        low=round(spot - dn, 2), high=round(spot + up, 2),
        em_dollars=round((up + dn) / 2.0, 3),
        em_pct=round((up + dn) / 2.0 / spot * 100, 3),
        iv_used=round((iv_call_pct + iv_put_pct) / 2.0, 2),
        asymmetric=abs(iv_call_pct - iv_put_pct) > 0.01,
        note="put-IV abajo · call-IV arriba (rango asimétrico real)",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Estimator 3 — Straddle MMM (market-priced, model-free)
# ─────────────────────────────────────────────────────────────────────────────
def _atm_leg_price(df: pd.DataFrame, spot: float) -> Optional[float]:
    """Mid price of the strike nearest to spot. Falls back through
    Mark → Last → (Bid+Ask)/2."""
    if df is None or df.empty or "Strike" not in df.columns:
        return None
    strikes = pd.to_numeric(df["Strike"], errors="coerce")
    idx = (strikes - spot).abs().idxmin()
    row = df.loc[idx]
    for col in ("Mark", "Last"):
        if col in row and pd.notna(row[col]) and float(row[col]) > 0:
            return float(row[col])
    if "Bid" in row and "Ask" in row:
        b = pd.to_numeric(row["Bid"], errors="coerce")
        a = pd.to_numeric(row["Ask"], errors="coerce")
        if pd.notna(b) and pd.notna(a) and a > 0:
            return float((max(b, 0.0) + a) / 2.0)
    return None


def straddle_em(calls: pd.DataFrame, puts: pd.DataFrame,
                spot: float) -> Optional[RangeEstimate]:
    """Expected move implied by the actual ATM straddle MID price.

    The straddle pays E[|S_T − K|] ≈ 0.7979 · σ_dollar, so the implied
    1σ move is straddle × 1.2533. We report the 1σ band (so it's
    comparable to the other estimators) but note the raw straddle value
    too (the literal 'expected move' = E[|move|]).
    """
    if not spot or spot <= 0:
        return None
    c = _atm_leg_price(calls, spot)
    p = _atm_leg_price(puts, spot)
    if c is None or p is None:
        return None
    straddle = c + p
    if straddle <= 0:
        return None
    em_1sigma = straddle * _STRADDLE_TO_SIGMA
    return RangeEstimate(
        method="Straddle MMM",
        low=round(spot - em_1sigma, 2), high=round(spot + em_1sigma, 2),
        em_dollars=round(em_1sigma, 3),
        em_pct=round(em_1sigma / spot * 100, 3),
        iv_used=None, asymmetric=False,
        note=(f"straddle ${straddle:.2f} × 1.2533 (market-priced, "
              f"E[|move|]=${straddle:.2f})"),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Estimator 4 — Realized vol
# ─────────────────────────────────────────────────────────────────────────────
def realized_em(spot: float, realized_vol_pct: Optional[float],
                T: float) -> Optional[RangeEstimate]:
    """EM from REALIZED vol (what the underlying actually delivered).
    Pass an annualized realized-vol % (e.g. Yang-Zhang HV from
    `quant.vol`). Comparing this band to the IV bands tells you whether
    IV is rich (IV band wider → sell vol) or cheap (narrower → buy vol).
    """
    if (not spot or spot <= 0 or T <= 0
            or realized_vol_pct is None or realized_vol_pct <= 0):
        return None
    em = spot * (realized_vol_pct / 100.0) * np.sqrt(T)
    return RangeEstimate(
        method="Realized vol",
        low=round(spot - em, 2), high=round(spot + em, 2),
        em_dollars=round(em, 3), em_pct=round(em / spot * 100, 3),
        iv_used=round(realized_vol_pct, 2), asymmetric=False,
        note="spot × HV(Yang-Zhang) × √T — lo que el subyacente entregó",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Bundle the four parametric estimators
# ─────────────────────────────────────────────────────────────────────────────
def compare_estimators(
    spot: float, calls: pd.DataFrame, puts: pd.DataFrame,
    iv_call_pct: Optional[float], iv_put_pct: Optional[float],
    realized_vol_pct: Optional[float],
    dte: int = 0, now=None,
) -> tuple[list[RangeEstimate], float]:
    """Return (list_of_RangeEstimate, T_years). Any estimator that can't
    be computed (missing inputs) is skipped, never crashes the bundle."""
    T = _years_to_expiry(dte, now=now)
    iv_blend = None
    if iv_call_pct is not None and iv_put_pct is not None:
        iv_blend = (iv_call_pct + iv_put_pct) / 2.0
    elif iv_call_pct is not None:
        iv_blend = iv_call_pct
    elif iv_put_pct is not None:
        iv_blend = iv_put_pct

    out: list[RangeEstimate] = []
    g = iv_gaussian_em(spot, iv_blend, T) if iv_blend else None
    if g:
        out.append(g)
    if iv_call_pct is not None and iv_put_pct is not None:
        s = skew_em(spot, iv_call_pct, iv_put_pct, T)
        if s:
            out.append(s)
    st = straddle_em(calls, puts, spot)
    if st:
        out.append(st)
    rv = realized_em(spot, realized_vol_pct, T)
    if rv:
        out.append(rv)
    return out, T


# ─────────────────────────────────────────────────────────────────────────────
#  Probability cone over multiple expirations
# ─────────────────────────────────────────────────────────────────────────────
def prob_cone(spot: float, iv_pct: float,
              dtes: tuple[int, ...] = (0, 1, 2, 5),
              sigmas: tuple[float, ...] = (1.0, 2.0),
              now=None) -> pd.DataFrame:
    """Project ±kσ bands at each horizon in `dtes`. Returns long-format
    DataFrame: dte, T_years, sigma, low, high. The widening of the cone
    follows √T."""
    if not spot or spot <= 0 or iv_pct is None or iv_pct <= 0:
        return pd.DataFrame()
    rows = []
    for d in dtes:
        T = _years_to_expiry(int(d), now=now)
        if T <= 0:
            continue
        base = spot * (iv_pct / 100.0) * np.sqrt(T)
        for k in sigmas:
            rows.append({
                "dte": int(d), "T_years": round(T, 6),
                "sigma": float(k),
                "low": round(spot - base * k, 2),
                "high": round(spot + base * k, 2),
                "move": round(base * k, 3),
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
#  Risk-neutral density via Breeden-Litzenberger
# ─────────────────────────────────────────────────────────────────────────────
def _bs_call(S, K, T, sigma, r, q):
    """Vectorized BS call price (sigma in decimal)."""
    S = np.asarray(S, float); K = np.asarray(K, float)
    sigma = np.asarray(sigma, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        c = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return c


def risk_neutral_density(
    calls: pd.DataFrame, spot: float, dte: int = 0,
    r: float = 0.045, q: float = 0.0, now=None,
    grid_points: int = 201, grid_pct: float = 0.10,
) -> Optional[pd.DataFrame]:
    """Extract the implied risk-neutral PDF from the call smile.

    Method (Breeden-Litzenberger, 1978):
      1. Take per-strike call IVs from the chain.
      2. Fit a smooth IV(K) curve (cubic) and sample it on a fine,
         evenly-spaced strike grid — second derivatives are very noisy
         on raw, irregular chain strikes, so smoothing is essential.
      3. Price calls on the grid with Black-Scholes.
      4. f(K) = e^{rT} · d²C/dK²  (discrete second difference).
      5. Clip negatives (residual noise), normalise to integrate to 1.

    Returns DataFrame: strike, pdf, cdf. None if insufficient IV points.
    """
    if calls is None or calls.empty or not spot or spot <= 0:
        return None
    need = {"Strike", "IV%"}
    if not need.issubset(calls.columns):
        return None
    df = calls[["Strike", "IV%"]].copy()
    df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
    df["IV%"] = pd.to_numeric(df["IV%"], errors="coerce")
    df = df.dropna()
    df = df[(df["IV%"] > 0) & (df["IV%"] < 1000)]
    df = df.groupby("Strike", as_index=False)["IV%"].mean().sort_values("Strike")
    if len(df) < 5:
        return None

    T = _years_to_expiry(int(dte), now=now)
    if T <= 0:
        return None

    K = df["Strike"].to_numpy(dtype=float)
    iv = df["IV%"].to_numpy(dtype=float) / 100.0

    # Restrict the grid to ±grid_pct around spot where the smile is
    # well-defined (far wings have unreliable IV in 0DTE).
    lo = spot * (1 - grid_pct)
    hi = spot * (1 + grid_pct)
    grid = np.linspace(lo, hi, grid_points)

    # Smooth IV onto the grid. Prefer a cubic spline; fall back to numpy
    # linear interp if scipy isn't available or the fit fails.
    try:
        from scipy.interpolate import UnivariateSpline
        # Light smoothing factor proportional to the IV scale × n.
        s_factor = max(len(K) * 0.5, 1.0) * float(np.nanvar(iv)) * 0.5
        spline = UnivariateSpline(K, iv, k=3, s=s_factor, ext=3)
        iv_grid = spline(grid)
    except Exception:
        iv_grid = np.interp(grid, K, iv)
    iv_grid = np.clip(iv_grid, 1e-4, None)

    # Price calls on the grid, then second finite difference.
    c = _bs_call(spot, grid, T, iv_grid, r, q)
    dK = grid[1] - grid[0]
    second = np.full_like(c, np.nan)
    second[1:-1] = (c[2:] - 2.0 * c[1:-1] + c[:-2]) / (dK ** 2)
    pdf = np.exp(r * T) * second
    pdf = np.where(np.isfinite(pdf), pdf, 0.0)
    pdf = np.clip(pdf, 0.0, None)  # densities are non-negative

    area = _trapz(pdf, grid)
    if area <= 0:
        return None
    pdf = pdf / area
    cdf = np.cumsum(pdf) * dK
    cdf = np.clip(cdf / cdf[-1], 0.0, 1.0) if cdf[-1] > 0 else cdf

    return pd.DataFrame({"strike": grid, "pdf": pdf, "cdf": cdf})


def rnd_stats(rnd: pd.DataFrame, spot: float,
              levels: Optional[dict] = None) -> dict:
    """Summary statistics of a risk-neutral density:
       · mean, std, skewness, excess kurtosis of the implied distribution
       · P(S_T < level) for each level in `levels` (e.g. put_wall, etc.)
    Compares skew/kurtosis to the lognormal baseline (kurtosis 0 = normal).
    """
    if rnd is None or rnd.empty:
        return {}
    k = rnd["strike"].to_numpy()
    p = rnd["pdf"].to_numpy()
    dk = k[1] - k[0]
    mean = float(np.sum(k * p) * dk)
    var = float(np.sum((k - mean) ** 2 * p) * dk)
    std = float(np.sqrt(max(var, 0.0)))
    if std > 0:
        skew = float(np.sum(((k - mean) / std) ** 3 * p) * dk)
        kurt = float(np.sum(((k - mean) / std) ** 4 * p) * dk) - 3.0
    else:
        skew = kurt = 0.0

    out = {
        "mean": round(mean, 2),
        "std": round(std, 2),
        "std_pct": round(std / spot * 100, 2) if spot else None,
        "skew": round(skew, 3),
        "excess_kurtosis": round(kurt, 3),
        "level_probs": {},
    }
    if levels:
        cdf = rnd["cdf"].to_numpy()
        for name, lvl in levels.items():
            if lvl is None:
                continue
            try:
                lvl = float(lvl)
            except (TypeError, ValueError):
                continue
            # P(S_T < lvl) via interpolation of the CDF
            p_below = float(np.interp(lvl, k, cdf, left=0.0, right=1.0))
            out["level_probs"][name] = {
                "level": round(lvl, 2),
                "p_below": round(p_below, 4),
                "p_above": round(1.0 - p_below, 4),
            }
    return out
