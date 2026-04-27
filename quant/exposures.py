"""
Dealer exposures — GEX / VEX / CEX / DEX.

Convention (SqueezeMetrics / GEXbot): dealer is long calls, short puts.
  GEX(k) = Γ(k) × OI(k) × 100 × S² × 0.01 × sign(k)   — $ hedge per 1% move
  VEX(k) = Vanna(k) × OI(k) × 100 × S × 0.01 × sign(k) — $ hedge per +1 vol pt
  CEX(k) = Charm(k) × OI(k) × 100 × S × sign(k)       — $ hedge per 1 calendar day
  DEX(k) = Δ(k) × OI(k) × 100 × S                     — directional bias

Important fixes vs legacy:
  - IV filter uses MIN_IV_PCT (≥1%) rather than 0.01
  - Time to expiry via bs.time_to_expiry_years (intraday 0DTE)
  - Rate from curve interpolation
  - Dividend yield q per symbol
  - Gamma flip computed on a *spot grid* (true SqueezeMetrics semantics)
  - Walls found as smoothed local extrema (not raw argmax)
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from config import MIN_IV_PCT, dividend_yield_for
from quant import bs


# ─────────────────────────────────────────────────────────────────────────────
#  Filters
# ─────────────────────────────────────────────────────────────────────────────
def filter_chain(df: pd.DataFrame, max_dte: int = 60, min_oi: int = 0,
                 require_iv: bool = False) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    required = ["Strike", "OI", "Gamma"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame()
    out = df.copy()
    out = out[out["OI"] > min_oi]
    if "DTE" in out.columns:
        out = out[out["DTE"] <= max_dte]
    out = out.dropna(subset=["Strike", "Gamma"])
    out = out[out["Gamma"] > 0]
    if require_iv:
        if "IV%" not in out.columns or "DTE" not in out.columns:
            return pd.DataFrame()
        out = out[out["IV%"].notna() & (out["IV%"] > MIN_IV_PCT)]
    return out.reset_index(drop=True)


def _group_strike(strike_arr: np.ndarray, val_arr: np.ndarray,
                  col_name: str) -> pd.DataFrame:
    if len(strike_arr) == 0:
        return pd.DataFrame(columns=["Strike", col_name])
    df = pd.DataFrame({"Strike": strike_arr, col_name: val_arr})
    return df.groupby("Strike", as_index=False)[col_name].sum()


# ─────────────────────────────────────────────────────────────────────────────
#  Walls — smoothed peak detection
# ─────────────────────────────────────────────────────────────────────────────
def _smooth(y: np.ndarray, win: int = 3) -> np.ndarray:
    if len(y) <= win:
        return y.copy()
    w = np.ones(win) / win
    return np.convolve(y, w, mode="same")


def _find_wall(strikes: np.ndarray, values: np.ndarray,
               sign: int = 1) -> Optional[float]:
    """Find the strike with the most extreme (sign * value) after smoothing.

    Returns None if no candidate exceeds 50% of the max |extreme|."""
    if len(strikes) == 0:
        return None
    series = sign * values
    smooth = _smooth(series, 3)
    idx = int(np.argmax(smooth))
    if smooth[idx] <= 0:
        return None
    # Robustness check: the peak must be meaningful
    peak = smooth[idx]
    if peak < 0.5 * np.max(np.abs(smooth)):
        return None
    return float(strikes[idx])


# ─────────────────────────────────────────────────────────────────────────────
#  Gamma flip — compute Γ-exposure as a function of a hypothetical spot S',
#  then locate the zero crossing. True SqueezeMetrics semantics.
# ─────────────────────────────────────────────────────────────────────────────
def gamma_flip_on_spot_grid(
    calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
    symbol: str = "", max_dte: int = 60, min_oi: int = 0,
    grid_pct: float = 0.10, n_points: int = 81,
) -> Optional[float]:
    """Re-price each option's Γ on a grid of hypothetical S', aggregate GEX(S'),
    and return the S' where the aggregate crosses zero.

    Requires IV% and DTE (so we can recompute γ). Falls back to None otherwise.
    """
    c = filter_chain(calls, max_dte=max_dte, min_oi=min_oi, require_iv=True)
    p = filter_chain(puts, max_dte=max_dte, min_oi=min_oi, require_iv=True)
    if c.empty and p.empty:
        return None

    q = dividend_yield_for(symbol)
    S_grid = np.linspace(spot * (1 - grid_pct), spot * (1 + grid_pct), n_points)
    gex_curve = np.zeros_like(S_grid)

    for df, sign in ((c, +1.0), (p, -1.0)):
        if df.empty:
            continue
        K = df["Strike"].to_numpy(dtype=float)
        iv = df["IV%"].to_numpy(dtype=float) / 100.0
        dte = df["DTE"].to_numpy(dtype=float)
        oi = df["OI"].to_numpy(dtype=float)
        T = bs.time_to_expiry_years(dte)
        r = bs.rate_for_dte(dte)
        # Broadcast: S_grid (G,) vs strikes (N,)
        S_b = S_grid[:, None]
        g = bs.gamma(S_b, K[None, :], T[None, :], iv[None, :], r[None, :], q)
        # GEX contribution per point: gamma × OI × 100 × S'² × 0.01 × sign
        contrib = g * oi[None, :] * 100.0 * (S_b ** 2) * 0.01 * sign
        gex_curve += contrib.sum(axis=1)

    # Find sign change nearest to spot
    sign_arr = np.sign(gex_curve)
    changes = np.where(np.diff(sign_arr) != 0)[0]
    if len(changes) == 0:
        return None
    # Pick the crossing closest to current spot
    spot_idx = int(np.argmin(np.abs(S_grid - spot)))
    best = min(changes, key=lambda i: abs(i - spot_idx))
    y0, y1 = gex_curve[best], gex_curve[best + 1]
    x0, x1 = S_grid[best], S_grid[best + 1]
    if y1 == y0:
        return float(x0)
    # Linear interpolation for precise zero
    return float(x0 - y0 * (x1 - x0) / (y1 - y0))


# ─────────────────────────────────────────────────────────────────────────────
#  GEX profile
# ─────────────────────────────────────────────────────────────────────────────
def compute_gex_profile(
    calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
    symbol: str = "", max_dte: int = 60, min_oi: int = 0,
    use_spot_grid_flip: bool = True,
) -> Tuple[pd.DataFrame, dict]:
    if spot <= 0:
        return pd.DataFrame(), {}
    c = filter_chain(calls, max_dte=max_dte, min_oi=min_oi)
    p = filter_chain(puts, max_dte=max_dte, min_oi=min_oi)
    if c.empty and p.empty:
        return pd.DataFrame(), {}

    SCALE = 100.0 * spot * spot * 0.01

    c_gex = (c["Gamma"].to_numpy() * c["OI"].to_numpy() * SCALE * (+1.0)
             if not c.empty else np.array([]))
    p_gex = (p["Gamma"].to_numpy() * p["OI"].to_numpy() * SCALE * (-1.0)
             if not p.empty else np.array([]))

    c_g = _group_strike(c["Strike"].to_numpy() if not c.empty else np.array([]),
                        c_gex, "C_GEX")
    p_g = _group_strike(p["Strike"].to_numpy() if not p.empty else np.array([]),
                        p_gex, "P_GEX")

    df = c_g.merge(p_g, on="Strike", how="outer").fillna(0.0).sort_values("Strike")
    df["Net_GEX"] = df["C_GEX"] + df["P_GEX"]
    df["Abs_GEX"] = df["Net_GEX"].abs()
    df["CumGEX"] = df["Net_GEX"].cumsum()
    df = df.reset_index(drop=True)

    total = float(df["Net_GEX"].sum())
    call_tot = float(df["C_GEX"].sum())
    put_tot = float(df["P_GEX"].sum())

    # Gamma flip: spot-grid (proper) with strike-cumulative fallback
    flip = None
    if use_spot_grid_flip:
        flip = gamma_flip_on_spot_grid(calls, puts, spot, symbol=symbol,
                                       max_dte=max_dte, min_oi=min_oi)
    if flip is None:
        cum = df["CumGEX"].to_numpy()
        stk = df["Strike"].to_numpy()
        for i in range(1, len(cum)):
            if cum[i - 1] * cum[i] < 0:
                denom = abs(cum[i - 1]) + abs(cum[i]) + 1e-12
                w = abs(cum[i - 1]) / denom
                flip = float(stk[i - 1] + (stk[i] - stk[i - 1]) * w)
                break

    # Walls — smoothed peak detection instead of raw argmax
    strikes_np = df["Strike"].to_numpy()
    net_np = df["Net_GEX"].to_numpy()
    call_wall = _find_wall(strikes_np, net_np, sign=+1)
    put_wall = _find_wall(strikes_np, net_np, sign=-1)

    hvl = float(df.loc[df["Abs_GEX"].idxmax(), "Strike"]) if not df.empty else None

    if total > 1e3:
        regime = "POSITIVE"
    elif total < -1e3:
        regime = "NEGATIVE"
    else:
        regime = "NEUTRAL"
    flip_pct = ((flip - spot) / spot * 100) if flip else None

    summary = dict(
        regime=regime,
        total_gex=total,
        call_gex=call_tot,
        put_gex=put_tot,
        gamma_flip=flip,
        flip_pct=flip_pct,
        call_wall=call_wall,
        put_wall=put_wall,
        hvl=hvl,
        n_strikes=int(len(df)),
        max_dte=max_dte,
    )
    return df, summary


# ─────────────────────────────────────────────────────────────────────────────
#  VEX
# ─────────────────────────────────────────────────────────────────────────────
def compute_vex_profile(calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
                        symbol: str = "", max_dte: int = 60,
                        min_oi: int = 0) -> Tuple[pd.DataFrame, dict]:
    if spot <= 0:
        return pd.DataFrame(), {}
    c = filter_chain(calls, max_dte=max_dte, min_oi=min_oi, require_iv=True)
    p = filter_chain(puts, max_dte=max_dte, min_oi=min_oi, require_iv=True)
    if c.empty and p.empty:
        return pd.DataFrame(), {}

    q = dividend_yield_for(symbol)
    SCALE = 100.0 * spot * 0.01

    def _per_side(df: pd.DataFrame, sign: float) -> tuple[np.ndarray, np.ndarray]:
        if df.empty:
            return np.array([]), np.array([])
        K = df["Strike"].to_numpy(dtype=float)
        iv = df["IV%"].to_numpy(dtype=float) / 100.0
        dte = df["DTE"].to_numpy(dtype=float)
        T = bs.time_to_expiry_years(dte)
        r = bs.rate_for_dte(dte)
        v = bs.vanna(spot, K, T, iv, r, q)
        vex = v * df["OI"].to_numpy(dtype=float) * SCALE * sign
        return K, vex

    cK, cV = _per_side(c, +1.0)
    pK, pV = _per_side(p, -1.0)

    c_g = _group_strike(cK, cV, "C_VEX")
    p_g = _group_strike(pK, pV, "P_VEX")

    df = c_g.merge(p_g, on="Strike", how="outer").fillna(0.0).sort_values("Strike")
    df["Net_VEX"] = df["C_VEX"] + df["P_VEX"]
    df["Abs_VEX"] = df["Net_VEX"].abs()
    df = df.reset_index(drop=True)

    total = float(df["Net_VEX"].sum())
    summary = dict(
        total_vex=total,
        call_vex=float(df["C_VEX"].sum()),
        put_vex=float(df["P_VEX"].sum()),
        regime="LONG_VANNA" if total > 0 else ("SHORT_VANNA" if total < 0 else "NEUTRAL"),
        max_dte=max_dte,
    )
    return df, summary


# ─────────────────────────────────────────────────────────────────────────────
#  CEX
# ─────────────────────────────────────────────────────────────────────────────
def compute_cex_profile(calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
                        symbol: str = "", max_dte: int = 60,
                        min_oi: int = 0) -> Tuple[pd.DataFrame, dict]:
    if spot <= 0:
        return pd.DataFrame(), {}
    c = filter_chain(calls, max_dte=max_dte, min_oi=min_oi, require_iv=True)
    p = filter_chain(puts, max_dte=max_dte, min_oi=min_oi, require_iv=True)
    if c.empty and p.empty:
        return pd.DataFrame(), {}

    q = dividend_yield_for(symbol)
    SCALE = 100.0 * spot

    def _per_side(df: pd.DataFrame, sign: float) -> tuple[np.ndarray, np.ndarray]:
        if df.empty:
            return np.array([]), np.array([])
        K = df["Strike"].to_numpy(dtype=float)
        iv = df["IV%"].to_numpy(dtype=float) / 100.0
        dte = df["DTE"].to_numpy(dtype=float)
        T = bs.time_to_expiry_years(dte)
        r = bs.rate_for_dte(dte)
        ch = bs.charm(spot, K, T, iv, r, q, per="day")
        cex = ch * df["OI"].to_numpy(dtype=float) * SCALE * sign
        return K, cex

    cK, cV = _per_side(c, +1.0)
    pK, pV = _per_side(p, -1.0)

    c_g = _group_strike(cK, cV, "C_CEX")
    p_g = _group_strike(pK, pV, "P_CEX")

    df = c_g.merge(p_g, on="Strike", how="outer").fillna(0.0).sort_values("Strike")
    df["Net_CEX"] = df["C_CEX"] + df["P_CEX"]
    df["Abs_CEX"] = df["Net_CEX"].abs()
    df = df.reset_index(drop=True)

    total = float(df["Net_CEX"].sum())
    summary = dict(
        total_cex=total,
        call_cex=float(df["C_CEX"].sum()),
        put_cex=float(df["P_CEX"].sum()),
        regime="POS_CHARM" if total > 0 else ("NEG_CHARM" if total < 0 else "NEUTRAL"),
        max_dte=max_dte,
    )
    return df, summary


# ─────────────────────────────────────────────────────────────────────────────
#  DEX
# ─────────────────────────────────────────────────────────────────────────────
def compute_dex_profile(calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
                        max_dte: int = 60, min_oi: int = 0,
                        ) -> Tuple[pd.DataFrame, dict]:
    if spot <= 0:
        return pd.DataFrame(), {}

    def _prep(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty or "Delta" not in df.columns:
            return pd.DataFrame()
        d = df.copy()
        if "DTE" in d.columns:
            d = d[d["DTE"] <= max_dte]
        d = d[d["OI"] > min_oi]
        return d.dropna(subset=["Strike", "Delta"])

    c = _prep(calls)
    p = _prep(puts)
    if c.empty and p.empty:
        return pd.DataFrame(), {}

    SCALE = 100.0 * spot
    c_d = (c["Delta"].clip(0, 1).to_numpy() * c["OI"].to_numpy() * SCALE
           if not c.empty else np.array([]))
    p_d = (p["Delta"].clip(-1, 0).to_numpy() * p["OI"].to_numpy() * SCALE
           if not p.empty else np.array([]))

    c_g = _group_strike(c["Strike"].to_numpy() if not c.empty else np.array([]),
                        c_d, "C_DEX")
    p_g = _group_strike(p["Strike"].to_numpy() if not p.empty else np.array([]),
                        p_d, "P_DEX")

    df = c_g.merge(p_g, on="Strike", how="outer").fillna(0.0).sort_values("Strike")
    df["Net_DEX"] = df["C_DEX"] + df["P_DEX"]
    df = df.reset_index(drop=True)

    total = float(df["Net_DEX"].sum())
    bias = "CALL-HEAVY" if total > 0 else ("PUT-HEAVY" if total < 0 else "NEUTRAL")
    summary = dict(
        total_dex=total,
        call_dex=float(df["C_DEX"].sum()),
        put_dex=float(df["P_DEX"].sum()),
        bias=bias,
    )
    return df, summary


# ─────────────────────────────────────────────────────────────────────────────
#  GEX by expiry
# ─────────────────────────────────────────────────────────────────────────────
def compute_gex_by_expiry(calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
                          max_dte: int = 60, min_oi: int = 0) -> pd.DataFrame:
    if spot <= 0 or (calls.empty and puts.empty):
        return pd.DataFrame()
    c = filter_chain(calls, max_dte=max_dte, min_oi=min_oi)
    p = filter_chain(puts, max_dte=max_dte, min_oi=min_oi)
    if c.empty and p.empty:
        return pd.DataFrame()

    SCALE = 100.0 * spot * spot * 0.01
    rows: list[dict] = []
    exps = sorted(set(
        (c["Expiry"].tolist() if "Expiry" in c.columns else []) +
        (p["Expiry"].tolist() if "Expiry" in p.columns else [])
    ))
    for exp in exps:
        ce = c[c["Expiry"] == exp] if not c.empty else pd.DataFrame()
        pe = p[p["Expiry"] == exp] if not p.empty else pd.DataFrame()
        c_g = (ce["Gamma"] * ce["OI"]).sum() * SCALE if not ce.empty else 0.0
        p_g = (pe["Gamma"] * pe["OI"]).sum() * SCALE * (-1.0) if not pe.empty else 0.0
        dte_val = 0
        for d in (ce, pe):
            if not d.empty and "DTE" in d.columns:
                try:
                    dte_val = int(d["DTE"].iloc[0])
                    break
                except Exception:
                    pass
        rows.append({
            "Expiry": exp, "DTE": dte_val,
            "Call_GEX_M": c_g / 1e6,
            "Put_GEX_M": p_g / 1e6,
            "Net_GEX_M": (c_g + p_g) / 1e6,
        })
    if not rows:
        return pd.DataFrame(columns=["Expiry", "DTE", "Call_GEX_M",
                                     "Put_GEX_M", "Net_GEX_M"])
    return pd.DataFrame(rows).sort_values("DTE").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  GEX curve over spot grid (for scenario chart)
# ─────────────────────────────────────────────────────────────────────────────
def gex_curve_over_spot(calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
                        symbol: str = "", max_dte: int = 60, min_oi: int = 0,
                        grid_pct: float = 0.10, n_points: int = 81
                        ) -> pd.DataFrame:
    c = filter_chain(calls, max_dte=max_dte, min_oi=min_oi, require_iv=True)
    p = filter_chain(puts, max_dte=max_dte, min_oi=min_oi, require_iv=True)
    if c.empty and p.empty:
        return pd.DataFrame()
    q = dividend_yield_for(symbol)
    S_grid = np.linspace(spot * (1 - grid_pct), spot * (1 + grid_pct), n_points)
    gex_curve = np.zeros_like(S_grid)
    for df, sign in ((c, +1.0), (p, -1.0)):
        if df.empty:
            continue
        K = df["Strike"].to_numpy(dtype=float)
        iv = df["IV%"].to_numpy(dtype=float) / 100.0
        dte = df["DTE"].to_numpy(dtype=float)
        oi = df["OI"].to_numpy(dtype=float)
        T = bs.time_to_expiry_years(dte)
        r = bs.rate_for_dte(dte)
        S_b = S_grid[:, None]
        g = bs.gamma(S_b, K[None, :], T[None, :], iv[None, :], r[None, :], q)
        contrib = g * oi[None, :] * 100.0 * (S_b ** 2) * 0.01 * sign
        gex_curve += contrib.sum(axis=1)
    return pd.DataFrame({"Spot": S_grid, "GEX": gex_curve})


# ─────────────────────────────────────────────────────────────────────────────
#  Second-order greeks
# ─────────────────────────────────────────────────────────────────────────────
def compute_second_order_greeks(df: pd.DataFrame, spot: float,
                                symbol: str = "") -> pd.DataFrame:
    if df is None or df.empty:
        return df
    required = {"Strike", "IV%", "DTE"}
    if not required.issubset(df.columns):
        return df
    q = dividend_yield_for(symbol)
    out = df.copy()
    K = out["Strike"].to_numpy(dtype=float)
    iv = out["IV%"].to_numpy(dtype=float) / 100.0
    dte = out["DTE"].to_numpy(dtype=float)
    T = bs.time_to_expiry_years(dte)
    r = bs.rate_for_dte(dte)
    out["Vanna"] = bs.vanna(spot, K, T, iv, r, q).round(6)
    out["Charm"] = bs.charm(spot, K, T, iv, r, q, per="day").round(6)
    return out
