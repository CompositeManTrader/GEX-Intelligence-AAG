"""
Gamma zones — clustered ranking of dealer gamma concentration.

Where ``call_wall`` / ``put_wall`` / ``hvl`` each return a single strike,
gamma zones return *ranges* with width and rank. The convention used by
MenthorQ / Tradytics / GEXBot:

    P1 = primary cluster   (largest integrated |GEX|)
    P2 = secondary
    P3 = tertiary
    ...

A "cluster" is a contiguous range of strikes around a local |GEX| peak,
expanded outward to where |GEX| falls below `peak_threshold_pct` of the
peak. This captures the realistic *width* of a gamma wall instead of
collapsing it to a single strike.

Zones are direction-agnostic: the ranking is by raw |GEX| concentration,
and `side` is metadata (call_dominant / put_dominant / mixed). This is
useful precisely because real walls don't always align with the
SqueezeMetrics convention — sometimes the strongest cluster is on the
"wrong" side of spot, and the trader needs to know.

Public API
----------
    GammaZone                — dataclass with rank/label/strikes/width/score
    find_gamma_zones(df, …)  — top-N clusters from a per-strike GEX profile
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd

# scipy.signal.find_peaks is the standard tool but already-imported scipy
# would be heavy; only import on first call so cold imports stay light.


@dataclass
class GammaZone:
    """A ranked gamma cluster with explicit width and strength."""
    rank: int                    # 1 = strongest
    label: str                   # "P1", "P2", "P3", ...
    peak_strike: float
    low_strike: float
    high_strike: float
    width: float                 # high - low (in strike units)
    peak_gex_mm: float           # signed Net GEX at the peak strike, $M
    integrated_gex_mm: float     # Σ|Net_GEX| inside the cluster, $M (the score)
    side: str                    # "call_dominant" | "put_dominant" | "mixed"
    distance_pct: float          # (peak − spot) / spot × 100
    is_above_spot: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _smooth(y: np.ndarray, win: int = 3) -> np.ndarray:
    """Boxcar smoother — same kernel used in `_find_wall` so semantics
    align across the codebase."""
    if len(y) <= win:
        return y.astype(float).copy()
    w = np.ones(win) / win
    return np.convolve(y.astype(float), w, mode="same")


def _local_maxima(y: np.ndarray, prominence: float) -> np.ndarray:
    """Find local maxima with the given prominence threshold.

    Tries scipy.signal.find_peaks first (preferred — robust prominence
    semantics). Falls back to a pure-numpy implementation if scipy is
    not present, so the module still imports in lightweight
    environments.
    """
    try:
        from scipy.signal import find_peaks
        peaks, _props = find_peaks(y, prominence=prominence)
        return peaks
    except Exception:
        # Naive fallback: any sample greater than both neighbours that
        # exceeds the absolute prominence threshold.
        out = []
        for i in range(1, len(y) - 1):
            if y[i] > y[i - 1] and y[i] > y[i + 1] and y[i] >= prominence:
                out.append(i)
        return np.asarray(out, dtype=int)


def find_gamma_zones(
    gex_df: Optional[pd.DataFrame], spot: float,
    top_n: int = 3,
    peak_threshold_pct: float = 0.50,
    min_peak_prominence_pct: float = 0.10,
) -> list[GammaZone]:
    """Detect the top-N gamma clusters from a per-strike GEX profile.

    Parameters
    ----------
    gex_df : DataFrame
        Must have columns ``Strike`` and ``Net_GEX`` (in $, signed by
        the SqueezeMetrics dealer convention used in
        :func:`quant.exposures.compute_gex_profile`).
    spot : float
        Current spot — used to compute distance and side metadata.
    top_n : int
        Maximum number of zones to return. The actual count may be
        smaller if there are fewer separable peaks.
    peak_threshold_pct : float (0, 1]
        Boundary cutoff. A strike is part of the cluster if its
        smoothed |GEX| ≥ ``peak_threshold_pct × peak``. Default 0.50
        (the half-max width convention).
    min_peak_prominence_pct : float (0, 1]
        Minimum peak prominence as a fraction of the maximum smoothed
        |GEX| in the chain. Filters out tiny noise peaks.

    Returns
    -------
    list[GammaZone]
        Sorted by rank (1 = strongest). Empty list when input is too
        small or has no real peaks.
    """
    if gex_df is None or gex_df.empty or spot <= 0:
        return []
    needed = {"Strike", "Net_GEX"}
    if not needed.issubset(gex_df.columns):
        return []

    df = (gex_df.dropna(subset=["Strike", "Net_GEX"])
                .sort_values("Strike")
                .reset_index(drop=True))
    if len(df) < 3:
        return []

    strikes = df["Strike"].to_numpy(dtype=float)
    net_gex = df["Net_GEX"].to_numpy(dtype=float)
    abs_gex = np.abs(net_gex)
    abs_smooth = _smooth(abs_gex, 3)
    max_abs = float(abs_smooth.max())
    if max_abs <= 0:
        return []

    # ── Locate candidate peaks ──────────────────────────────────────────
    min_prom = min_peak_prominence_pct * max_abs
    peak_idxs = _local_maxima(abs_smooth, prominence=min_prom)
    if len(peak_idxs) == 0:
        # Fall back to global argmax so we always return at least one
        # zone when there *is* gamma in the chain (better than blank).
        peak_idxs = np.array([int(np.argmax(abs_smooth))])

    # ── Expand each peak into a cluster ─────────────────────────────────
    candidates: list[dict] = []
    for pidx in peak_idxs:
        peak_val = float(abs_smooth[pidx])
        if peak_val <= 0:
            continue
        boundary = peak_val * peak_threshold_pct
        left = int(pidx)
        while left > 0 and abs_smooth[left - 1] >= boundary:
            left -= 1
        right = int(pidx)
        while right < len(abs_smooth) - 1 and abs_smooth[right + 1] >= boundary:
            right += 1
        # Score = integrated raw |GEX| over the cluster (NOT smoothed —
        # the smoother is only for boundary detection, not magnitude).
        score = float(np.sum(abs_gex[left : right + 1]))
        zone_net = float(np.sum(net_gex[left : right + 1]))
        # Side: a cluster is "mixed" only when its net is small relative
        # to its score (i.e. calls and puts roughly cancel inside).
        if score > 0 and abs(zone_net) < 0.10 * score:
            side = "mixed"
        elif zone_net > 0:
            side = "call_dominant"
        else:
            side = "put_dominant"
        candidates.append({
            "left": left,
            "right": right,
            "peak_idx": int(pidx),
            "peak_strike": float(strikes[pidx]),
            "low_strike": float(strikes[left]),
            "high_strike": float(strikes[right]),
            "width": float(strikes[right] - strikes[left]),
            "peak_gex_mm": float(net_gex[pidx]) / 1e6,
            "integrated_gex_mm": score / 1e6,
            "score_raw": score,
            "side": side,
        })

    # ── Rank by integrated score ─────────────────────────────────────────
    candidates.sort(key=lambda c: -c["score_raw"])

    # ── Resolve overlaps — strongest zone wins, weaker overlapping
    #    zones are discarded entirely (rather than truncated, which
    #    would lie about their boundary).
    accepted: list[dict] = []
    used = np.zeros(len(strikes), dtype=bool)
    for c in candidates:
        sl = used[c["left"] : c["right"] + 1]
        if sl.any():
            continue
        accepted.append(c)
        used[c["left"] : c["right"] + 1] = True
        if len(accepted) >= top_n:
            break

    # ── Materialise GammaZone objects ────────────────────────────────────
    zones: list[GammaZone] = []
    for i, c in enumerate(accepted):
        zones.append(GammaZone(
            rank=i + 1,
            label=f"P{i + 1}",
            peak_strike=round(c["peak_strike"], 2),
            low_strike=round(c["low_strike"], 2),
            high_strike=round(c["high_strike"], 2),
            width=round(c["width"], 2),
            peak_gex_mm=round(c["peak_gex_mm"], 2),
            integrated_gex_mm=round(c["integrated_gex_mm"], 2),
            side=c["side"],
            distance_pct=round((c["peak_strike"] - spot) / spot * 100, 2),
            is_above_spot=bool(c["peak_strike"] > spot),
        ))
    return zones


def zones_to_records(zones: list[GammaZone]) -> list[dict]:
    """Convert a zones list into JSON-friendly dicts. Useful for
    persistence and for passing to chart overlays."""
    return [z.to_dict() for z in zones]


def spot_in_zone(zones: list[GammaZone],
                 spot: float) -> Optional[GammaZone]:
    """Return the zone (if any) whose [low, high] contains the spot.
    When the spot is *between* zones it returns None — useful for the
    'pinning probable / test pendiente' classification in widgets."""
    if not zones or spot is None:
        return None
    for z in zones:
        if z.low_strike <= spot <= z.high_strike:
            return z
    return None
