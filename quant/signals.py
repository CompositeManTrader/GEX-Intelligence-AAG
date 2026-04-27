"""
Intraday signal engine — regime-aware buy/sell rules.

Theory
------
The GEX regime tells us how dealer hedging will respond to spot moves:

  • Positive net GEX (above gamma flip) → dealers BUY weakness, SELL strength.
    Their hedging is **counter-cyclical**, suppresses volatility, pins price
    around high-OI levels (HVL). Optimal play: **mean reversion** around VWAP.

  • Negative net GEX (below gamma flip) → dealers SELL weakness, BUY strength.
    Their hedging is **pro-cyclical**, amplifies moves once a level breaks.
    Optimal play: **breakout / momentum** off the opening range.

This module produces deterministic signals that can be backtested. Every
signal comes with: side, entry, stop, target1, target2, R-multiple,
generation timestamp, and a snapshot of the inputs that fired it.

Inputs
------
  • intraday OHLCV bars (`pd.DataFrame` with date/open/high/low/close/volume)
  • a `gex_summary` dict (regime, net_gex, call_wall, put_wall,
                          gamma_flip, hvl)
  • optional `hiro_z` (z-score of dealer hedging flow). If None, we skip
    confirmation but still allow the trade.

Outputs
-------
  list[Signal] — every signal evaluated for the latest bar. The UI shows
  ACTIVE signals (state == "armed"), the backtester replays the whole list.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional

import numpy as np
import pandas as pd

from config import ET_TZ


# ─────────────────────────────────────────────────────────────────────────────
#  Data types
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Signal:
    """A single trade signal with all the math behind it."""
    timestamp: str            # ISO UTC of the bar that generated it
    symbol: str
    regime: str               # "POSITIVE" | "NEGATIVE" | "NEUTRAL"
    strategy: str             # "mean_reversion" | "trend_breakout"
    side: str                 # "LONG" | "SHORT"
    entry: float
    stop: float
    target1: float
    target2: float
    r_unit: float             # |entry - stop| in price units (1R)
    rr_target1: float         # reward/risk to TP1
    rr_target2: float         # reward/risk to TP2
    confidence: float         # 0..1 score from confluence factors
    rationale: str            # human-readable why
    inputs: dict = field(default_factory=dict)  # snapshot of inputs

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _ensure_et(df: pd.DataFrame) -> pd.DataFrame:
    """Add `_et` column with ET timestamps. Idempotent."""
    if "_et" in df.columns:
        return df
    out = df.copy()
    if df["date"].dt.tz is None:
        out["_et"] = pd.to_datetime(out["date"]).dt.tz_localize("UTC").dt.tz_convert(ET_TZ)
    else:
        out["_et"] = pd.to_datetime(out["date"]).dt.tz_convert(ET_TZ)
    return out


def session_slice(df: pd.DataFrame, day: Optional[datetime.date] = None
                  ) -> pd.DataFrame:
    """Return only RTH bars (09:30–16:00 ET) for the given day. If `day` is
    None, uses the most recent ET date present in `df`."""
    if df is None or df.empty:
        return df
    d = _ensure_et(df)
    if day is None:
        day = d["_et"].dt.date.iloc[-1]
    mask = (
        (d["_et"].dt.date == day)
        & (d["_et"].dt.time >= datetime.time(9, 30))
        & (d["_et"].dt.time < datetime.time(16, 0))
    )
    return d.loc[mask].reset_index(drop=True)


def vwap_anchored(df: pd.DataFrame) -> np.ndarray:
    """Volume-weighted average price anchored to the first row."""
    if df is None or df.empty:
        return np.array([])
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (typical * df["volume"]).cumsum().to_numpy()
    cv = df["volume"].cumsum().to_numpy()
    cv = np.where(cv <= 0, 1.0, cv)
    return pv / cv


def vwap_bands(df: pd.DataFrame, n_sigma: float = 1.5
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """VWAP and ±n·σ bands using the rolling typical-price std."""
    if df is None or df.empty:
        return np.array([]), np.array([]), np.array([])
    vwap = vwap_anchored(df)
    typical = ((df["high"] + df["low"] + df["close"]) / 3.0).to_numpy()
    # Rolling std of typical price around VWAP, expanding for the first
    # 20 bars then 20-bar rolling.
    diff = typical - vwap
    n = len(typical)
    sd = np.zeros(n)
    for i in range(n):
        lo = max(0, i - 19)
        sd[i] = np.std(diff[lo : i + 1]) if i > 0 else 0.0
    upper = vwap + n_sigma * sd
    lower = vwap - n_sigma * sd
    return vwap, upper, lower


def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    """Average true range, expanding then rolling."""
    if df is None or df.empty:
        return np.array([])
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    out = np.zeros_like(tr)
    for i in range(len(tr)):
        lo = max(0, i - n + 1)
        out[i] = np.mean(tr[lo : i + 1])
    return out


def opening_range(df_session: pd.DataFrame, minutes: int = 30
                  ) -> tuple[Optional[float], Optional[float]]:
    """High / low of the first `minutes` minutes of the RTH session."""
    if df_session is None or df_session.empty:
        return None, None
    cutoff = df_session["_et"].iloc[0] + pd.Timedelta(minutes=minutes)
    or_df = df_session[df_session["_et"] < cutoff]
    if or_df.empty:
        return None, None
    return float(or_df["high"].max()), float(or_df["low"].min())


# ─────────────────────────────────────────────────────────────────────────────
#  Signal generators
# ─────────────────────────────────────────────────────────────────────────────
def generate_signals(
    intraday_df: pd.DataFrame,
    gex_summary: Optional[dict],
    symbol: str = "",
    hiro_z: Optional[float] = None,
    sigma_threshold: float = 1.5,
    or_minutes: int = 30,
    breakout_buffer_pct: float = 0.0005,   # 5 bps
    flat_close_et: datetime.time = datetime.time(15, 50),
) -> list[Signal]:
    """Evaluate the latest bar of `intraday_df` and return any armed signals.

    The function is **side-effect free** and **deterministic** — same inputs
    always yield the same outputs. That's what makes the strategy
    backtestable: we can replay every bar of every saved session through
    this function and reconstruct the exact signals that would have fired
    in real time.

    Returns
    -------
    list[Signal]
        Zero, one, or more signals. We allow up to one MR signal and one
        trend signal per evaluation so opposite biases don't cancel out
        — the UI / backtester decides which to take.
    """
    out: list[Signal] = []
    if intraday_df is None or intraday_df.empty or not gex_summary:
        return out

    sess = session_slice(intraday_df)
    if sess.empty or len(sess) < 5:
        return out

    last = sess.iloc[-1]
    last_et: pd.Timestamp = last["_et"]
    if last_et.time() >= flat_close_et:
        return out  # no new entries in last 10 min

    spot = float(last["close"])
    regime = (gex_summary.get("regime") or "NEUTRAL").upper()
    net_gex = float(gex_summary.get("total_gex") or 0.0)
    cw = gex_summary.get("call_wall")
    pw = gex_summary.get("put_wall")
    gf = gex_summary.get("gamma_flip")
    hvl = gex_summary.get("hvl")

    vwap, upper, lower = vwap_bands(sess, sigma_threshold)
    atrv = atr(sess, 14)
    last_vwap = float(vwap[-1])
    last_upper = float(upper[-1])
    last_lower = float(lower[-1])
    last_atr = float(atrv[-1]) if len(atrv) else 0.0
    if last_atr <= 0:
        return out  # not enough data

    # ── 1) MEAN REVERSION (positive gamma regime) ─────────────────────────
    if regime == "POSITIVE":
        # SHORT fade: price stretched above upper band, room to fall to VWAP,
        #             still below the call wall.
        if (spot >= last_upper
                and (cw is None or spot < cw * 0.999)
                and (hiro_z is None or hiro_z < 1.0)):
            entry = spot
            stop = entry + 0.5 * last_atr
            t1 = last_vwap
            t2 = float(hvl) if hvl else last_vwap - last_atr
            sig = _build_signal(
                last_et, symbol, regime, "mean_reversion", "SHORT",
                entry, stop, t1, t2,
                rationale=(
                    f"Spot {spot:.2f} > VWAP+{sigma_threshold}σ ({last_upper:.2f})"
                    f" en régimen +Γ. Fade hacia VWAP {last_vwap:.2f}."
                ),
                inputs=dict(spot=spot, vwap=last_vwap, upper=last_upper,
                            atr=last_atr, net_gex=net_gex, hiro_z=hiro_z,
                            call_wall=cw, hvl=hvl),
                base_conf=0.55,
            )
            if sig is not None:
                out.append(sig)

        # LONG fade: price stretched below lower band, above put wall.
        if (spot <= last_lower
                and (pw is None or spot > pw * 1.001)
                and (hiro_z is None or hiro_z > -1.0)):
            entry = spot
            stop = entry - 0.5 * last_atr
            t1 = last_vwap
            t2 = float(hvl) if hvl else last_vwap + last_atr
            sig = _build_signal(
                last_et, symbol, regime, "mean_reversion", "LONG",
                entry, stop, t1, t2,
                rationale=(
                    f"Spot {spot:.2f} < VWAP−{sigma_threshold}σ ({last_lower:.2f})"
                    f" en régimen +Γ. Fade hacia VWAP {last_vwap:.2f}."
                ),
                inputs=dict(spot=spot, vwap=last_vwap, lower=last_lower,
                            atr=last_atr, net_gex=net_gex, hiro_z=hiro_z,
                            put_wall=pw, hvl=hvl),
                base_conf=0.55,
            )
            if sig is not None:
                out.append(sig)

    # ── 2) TREND BREAKOUT (negative gamma regime) ─────────────────────────
    if regime == "NEGATIVE":
        or_high, or_low = opening_range(sess, minutes=or_minutes)
        if or_high is None or or_low is None:
            return out
        buf = spot * breakout_buffer_pct

        # Look at the previous bar to detect a fresh break (current bar must
        # be the first to close past the level).
        if len(sess) >= 2:
            prev = sess.iloc[-2]
        else:
            return out

        # LONG breakout
        if (last["close"] > or_high + buf
                and prev["close"] <= or_high + buf
                and (hiro_z is None or hiro_z > 0.3)):
            entry = float(last["close"])
            stop = float(or_low)  # opposite end of OR
            r_unit = entry - stop
            if r_unit > 0:
                # TP1 = nearest wall above; TP2 = 2× OR range from entry
                t1 = (float(cw) if (cw and cw > entry) else entry + 1.5 * r_unit)
                t2 = entry + 2.0 * (or_high - or_low)
                sig = _build_signal(
                    last_et, symbol, regime, "trend_breakout", "LONG",
                    entry, stop, t1, t2,
                    rationale=(
                        f"Cierre {entry:.2f} > OR.high {or_high:.2f} en régimen "
                        f"−Γ. Stop al opposite end OR {or_low:.2f}."
                    ),
                    inputs=dict(spot=spot, or_high=or_high, or_low=or_low,
                                atr=last_atr, net_gex=net_gex, hiro_z=hiro_z,
                                call_wall=cw),
                    base_conf=0.50,
                )
                if sig is not None:
                    out.append(sig)

        # SHORT breakdown
        if (last["close"] < or_low - buf
                and prev["close"] >= or_low - buf
                and (hiro_z is None or hiro_z < -0.3)):
            entry = float(last["close"])
            stop = float(or_high)
            r_unit = stop - entry
            if r_unit > 0:
                t1 = (float(pw) if (pw and pw < entry) else entry - 1.5 * r_unit)
                t2 = entry - 2.0 * (or_high - or_low)
                sig = _build_signal(
                    last_et, symbol, regime, "trend_breakout", "SHORT",
                    entry, stop, t1, t2,
                    rationale=(
                        f"Cierre {entry:.2f} < OR.low {or_low:.2f} en régimen "
                        f"−Γ. Stop al opposite end OR {or_high:.2f}."
                    ),
                    inputs=dict(spot=spot, or_high=or_high, or_low=or_low,
                                atr=last_atr, net_gex=net_gex, hiro_z=hiro_z,
                                put_wall=pw),
                    base_conf=0.50,
                )
                if sig is not None:
                    out.append(sig)

    return out


def _build_signal(ts: pd.Timestamp, symbol: str, regime: str,
                  strategy: str, side: str,
                  entry: float, stop: float, t1: float, t2: float,
                  rationale: str, inputs: dict,
                  base_conf: float = 0.5) -> Optional[Signal]:
    r_unit = abs(entry - stop)
    if r_unit <= 0:
        return None
    if side == "LONG":
        rr1 = (t1 - entry) / r_unit
        rr2 = (t2 - entry) / r_unit
    else:
        rr1 = (entry - t1) / r_unit
        rr2 = (entry - t2) / r_unit
    if rr1 < 0.5:
        # Skip signals where TP1 is too close to entry — bad RR.
        return None
    # Confluence bumps confidence:
    conf = base_conf
    hz = inputs.get("hiro_z")
    if hz is not None:
        if (side == "LONG" and hz > 0.5) or (side == "SHORT" and hz < -0.5):
            conf += 0.15
    return Signal(
        timestamp=ts.tz_convert("UTC").isoformat(),
        symbol=symbol,
        regime=regime,
        strategy=strategy,
        side=side,
        entry=round(float(entry), 4),
        stop=round(float(stop), 4),
        target1=round(float(t1), 4),
        target2=round(float(t2), 4),
        r_unit=round(float(r_unit), 4),
        rr_target1=round(float(rr1), 3),
        rr_target2=round(float(rr2), 3),
        confidence=round(float(min(conf, 0.95)), 3),
        rationale=rationale,
        inputs=inputs,
    )
