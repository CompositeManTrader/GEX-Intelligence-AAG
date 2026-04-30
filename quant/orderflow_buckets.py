"""
DTE-bucketed dealer exposures.

Net GEX/DEX/VEX aggregated over the full 0–60 DTE chain hides regime
information that intraday traders need: 0DTE flow can be flipping the
sign of net GEX while the structural monthly book stays positive. The
trader sees "+$1B Net GEX" and feels safe; meanwhile the 0DTE leg is
−$300M and likely to drive a violent close.

This module slices the chain into three canonical buckets and returns
fully-formed (df, summary) tuples for each one, reusing the existing
`compute_*_profile` plumbing in `quant.exposures`.

Buckets
-------
  · 0DTE        DTE == 0          (today's expiry)
  · WEEK        1 <= DTE <= 7     (next 5 trading days)
  · MONTH       8 <= DTE <= 60    (structural)
"""
from __future__ import annotations

from typing import Tuple

import pandas as pd

from quant.exposures import (
    compute_dex_profile, compute_gex_profile, compute_vex_profile,
)


# Canonical bucket boundaries — keep in sync with persistence schema.
BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0dte",  0, 0),
    ("week",  1, 7),
    ("month", 8, 60),
)


def compute_gex_buckets(calls: pd.DataFrame, puts: pd.DataFrame,
                        spot: float, symbol: str = "",
                        min_oi: int = 0,
                        ) -> dict[str, Tuple[pd.DataFrame, dict]]:
    """Return {bucket_name: (gex_profile_df, gex_summary)} for the three
    canonical DTE buckets. Buckets with no contracts return (empty, {})."""
    out: dict = {}
    for name, lo, hi in BUCKETS:
        df, summary = compute_gex_profile(
            calls, puts, spot=spot, symbol=symbol,
            max_dte=hi, min_dte=lo, min_oi=min_oi,
            # Skip the spot-grid flip for buckets — it requires IV which
            # the 0DTE bucket may have noisy values for, and the per-bucket
            # flip is rarely actionable. The aggregate keeps it.
            use_spot_grid_flip=False,
        )
        out[name] = (df, summary)
    return out


def compute_dex_buckets(calls: pd.DataFrame, puts: pd.DataFrame,
                        spot: float, min_oi: int = 0,
                        ) -> dict[str, Tuple[pd.DataFrame, dict]]:
    out: dict = {}
    for name, lo, hi in BUCKETS:
        df, summary = compute_dex_profile(
            calls, puts, spot=spot, max_dte=hi, min_dte=lo, min_oi=min_oi,
        )
        out[name] = (df, summary)
    return out


def compute_vex_buckets(calls: pd.DataFrame, puts: pd.DataFrame,
                        spot: float, symbol: str = "", min_oi: int = 0,
                        ) -> dict[str, Tuple[pd.DataFrame, dict]]:
    out: dict = {}
    for name, lo, hi in BUCKETS:
        df, summary = compute_vex_profile(
            calls, puts, spot=spot, symbol=symbol,
            max_dte=hi, min_dte=lo, min_oi=min_oi,
        )
        out[name] = (df, summary)
    return out


def flatten_to_tick(gex_buckets: dict, dex_buckets: dict,
                    vex_buckets: dict) -> dict:
    """Flatten the three bucket dicts into the flat fields persisted in
    the orderflow_ticks table — `<metric>_<bucket>_mm`. Missing buckets
    map to None so downstream consumers can treat them as 'no data'.
    """
    out: dict = {}

    def _put(prefix: str, summary_key: str, source: dict) -> None:
        for name, _lo, _hi in BUCKETS:
            df, summ = source.get(name, (None, {}))
            v = (summ or {}).get(summary_key)
            try:
                out[f"{prefix}_{name}_mm"] = float(v) / 1e6 if v is not None else None
            except (TypeError, ValueError):
                out[f"{prefix}_{name}_mm"] = None

    _put("gex_net",  "total_gex", gex_buckets)
    _put("gex_call", "call_gex",  gex_buckets)
    _put("gex_put",  "put_gex",   gex_buckets)
    _put("dex_net",  "total_dex", dex_buckets)
    _put("vex_net",  "total_vex", vex_buckets)
    return out
