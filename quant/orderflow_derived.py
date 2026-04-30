"""
Derived metrics over the orderflow tick stream.

Everything here is pure: takes a `history` list (and optional spot
price series) and returns scalars / Series that downstream charts /
panels render. No I/O, no Streamlit imports, easy to unit-test.

Functions
---------
  · velocity(history, field, window_min)        — ∂field/∂t in $M/min
  · zscore_intraday(history, field)             — current vs session distribution
  · cumulative_hedge_flow(history, field)       — Σ ΔGEX × ΔSpot, an
                                                  estimate of dealer hedging
                                                  demand realised so far in the
                                                  session, in $M·points·units.
  · wall_stability(history, key, lookback)      — age + variance score of a wall
  · what_changed(strike_now, strike_prev, n)    — top-N strike movers
  · session_vol_score(history, intraday_df)     — scalar in [0,3] used to
                                                  pick adaptive cadence
"""
from __future__ import annotations

import datetime
from typing import Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _to_df(history: list) -> Optional[pd.DataFrame]:
    if not history:
        return None
    df = pd.DataFrame(history)
    if "timestamp" not in df.columns:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    return df.reset_index(drop=True) if not df.empty else None


# ─────────────────────────────────────────────────────────────────────────────
#  Velocity — minute-level rate of change
# ─────────────────────────────────────────────────────────────────────────────
def velocity(history: list, field: str = "net_gex_mm",
             window_min: int = 5) -> Optional[pd.DataFrame]:
    """Return a DataFrame with `timestamp` and `<field>_velocity_per_min`,
    computed as the slope of `field` over a rolling `window_min` minute
    window. Resamples to 1-minute bars first so irregular tick cadence
    doesn't bias the slope.

    Returns None if history is too short or the field has no real values.
    Constant series (e.g. cached chain in a closed market) return a
    DataFrame with all-zero velocity so callers can render an explicit
    "calm" overlay instead of an empty panel.
    """
    df = _to_df(history)
    if df is None or field not in df.columns or len(df) < 3:
        return None
    # Pre-coerce to numeric BEFORE indexing. astype(float) on a Series
    # with stringified numbers (Schwab occasionally returns them) raises;
    # to_numeric(errors="coerce") returns NaN-safe floats.
    numeric = pd.to_numeric(df[field], errors="coerce")
    if numeric.notna().sum() < 3:
        return None
    ts = pd.Series(numeric.values, index=df["timestamp"])
    # Drop tz from the index just for the resample — pandas ≥2 handles
    # tz-aware indices fine in resample but a few combinations have edge
    # cases; using naive UTC here is robust and we never re-publish the
    # index so timezone info isn't load-bearing downstream.
    if getattr(ts.index, "tz", None) is not None:
        ts.index = ts.index.tz_convert("UTC").tz_localize(None)
    ts_min = ts.resample("1min").mean().interpolate("linear")
    if len(ts_min) < 3:
        return None
    deriv = (ts_min - ts_min.shift(window_min)) / float(max(window_min, 1))
    out = pd.DataFrame({
        "timestamp": deriv.index,
        f"{field}_velocity_per_min": deriv.to_numpy(),
    })
    return out.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Intraday z-score — context-aware "is this extreme?" indicator
# ─────────────────────────────────────────────────────────────────────────────
def zscore_intraday(history: list, field: str = "net_gex_mm",
                    min_obs: int = 8) -> Optional[float]:
    """Z-score of the latest tick's `field` vs the rolling intraday
    distribution. Uses sample stdev (ddof=1) — population stdev
    underestimated dispersion on short windows. Returns None if too few
    observations or σ ≈ 0.
    """
    df = _to_df(history)
    if df is None or field not in df.columns:
        return None
    s = pd.to_numeric(df[field], errors="coerce").dropna()
    if len(s) < min_obs:
        return None
    sd = float(s.std(ddof=1))
    if not np.isfinite(sd) or sd <= 1e-9:
        return 0.0
    return round(float((s.iloc[-1] - s.mean()) / sd), 2)


# ─────────────────────────────────────────────────────────────────────────────
#  Cumulative dealer hedge flow estimate
# ─────────────────────────────────────────────────────────────────────────────
def cumulative_hedge_flow(history: list,
                          gex_field: str = "net_gex_mm",
                          spot_field: str = "spot") -> Optional[pd.DataFrame]:
    """Estimate cumulative dealer hedging demand using the GEX-times-dS proxy.

    Reasoning:
      Net GEX is the $-hedge-per-1%-move. Between two consecutive ticks
      with spot moving by ΔS / S, the dealer's directional hedge demand
      is approximately `Net_GEX × (ΔS / S × 100)` — i.e. positive net GEX
      * positive spot move = dealer SOLD shares (long-gamma counter-trend
      hedging). Cumulating that gives a running tally of session hedge
      flow expressed in $M.

    Sign convention: positive cumulative value = dealer has been net
    SELLING into rallies and BUYING into dips (long-γ regime). Negative
    = dealer has been net BUYING strength / SELLING weakness (short-γ).
    """
    df = _to_df(history)
    if df is None or gex_field not in df.columns or spot_field not in df.columns:
        return None
    df = df[["timestamp", gex_field, spot_field]].copy()
    df[gex_field] = pd.to_numeric(df[gex_field], errors="coerce")
    df[spot_field] = pd.to_numeric(df[spot_field], errors="coerce")
    df = df.dropna(subset=[gex_field, spot_field])
    if len(df) < 2:
        return None
    spot = df[spot_field].to_numpy()
    gex = df[gex_field].to_numpy()
    d_spot_pct = np.zeros_like(spot)
    d_spot_pct[1:] = (spot[1:] - spot[:-1]) / np.where(spot[:-1] != 0, spot[:-1], 1.0) * 100.0
    # GEX is per 1% so multiply by Δspot_pct (in %); keep sign so positive
    # cumulative = long-γ counter-trend hedging.
    incr = gex * d_spot_pct
    cum = np.cumsum(incr)
    return pd.DataFrame({"timestamp": df["timestamp"].to_numpy(),
                         "incr_mm": incr, "cum_mm": cum}).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Wall stability — how long has it been there + how much has it moved?
