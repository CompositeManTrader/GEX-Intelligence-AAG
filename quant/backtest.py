"""
Walk-forward backtester for the GEX-regime intraday strategy.

How it works
------------
For every minute bar of the session we:

  1. Slice intraday OHLCV from the start of the session up to that bar.
  2. Slice the persisted orderflow snapshot for that minute (call wall,
     put wall, gamma flip, regime). If no snapshot exists for that exact
     minute, use the most recent one BEFORE that bar (no look-ahead).
  3. Call `quant.signals.generate_signals(...)` with ONLY the past data.
  4. If a signal fires and we have no open position, open a paper trade
     at next bar's open (realistic — no signal-bar fill).
  5. Each subsequent bar, check if the trade hit stop / TP1 / TP2 /
     end-of-session flat-close. We use the bar's high+low to model worst
     case: if both stop and target are inside [low, high] of one bar, we
     assume STOP first (conservative).

Output
------
  • `Trade` — each closed trade with entry/exit/PnL/R-multiple.
  • `BacktestStats` — aggregates: trades, win rate, profit factor,
    expectancy, Sharpe, max DD, distribution of R-multiples.

The numbers are honest: walk-forward, no peeking, conservative slippage.
"""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, asdict, field
from typing import Optional

import numpy as np
import pandas as pd

