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
) -> dict:
    """Single orderflow observation tagged with UTC timestamp.

    All monetary fields are scaled to millions so the charts fit in a small
    y-axis range without axis-label clutter.
    """
    def _mm(d: Optional[dict], key: str) -> Optional[float]:
        v = _safe(d, key)
        if v is None:
            return None
        try:
            return float(v) / 1e6
        except (TypeError, ValueError):
            return None

    return dict(
        timestamp=datetime.datetime.utcnow().isoformat(),
        spot=float(spot) if spot else None,
        # GEX
        net_gex_mm=_mm(gex_sum, "total_gex"),
        call_gex_mm=_mm(gex_sum, "call_gex"),
        put_gex_mm=_mm(gex_sum, "put_gex"),
        call_wall=_safe(gex_sum, "call_wall"),
        put_wall=_safe(gex_sum, "put_wall"),
        gamma_flip=_safe(gex_sum, "gamma_flip"),
        # DEX
        net_dex_mm=_mm(dex_sum, "total_dex"),
        call_dex_mm=_mm(dex_sum, "call_dex"),
        put_dex_mm=_mm(dex_sum, "put_dex"),
        # VEX (convexity proxy — $ delta per +1 IV pt)
        net_vex_mm=_mm(vex_sum, "total_vex"),
        call_vex_mm=_mm(vex_sum, "call_vex"),
        put_vex_mm=_mm(vex_sum, "put_vex"),
    )


def update_orderflow_history(history: list, new_point: dict,
                             max_len: int = 500) -> list:
    """Append a tick to the rolling orderflow history, bounded to max_len."""
    if not isinstance(history, list):
        history = []
    history.append(new_point)
    if len(history) > max_len:
        history = history[-max_len:]
    return history
