"""
Orderflow — rolling time-series of dealer exposures (gexbot-style panel).

Three stacked views over time, persisted in Streamlit session_state so they
accumulate across reruns (same pattern used by HIRO):

  · DEX (Delta Exposure)     — call/put/net dealer delta in $M per 1% move
  · Net GEX                  — call/put/net dealer gamma + wall references
  · Net Convexity / VEX      — dealer vanna ($ delta per +1pt IV)

Every exposure is already in dollar terms ($ per 1% move for DEX/GEX,
$ per +1 IV pt for VEX) straight out of quant.exposures, so we just scale
to millions for readability and snapshot the walls + spot at each tick.
"""
from __future__ import annotations

import datetime
from datetime import timezone
from typing import Optional


def _safe(d: Optional[dict], key: str, default=None):
    if not d:
        return default
    v = d.get(key, default)
    return v if v is not None else default


def tick_orderflow(
    spot: float,
    gex_sum: Optional[dict],
    dex_sum: Optional[dict],
    vex_sum: Optional[dict],
    bucket_fields: Optional[dict] = None,
    cex_sum: Optional[dict] = None,
) -> dict:
    """Single orderflow observation tagged with UTC timestamp.

    All monetary fields are scaled to millions so the charts fit in a small
    y-axis range without axis-label clutter.

    Parameters
    ----------
    bucket_fields : dict, optional
        Pre-flattened DTE-bucket fields (per `quant.orderflow_buckets.flatten_to_tick`).
        Already in $M. Merged into the returned tick. Lets the caller
        persist intraday 0DTE / front-week / monthly+ exposures without
        adding a second tick path.
    cex_sum : dict, optional
        Charm-exposure summary so the persisted tick can carry the
        EOD-flow estimate for downstream analytics.
    """
    def _mm(d: Optional[dict], key: str) -> Optional[float]:
        v = _safe(d, key)
        if v is None:
            return None
        try:
            return float(v) / 1e6
        except (TypeError, ValueError):
            return None

    tick = dict(
        timestamp=datetime.datetime.now(timezone.utc).isoformat(),
        spot=float(spot) if spot else None,
        # GEX
        net_gex_mm=_mm(gex_sum, "total_gex"),
        call_gex_mm=_mm(gex_sum, "call_gex"),
        put_gex_mm=_mm(gex_sum, "put_gex"),
        call_wall=_safe(gex_sum, "call_wall"),
        put_wall=_safe(gex_sum, "put_wall"),
        gamma_flip=_safe(gex_sum, "gamma_flip"),
        hvl=_safe(gex_sum, "hvl"),
        regime=_safe(gex_sum, "regime"),
        # DEX
        net_dex_mm=_mm(dex_sum, "total_dex"),
        call_dex_mm=_mm(dex_sum, "call_dex"),
        put_dex_mm=_mm(dex_sum, "put_dex"),
        # VEX (convexity proxy — $ delta per +1 IV pt)
        net_vex_mm=_mm(vex_sum, "total_vex"),
        call_vex_mm=_mm(vex_sum, "call_vex"),
        put_vex_mm=_mm(vex_sum, "put_vex"),
        # CEX
        net_cex_mm=_mm(cex_sum, "total_cex"),
    )
    if bucket_fields:
        # Sanity-coerce all bucket fields to float|None so the persistence
        # layer doesn't have to second-guess types.
        for k, v in bucket_fields.items():
            if v is None:
                tick[k] = None
            else:
                try:
                    tick[k] = float(v)
                except (TypeError, ValueError):
                    tick[k] = None
    return tick


def should_persist_tick(prev: Optional[dict], curr: dict,
                        min_seconds: float = 25.0,
                        max_seconds: float = 120.0,
                        net_gex_pct: float = 0.5,
                        wall_strike_delta: float = 1.0) -> bool:
    """Delta-based persistence: write a tick only when something *moved*.

    Triggers a write if ANY of:
      • >= `max_seconds` since the previous persisted tick
      • |Δ net_gex_mm| / max(|prev|,1) ≥ `net_gex_pct`/100
      • Either wall jumped by ≥ `wall_strike_delta` strike points
      • Regime label changed
      • Previous tick is None (first ever)
    AND at least `min_seconds` have elapsed (rate-limit floor — never
    write more than ~1 row per 25s even on chaotic ticks).

    Trims the orderflow_ticks table by 3-5× without losing information
    that a chart would actually show.
    """
    if prev is None:
        return True
    try:
        t_prev = datetime.datetime.fromisoformat(prev.get("timestamp", ""))
        t_curr = datetime.datetime.fromisoformat(curr.get("timestamp", ""))
    except (TypeError, ValueError):
        return True
    elapsed = (t_curr - t_prev).total_seconds()
    if elapsed < min_seconds:
        return False
    if elapsed >= max_seconds:
        return True

    # Regime change always writes
    if (prev.get("regime") or None) != (curr.get("regime") or None):
        return True

    # Material net-GEX move
    p, c = prev.get("net_gex_mm"), curr.get("net_gex_mm")
    if p is not None and c is not None:
        ref = max(abs(float(p)), 1.0)
        if abs(float(c) - float(p)) / ref >= (net_gex_pct / 100.0):
            return True

    # Wall jump in either direction
    for k in ("call_wall", "put_wall", "gamma_flip"):
        p, c = prev.get(k), curr.get(k)
        if p is None or c is None:
            if p != c:  # wall appeared/disappeared
                return True
            continue
        try:
            if abs(float(c) - float(p)) >= wall_strike_delta:
                return True
        except (TypeError, ValueError):
            return True
    return False


def update_orderflow_history(history: list, new_point: dict,
                             max_len: int = 500) -> list:
    """Append a tick to the rolling orderflow history, bounded to max_len."""
    if not isinstance(history, list):
        history = []
    history.append(new_point)
    if len(history) > max_len:
        history = history[-max_len:]
    return history
