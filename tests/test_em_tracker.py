"""Tests for quant/em_tracker — prediction build, settle, calibration."""
from __future__ import annotations

import datetime

import pytest

from quant.em_tracker import (
    accuracy_stats, build_prediction, settle_record, verdict_text,
    CLEAN_WINDOW_MIN,
)


def _levels(p10=575, p90=585, p5=573, p95=587, p50=580, std=3.0):
    return {
        "percentiles": {"p5": p5, "p10": p10, "p25": 578, "p50": p50,
                        "p75": 582, "p90": p90, "p95": p95},
        "p16": 577.0, "p84": 583.0, "mode": p50, "std": std,
    }


def _clean_ts():
    """ET 09:40 → within the clean window."""
    from config import ET_TZ
    et = datetime.datetime.now(ET_TZ).replace(hour=9, minute=40, second=0,
                                              microsecond=0)
    return et.astimezone(datetime.timezone.utc).isoformat()


def _late_ts():
    """ET 14:00 → outside the clean window."""
    from config import ET_TZ
    et = datetime.datetime.now(ET_TZ).replace(hour=14, minute=0, second=0,
                                              microsecond=0)
    return et.astimezone(datetime.timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
#  build_prediction
# ─────────────────────────────────────────────────────────────────────────────
def test_build_prediction_basic():
    rec = build_prediction("SPY", "2026-06-01", _clean_ts(), 580.0, 0,
                           _levels(), {"method": "svi"})
    assert rec is not None
    assert rec["symbol"] == "SPY"
    assert rec["rnd_p10"] == 575 and rec["rnd_p90"] == 585
    assert rec["rnd_method"] == "svi"
    assert rec["settled"] == 0
    assert rec["close_actual"] is None


def test_build_prediction_incomplete_levels():
    bad = {"percentiles": {"p10": 575}}  # missing the rest
    assert build_prediction("SPY", "2026-06-01", _clean_ts(),
                            580, 0, bad, {}) is None
    assert build_prediction("SPY", "2026-06-01", _clean_ts(),
                            580, 0, {}, {}) is None


# ─────────────────────────────────────────────────────────────────────────────
#  settle_record
# ─────────────────────────────────────────────────────────────────────────────
def test_settle_inside():
    rec = build_prediction("SPY", "2026-06-01", _clean_ts(), 580.0, 0,
                           _levels(), {})
    f = settle_record(rec, close_actual=582.0)  # inside 575-585
    assert f["inside_p10_p90"] == 1
    assert f["inside_p05_p95"] == 1
    assert f["settled"] == 1
    assert f["move_actual"] == pytest.approx(2.0)


def test_settle_outside():
    rec = build_prediction("SPY", "2026-06-01", _clean_ts(), 580.0, 0,
                           _levels(), {})
    f = settle_record(rec, close_actual=590.0)  # above P95=587
    assert f["inside_p10_p90"] == 0
    assert f["inside_p05_p95"] == 0
    assert f["move_actual"] == pytest.approx(10.0)


def test_settle_edge_at_p90():
    rec = build_prediction("SPY", "2026-06-01", _clean_ts(), 580.0, 0,
                           _levels(p90=585), {})
    f = settle_record(rec, close_actual=585.0)  # exactly at P90 → inside
    assert f["inside_p10_p90"] == 1


# ─────────────────────────────────────────────────────────────────────────────
#  accuracy_stats — calibration
# ─────────────────────────────────────────────────────────────────────────────
def _settled_row(inside_8, inside_9=1, inside_1s=1, move=2.0, std=3.0,
                 clean=True):
    return {
        "snapshot_ts": _clean_ts() if clean else _late_ts(),
        "settled": 1, "close_actual": 580.0,
        "inside_p10_p90": inside_8, "inside_p05_p95": inside_9,
        "inside_1sigma": inside_1s, "move_actual": move, "rnd_std": std,
    }


def test_stats_insufficient():
    rows = [_settled_row(1) for _ in range(5)]
    s = accuracy_stats(rows)
    assert s["ready"] is False
    assert s["verdict"] == "insufficient_data"


def test_stats_well_calibrated():
    # 8/10 inside P10-P90 = 80% → well calibrated
    rows = [_settled_row(1) for _ in range(8)] + [_settled_row(0) for _ in range(2)]
    s = accuracy_stats(rows)
    assert s["ready"] is True
    assert s["hit_p10_p90"] == 0.8
    assert s["verdict"] == "well_calibrated"


def test_stats_over_estimates():
    # 10/10 inside → over-estimates (IV rich)
    rows = [_settled_row(1) for _ in range(12)]
    s = accuracy_stats(rows)
    assert s["verdict"] == "over_estimates"


def test_stats_under_estimates():
    # 6/12 inside = 50% → under-estimates (fat tails)
    rows = ([_settled_row(1) for _ in range(6)]
            + [_settled_row(0) for _ in range(6)])
    s = accuracy_stats(rows)
    assert s["verdict"] == "under_estimates"


def test_stats_only_clean_filter():
    # 10 clean (all inside) + 5 late (all outside). only_clean should
    # ignore the late ones → 100% clean hit-rate.
    rows = ([_settled_row(1, clean=True) for _ in range(10)]
            + [_settled_row(0, clean=False) for _ in range(5)])
    s_clean = accuracy_stats(rows, only_clean=True)
    s_all = accuracy_stats(rows, only_clean=False)
    assert s_clean["n_clean"] == 10
    assert s_clean["hit_p10_p90"] == 1.0
    # Including late ones drags it down
    assert s_all["hit_p10_p90"] < 1.0


def test_move_ratio():
    rows = [_settled_row(1, move=3.0, std=3.0) for _ in range(10)]
    s = accuracy_stats(rows)
    assert s["avg_move_ratio"] == pytest.approx(1.0, abs=1e-6)


def test_verdict_text():
    assert verdict_text({"ready": False, "n_clean": 3})[0].startswith("Acumulando")
    assert "BIEN" in verdict_text({"ready": True, "verdict": "well_calibrated"})[0]
    assert "SOBRE" in verdict_text({"ready": True, "verdict": "over_estimates"})[0]
    assert "SUB" in verdict_text({"ready": True, "verdict": "under_estimates"})[0]
