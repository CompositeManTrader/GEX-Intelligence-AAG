"""
Key-level analytics:
  - Max pain (O(N^2) vectorized)
  - Put/Call ratio (OI-based; pass volumes if you want a sentiment variant)
  - ATM IV (linear interp on two strikes straddling spot)
  - Expected move
  - IV skew — both absolute (P_IV − C_IV by strike) and 25Δ risk-reversal
  - Term structure — ATM IV per expiry (interpolated)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from config import CALENDAR_DAYS, MIN_IV_PCT


# ─────────────────────────────────────────────────────────────────────────────
def max_pain(c: pd.DataFrame, p: pd.DataFrame) -> Optional[float]:
    if c is None or p is None or c.empty or p.empty or "OI" not in c.columns:
        return None
    all_strikes = sorted(set(c["Strike"].tolist() + p["Strike"].tolist()))
    if not all_strikes:
        return None
    strikes = np.array(all_strikes, dtype=float)
    co = c.set_index("Strike")["OI"].reindex(strikes, fill_value=0).to_numpy(dtype=float)
    po = p.set_index("Strike")["OI"].reindex(strikes, fill_value=0).to_numpy(dtype=float)
    diff_call = np.maximum(0.0, strikes[:, None] - strikes[None, :])
    diff_put = np.maximum(0.0, strikes[None, :] - strikes[:, None])
    pain = diff_call @ co + diff_put @ po
    return float(strikes[int(np.argmin(pain))])


def put_call_ratio(c: pd.DataFrame, p: pd.DataFrame,
                   field: str = "OI") -> Optional[float]:
    if c is None or p is None or c.empty or p.empty or field not in c.columns:
        return None
    tot = float(c[field].sum())
    return round(float(p[field].sum()) / tot, 2) if tot > 0 else None


def _interp_iv_one_side(df: pd.DataFrame, spot: float) -> Optional[float]:
    """Linear-interp IV at K=spot on the nearest expiry of one side (calls or puts)."""
    if df is None or df.empty or "IV%" not in df.columns:
        return None
    valid = df[df["IV%"].notna() & (df["IV%"] > MIN_IV_PCT)].copy()
    if valid.empty:
        return None
    if "DTE" in valid.columns:
        # Pick the genuinely nearest expiry — the smallest non-negative DTE.
        # Previous code picked the DTE of the row whose strike was nearest
        # to spot, which is non-deterministic when several expiries share
        # the same strike grid.
        non_neg = valid[valid["DTE"] >= 0]
        if not non_neg.empty:
            nearest_dte = float(non_neg["DTE"].min())
            valid = valid[valid["DTE"] == nearest_dte]
        if valid.empty:
            return None
    valid = valid.sort_values("Strike")
    below = valid[valid["Strike"] <= spot]
    above = valid[valid["Strike"] >= spot]
    if below.empty or above.empty:
        idx = (valid["Strike"] - spot).abs().idxmin()
        return float(valid.loc[idx, "IV%"])
    k_lo = float(below.iloc[-1]["Strike"])
    k_hi = float(above.iloc[0]["Strike"])
    iv_lo = float(below.iloc[-1]["IV%"])
    iv_hi = float(above.iloc[0]["IV%"])
    if k_hi == k_lo:
        return float(iv_lo)
    w = (spot - k_lo) / (k_hi - k_lo)
    return float(iv_lo + w * (iv_hi - iv_lo))


def atm_iv_interp(c: pd.DataFrame, spot: float,
                  p: Optional[pd.DataFrame] = None) -> Optional[float]:
    """Linear interpolation of IV at K=spot using the two nearest strikes.

    If `p` (puts) is provided, the ATM IV is the average of the call-side
    and put-side ATM interpolations (the OCC convention). This removes the
    bias caused by ignoring put-side IV when call-side liquidity is thin.
    """
    if spot <= 0:
        return None
    iv_c = _interp_iv_one_side(c, spot)
    iv_p = _interp_iv_one_side(p, spot) if p is not None else None
    vals = [v for v in (iv_c, iv_p) if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def expected_move(spot: float, iv_pct: Optional[float],
                  dte: int) -> tuple[Optional[float], Optional[float]]:
    """1σ expected move band [spot − σ, spot + σ] where
    σ = spot · IV · √T, IV in decimal.

    For DTE > 0 the legacy formula √(dte/365) works fine. For DTE == 0
    that collapses to zero (sqrt(0) = 0) and the band degenerates to
    [spot, spot] — the bug the user reported. We delegate to
    `bs.time_to_expiry_years` which has the fractional-hours-to-close
    logic so 0DTE bands actually have width.
    """
    if not spot or not iv_pct or dte is None:
        return None, None
    if dte <= 0:
        # Lazy import to keep this module dependency-light when the BS
        # path isn't needed (multi-DTE callers don't pay for it).
        from quant import bs
        T = float(bs.time_to_expiry_years(np.array([0]))[0])
    else:
        T = float(max(dte, 0)) / CALENDAR_DAYS
    move = spot * (iv_pct / 100.0) * np.sqrt(T)
    return round(spot - move, 2), round(spot + move, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  Skew — absolute + 25Δ risk reversal
# ─────────────────────────────────────────────────────────────────────────────
def iv_skew(c: pd.DataFrame, p: pd.DataFrame, spot: float) -> pd.DataFrame:
    """Put IV − Call IV by shared strike (legacy)."""
    if c is None or p is None or c.empty or p.empty:
        return pd.DataFrame()
    need = {"IV%", "Strike"}
    if not need.issubset(c.columns) or not need.issubset(p.columns):
        return pd.DataFrame()
    c2 = c[["Strike", "IV%"] + (["DTE"] if "DTE" in c.columns else [])].copy()
    p2 = p[["Strike", "IV%"] + (["DTE"] if "DTE" in p.columns else [])].copy()
    for df in (c2, p2):
        df["IV%"] = pd.to_numeric(df["IV%"], errors="coerce")
        df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
        if "DTE" in df.columns:
            df["DTE"] = pd.to_numeric(df["DTE"], errors="coerce").fillna(9999)
    c2 = c2[c2["IV%"].notna() & (c2["IV%"] > MIN_IV_PCT)].dropna(subset=["Strike"])
    p2 = p2[p2["IV%"].notna() & (p2["IV%"] > MIN_IV_PCT)].dropna(subset=["Strike"])
    if c2.empty or p2.empty:
        return pd.DataFrame()
    if "DTE" in c2.columns and "DTE" in p2.columns:
        c_near = c2.sort_values("DTE").groupby("Strike")["IV%"].first().reset_index()
        p_near = p2.sort_values("DTE").groupby("Strike")["IV%"].first().reset_index()
    else:
        c_near = c2.groupby("Strike")["IV%"].mean().reset_index()
        p_near = p2.groupby("Strike")["IV%"].mean().reset_index()
    c_near.columns = ["Strike", "C_IV"]
    p_near.columns = ["Strike", "P_IV"]
    skew = c_near.merge(p_near, on="Strike", how="inner").dropna()
    if skew.empty:
        return pd.DataFrame()
    skew["Skew"] = skew["P_IV"] - skew["C_IV"]
    atm_idx = (skew["Strike"] - spot).abs().idxmin()
    atm_iv_val = (skew.loc[atm_idx, "C_IV"] + skew.loc[atm_idx, "P_IV"]) / 2
    skew["Moneyness"] = ((skew["Strike"] - spot) / spot * 100).round(2)
    if atm_iv_val > 0:
        skew["Skew_norm"] = (skew["Skew"] / atm_iv_val * 100).round(2)
    return skew.sort_values("Strike").reset_index(drop=True)


def risk_reversal_25d(c: pd.DataFrame, p: pd.DataFrame) -> Optional[float]:
    """25Δ risk reversal = IV(25Δ put) − IV(25Δ call).

    Works on the shortest expiry available and uses the *nearest* delta each
    side. Returns IV points (e.g. 3.2 == 3.2 vol points higher on puts)."""
    if c is None or p is None or c.empty or p.empty:
        return None
    need = {"Delta", "IV%"}
    if not need.issubset(c.columns) or not need.issubset(p.columns):
        return None
    dte_col = "DTE" if "DTE" in c.columns else None
    if dte_col:
        # Restrict to non-expired tenors BEFORE taking the nearest expiry —
        # a stale/expired row with DTE<0 would otherwise be picked as the
        # "shortest" expiry (model-validation finding).
        c = c[c[dte_col] >= 0]
        p = p[p[dte_col] >= 0]
        if c.empty or p.empty:
            return None
        nearest_dte = int(c[dte_col].min())
        c = c[c[dte_col] == nearest_dte]
        p = p[p[dte_col] == nearest_dte]
    c = c[c["IV%"].notna() & (c["IV%"] > MIN_IV_PCT) & c["Delta"].notna()]
    p = p[p["IV%"].notna() & (p["IV%"] > MIN_IV_PCT) & p["Delta"].notna()]
    if c.empty or p.empty:
        return None
    # Calls: Δ in [0,1], target 0.25. Puts: Δ in [-1,0], target -0.25.
    c_idx = (c["Delta"] - 0.25).abs().idxmin()
    p_idx = (p["Delta"] + 0.25).abs().idxmin()
    iv_call = float(c.loc[c_idx, "IV%"])
    iv_put = float(p.loc[p_idx, "IV%"])
    return round(iv_put - iv_call, 2)


# ─────────────────────────────────────────────────────────────────────────────
def term_structure(c_all: pd.DataFrame, spot: float,
                   p_all: pd.DataFrame | None = None) -> pd.DataFrame:
    """ATM IV per expiry (linear interp at K=spot on each side, then averaged)."""
    if c_all is None or c_all.empty or "IV%" not in c_all.columns or "Expiry" not in c_all.columns:
        return pd.DataFrame()
    rows: list[dict] = []
    p_groups: dict = {}
    if p_all is not None and not p_all.empty and "Expiry" in p_all.columns:
        p_groups = {exp: g for exp, g in p_all.groupby("Expiry")}

    def _interp_atm(df: pd.DataFrame) -> Optional[float]:
        df = df.copy()
        df["IV%"] = pd.to_numeric(df["IV%"], errors="coerce")
        df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
        df = df.dropna(subset=["IV%", "Strike"])
        df = df[df["IV%"] > MIN_IV_PCT]
        if df.empty:
            return None
        df = df.sort_values("Strike")
        below = df[df["Strike"] <= spot]
        above = df[df["Strike"] >= spot]
        if below.empty or above.empty:
            idx = (df["Strike"] - spot).abs().idxmin()
            return float(df.loc[idx, "IV%"])
        k_lo = float(below.iloc[-1]["Strike"])
        k_hi = float(above.iloc[0]["Strike"])
        iv_lo = float(below.iloc[-1]["IV%"])
        iv_hi = float(above.iloc[0]["IV%"])
        if k_hi == k_lo:
            return iv_lo
        w = (spot - k_lo) / (k_hi - k_lo)
        return iv_lo + w * (iv_hi - iv_lo)

    for exp, grp in c_all.groupby("Expiry"):
        # Defensive DTE extraction: works even if column missing or all-NaN.
        if "DTE" in grp.columns and not grp["DTE"].dropna().empty:
            dte_val = int(float(grp["DTE"].dropna().iloc[0]))
        else:
            dte_val = 0
        atm_c = _interp_atm(grp)
        atm_p = _interp_atm(p_groups[exp]) if exp in p_groups else None
        if atm_c is None:
            continue
        atm = (atm_c + atm_p) / 2.0 if atm_p is not None else atm_c
        if atm > 0:
            rows.append({"Expiry": exp, "DTE": dte_val, "ATM_IV": round(float(atm), 2)})
    if not rows:
        return pd.DataFrame(columns=["Expiry", "DTE", "ATM_IV"])
    return pd.DataFrame(rows).sort_values("DTE").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Volatility smile — single-expiry, calls+puts with market-smile (OTM blend)
# ─────────────────────────────────────────────────────────────────────────────
def iv_smile_by_expiry(c_all: pd.DataFrame, p_all: pd.DataFrame,
                       spot: float, expiry: Optional[str]) -> pd.DataFrame:
    """Volatility smile for one expiry.

    Returns columns: Strike, Moneyness (%), C_IV, P_IV, Market_IV, LogK
    - Market_IV uses OTM puts (K<S) and OTM calls (K>=S), the convention
      used by exchanges and vendors like gexbot/OVX.
    """
    if c_all is None or p_all is None or c_all.empty or p_all.empty:
        return pd.DataFrame()
    if "Expiry" not in c_all.columns or "Expiry" not in p_all.columns:
        return pd.DataFrame()
    if expiry is None:
        # Pick the nearest expiry
        try:
            expiry = c_all.sort_values("DTE").iloc[0]["Expiry"]
        except Exception:
            return pd.DataFrame()
    c = c_all[c_all["Expiry"] == expiry].copy()
    p = p_all[p_all["Expiry"] == expiry].copy()
    if c.empty or p.empty or "IV%" not in c.columns or "IV%" not in p.columns:
        return pd.DataFrame()
    for d in (c, p):
        d["IV%"] = pd.to_numeric(d["IV%"], errors="coerce")
        d["Strike"] = pd.to_numeric(d["Strike"], errors="coerce")
    c = c[c["IV%"].notna() & (c["IV%"] > MIN_IV_PCT)].dropna(subset=["Strike"])
    p = p[p["IV%"].notna() & (p["IV%"] > MIN_IV_PCT)].dropna(subset=["Strike"])
    if c.empty or p.empty:
        return pd.DataFrame()
    c = c.groupby("Strike", as_index=False)["IV%"].mean().rename(columns={"IV%": "C_IV"})
    p = p.groupby("Strike", as_index=False)["IV%"].mean().rename(columns={"IV%": "P_IV"})
    sm = c.merge(p, on="Strike", how="outer").sort_values("Strike")
    sm["Moneyness"] = ((sm["Strike"] - spot) / spot * 100).round(2)
    # Market smile: OTM puts (K<S) → P_IV, OTM calls (K>=S) → C_IV
    sm["Market_IV"] = np.where(sm["Strike"] >= spot,
                               sm["C_IV"].fillna(sm["P_IV"]),
                               sm["P_IV"].fillna(sm["C_IV"]))
    # log-moneyness for clean x-axis alternative
    sm["LogK"] = np.log(sm["Strike"] / spot).round(4)
    return sm.reset_index(drop=True)


def skew_metrics(c_all: pd.DataFrame, p_all: pd.DataFrame,
                 spot: float, expiry: Optional[str]) -> dict:
    """Per-expiry skew scalars: ATM_IV, RR25, BF25, slope_90_110."""
    sm = iv_smile_by_expiry(c_all, p_all, spot, expiry)
    if sm.empty:
        return {}
    # ATM
    atm_idx = (sm["Strike"] - spot).abs().idxmin()
    atm_row = sm.loc[atm_idx]
    atm_iv = ((atm_row["C_IV"] or 0) + (atm_row["P_IV"] or 0)) / 2 if \
        pd.notna(atm_row["C_IV"]) and pd.notna(atm_row["P_IV"]) else \
        (atm_row["C_IV"] if pd.notna(atm_row["C_IV"]) else atm_row["P_IV"])
    # NOTE (model-validation): these are NOT true 25-delta wings. They are a
    # robust ±7%-MONEYNESS proxy (averaging up to 3 strikes per wing) used
    # because reliable per-strike delta isn't always present. Keep that in
    # mind when comparing rr25/bf25 to a broker's true-25Δ risk reversal.
    wing_lo = sm[sm["Moneyness"] <= -7].sort_values("Moneyness").tail(3)
    wing_hi = sm[sm["Moneyness"] >= 7].sort_values("Moneyness").head(3)
    put_wing = wing_lo["P_IV"].mean() if not wing_lo.empty else None
    call_wing = wing_hi["C_IV"].mean() if not wing_hi.empty else None
    rr25 = None
    bf25 = None
    if put_wing is not None and call_wing is not None and atm_iv:
        rr25 = round(float(put_wing - call_wing), 2)
        bf25 = round(float((put_wing + call_wing) / 2 - atm_iv), 2)
    # Slope 90-110: normalized to atm
    lo = sm[sm["Moneyness"] <= -10]
    hi = sm[sm["Moneyness"] >= 10]
    slope = None
    if not lo.empty and not hi.empty and atm_iv:
        iv_lo = lo["Market_IV"].iloc[-1] if pd.notna(lo["Market_IV"].iloc[-1]) else None
        iv_hi = hi["Market_IV"].iloc[0] if pd.notna(hi["Market_IV"].iloc[0]) else None
        if iv_lo is not None and iv_hi is not None:
            slope = round(float(iv_lo - iv_hi), 2)
    return {
        "expiry": expiry,
        "atm_iv": round(float(atm_iv), 2) if atm_iv else None,
        "rr25": rr25,
        "bf25": bf25,
        "slope_90_110": slope,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Back-compat
# ─────────────────────────────────────────────────────────────────────────────
calc_max_pain = max_pain
calc_pcr = put_call_ratio
calc_atm_iv = atm_iv_interp
calc_expected_move = expected_move
calc_iv_skew = iv_skew
calc_term_structure = term_structure
