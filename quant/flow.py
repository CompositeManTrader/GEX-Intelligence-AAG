"""
HIRO — Hedging Impact Real-time Oscillator (SpotGamma-inspired).

Purpose: estimate dealer hedging flow from options activity.

Theory:
  When a client BUYS a call, the dealer SELLS it (short call) → dealer is
  SHORT delta, so the dealer must BUY underlying shares to hedge. That is
  BULLISH share-flow pressure from dealer hedging.

  When a client BUYS a put, the dealer is SHORT put → LONG delta (puts have
  negative delta, so short put → short |Δ| = long Δ = positive delta), and the
  dealer must SELL shares to hedge. BEARISH share-flow pressure.

  Without trade-side tick data, we proxy flow direction with two signals:
    (a) Snapshot HIRO — volume × delta product, sign-conventioned per leg.
    (b) OI-delta HIRO — Δ(OI) × delta between chain refreshes = truly *new*
        open interest, filtered to dealer-hedge-relevant flow.

Returned scales:
  HIRO values are raw "contract-delta units". Multiply by 100 × spot to express
  in notional USD; the chart normalizes to z-score for readability.
"""
from __future__ import annotations

import datetime
from datetime import timezone
from typing import Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
#  Core HIRO computations
# ─────────────────────────────────────────────────────────────────────────────
def compute_hiro_snapshot(calls: pd.DataFrame, puts: pd.DataFrame) -> dict:
    """Pure-snapshot HIRO from today's volume × delta (no history needed).

    Convention (dealer perspective):
      + call volume  → dealer short calls → BUYS shares   (bullish)
      − put volume   → dealer short puts  → SELLS shares  (bearish)
    We sign-convention: call contribution is +1, put contribution is −1.

    Returns
    -------
    dict with keys:
        call_flow   Σ (call_vol × call_Δ) — always ≥ 0 for normal Δ
        put_flow    Σ (put_vol × |put_Δ|) — always ≥ 0
        hiro        call_flow − put_flow  (positive = bullish hedging pressure)
        ratio       call_flow / (call_flow + put_flow)  ∈ [0, 1]
    """
    def _side(df: pd.DataFrame, put: bool = False) -> float:
        if df is None or df.empty:
            return 0.0
        if "Volume" not in df.columns or "Delta" not in df.columns:
            return 0.0
        v = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)
        d = pd.to_numeric(df["Delta"], errors="coerce").fillna(0.0)
        if put:
            d = d.abs()
        return float((v * d).sum())

    call_flow = _side(calls, put=False)
    put_flow = _side(puts, put=True)
    hiro = call_flow - put_flow
    tot = call_flow + put_flow
    ratio = (call_flow / tot) if tot > 0 else 0.5
    return dict(
        call_flow=round(call_flow, 2),
        put_flow=round(put_flow, 2),
        hiro=round(hiro, 2),
        ratio=round(ratio, 3),
    )


def compute_hiro_by_strike(calls: pd.DataFrame, puts: pd.DataFrame,
                           spot: float) -> pd.DataFrame:
    """HIRO contribution per strike (for the bar-chart visualization).

    Positive bar = call-side dealer buy pressure on that strike
    Negative bar = put-side dealer sell pressure on that strike
    """
    def _prep(df: pd.DataFrame, sign: int) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["Strike", "Flow"])
        if "Volume" not in df.columns or "Delta" not in df.columns:
            return pd.DataFrame(columns=["Strike", "Flow"])
        d = df[["Strike", "Volume", "Delta"]].copy()
        d["Volume"] = pd.to_numeric(d["Volume"], errors="coerce").fillna(0.0)
        d["Delta"] = pd.to_numeric(d["Delta"], errors="coerce").fillna(0.0)
        d["Flow"] = d["Volume"] * d["Delta"].abs() * sign
        return d.groupby("Strike", as_index=False)["Flow"].sum()

    c = _prep(calls, +1)
    p = _prep(puts, -1)
    if c.empty and p.empty:
        return pd.DataFrame()
    out = c.merge(p, on="Strike", how="outer", suffixes=("_C", "_P")).fillna(0.0)
    out.columns = ["Strike", "C_Flow", "P_Flow"]
    out["Net_Flow"] = out["C_Flow"] + out["P_Flow"]
    out["Abs_Flow"] = out["Net_Flow"].abs()
    out = out.sort_values("Strike").reset_index(drop=True)
    return out


