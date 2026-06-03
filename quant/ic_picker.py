"""
Iron-condor strike-placement helper for 0DTE (or any single expiry).

What we reuse from the existing pipeline
----------------------------------------
The chain already carries per-strike IV in the `IV%` column produced by
`data.parse.clean` (normalised to percent). Greeks (Delta, Gamma) and
liquidity (OI, Volume, Bid/Ask/Mark) are also present per row. We do NOT
recompute any of this — we only restructure it for the smile and run
metrics on top.

`quant.levels.iv_smile_by_expiry(c_all, p_all, spot, expiry)` already
constructs the per-expiry smile with the OTM convention (`Market_IV` =
put-OTM for K<S, call-OTM for K≥S) and `LogK = log(K/S)`. We reuse it
verbatim and augment with a unified per-strike Delta column built from
the same OTM convention.

Public API
----------
  · build_iv_long_table(c, p)       — long-format strike/side/iv/gamma/oi
  · build_smile_blend(c, p, spot)   — wide smile with Delta added (OTM blend)
  · iron_condor_metrics(...)        — VRP + credit + max-loss + POT for ONE IC
  · compare_wing_widths(...)        — table of metrics across wing widths
  · suggest_strikes_from_walls(...) — short_put / short_call respecting walls
  · gex_gate_check(...)             — pass/fail of the GEX regime gate
  · rich_zone_mask(...)             — boolean mask of "rich" smile strikes

Sign / probability conventions
------------------------------
  · Delta in the chain is signed: calls ∈ [0,1], puts ∈ [-1,0].
  · For OTM-blended smile we use call-Delta on strikes ≥ spot and
    |put-Delta| on strikes < spot, so the "effective" |Δ_short| is
    directly the probability of expiring ITM under risk-neutral measure
    (Bachelier-style approximation).
  · Probability of touch ≈ 2 × |Δ_short| — standard short-T proxy used
    by most retail platforms. For a 0DTE leg with Δ_short = -0.15, that
    gives PoT ≈ 30 %.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd

from quant.levels import iv_smile_by_expiry


# ─────────────────────────────────────────────────────────────────────────────
#  Long-format IV exposure table (debug / introspection)
# ─────────────────────────────────────────────────────────────────────────────
def build_iv_long_table(c: pd.DataFrame, p: pd.DataFrame) -> pd.DataFrame:
    """Long-format `(Strike, side, IV%, Gamma, OI)` from both sides of the
    chain. Used by debug panels and the smile chart's hover. Vectorised.
    Empty DataFrame if neither side has data.
    """
    pieces: list[pd.DataFrame] = []
    cols = ["Strike", "IV%", "Gamma", "OI"]
    if c is not None and not c.empty and all(k in c.columns for k in cols):
        ci = c[cols].copy()
        ci["side"] = "call"
        pieces.append(ci)
    if p is not None and not p.empty and all(k in p.columns for k in cols):
        pi = p[cols].copy()
        pi["side"] = "put"
        pieces.append(pi)
    if not pieces:
        return pd.DataFrame(columns=["Strike", "side", "IV%", "Gamma", "OI"])
    out = pd.concat(pieces, ignore_index=True)
    out["IV%"] = pd.to_numeric(out["IV%"], errors="coerce")
    out["Gamma"] = pd.to_numeric(out["Gamma"], errors="coerce")
    out["OI"] = pd.to_numeric(out["OI"], errors="coerce").fillna(0).astype(int)
    out = out.dropna(subset=["Strike", "IV%"])
    return out.sort_values(["Strike", "side"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Smile blend with delta
# ─────────────────────────────────────────────────────────────────────────────
def _pick_expiry(c_all: pd.DataFrame) -> Optional[str]:
    """Pick the nearest expiry (smallest DTE ≥ 0). Used for 0DTE detection."""
    if c_all is None or c_all.empty or "DTE" not in c_all.columns:
        return None
    dte = pd.to_numeric(c_all["DTE"], errors="coerce")
    valid = c_all.loc[dte.notna() & (dte >= 0)]
    if valid.empty:
        return None
    idx = pd.to_numeric(valid["DTE"], errors="coerce").idxmin()
    return str(valid.loc[idx, "Expiry"]) if "Expiry" in valid.columns else None


def build_smile_blend(c: pd.DataFrame, p: pd.DataFrame, spot: float,
                      expiry: Optional[str] = None) -> pd.DataFrame:
    """Return the per-strike smile for `expiry` with an OTM-blended
    `Delta` column added on top of `iv_smile_by_expiry`'s output.

    Columns: Strike, Moneyness, C_IV, P_IV, Market_IV, LogK, Delta, Gamma, OI.
    Delta is unified using the OTM convention:
        · K >= spot  →  call delta  (positive, [0, 1])
        · K <  spot  →  |put delta| (positive, [0, 1])
    Gamma / OI are summed across the two sides at each strike so the
    chart can sanity-check liquidity.
    """
    if c is None or p is None:
        return pd.DataFrame()
    if expiry is None:
        expiry = _pick_expiry(c)
    sm = iv_smile_by_expiry(c, p, spot=spot, expiry=expiry)
    if sm.empty:
        return sm

    # Augment with delta + per-strike gamma/oi using the OTM convention.
    def _slice(df: pd.DataFrame, side: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["Strike", "Delta", "Gamma", "OI"])
        cols = [k for k in ("Strike", "Delta", "Gamma", "OI") if k in df.columns]
        out = df[cols].copy()
        if "DTE" in df.columns and expiry is not None:
            out = out.loc[df["Expiry"] == expiry] if "Expiry" in df.columns else out
        for col in ("Delta", "Gamma", "OI"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        out = (out.dropna(subset=["Strike"]).groupby("Strike", as_index=False)
                  .agg({"Delta": "mean", "Gamma": "mean", "OI": "sum"})
                  if not out.empty else out)
        out["side"] = side
        return out

    c_side = _slice(c, "call")
    p_side = _slice(p, "put")

    # OTM convention: pick call-delta when K>=spot, |put-delta| when K<spot.
    sm = sm.sort_values("Strike").reset_index(drop=True)

    c_idx = c_side.set_index("Strike") if not c_side.empty else pd.DataFrame()
    p_idx = p_side.set_index("Strike") if not p_side.empty else pd.DataFrame()

    def _lookup(strike: float, col: str) -> float:
        if strike >= spot:
            return float(c_idx[col].get(strike, np.nan)) if not c_idx.empty else np.nan
        else:
            v = float(p_idx[col].get(strike, np.nan)) if not p_idx.empty else np.nan
            return abs(v) if col == "Delta" and not np.isnan(v) else v

    sm["Delta"] = sm["Strike"].map(lambda k: _lookup(k, "Delta"))
    # Gamma / OI: sum both sides (they're independent liquidity contributors).
    gc = c_idx["Gamma"] if not c_idx.empty and "Gamma" in c_idx.columns else pd.Series(dtype=float)
    gp = p_idx["Gamma"] if not p_idx.empty and "Gamma" in p_idx.columns else pd.Series(dtype=float)
    oc = c_idx["OI"] if not c_idx.empty and "OI" in c_idx.columns else pd.Series(dtype=float)
    op = p_idx["OI"] if not p_idx.empty and "OI" in p_idx.columns else pd.Series(dtype=float)
    sm["Gamma"] = sm["Strike"].map(
        lambda k: float(gc.get(k, 0) or 0) + float(gp.get(k, 0) or 0)
    )
    sm["OI"] = sm["Strike"].map(
        lambda k: int(float(oc.get(k, 0) or 0) + float(op.get(k, 0) or 0))
    )
    return sm.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Rich-zone detector (smile points where IV is statistically elevated)
# ─────────────────────────────────────────────────────────────────────────────
def rich_zone_mask(smile_df: pd.DataFrame,
                   sigma: float = 1.0) -> np.ndarray:
    """Boolean mask of strikes whose `Market_IV` is > median + sigma·std.
    Used to highlight visually the "rich" region of the smile.
    """
    if smile_df is None or smile_df.empty or "Market_IV" not in smile_df.columns:
        return np.array([], dtype=bool)
    iv = pd.to_numeric(smile_df["Market_IV"], errors="coerce")
    med = float(iv.median(skipna=True))
    sd = float(iv.std(ddof=1, skipna=True)) if iv.notna().sum() > 2 else 0.0
    if sd <= 0:
        return np.zeros(len(smile_df), dtype=bool)
    return (iv > med + sigma * sd).fillna(False).to_numpy()


# ─────────────────────────────────────────────────────────────────────────────
#  Iron Condor metrics
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ICCandidate:
    short_put: float
    long_put: float
    short_call: float
    long_call: float
    wing_width: float
    # IV per leg (percent points)
    iv_short_put: float
    iv_long_put: float
    iv_short_call: float
    iv_long_call: float
    # VRP proxy (IV points)
    vrp_put_side: float
    vrp_call_side: float
    net_vrp_iv_points: float
    # Credit / max loss / efficiency
    # NOTE (model-validation): the "vrp_*" fields are NOT variance risk
    # premium (IV²−RV²). They are IV-SKEW GRADIENTS across each wing:
    # vrp_put = IV(short put) − IV(long put), vrp_call = IV(short call) −
    # IV(long call). Positive ⇒ you sell richer IV than you buy. Treat them
    # as a wing-richness score, not as a true VRP.
    credit: float
    max_loss: float
    vrp_per_max_loss: float    # wing IV-skew points per $ of max loss
    credit_per_max_loss: float  # ROI (%) ≈ credit / max_loss × 100
    # Probabilities
    delta_short_put: float
    delta_short_call: float
    p_touch_put: float
    p_touch_call: float
    pop: float                 # 1 − (Δ_short_put + Δ_short_call), clipped [0,1]
    # Provenance
    credit_source: str         # "mark" | "iv_proxy" | "empty"

    def to_dict(self) -> dict:
        return asdict(self)


def _nearest_strike(df: pd.DataFrame, target: float) -> Optional[float]:
    """Closest available strike in `df` to `target`. None if df empty."""
    if df is None or df.empty or "Strike" not in df.columns:
        return None
    strikes = pd.to_numeric(df["Strike"], errors="coerce").dropna().unique()
    if len(strikes) == 0:
        return None
    return float(strikes[np.argmin(np.abs(strikes - target))])


def _leg_price(df: pd.DataFrame, strike: float) -> Optional[float]:
    """Mark price for `strike` from `df`. Falls back to (Bid+Ask)/2 if Mark
    is missing or zero. Returns None if no price available."""
    if df is None or df.empty:
        return None
    row = df.loc[df["Strike"] == strike]
    if row.empty:
        return None
    for col in ("Mark", "Last"):
        if col in row.columns:
            v = pd.to_numeric(row[col].iloc[0], errors="coerce")
            if pd.notna(v) and v > 0:
                return float(v)
    if "Bid" in row.columns and "Ask" in row.columns:
        b = pd.to_numeric(row["Bid"].iloc[0], errors="coerce")
        a = pd.to_numeric(row["Ask"].iloc[0], errors="coerce")
        if pd.notna(b) and pd.notna(a) and a > 0:
            return float((max(b, 0.0) + a) / 2.0)
    return None


def _leg_iv(smile_df: pd.DataFrame, strike: float, side: str) -> Optional[float]:
    """IV at `strike` from the smile. Uses OTM convention by default; if
    the OTM leg is missing fall back to Market_IV."""
    if smile_df is None or smile_df.empty:
        return None
    row = smile_df.loc[smile_df["Strike"] == strike]
    if row.empty:
        # Nearest-neighbour fallback
        idx = (pd.to_numeric(smile_df["Strike"], errors="coerce") - strike).abs().idxmin()
        row = smile_df.loc[[idx]]
    col_pref = "C_IV" if side == "call" else "P_IV"
    if col_pref in row.columns:
        v = pd.to_numeric(row[col_pref].iloc[0], errors="coerce")
        if pd.notna(v) and v > 0:
            return float(v)
    if "Market_IV" in row.columns:
        v = pd.to_numeric(row["Market_IV"].iloc[0], errors="coerce")
        if pd.notna(v) and v > 0:
            return float(v)
    return None


def _leg_delta(smile_df: pd.DataFrame, strike: float) -> Optional[float]:
    """Unified |delta| at `strike` from the OTM-blended smile."""
    if smile_df is None or smile_df.empty or "Delta" not in smile_df.columns:
        return None
    row = smile_df.loc[smile_df["Strike"] == strike]
    if row.empty:
        idx = (pd.to_numeric(smile_df["Strike"], errors="coerce") - strike).abs().idxmin()
        row = smile_df.loc[[idx]]
    v = pd.to_numeric(row["Delta"].iloc[0], errors="coerce")
    return float(abs(v)) if pd.notna(v) else None


def iron_condor_metrics(
    c: pd.DataFrame, p: pd.DataFrame,
    smile_df: pd.DataFrame, spot: float,
    short_put: float, short_call: float, wing_width: float,
) -> Optional[ICCandidate]:
    """Metrics for one IC configuration. All four strikes are snapped to
    the nearest available chain strike; `wing_width` is the *requested*
    width in strike units (the realised width may differ if the chain is
    coarse — we report both)."""
    if spot is None or spot <= 0 or wing_width <= 0:
        return None
    # Snap shorts to available chain
    sp_k = _nearest_strike(p, short_put)
    sc_k = _nearest_strike(c, short_call)
    if sp_k is None or sc_k is None:
        return None
    lp_k = _nearest_strike(p, sp_k - wing_width)
    lc_k = _nearest_strike(c, sc_k + wing_width)
    if lp_k is None or lc_k is None:
        return None
    realised_put_wing = float(sp_k - lp_k)
    realised_call_wing = float(lc_k - sc_k)
    # Use the smaller realised wing for max_loss conservatism
    realised_wing = float(min(realised_put_wing, realised_call_wing))
    if realised_wing <= 0:
        return None

    # IV per leg from the smile (preferring the right side)
    iv_sp = _leg_iv(smile_df, sp_k, "put") or 0.0
    iv_lp = _leg_iv(smile_df, lp_k, "put") or 0.0
    iv_sc = _leg_iv(smile_df, sc_k, "call") or 0.0
    iv_lc = _leg_iv(smile_df, lc_k, "call") or 0.0

    vrp_put = iv_sp - iv_lp
    vrp_call = iv_sc - iv_lc
    # Weighted (equal weights here; could be IV-weighted in principle)
    net_vrp = (vrp_put + vrp_call) / 2.0

    # Credit estimation: prefer real mark mid; fall back to a rough IV-
    # proportional proxy as last resort.
    mark_sp = _leg_price(p, sp_k)
    mark_lp = _leg_price(p, lp_k)
    mark_sc = _leg_price(c, sc_k)
    mark_lc = _leg_price(c, lc_k)
    if None not in (mark_sp, mark_lp, mark_sc, mark_lc):
        credit = (mark_sp + mark_sc) - (mark_lp + mark_lc)
        credit_source = "mark"
    else:
        # IV-proxy: tiny T/360 weight × IV difference is a rough premium proxy.
        # Better than nothing for symbols missing fresh quotes pre-market.
        credit = max(0.01 * (vrp_put + vrp_call) * realised_wing, 0.0)
        credit_source = "iv_proxy" if (iv_sp + iv_sc) > 0 else "empty"

    max_loss = max(realised_wing - credit, 0.01)
    vrp_per_ml = net_vrp / max_loss
    credit_per_ml = credit / max_loss

    # Deltas / probabilities
    delta_sp = _leg_delta(smile_df, sp_k) or 0.0
    delta_sc = _leg_delta(smile_df, sc_k) or 0.0
    p_touch_p = min(1.0, 2.0 * delta_sp)
    p_touch_c = min(1.0, 2.0 * delta_sc)
    # POP for an IC is "spot stays inside both shorts at expiry" — a tight
    # proxy is 1 − (Δ_sp + Δ_sc) (sum of the two ITM-probabilities). This
    # is what TastyTrade / dough display for 0DTE/short DTE.
    pop = max(0.0, min(1.0, 1.0 - (delta_sp + delta_sc)))

    return ICCandidate(
        short_put=sp_k, long_put=lp_k,
        short_call=sc_k, long_call=lc_k,
        wing_width=realised_wing,
        iv_short_put=round(iv_sp, 2), iv_long_put=round(iv_lp, 2),
        iv_short_call=round(iv_sc, 2), iv_long_call=round(iv_lc, 2),
        vrp_put_side=round(vrp_put, 2),
        vrp_call_side=round(vrp_call, 2),
        net_vrp_iv_points=round(net_vrp, 2),
        credit=round(credit, 3),
        max_loss=round(max_loss, 3),
        vrp_per_max_loss=round(vrp_per_ml, 4),
        credit_per_max_loss=round(credit_per_ml, 4),
        delta_short_put=round(delta_sp, 3),
        delta_short_call=round(delta_sc, 3),
        p_touch_put=round(p_touch_p, 3),
        p_touch_call=round(p_touch_c, 3),
        pop=round(pop, 3),
        credit_source=credit_source,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Wing-width comparison
# ─────────────────────────────────────────────────────────────────────────────
def compare_wing_widths(c: pd.DataFrame, p: pd.DataFrame,
                        spot: float, short_put: float, short_call: float,
                        wing_widths: tuple[float, ...] = (1.0, 3.0, 5.0, 10.0),
                        expiry: Optional[str] = None,
                        ) -> pd.DataFrame:
    """Return a DataFrame of IC metrics across `wing_widths`, holding the
    short strikes fixed. One row per width, sorted by `vrp_per_max_loss`
    descending so the most efficient wing rises to the top."""
    smile_df = build_smile_blend(c, p, spot=spot, expiry=expiry)
    rows: list[dict] = []
    for w in wing_widths:
        ic = iron_condor_metrics(c, p, smile_df, spot,
                                 short_put=short_put,
                                 short_call=short_call,
                                 wing_width=float(w))
        if ic is None:
            continue
        d = ic.to_dict()
        d["requested_wing"] = float(w)
        rows.append(d)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Sort by efficiency
    return df.sort_values("vrp_per_max_loss",
                          ascending=False).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Strike suggestion respecting the GEX walls
# ─────────────────────────────────────────────────────────────────────────────
def suggest_strikes_from_walls(
    c: pd.DataFrame, p: pd.DataFrame, spot: float,
    gex_sum: Optional[dict] = None,
    target_short_delta: float = 0.16,
    smile_df: Optional[pd.DataFrame] = None,
    buffer_pct: float = 0.001,
) -> dict:
    """Pick `short_put` and `short_call` strikes that:
      (a) are close to the given delta target (default 16Δ ≈ 1σ band)
      (b) stay OUTSIDE the put/call wall by at least `buffer_pct`
      (c) are actual available chain strikes
    Center of the structure is biased toward `hvl` (pin) when present.

    Returns dict with `short_put`, `short_call`, `centre`, `source`, and
    a `notes` list explaining why each was chosen.
    """
    if spot is None or spot <= 0:
        return {}
    smile_df = (smile_df if smile_df is not None
                else build_smile_blend(c, p, spot=spot))
    notes: list[str] = []

    # Candidate strikes by delta target
    if smile_df is not None and not smile_df.empty and "Delta" in smile_df.columns:
        below = smile_df[smile_df["Strike"] < spot].copy()
        above = smile_df[smile_df["Strike"] >= spot].copy()
        sp_candidate = sc_candidate = None
        if not below.empty:
            below["_dd"] = (below["Delta"].abs() - target_short_delta).abs()
            sp_candidate = float(below.sort_values("_dd").iloc[0]["Strike"])
        if not above.empty:
            above["_dd"] = (above["Delta"].abs() - target_short_delta).abs()
            sc_candidate = float(above.sort_values("_dd").iloc[0]["Strike"])
    else:
        sp_candidate = sc_candidate = None

    # Wall constraints
    pw = (gex_sum or {}).get("put_wall")
    cw = (gex_sum or {}).get("call_wall")
    hvl = (gex_sum or {}).get("hvl")

    if pw and sp_candidate is not None:
        pw_floor = float(pw) * (1.0 - buffer_pct)
        if sp_candidate > pw_floor:
            # Push BELOW the put wall by buffer_pct
            cand = _nearest_strike(p, pw_floor)
            if cand is not None:
                notes.append(
                    f"short_put pulled from ${sp_candidate:.0f} → ${cand:.0f} "
                    f"to sit below put_wall ${pw:.0f}"
                )
                sp_candidate = cand
    if cw and sc_candidate is not None:
        cw_ceil = float(cw) * (1.0 + buffer_pct)
        if sc_candidate < cw_ceil:
            cand = _nearest_strike(c, cw_ceil)
            if cand is not None:
                notes.append(
                    f"short_call pulled from ${sc_candidate:.0f} → ${cand:.0f} "
                    f"to sit above call_wall ${cw:.0f}"
                )
                sc_candidate = cand

    return {
        "short_put": sp_candidate,
        "short_call": sc_candidate,
        "centre": float(hvl) if hvl else float(spot),
        "source": ("walls+delta" if (pw or cw) else "delta_only"),
        "notes": notes,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  GEX regime gate — verdict on whether the IC setup conditions are met
# ─────────────────────────────────────────────────────────────────────────────
def gex_gate_check(
    gex_sum: Optional[dict],
    spot: float,
    min_net_gex_usd: float = 1e9,
    min_cushion_pct: float = 0.30,
) -> dict:
    """Pass / fail the conditions to safely sell a 0DTE iron condor:

      1. Net GEX > `min_net_gex_usd` (dealers long-Γ → pinning expected)
      2. Regime label is POSITIVE
      3. spot > gamma_flip (we're on the long-Γ side of the flip)
      4. (spot − gamma_flip) / spot >= min_cushion_pct   (away from flip)

    UNITS TRAP (model-validation): `cushion_pct` and `min_cushion_pct` are
    in PERCENT POINTS. The default 0.30 means 0.30%, NOT 30%. A 30% cushion
    would never trigger intraday, so do not "fix" 0.30 to 30. For SPY≈580
    that default is ~$1.7 above the flip.

    Returns dict with `pass`, individual checks, and a `verdict` string.
    """
    out = {
        "pass": False,
        "regime_ok": False, "net_gex_ok": False,
        "above_flip_ok": False, "cushion_ok": False,
        "net_gex_usd": None, "regime": None,
        "cushion_pct": None, "gamma_flip": None,
        "verdict": "no_data",
    }
    if not gex_sum or spot is None or spot <= 0:
        return out

    total = gex_sum.get("total_gex")
    regime = gex_sum.get("regime")
    gf = gex_sum.get("gamma_flip")
    out["net_gex_usd"] = total
    out["regime"] = regime
    out["gamma_flip"] = gf

    out["regime_ok"] = (regime == "POSITIVE")
    out["net_gex_ok"] = (total is not None and float(total) >= min_net_gex_usd)
    if gf is not None:
        out["above_flip_ok"] = (spot > float(gf))
        cushion = (spot - float(gf)) / spot * 100.0
        out["cushion_pct"] = round(cushion, 3)
        out["cushion_ok"] = (cushion >= min_cushion_pct)

    out["pass"] = bool(
        out["regime_ok"] and out["net_gex_ok"]
        and out["above_flip_ok"] and out["cushion_ok"]
    )
    if out["pass"]:
        out["verdict"] = "PASS — condiciones de IC favorables"
    else:
        reasons = []
        if not out["regime_ok"]:
            reasons.append(f"régimen {regime} ≠ POSITIVE")
        if not out["net_gex_ok"]:
            ng_bn = (float(total) / 1e9) if total is not None else None
            reasons.append(
                f"Net GEX {ng_bn:+.2f}B < ${min_net_gex_usd/1e9:.1f}B"
                if ng_bn is not None else "Net GEX no disponible"
            )
        if not out["above_flip_ok"]:
            reasons.append(
                f"spot ${spot:.2f} ≤ Zero Γ ${gf:.2f}" if gf is not None
                else "Zero Γ no disponible"
            )
        if not out["cushion_ok"]:
            reasons.append(
                f"colchón {out['cushion_pct']:.2f}% < {min_cushion_pct:.2f}%"
                if out["cushion_pct"] is not None else "sin Zero Γ"
            )
        out["verdict"] = "FAIL — " + " · ".join(reasons)
    return out
