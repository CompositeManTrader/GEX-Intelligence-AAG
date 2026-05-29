"""
Expected-Move accuracy tracker — pure logic (no I/O).

Records, each session, the range the RND model PREDICTED at the open,
then at the close checks whether the actual close landed inside the
predicted bands. Accumulated over sessions it tells you whether the
model is well-calibrated, over-estimates, or under-estimates volatility
for YOUR symbol — closing the loop between theory and reality.

Calibration logic
-----------------
If the model is well-calibrated:
  · the close falls inside the P10–P90 band ≈ 80% of the time
  · inside P5–P95 ≈ 90%
  · inside the 1σ-equivalent (P16–P84) ≈ 68%

  Observed inside-P10-P90 > 85%  → model OVER-estimates vol (IV rich → sell)
                          ~80%   → well calibrated
                          < 72%  → model UNDER-estimates (fat tails → buy / widen)

Plus the average "move ratio" = |close − open| / σ_implied. If it
consistently exceeds 1, realized vol is beating implied (IV cheap).

This module is pure: it builds the record dict from an RND levels dict,
decides settlement, and computes aggregate stats. All persistence lives
in `data.em_store`.
"""
from __future__ import annotations

from typing import Optional


# Clean-prediction window: only predictions snapshotted within the first
# `CLEAN_WINDOW_MIN` minutes of RTH count toward the headline hit-rate
# (so an open-anchored prediction is a fair test; a 2pm snapshot isn't).
CLEAN_WINDOW_MIN = 45


def build_prediction(symbol: str, date_iso: str, snapshot_ts: str,
                     spot_open: float, dte: int,
                     rnd_levels: dict, rnd_meta: dict) -> Optional[dict]:
    """Assemble a prediction record from an RND levels dict
    (`quant.rnd.rnd_levels`) and meta (`quant.rnd.build_rnd`).

    Returns a flat dict ready for the store, or None if the levels are
    incomplete.
    """
    if not rnd_levels or "percentiles" not in rnd_levels:
        return None
    pct = rnd_levels["percentiles"]
    needed = ("p5", "p10", "p25", "p50", "p75", "p90", "p95")
    if any(pct.get(k) is None for k in needed):
        return None
    return {
        "symbol": symbol,
        "date": date_iso,
        "snapshot_ts": snapshot_ts,
        "spot_open": float(spot_open),
        "dte": int(dte),
        "rnd_method": (rnd_meta or {}).get("method"),
        "rnd_p05": float(pct["p5"]),
        "rnd_p10": float(pct["p10"]),
        "rnd_p25": float(pct["p25"]),
        "rnd_p50": float(pct["p50"]),
        "rnd_p75": float(pct["p75"]),
        "rnd_p90": float(pct["p90"]),
        "rnd_p95": float(pct["p95"]),
        "rnd_p16": float(rnd_levels.get("p16") or pct["p10"]),
        "rnd_p84": float(rnd_levels.get("p84") or pct["p90"]),
        "rnd_mode": float(rnd_levels.get("mode") or pct["p50"]),
        "rnd_std": float(rnd_levels.get("std") or 0.0),
        # settlement fields, filled later
        "close_actual": None,
        "move_actual": None,
        "inside_p10_p90": None,
        "inside_p05_p95": None,
        "inside_1sigma": None,
        "settled": 0,
    }


def settle_record(record: dict, close_actual: float) -> dict:
    """Given a stored prediction and the actual close, compute the
    settlement fields. Returns a dict of just the fields to UPDATE."""
    spot_open = float(record.get("spot_open") or 0.0)
    p10 = float(record.get("rnd_p10"))
    p90 = float(record.get("rnd_p90"))
    p05 = float(record.get("rnd_p05"))
    p95 = float(record.get("rnd_p95"))
    p16 = float(record.get("rnd_p16"))
    p84 = float(record.get("rnd_p84"))
    c = float(close_actual)
    return {
        "close_actual": c,
        "move_actual": abs(c - spot_open),
        "inside_p10_p90": 1 if (p10 <= c <= p90) else 0,
        "inside_p05_p95": 1 if (p05 <= c <= p95) else 0,
        "inside_1sigma": 1 if (p16 <= c <= p84) else 0,
        "settled": 1,
    }