def compute_hiro_oi_delta(calls_now: pd.DataFrame, puts_now: pd.DataFrame,
                          calls_prev: Optional[pd.DataFrame] = None,
                          puts_prev: Optional[pd.DataFrame] = None) -> dict:
    """True dealer-hedge proxy using *change* in OI between two chain snapshots.

    ΔOI × sign(Δ) × spot tells you how many new delta-equivalent shares the
    dealer had to hedge since the previous snapshot.

    Returns {"hiro_oi": float, "call_oi_flow": float, "put_oi_flow": float}
    """
    if calls_prev is None or puts_prev is None \
       or calls_prev.empty or puts_prev.empty:
        return dict(hiro_oi=None, call_oi_flow=None, put_oi_flow=None)

    def _oi_delta(now: pd.DataFrame, prev: pd.DataFrame, put: bool) -> float:
        if "Strike" not in now or "OI" not in now or "Delta" not in now:
            return 0.0
        # Merge on strike+expiry to track the same contracts
        keys = ["Strike"] + (["Expiry"] if "Expiry" in now.columns and "Expiry" in prev.columns else [])
        m = now.merge(prev[keys + ["OI"]], on=keys, how="left", suffixes=("", "_prev"))
        m["OI_prev"] = pd.to_numeric(m.get("OI_prev", 0), errors="coerce").fillna(0.0)
        m["dOI"] = pd.to_numeric(m["OI"], errors="coerce").fillna(0.0) - m["OI_prev"]
        d = pd.to_numeric(m["Delta"], errors="coerce").fillna(0.0)
        if put:
            d = d.abs()
        return float((m["dOI"] * d).sum())

    call_oi_flow = _oi_delta(calls_now, calls_prev, put=False)
    put_oi_flow = _oi_delta(puts_now, puts_prev, put=True)
    hiro_oi = call_oi_flow - put_oi_flow
    return dict(
        hiro_oi=round(hiro_oi, 2),
        call_oi_flow=round(call_oi_flow, 2),
        put_oi_flow=round(put_oi_flow, 2),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Historical HIRO oscillator — persists across refreshes via session_state
# ─────────────────────────────────────────────────────────────────────────────
def update_hiro_history(history: list, new_point: dict,
                        max_len: int = 200) -> list:
    """Append a HIRO data point to the rolling history, bounded to max_len."""
    if not isinstance(history, list):
        history = []
    history.append(new_point)
    if len(history) > max_len:
        history = history[-max_len:]
    return history


def hiro_zscore(history: list, window: int = 20) -> Optional[float]:
    """Rolling z-score of the most recent HIRO vs a window of history.

    Interpretation: z > +2 → strong dealer buy pressure (bullish tilt)
                    z < −2 → strong dealer sell pressure (bearish tilt)
    """
    if not history or len(history) < 3:
        return None
    series = pd.Series([h["hiro"] for h in history[-window:]])
    # Sample stdev (ddof=1): correct for finite-history z-score. Population
    # stdev underestimated dispersion on short windows and made the score
    # overshoot, occasionally crossing the |z|>2 threshold spuriously.
    sd = series.std(ddof=1)
    if not pd.notna(sd) or sd <= 1e-9:
        return 0.0
    return round(float((series.iloc[-1] - series.mean()) / sd), 2)


# ─────────────────────────────────────────────────────────────────────────────
#  Convenience: stamp a HIRO tick at the current time
# ─────────────────────────────────────────────────────────────────────────────
def tick_hiro(calls: pd.DataFrame, puts: pd.DataFrame,
              spot: float) -> dict:
    """Single HIRO observation tagged with UTC timestamp."""
    snap = compute_hiro_snapshot(calls, puts)
    # tz-aware UTC ISO timestamp (datetime.utcnow is deprecated in 3.12+)
    snap["timestamp"] = datetime.datetime.now(timezone.utc).isoformat()
    snap["spot"] = float(spot) if spot else None
    return snap
