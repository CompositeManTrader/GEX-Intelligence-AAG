"""Tests for the continuous-orderflow pipeline: store roundtrip (SQLite),
session digest, strike activity, and session charts."""
from __future__ import annotations

import datetime

import pytest

from quant.orderflow_derived import session_changes, strike_activity


def _ts(minutes_ago: float) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=minutes_ago)).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
#  of_store — SQLite roundtrip
# ─────────────────────────────────────────────────────────────────────────────
def test_of_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("OF_STORE_DB", str(tmp_path / "of.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from data import of_store

    tick = {"symbol": "SPY", "ts": _ts(5), "spot": 728.9,
            "net_gex_mm": -11280.0, "call_wall": 742.0, "put_wall": 719.0,
            "gamma_flip": 713.0, "hvl": 720.0, "regime": "NEGATIVE",
            "gex_0dte_mm": -4260.0, "call_wall_0dte": 741.0,
            "put_wall_0dte": 726.0}
    strikes = [
        {"symbol": "SPY", "ts": tick["ts"], "strike": 728.0,
         "net_gex_mm": -55.0, "call_oi": 1000, "put_oi": 2500,
         "call_vol": 5000, "put_vol": 9000},
        {"symbol": "SPY", "ts": tick["ts"], "strike": 730.0,
         "net_gex_mm": 12.0, "call_oi": 800, "put_oi": 700,
         "call_vol": 2000, "put_vol": 1000},
    ]
    assert of_store.record_tick(tick, strikes) is True
    # Duplicate (symbol, ts) is ignored, not duplicated.
    assert of_store.record_tick(tick, strikes) is False

    ticks = of_store.load_ticks("SPY", hours=1)
    assert len(ticks) == 1
    assert ticks[0]["regime"] == "NEGATIVE"
    assert ticks[0]["net_gex_mm"] == pytest.approx(-11280.0)

    rows = of_store.load_strikes("SPY", hours=1)
    assert len(rows) == 2
    assert {r["strike"] for r in rows} == {728.0, 730.0}
    assert of_store.backend_info()["backend"] == "sqlite"


# ─────────────────────────────────────────────────────────────────────────────
#  session_changes — digest
# ─────────────────────────────────────────────────────────────────────────────
def _tick(mins_ago, gex, regime, cw, pw, hvl, spot):
    return {"ts": _ts(mins_ago), "spot": spot, "net_gex_mm": gex,
            "regime": regime, "call_wall": cw, "put_wall": pw, "hvl": hvl}


def test_session_changes_detects_regime_and_walls():
    ticks = [
        _tick(120, +500.0, "POSITIVE", 742, 719, 730, 731.0),
        _tick(90, +120.0, "POSITIVE", 742, 719, 730, 729.5),
        _tick(60, -300.0, "NEGATIVE", 742, 719, 730, 727.0),   # regime flip
        _tick(30, -800.0, "NEGATIVE", 742, 723, 728, 726.0),   # PW + HVL move
        _tick(1, -1100.0, "NEGATIVE", 742, 723, 728, 725.0),
    ]
    out = session_changes(ticks, wall_min_jump=0.5)
    assert out["n_ticks"] == 5
    assert out["regime_open"] == "POSITIVE" and out["regime_now"] == "NEGATIVE"
    assert len(out["regime_changes"]) == 1
    assert out["regime_changes"][0]["to"] == "NEGATIVE"
    assert out["gex_delta_mm"] == pytest.approx(-1600.0)
    # Put wall moved 719→723 once; call wall never moved.
    assert len(out["walls"]["put_wall"]["moves"]) == 1
    assert out["walls"]["put_wall"]["moves"][0]["to"] == 723
    assert out["walls"]["call_wall"]["moves"] == []
    assert len(out["walls"]["hvl"]["moves"]) == 1


def test_session_changes_handles_live_timestamp_key_and_empty():
    assert session_changes([]) == {}
    ticks = [{"timestamp": _ts(10), "spot": 100.0, "net_gex_mm": 5.0,
              "regime": "POSITIVE"},
             {"timestamp": _ts(1), "spot": 101.0, "net_gex_mm": 7.0,
              "regime": "POSITIVE"}]
    out = session_changes(ticks)
    assert out["n_ticks"] == 2
    assert out["gex_delta_mm"] == pytest.approx(2.0)
    assert out["regime_changes"] == []


# ─────────────────────────────────────────────────────────────────────────────
#  strike_activity — volume acceleration
# ─────────────────────────────────────────────────────────────────────────────
def _srow(mins_ago, strike, cvol, pvol, coi=1000, poi=1000):
    return {"ts": _ts(mins_ago), "strike": strike, "call_oi": coi,
            "put_oi": poi, "call_vol": cvol, "put_vol": pvol,
            "net_gex_mm": 0.0}


def test_strike_activity_window_delta():
    rows = [
        # snapshot at t-40
        _srow(40, 728, 1000, 3000), _srow(40, 730, 500, 200),
        # latest snapshot
        _srow(0, 728, 1500, 8000), _srow(0, 730, 700, 250),
    ]
    out = strike_activity(rows, window_minutes=30, top_n=5)
    assert out and out["window_min"] == pytest.approx(40.0, abs=1.0)
    top = out["rows"][0]
    # 728 traded 500 calls + 5000 puts in the window → top mover
    assert top["strike"] == 728.0
    assert top["d_put_vol"] == pytest.approx(5000.0)
    assert top["d_call_vol"] == pytest.approx(500.0)
    assert top["vol_oi"] == pytest.approx((1500 + 8000) / 2000, rel=0.01)


def test_strike_activity_single_snapshot_falls_back_to_day_volume():
    rows = [_srow(0, 728, 1200, 900)]
    out = strike_activity(rows, window_minutes=30)
    assert out["window_min"] is None          # no baseline → whole day
    assert out["rows"][0]["d_total"] == pytest.approx(2100.0)
    assert strike_activity([], 30) == {}


# ─────────────────────────────────────────────────────────────────────────────
#  Session charts construct figures
# ─────────────────────────────────────────────────────────────────────────────
def test_session_charts_build():
    from charts.of_session import (
        chart_session_trajectory, chart_strike_flow, chart_walls_timeline,
    )
    ticks = [
        _tick(60, 200.0, "POSITIVE", 742, 719, 730, 729.0),
        _tick(30, -150.0, "NEGATIVE", 742, 719, 730, 727.5),
        _tick(1, -400.0, "NEGATIVE", 742, 721, 728, 726.0),
    ]
    fig1 = chart_session_trajectory(ticks, "SPY")
    assert fig1 is not None and len(fig1.data) >= 2
    fig2 = chart_walls_timeline(ticks, "SPY")
    assert fig2 is not None and len(fig2.data) >= 3
    act = strike_activity([
        _srow(40, 728, 100, 300), _srow(0, 728, 600, 900),
    ], window_minutes=30)
    fig3 = chart_strike_flow(act, "SPY", spot=727.8)
    assert fig3 is not None and len(fig3.data) == 2
    # Empty inputs → None (no crash)
    assert chart_session_trajectory([], "SPY") is None
    assert chart_walls_timeline([], "SPY") is None
    assert chart_strike_flow({}, "SPY") is None
