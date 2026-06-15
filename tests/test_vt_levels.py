"""Tests para Volume Trigger (VT-C/VT-P + dominancia) y Call Bridge."""
from __future__ import annotations

import pandas as pd
import pytest

from quant.vt_levels import call_bridge, volume_trigger, vt_dominance_label


def _chain(rows):
    return pd.DataFrame(rows, columns=["Strike", "Volume", "OI"])


def test_volume_trigger_picks_max_volume_strike_per_side():
    calls = _chain([(5300, 1000, 10), (5310, 4000, 20), (5320, 500, 5)])
    puts = _chain([(5290, 9000, 30), (5280, 1200, 8), (5270, 300, 2)])
    vt = volume_trigger(calls, puts)
    assert vt["vt_c"] == 5310.0 and vt["vt_c_vol"] == 4000
    assert vt["vt_p"] == 5290.0 and vt["vt_p_vol"] == 9000


def test_volume_trigger_dominance_ratio_and_side():
    # total call vol = 5500, total put vol = 11000 → puts dominan 2.0x
    calls = _chain([(5300, 2000, 0), (5310, 3500, 0)])
    puts = _chain([(5290, 8000, 0), (5280, 3000, 0)])
    vt = volume_trigger(calls, puts)
    assert vt["vt_dom_side"] == "P"
    assert vt["vt_dom_ratio"] == pytest.approx(2.0, rel=1e-6)
    lbl = vt_dominance_label(vt)
    assert lbl["side"] == "P" and "puts dominan" in lbl["text"]


def test_volume_trigger_aggregates_duplicate_strikes_across_expiries():
    # mismo strike en dos vencimientos → se suma el volumen
    calls = _chain([(5300, 1000, 5), (5300, 2500, 5), (5310, 3000, 5)])
    puts = _chain([(5290, 100, 5)])
    vt = volume_trigger(calls, puts)
    # 5300 acumula 3500 > 3000 de 5310
    assert vt["vt_c"] == 5300.0 and vt["vt_c_vol"] == 3500


def test_call_bridge_is_max_total_oi_strike():
    calls = _chain([(5300, 0, 1000), (5310, 0, 4000), (5320, 0, 200)])
    puts = _chain([(5310, 0, 6000), (5290, 0, 500)])
    # 5310 total OI = 4000 + 6000 = 10000 → CB
    assert call_bridge(calls, puts) == 5310.0


def test_call_bridge_one_side_only():
    calls = _chain([(5300, 0, 100), (5310, 0, 900)])
    assert call_bridge(calls, None) == 5310.0
    assert call_bridge(None, None) is None


def test_empty_and_zero_inputs_are_safe():
    empty = pd.DataFrame(columns=["Strike", "Volume", "OI"])
    vt = volume_trigger(empty, empty)
    assert vt["vt_c"] is None and vt["vt_p"] is None
    assert vt["vt_dom_ratio"] is None
    assert call_bridge(empty, empty) is None
    assert vt_dominance_label({}) is None
    # volumen todo cero → sin VT
    zc = _chain([(5300, 0, 10), (5310, 0, 20)])
    vt0 = volume_trigger(zc, zc)
    assert vt0["vt_c"] is None and vt0["vt_dom_ratio"] is None


def test_integration_through_compute_gex_profile():
    """VT/CB deben aparecer en el summary de compute_gex_profile."""
    from quant.exposures import compute_gex_profile
    import numpy as np
    spot = 5300.0
    ks = np.arange(5260, 5341, 5.0)
    rows_c, rows_p = [], []
    for k in ks:
        rows_c.append({"Strike": k, "Gamma": 0.001, "OI": 100,
                       "Volume": 9000 + 100 if k == 5320 else 100,
                       "DTE": 0, "IV%": 20.0})
        rows_p.append({"Strike": k, "Gamma": 0.001, "OI": 100,
                       "Volume": 12000 + 100 if k == 5280 else 100,
                       "DTE": 0, "IV%": 20.0})
    calls = pd.DataFrame(rows_c)
    puts = pd.DataFrame(rows_p)
    _df, summ = compute_gex_profile(calls, puts, spot=spot, max_dte=0,
                                    use_spot_grid_flip=False)
    assert summ.get("vt_c") == 5320.0
    assert summ.get("vt_p") == 5280.0
    assert summ.get("vt_dom_side") == "P"        # puts mueven más volumen
    assert summ.get("call_bridge") is not None