def _snapshot_minutes_into_rth(snapshot_ts: str) -> Optional[float]:
    """Minutes from 09:30 ET to the snapshot. Used to flag 'clean'
    open-anchored predictions. Returns None if unparseable."""
    import datetime
    try:
        from config import ET_TZ
        ts = datetime.datetime.fromisoformat(str(snapshot_ts))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        et = ts.astimezone(ET_TZ)
        return (et.hour - 9) * 60 + (et.minute - 30)
    except Exception:
        return None


def accuracy_stats(rows: list[dict], only_clean: bool = True) -> dict:
    """Aggregate calibration stats over settled prediction rows.

    `only_clean=True` restricts the headline hit-rates to predictions
    snapshotted within the first `CLEAN_WINDOW_MIN` minutes of RTH —
    a fair open-anchored test. Set False to include all snapshots.
    """
    settled = [r for r in rows if r.get("settled") and r.get("close_actual") is not None]
    if only_clean:
        clean = []
        for r in settled:
            m = _snapshot_minutes_into_rth(r.get("snapshot_ts"))
            if m is not None and 0 <= m <= CLEAN_WINDOW_MIN:
                clean.append(r)
        used = clean
    else:
        used = settled

    n = len(used)
    out = {
        "n_settled": len(settled),
        "n_clean": n,
        "only_clean": only_clean,
        "hit_p10_p90": None,
        "hit_p05_p95": None,
        "hit_1sigma": None,
        "avg_move_ratio": None,
        "verdict": "insufficient_data",
        "ready": n >= 10,
    }
    if n == 0:
        return out

    h_8 = sum(1 for r in used if r.get("inside_p10_p90")) / n
    h_9 = sum(1 for r in used if r.get("inside_p05_p95")) / n
    h_1s = sum(1 for r in used if r.get("inside_1sigma")) / n
    out["hit_p10_p90"] = round(h_8, 3)
    out["hit_p05_p95"] = round(h_9, 3)
    out["hit_1sigma"] = round(h_1s, 3)

    # Move ratio = |close − open| / σ_implied (avg over rows with σ>0)
    ratios = []
    for r in used:
        sd = float(r.get("rnd_std") or 0.0)
        mv = r.get("move_actual")
        if sd > 0 and mv is not None:
            ratios.append(float(mv) / sd)
    if ratios:
        out["avg_move_ratio"] = round(sum(ratios) / len(ratios), 3)

    # Calibration verdict (needs ≥10 clean samples to be meaningful)
    if n >= 10:
        if h_8 > 0.85:
            out["verdict"] = "over_estimates"   # IV rich → sell vol
        elif h_8 < 0.72:
            out["verdict"] = "under_estimates"  # fat tails → buy / widen
        else:
            out["verdict"] = "well_calibrated"
    return out


def verdict_text(stats: dict) -> tuple[str, str]:
    """Human-readable (label, color_hex) for the verdict."""
    v = stats.get("verdict")
    if not stats.get("ready"):
        n = stats.get("n_clean", 0)
        return (f"Acumulando datos ({n}/10 sesiones limpias)", "#9090b0")
    if v == "over_estimates":
        return ("Modelo SOBRE-estima vol → IV cara, favor VENDER vol", "#f59e0b")
    if v == "under_estimates":
        return ("Modelo SUB-estima vol → colas gordas, COMPRA vol / amplía wings", "#f43f5e")
    if v == "well_calibrated":
        return ("Modelo BIEN CALIBRADO → opera con confianza normal", "#22c55e")
    return ("—", "#9090b0")