# ─────────────────────────────────────────────────────────────────────────────
def wall_stability(history: list, key: str = "call_wall",
                   lookback: int = 20) -> dict:
    """Quantify how 'real' a wall is.

    Returns dict with:
      · current   — latest value
      · age_min   — how many minutes the wall has held within ±1 strike
                    of its mean (proxy for stability)
      · stddev    — stdev of the wall over the last `lookback` ticks
      · n_obs     — observations counted
    Empty dict if no data.
    """
    df = _to_df(history)
    if df is None or key not in df.columns:
        return {}
    s = pd.to_numeric(df[key], errors="coerce")
    s = s.dropna()
    if s.empty:
        return {}
    tail = s.iloc[-lookback:]
    if tail.empty:
        return {}
    cur = float(tail.iloc[-1])
    sd = float(tail.std(ddof=1)) if len(tail) >= 2 else 0.0
    # Find earliest tick still within ±1 of the mean for the "stable since"
    # heuristic. Robust enough for floating strikes (SPX = 5pt grid).
    mean_v = float(tail.mean())
    mask = (tail.sub(mean_v).abs() <= 1.0)
    if mask.any():
        first_label = mask[mask].index[0]
        first_ts = df.loc[first_label, "timestamp"]
        last_ts = df.loc[s.index[-1], "timestamp"]
        age_min = max(0.0, (last_ts - first_ts).total_seconds() / 60.0)
    else:
        age_min = 0.0
    return dict(
        current=cur, stddev=round(sd, 2),
        age_min=round(age_min, 1), n_obs=int(len(tail)),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  What changed in the last N minutes — top strike movers
# ─────────────────────────────────────────────────────────────────────────────
def what_changed(strike_now: pd.DataFrame,
                 strike_prev: pd.DataFrame,
                 metric: str = "Net_GEX",
                 top_n: int = 6) -> pd.DataFrame:
    """Return a DataFrame of the strikes whose `metric` changed the most
    between two snapshots. Both inputs must have columns `Strike` and
    `metric`. Output: Strike, prev, now, delta (sorted by |delta|).
    """
    cols = ("Strike", metric)
    if (strike_now is None or strike_prev is None or
            any(c not in strike_now.columns for c in cols) or
            any(c not in strike_prev.columns for c in cols)):
        return pd.DataFrame(columns=["Strike", "prev", "now", "delta"])
    n = strike_now[["Strike", metric]].rename(columns={metric: "now"})
    p = strike_prev[["Strike", metric]].rename(columns={metric: "prev"})
    m = n.merge(p, on="Strike", how="outer").fillna(0.0)
    m["delta"] = m["now"] - m["prev"]
    m["abs_delta"] = m["delta"].abs()
    m = m.sort_values("abs_delta", ascending=False).head(top_n)
    return m[["Strike", "prev", "now", "delta"]].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Session volatility score — drives adaptive sampling cadence
# ─────────────────────────────────────────────────────────────────────────────
def session_vol_score(history: list,
                      intraday_df: Optional[pd.DataFrame] = None,
                      gex_field: str = "net_gex_mm",
                      spot_field: str = "spot") -> float:
    """Score in [0, 3] driving how aggressive the auto-refresh interval
    should be. Higher = sample more often.

    Components:
      · realized_score — recent 5-min spot stdev / typical level
      · gex_score      — |last-tick z-score of net GEX|, capped at 2
      · session_edge   — boost near open / close (first/last 30 min ET)
    """
    score = 0.0

    # 1) realized score from intraday
    if intraday_df is not None and "close" in intraday_df.columns and len(intraday_df) >= 30:
        c = pd.to_numeric(intraday_df["close"], errors="coerce").dropna()
        tail = c.tail(15)
        if len(tail) >= 5:
            ret = tail.pct_change().dropna()
            if not ret.empty:
                # 5-15min vol; scale so 1.5% session ≈ 1.0 score
                rv = float(ret.std(ddof=1) * np.sqrt(390))  # approx daily
                score += min(1.5, rv * 1.0)

    # 2) GEX z-score component
    z = zscore_intraday(history, field=gex_field, min_obs=6)
    if z is not None:
        score += min(1.0, abs(z) / 2.0)

    # 3) session-edge boost
    df = _to_df(history)
    if df is not None and not df.empty:
        try:
            last = df["timestamp"].iloc[-1].tz_convert("America/New_York")
            mins_from_open = (last.hour - 9) * 60 + (last.minute - 30)
            mins_to_close = (16 - last.hour) * 60 - last.minute
            if 0 <= mins_from_open <= 30 or 0 <= mins_to_close <= 30:
                score += 0.5
        except Exception:
            pass

    return round(min(3.0, max(0.0, score)), 2)


def adaptive_refresh_seconds(score: float,
                             fast_s: int = 15, base_s: int = 30,
                             slow_s: int = 60) -> int:
    """Map a session_vol_score into a refresh interval.
        score >= 1.5 → fast   (open / FOMC / breakout)
        score >= 0.7 → base
        else         → slow   (mid-session calm)
    """
    if score >= 1.5:
        return fast_s
    if score >= 0.7:
        return base_s
    return slow_s
