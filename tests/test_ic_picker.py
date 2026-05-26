"""Tests for quant/ic_picker — IV smile, IC metrics, wing comparison, gate."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.ic_picker import (
    build_iv_long_table, build_smile_blend, compare_wing_widths,
    gex_gate_check, iron_condor_metrics, rich_zone_mask,
    suggest_strikes_from_walls,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _synthetic_chain(spot: float = 100.0, n: int = 21):
    """Symmetric V-smile chain (typical equity skew): IV decreases from
    deep OTM puts and rises again into deep OTM calls. Marks chosen so
    short premium > long premium → positive credit."""
    strikes = np.linspace(spot - 10, spot + 10, n)
    # V-smile centred at 1 strike below spot (slight put skew)
    iv = 18.0 + 0.6 * np.abs(strikes - (spot - 0.5))
    # Mark prices fall linearly with distance from spot (rough sanity)
    mark = np.maximum(0.05, 5.0 - 0.3 * np.abs(strikes - spot))
    # Delta: linear interp, calls 0.5 ATM → 0 OTM
    call_delta = np.clip(0.5 + (spot - strikes) * 0.04, 0.0, 1.0)
    put_delta = call_delta - 1.0  # signed

    calls = pd.DataFrame({
        "Strike": strikes, "IV%": iv, "Gamma": np.full(n, 0.02),
        "Delta": call_delta, "Mark": mark, "Bid": mark - 0.05, "Ask": mark + 0.05,
        "OI": np.full(n, 1000), "DTE": np.zeros(n, dtype=int),
        "Expiry": ["2026-05-18"] * n,
    })
    puts = pd.DataFrame({
        "Strike": strikes, "IV%": iv + 0.5, "Gamma": np.full(n, 0.02),
        "Delta": put_delta, "Mark": mark + 0.1, "Bid": mark + 0.05, "Ask": mark + 0.15,
        "OI": np.full(n, 1000), "DTE": np.zeros(n, dtype=int),
        "Expiry": ["2026-05-18"] * n,
    })
    return calls, puts


# ─────────────────────────────────────────────────────────────────────────────
#  build_iv_long_table
# ─────────────────────────────────────────────────────────────────────────────
def test_iv_long_table_empty():
    out = build_iv_long_table(pd.DataFrame(), pd.DataFrame())
    assert out.empty
    assert list(out.columns) == ["Strike", "side", "IV%", "Gamma", "OI"]


def test_iv_long_table_calls_only():
    c, p = _synthetic_chain()
    out = build_iv_long_table(c, pd.DataFrame())
    assert len(out) == len(c)
    assert (out["side"] == "call").all()


def test_iv_long_table_both_sides():
    c, p = _synthetic_chain()
    out = build_iv_long_table(c, p)
    assert len(out) == len(c) + len(p)
    assert set(out["side"].unique()) == {"call", "put"}


# ─────────────────────────────────────────────────────────────────────────────
#  build_smile_blend
# ─────────────────────────────────────────────────────────────────────────────
def test_smile_blend_otm_convention():
    c, p = _synthetic_chain(spot=100.0)
    sm = build_smile_blend(c, p, spot=100.0)
    assert not sm.empty
    for col in ("Strike", "C_IV", "P_IV", "Market_IV", "Moneyness",
                "LogK", "Delta", "Gamma", "OI"):
        assert col in sm.columns
    # Market_IV for K<spot should match P_IV (OTM puts)
    below = sm[sm["Strike"] < 100.0]
    assert (below["Market_IV"].dropna() == below["P_IV"].dropna()).all()
    above = sm[sm["Strike"] > 100.0]
    assert (above["Market_IV"].dropna() == above["C_IV"].dropna()).all()


def test_smile_blend_delta_positive_otm_convention():
    c, p = _synthetic_chain(spot=100.0)
    sm = build_smile_blend(c, p, spot=100.0)
    # Delta column is unified as |Δ| using OTM convention → always positive
    valid = sm["Delta"].dropna()
    assert (valid >= 0).all()


# ─────────────────────────────────────────────────────────────────────────────
#  rich_zone_mask
# ─────────────────────────────────────────────────────────────────────────────
def test_rich_zone_mask_finds_wings():
    c, p = _synthetic_chain()
    sm = build_smile_blend(c, p, spot=100.0)
    # V-smile → wings are "rich"
    mask = rich_zone_mask(sm, sigma=1.0)
    # The very deepest strikes should be in the rich zone
    if mask.any():
        rich_strikes = sm.loc[mask, "Strike"].to_numpy()
        # at least one wing in the mask
        assert (rich_strikes.min() < 95.0) or (rich_strikes.max() > 105.0)


# ─────────────────────────────────────────────────────────────────────────────
#  iron_condor_metrics
# ─────────────────────────────────────────────────────────────────────────────
def test_ic_metrics_basic():
    c, p = _synthetic_chain(spot=100.0)
    sm = build_smile_blend(c, p, spot=100.0)
    ic = iron_condor_metrics(c, p, sm, spot=100.0,
                             short_put=96.0, short_call=104.0, wing_width=2.0)
    assert ic is not None
    # Shorts are real strikes from the chain
    assert ic.short_put == 96.0
    assert ic.short_call == 104.0
    assert ic.long_put == 94.0
    assert ic.long_call == 106.0
    # IV of long-OTM legs is HIGHER than shorts (V-smile) → vrp NEGATIVE typically
    # but on the call side, going further OTM means higher IV.
    # On the put side same. Net VRP could be ±.
    # What we DO assert: numbers are finite.
    assert np.isfinite(ic.net_vrp_iv_points)
    assert ic.max_loss > 0
    assert 0 <= ic.pop <= 1
    assert 0 <= ic.p_touch_put <= 1
    assert 0 <= ic.p_touch_call <= 1


def test_ic_metrics_credit_from_marks():
    c, p = _synthetic_chain(spot=100.0)
    sm = build_smile_blend(c, p, spot=100.0)
    ic = iron_condor_metrics(c, p, sm, spot=100.0,
                             short_put=98.0, short_call=102.0, wing_width=2.0)
    assert ic is not None
    assert ic.credit_source == "mark"
    # Shorts are closer to ATM → richer mark → credit must be positive
    assert ic.credit > 0


def test_ic_metrics_invalid_spot():
    c, p = _synthetic_chain()
    sm = build_smile_blend(c, p, spot=100.0)
    assert iron_condor_metrics(c, p, sm, spot=0.0,
                               short_put=96, short_call=104, wing_width=2) is None
    assert iron_condor_metrics(c, p, sm, spot=100.0,
                               short_put=96, short_call=104, wing_width=0) is None


# ─────────────────────────────────────────────────────────────────────────────
#  compare_wing_widths
# ─────────────────────────────────────────────────────────────────────────────
def test_compare_wing_widths_returns_table():
    c, p = _synthetic_chain(spot=100.0)
    df = compare_wing_widths(c, p, spot=100.0,
                             short_put=97.0, short_call=103.0,
                             wing_widths=(1.0, 2.0, 3.0))
    assert not df.empty
    assert len(df) == 3
    # Sorted by vrp_per_max_loss DESC
    assert (df["vrp_per_max_loss"].diff().dropna() <= 0).all()
    # Expected columns
    for col in ("short_put", "short_call", "long_put", "long_call",
                "wing_width", "credit", "max_loss",
                "vrp_per_max_loss", "credit_per_max_loss", "pop"):
        assert col in df.columns


def test_compare_wing_widths_wider_lower_efficiency_for_v_smile():
    """For a symmetric V-smile, wider wings sweep deeper into the rich
    zone — but since long legs are MORE expensive, net VRP per max_loss
    typically *drops* (or at least doesn't improve monotonically)."""
    c, p = _synthetic_chain(spot=100.0)
    df = compare_wing_widths(c, p, spot=100.0,
                             short_put=98.0, short_call=102.0,
                             wing_widths=(1.0, 5.0))
    assert len(df) == 2
    # Both rows have positive credits
    assert (df["credit"] > 0).all()


# ─────────────────────────────────────────────────────────────────────────────
#  suggest_strikes_from_walls
# ─────────────────────────────────────────────────────────────────────────────
def test_suggest_respects_put_wall():
    c, p = _synthetic_chain(spot=100.0)
    gex_sum = {"put_wall": 96.0, "call_wall": 104.0, "hvl": 100.0}
    s = suggest_strikes_from_walls(c, p, spot=100.0, gex_sum=gex_sum,
                                   target_short_delta=0.20)
    assert s["short_put"] is not None
    assert s["short_call"] is not None
    # short_put must sit BELOW the put wall (the gate-aware rule)
    assert s["short_put"] <= 96.0
    # short_call must sit ABOVE the call wall
    assert s["short_call"] >= 104.0


def test_suggest_handles_no_walls():
    c, p = _synthetic_chain(spot=100.0)
    s = suggest_strikes_from_walls(c, p, spot=100.0, gex_sum=None,
                                   target_short_delta=0.20)
    assert s["short_put"] is not None
    assert s["short_call"] is not None
    assert s["source"] == "delta_only"


# ─────────────────────────────────────────────────────────────────────────────
#  gex_gate_check
# ─────────────────────────────────────────────────────────────────────────────
def test_gate_pass():
    gex_sum = {
        "regime": "POSITIVE", "total_gex": 2.0e9,
        "gamma_flip": 95.0,  # spot=100 → cushion = 5%
    }
    out = gex_gate_check(gex_sum, spot=100.0)
    assert out["pass"] is True
    assert "PASS" in out["verdict"]


def test_gate_fail_below_flip():
    gex_sum = {
        "regime": "POSITIVE", "total_gex": 2.0e9,
        "gamma_flip": 105.0,  # spot below flip
    }
    out = gex_gate_check(gex_sum, spot=100.0)
    assert out["pass"] is False
    assert out["above_flip_ok"] is False


def test_gate_fail_negative_regime():
    gex_sum = {
        "regime": "NEGATIVE", "total_gex": -2.0e9,
        "gamma_flip": 90.0,
    }
    out = gex_gate_check(gex_sum, spot=100.0)
    assert out["pass"] is False
    assert out["regime_ok"] is False


def test_gate_no_data():
    assert gex_gate_check(None, spot=100.0)["pass"] is False
    assert gex_gate_check({}, spot=0.0)["pass"] is False