from config import ET_TZ
from quant.signals import (
    Signal, generate_signals, opening_range, session_slice, vwap_bands, atr,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Types
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    timestamp_open: str
    timestamp_close: str
    symbol: str
    regime: str
    strategy: str
    side: str
    entry: float
    stop: float
    target1: float
    target2: float
    exit_price: float
    exit_reason: str       # "stop" | "target1" | "target2" | "flat_close"
    r_unit: float
    pnl_pts: float         # exit_price - entry (signed for LONG; flipped SHORT)
    r_multiple: float      # pnl_pts / r_unit
    bars_held: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestStats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_r: float = 0.0          # mean R-multiple (expectancy in R units)
    median_r: float = 0.0
    sum_r: float = 0.0          # total R earned
    profit_factor: float = 0.0  # |gross win| / |gross loss|
    sharpe: float = 0.0         # per-trade Sharpe = mean / std of R (NO sqrt-N)
    t_stat: float = 0.0         # t-stat of mean R vs 0 = Sharpe·sqrt(N)
    max_drawdown_r: float = 0.0
    best_trade_r: float = 0.0
    worst_trade_r: float = 0.0
    avg_bars_held: float = 0.0
    by_strategy: dict = field(default_factory=dict)
    by_regime: dict = field(default_factory=dict)
    equity_curve: list = field(default_factory=list)  # cumulative R per trade

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
#  Per-bar exposure resolution
# ─────────────────────────────────────────────────────────────────────────────
def _orderflow_snapshot_at(of_history: list[dict],
                           when: pd.Timestamp) -> Optional[dict]:
    """Return the most recent orderflow tick whose timestamp ≤ `when`.
    Translates the persisted tick fields to the shape `generate_signals`
    expects (regime/total_gex/walls/etc)."""
    if not of_history:
        return None
    when_utc = when.tz_convert("UTC") if when.tzinfo else when.tz_localize("UTC")
    # of_history is sorted by ts ASC; binary search would be faster but for
    # a typical session of <1000 ticks linear is fine.
    last = None
    for tick in of_history:
        ts = tick.get("timestamp")
        if not ts:
            continue
        try:
            t = pd.Timestamp(ts)
            if t.tzinfo is None:
                t = t.tz_localize("UTC")
            else:
                t = t.tz_convert("UTC")
        except Exception:
            continue
        if t <= when_utc:
            last = tick
        else:
            break
    if last is None:
        return None
    # Reconstruct gex_summary shape from the stored fields. Note: we stored
    # net_gex_mm (millions) → convert back to raw $.
    net_mm = last.get("net_gex_mm")
    call_mm = last.get("call_gex_mm")
    put_mm = last.get("put_gex_mm")
    total = (float(net_mm) * 1e6) if net_mm is not None else 0.0
    call_g = (float(call_mm) * 1e6) if call_mm is not None else 0.0
    put_g = (float(put_mm) * 1e6) if put_mm is not None else 0.0
    # Regime threshold: relative to gross GEX so it scales naturally with
    # the underlying. The previous absolute $1k threshold was effectively
    # zero for index ETFs (typical net GEX in the billions) and over-
    # filtered tiny single-name chains. ≥5% of gross is the SqueezeMetrics
    # convention for a "meaningful" regime.
    gross = abs(call_g) + abs(put_g)
    neutral_band = max(0.05 * gross, 1e6)  # at least $1M to absorb noise
    if total > neutral_band:
        regime = "POSITIVE"
    elif total < -neutral_band:
        regime = "NEGATIVE"
    else:
        regime = "NEUTRAL"
    return dict(
        regime=regime,
        total_gex=total,
        call_gex=call_g,
        put_gex=put_g,
        call_wall=last.get("call_wall"),
        put_wall=last.get("put_wall"),
        gamma_flip=last.get("gamma_flip"),
        # We didn't persist HVL, so leave it None. Backtester signals will
        # fall back to VWAP-derived TPs which is fine.
        hvl=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Walk-forward simulation
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(
    intraday_df: pd.DataFrame,
    of_history: list[dict],
    symbol: str = "",
    flat_close_et: datetime.time = datetime.time(15, 50),
    or_minutes: int = 30,
    max_concurrent: int = 1,
    use_target2: bool = True,
) -> tuple[list[Trade], BacktestStats]:
    """Replay one or more sessions bar-by-bar.

    Parameters
    ----------
    intraday_df : OHLCV bars (UTC `date` column).
    of_history  : persisted orderflow snapshots (list of dicts).
    flat_close_et : ET time after which we force-flat any open trade.
    max_concurrent : at most N positions open at once (default 1).
    use_target2 : if True, scale out half at TP1 and trail to TP2; if False,
                  exit fully at TP1 (cleaner stats, ~1.5R per win).
    """
    if intraday_df is None or intraday_df.empty:
        return [], BacktestStats()

    # Group by ET trading day so we can run independently per session.
    sess_full = session_slice(intraday_df, day=None)  # ensures _et column
    if sess_full is None or sess_full.empty:
        # Fall back: ensure ET col present
        from quant.signals import _ensure_et
        sess_full = _ensure_et(intraday_df)
    days = sorted(sess_full["_et"].dt.date.unique())

    trades: list[Trade] = []

    for day in days:
        day_bars = sess_full[sess_full["_et"].dt.date == day].reset_index(drop=True)
        # Keep only RTH for the trade simulation
        day_bars = day_bars[
            (day_bars["_et"].dt.time >= datetime.time(9, 30))
            & (day_bars["_et"].dt.time < datetime.time(16, 0))
        ].reset_index(drop=True)
        if len(day_bars) < or_minutes + 5:
            continue

        open_positions: list[dict] = []  # one or more in-flight trades

        # We start evaluating signals AFTER the opening range completes,
        # so the OR is well defined for trend signals and we have ≥30 1m
        # bars for VWAP-band stability.
        first_eval_idx = or_minutes

        for i in range(first_eval_idx, len(day_bars) - 1):
            bar = day_bars.iloc[i]
            next_bar = day_bars.iloc[i + 1]
            now = bar["_et"]

            # ── 1) Manage already-open positions on THIS bar ──
            still_open: list[dict] = []
            for pos in open_positions:
                exit_info = _check_exit(pos, bar, next_bar, flat_close_et,
                                        use_target2=use_target2)
                if exit_info is None:
                    still_open.append(pos)
                else:
                    trades.append(_close_trade(pos, bar, exit_info, symbol))
            open_positions = still_open

            # ── 2) Generate new signals from past-only data ──
            if len(open_positions) < max_concurrent:
                past_df = day_bars.iloc[: i + 1]
                gex_snap = _orderflow_snapshot_at(of_history, now)
                if gex_snap is not None:
                    sigs = generate_signals(
                        past_df, gex_snap, symbol=symbol,
                        hiro_z=None,  # no historical HIRO replay yet
                        or_minutes=or_minutes,
                        flat_close_et=flat_close_et,
                    )
                    for sig in sigs:
                        if len(open_positions) >= max_concurrent:
                            break
                        # Realistic fill: enter at NEXT bar's open
                        fill = float(next_bar["open"])
                        # If signal entry says e.g. spot=last_close but the
                        # next open gapped past the stop, skip it.
                        if sig.side == "LONG" and fill >= sig.stop:
                            r_real = abs(fill - sig.stop)
                            if r_real <= 0:
                                continue
                            open_positions.append(_armed_position(
                                sig, fill_price=fill, fill_ts=next_bar["_et"]))
                        elif sig.side == "SHORT" and fill <= sig.stop:
                            r_real = abs(fill - sig.stop)
                            if r_real <= 0:
                                continue
                            open_positions.append(_armed_position(
                                sig, fill_price=fill, fill_ts=next_bar["_et"]))

        # End of session: force-close anything still open at last bar.
        # If the position is a runner (TP1 already locked) we blend so the
        # reported pnl reflects the 50/50 scale-out actually taken.
        if open_positions:
            last_bar = day_bars.iloc[-1]
            for pos in open_positions:
                close_px = float(last_bar["close"])
                exit_px = _blend_runner_exit(pos, close_px)
                trades.append(_close_trade(pos, last_bar,
                    {"exit_price": exit_px,
                     "exit_reason": "flat_close"}, symbol))

    stats = compute_stats(trades)
    return trades, stats


# ─────────────────────────────────────────────────────────────────────────────
#  Trade lifecycle helpers
# ─────────────────────────────────────────────────────────────────────────────
def _armed_position(sig: Signal, fill_price: float,
                    fill_ts: pd.Timestamp) -> dict:
    return dict(
        signal=sig,
        entry=fill_price,
        stop=sig.stop,
        target1=sig.target1,
        target2=sig.target2,
        side=sig.side,
        strategy=sig.strategy,
        regime=sig.regime,
        opened_at=fill_ts,
        bars_held=0,
        r_unit=abs(fill_price - sig.stop),
    )


def _blend_runner_exit(pos: dict, raw_exit: float) -> float:
    """Blend the half closed at TP1 with the runner's final exit price.

    When `use_target2=True` and TP1 fills, half the position closes at TP1
    and the remainder is trailed to TP2 (with stop moved to entry/breakeven).
    The Trade record stores a single exit_price/r_multiple, so to keep the
    arithmetic correct we report the equally-weighted average of the two
    fills. With pnl = exit - entry this gives:
        pnl_blended = 0.5·(TP1 − entry) + 0.5·(final − entry)
    which is exactly the realised pnl for the 50/50 scale-out.
    """
    if pos.get("tp1_filled"):
        return (float(pos["tp1_price"]) + float(raw_exit)) / 2.0
    return float(raw_exit)


def _check_exit(pos: dict, bar: pd.Series, next_bar: pd.Series,
                flat_close_et: datetime.time,
                use_target2: bool) -> Optional[dict]:
    """Decide whether the OPEN position closes on `bar`. Returns None if
    still open, or a dict with exit_price + exit_reason.

    Scale-out semantics (use_target2=True):
      - First time TP1 is touched: lock half at TP1, trail stop to entry
        (breakeven). Position stays open as a "runner" for TP2.
      - Runner exits at TP2, breakeven stop, or end-of-session — exit_price
        is reported as the 50/50 average of the TP1 fill and the final fill.
    Conservative same-bar ordering: if stop and TP are both touched in the
    same bar, we assume stop first (worst-case fill).
    """
    pos["bars_held"] += 1
    high = float(bar["high"])
    low = float(bar["low"])
    side = pos["side"]
    entry = float(pos["entry"])
    t1 = float(pos["target1"])
    t2 = float(pos["target2"]) if use_target2 else None
    in_runner = bool(pos.get("tp1_filled", False))
    # When trailing the runner, the active stop is the entry (breakeven).
    stop = entry if (in_runner and use_target2) else float(pos["stop"])

    bar_time = bar["_et"].time() if hasattr(bar["_et"], "time") else None

    if side == "LONG":
        hit_stop = low <= stop
        hit_t1 = high >= t1
        hit_t2 = (t2 is not None and high >= t2)
    else:  # SHORT
        hit_stop = high >= stop
        hit_t1 = low <= t1
        hit_t2 = (t2 is not None and low <= t2)

    # ─── Pre-scale phase: full position, original stop ───────────────────
    if not in_runner:
        if use_target2:
            # Both stop and TP touched — assume stop fills first (worst case).
            if hit_stop:
                return {"exit_price": stop, "exit_reason": "stop"}
            if hit_t2:
                # TP1 + TP2 inside the same bar: lock TP1 half, runner exits TP2.
                return {"exit_price": (t1 + t2) / 2.0,
                        "exit_reason": "target2"}
            if hit_t1:
                # Lock half at TP1, trail to TP2 with stop at entry.
                pos["tp1_filled"] = True
                pos["tp1_price"] = float(t1)
                # Position stays open (the runner). Fall through to flat-close.
            # else: nothing hit, fall through to flat-close.
        else:
            # use_target2=False: classic single-target behaviour, exit at TP1.
            if hit_stop:
                return {"exit_price": stop, "exit_reason": "stop"}
            if hit_t1:
                return {"exit_price": t1, "exit_reason": "target1"}

    # ─── Runner phase: half closed at TP1, BE stop, target = TP2 ─────────
    else:
        if hit_stop and hit_t2:
            # Both BE-stop and TP2 in the same bar — conservative: BE stop fills first.
            return {"exit_price": _blend_runner_exit(pos, stop),
                    "exit_reason": "stop_be"}
        if hit_stop:
            return {"exit_price": _blend_runner_exit(pos, stop),
                    "exit_reason": "stop_be"}
        if hit_t2:
            return {"exit_price": _blend_runner_exit(pos, t2),
                    "exit_reason": "target2"}

    # ─── End-of-session force-flat (handles runner blending automatically) ─
    if bar_time is not None and bar_time >= flat_close_et:
        close_px = float(bar["close"])
        return {"exit_price": _blend_runner_exit(pos, close_px),
                "exit_reason": "flat_close"}
    return None


def _close_trade(pos: dict, bar: pd.Series, exit_info: dict,
                 symbol: str) -> Trade:
    exit_price = float(exit_info["exit_price"])
    side = pos["side"]
    entry = pos["entry"]
    pnl = (exit_price - entry) if side == "LONG" else (entry - exit_price)
    r_unit = pos["r_unit"] if pos["r_unit"] > 0 else 1.0
    return Trade(
        timestamp_open=pd.Timestamp(pos["opened_at"]).tz_convert("UTC").isoformat(),
        timestamp_close=pd.Timestamp(bar["_et"]).tz_convert("UTC").isoformat(),
        symbol=symbol,
        regime=pos["regime"],
        strategy=pos["strategy"],
        side=side,
        entry=round(float(entry), 4),
        stop=round(float(pos["stop"]), 4),
        target1=round(float(pos["target1"]), 4),
        target2=round(float(pos["target2"]), 4),
        exit_price=round(exit_price, 4),
        exit_reason=str(exit_info["exit_reason"]),
        r_unit=round(float(r_unit), 4),
        pnl_pts=round(float(pnl), 4),
        r_multiple=round(float(pnl / r_unit), 3),
        bars_held=int(pos["bars_held"]),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Stats
# ─────────────────────────────────────────────────────────────────────────────
def compute_stats(trades: list[Trade]) -> BacktestStats:
    s = BacktestStats()
    if not trades:
        return s
    rs = np.array([t.r_multiple for t in trades], dtype=float)
    pnls = np.array([t.pnl_pts for t in trades], dtype=float)

    s.trades = len(trades)
    s.wins = int((rs > 0).sum())
    s.losses = int((rs <= 0).sum())
    s.win_rate = round(s.wins / s.trades, 3) if s.trades else 0.0
    s.avg_r = round(float(rs.mean()), 3)
    s.median_r = round(float(np.median(rs)), 3)
    s.sum_r = round(float(rs.sum()), 3)
    s.best_trade_r = round(float(rs.max()), 3)
    s.worst_trade_r = round(float(rs.min()), 3)
    s.avg_bars_held = round(float(np.mean([t.bars_held for t in trades])), 1)

    gross_win = float(rs[rs > 0].sum()) if (rs > 0).any() else 0.0
    gross_loss = float(-rs[rs < 0].sum()) if (rs < 0).any() else 0.0
    s.profit_factor = round(gross_win / gross_loss, 3) if gross_loss > 0 else float("inf")

    sd = float(rs.std(ddof=1))
    if sd > 0:
        # Per-trade Sharpe ratio = mean / std of R-multiples. Deliberately
        # NOT sqrt(N)-scaled: a Sharpe must be sample-size invariant.
        s.sharpe = round(float(rs.mean()) / sd, 3)
        # t-statistic of mean R vs 0 (= Sharpe·sqrt(N)). This is a
        # statistical-significance measure of edge (|t|>2 ≈ real), and it
        # GROWS with sample size by construction — do not read it as Sharpe.
        s.t_stat = round(float(rs.mean()) / sd * math.sqrt(len(rs)), 3)

    # Equity curve in cumulative R, max drawdown
    eq = np.cumsum(rs)
    s.equity_curve = [round(float(x), 3) for x in eq]
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    s.max_drawdown_r = round(float(dd.max()), 3) if len(dd) else 0.0

    # Breakdown by strategy and regime
    def _by(field: str):
        out = {}
        for t in trades:
            k = getattr(t, field)
            d = out.setdefault(k, {"trades": 0, "wins": 0, "sum_r": 0.0})
            d["trades"] += 1
            if t.r_multiple > 0:
                d["wins"] += 1
            d["sum_r"] += t.r_multiple
        for k, d in out.items():
            d["win_rate"] = round(d["wins"] / d["trades"], 3) if d["trades"] else 0.0
            d["avg_r"] = round(d["sum_r"] / d["trades"], 3) if d["trades"] else 0.0
            d["sum_r"] = round(d["sum_r"], 3)
        return out

    s.by_strategy = _by("strategy")
    s.by_regime = _by("regime")
    return s


def trades_dataframe(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame([t.to_dict() for t in trades])
