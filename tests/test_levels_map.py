"""Tests for the Price & GEX Levels map (charts/levels_map.py)."""
from __future__ import annotations

import pandas as pd

from charts.levels_map import collect_price_levels, chart_price_levels
from charts.theme import GREEN, RED, ORANGE
from quant.zones import GammaZone


SPOT = 755.0
GEX = dict(regime="NEGATIVE", total_gex=-1.09e9, call_wall=756.0,
           put_wall=750.0, gamma_flip=755.0, hvl=753.0)


def test_collect_classifies_walls_and_flip():
    lv = {d["tag"]: d for d in collect_price_levels(SPOT, GEX)}
    assert lv["CALL WALL"]["role"] == "resistance" and lv["CALL WALL"]["color"] == GREEN
    assert lv["PUT WALL"]["role"] == "support" and lv["PUT WALL"]["color"] == RED
    assert lv["GAMMA FLIP"]["role"] == "flip" and lv["GAMMA FLIP"]["color"] == ORANGE


def test_collect_sorted_and_deduped():
    out = collect_price_levels(SPOT, GEX)
    prices = [d["price"] for d in out]
    assert prices == sorted(prices)              # ascending
    assert len(prices) == len(set(prices))       # no exact dupes


def test_collect_dedup_merges_near_levels_keeping_wider():
    # HVL within tolerance of the call wall → the wider wall must win.
    g = dict(GEX, hvl=756.05)   # ~0.05 from call wall 756.0
    out = collect_price_levels(SPOT, g)
    near = [d for d in out if abs(d["price"] - 756.0) < 0.5]
    assert len(near) == 1 and near[0]["tag"] == "CALL WALL"


def test_collect_zone_classification_by_side_and_position():
    zones = [
        GammaZone(1, "P1", 757.0, 756.5, 758.0, 1.5, 120.0, 300.0,
                  "call_dominant", 0.26, True),
        GammaZone(2, "P2", 752.0, 751.5, 753.0, 1.5, -90.0, 210.0,
                  "put_dominant", -0.40, False),
    ]
    out = {d["tag"]: d for d in collect_price_levels(SPOT, GEX, zones)}
    assert out["CLUSTER P1"]["role"] == "resistance"  # call cluster above spot
    assert out["CLUSTER P2"]["role"] == "support"     # put cluster below spot


def test_collect_empty_inputs():
    assert collect_price_levels(0, GEX) == []
    assert collect_price_levels(SPOT, None) == []
    assert collect_price_levels(SPOT, {}) == []


def test_chart_returns_figure_with_traces():
    idx = pd.date_range("2026-06-03 13:00", periods=12, freq="5min", tz="UTC")
    intra = pd.DataFrame({"date": idx, "close": [753 + (i % 3) for i in range(12)]})
    fig = chart_price_levels(SPOT, GEX, intra_df=intra, symbol="SPY")
    assert fig is not None
    # price line + spot marker + 5 legend dummies
    assert len(fig.data) >= 6
    # has horizontal level shapes
    assert len(fig.layout.shapes) >= 4


def test_chart_none_when_no_levels():
    assert chart_price_levels(SPOT, {}) is None
    assert chart_price_levels(0, GEX) is None


def test_chart_without_intraday_still_renders():
    # No price line → still draws the levels + a spot rail.
    fig = chart_price_levels(SPOT, GEX, intra_df=None)
    assert fig is not None
    assert len(fig.layout.shapes) >= 4
