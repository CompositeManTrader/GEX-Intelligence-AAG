"""Tests for quant/expected_range — estimators, cone, risk-neutral density."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.expected_range import (
    compare_estimators, iv_gaussian_em, prob_cone, realized_em,
    risk_neutral_density, rnd_stats, skew_em, straddle_em,
    _STRADDLE_TO_SIGMA,
)


# ─────────────────────────────────────────────────────────────────────────────
def _synthetic_calls(spot=100.0, n=41, iv=20.0):
    """Symmetric chain with a mild smile + BS-consistent mark prices."""
    from scipy.stats import norm
    strikes = np.linspace(spot * 0.9, spot * 1.1, n)
    # Mild V-smile
    ivs = iv + 0.10 * np.abs(strikes - spot)
    T = 1.0 / 365.0
    sig = ivs / 100.0
    d1 = (np.log(spot / strikes) + 0.5 * sig**2 * T) / (sig * np.sqrt(T))
    d2 = d1 - sig * np.sqrt(T)
    call = spot * norm.cdf(d1) - strikes * norm.cdf(d2)
    put = call - spot + strikes  # put-call parity, r=q=0
    calls = pd.DataFrame({"Strike": strikes, "IV%": ivs,
                          "Mark": np.maximum(call, 0.01)})
    puts = pd.DataFrame({"Strike": strikes, "IV%": ivs,
                         "Mark": np.maximum(put, 0.01)})
    return calls, puts


# ─────────────────────────────────────────────────────────────────────────────
#  IV Gaussian
# ─────────────────────────────────────────────────────────────────────────────
def test_iv_gaussian_sqrt_t_scaling():
    # 4× time → 2× expected move (√4 = 2)
    e1 = iv_gaussian_em(100.0, 20.0, 1.0 / 365.0)
    e4 = iv_gaussian_em(100.0, 20.0, 4.0 / 365.0)
    assert e1 and e4
    assert e4.em_dollars == pytest.approx(2.0 * e1.em_dollars, rel=1e-6)


def test_iv_gaussian_formula():
    em = iv_gaussian_em(580.0, 18.0, 0.0027)
    # 580 × 0.18 × √0.0027  (em_dollars is round(.,3), so allow 1e-3)
    expected = 580.0 * 0.18 * np.sqrt(0.0027)
    assert em.em_dollars == pytest.approx(expected, abs=1e-3)
    assert em.low < 580 < em.high


def test_iv_gaussian_invalid():
    assert iv_gaussian_em(0, 20, 0.01) is None
    assert iv_gaussian_em(100, 0, 0.01) is None
    assert iv_gaussian_em(100, 20, 0) is None


# ─────────────────────────────────────────────────────────────────────────────
#  Skew
# ─────────────────────────────────────────────────────────────────────────────
def test_skew_asymmetric():
    # Put IV higher than call IV → downside band wider
    e = skew_em(100.0, iv_call_pct=18.0, iv_put_pct=24.0, T=0.01)
    assert e.asymmetric
    down = 100.0 - e.low
    up = e.high - 100.0
    assert down > up  # put-IV bigger → lower band further from spot


def test_skew_symmetric_when_equal():
    e = skew_em(100.0, 20.0, 20.0, 0.01)
    assert not e.asymmetric
    assert (100.0 - e.low) == pytest.approx(e.high - 100.0, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
#  Straddle
# ─────────────────────────────────────────────────────────────────────────────
def test_straddle_factor():
    calls, puts = _synthetic_calls(spot=100.0)
    e = straddle_em(calls, puts, spot=100.0)
    assert e is not None
    # ATM straddle ≈ call_atm + put_atm; em_1sigma = straddle × 1.2533
    c_atm = float(calls.iloc[(calls["Strike"] - 100).abs().idxmin()]["Mark"])
    p_atm = float(puts.iloc[(puts["Strike"] - 100).abs().idxmin()]["Mark"])
    straddle = c_atm + p_atm
    assert e.em_dollars == pytest.approx(straddle * _STRADDLE_TO_SIGMA, abs=1e-3)


def test_straddle_close_to_gaussian():
    # The straddle-implied 1σ should be in the same ballpark as the IV
    # Gaussian 1σ when the ATM IV matches the straddle's IV.
    calls, puts = _synthetic_calls(spot=100.0, iv=20.0)
    e_str = straddle_em(calls, puts, spot=100.0)
    e_iv = iv_gaussian_em(100.0, 20.0, 1.0 / 365.0)
    # Within 15% — straddle has discreteness + the smile floor
    assert abs(e_str.em_dollars - e_iv.em_dollars) / e_iv.em_dollars < 0.15


# ─────────────────────────────────────────────────────────────────────────────
#  Realized
# ─────────────────────────────────────────────────────────────────────────────
def test_realized_em():
    e = realized_em(100.0, 15.0, 1.0 / 365.0)
    assert e and e.method == "Realized vol"
    assert e.em_dollars == pytest.approx(100 * 0.15 * np.sqrt(1/365), abs=1e-3)


# ─────────────────────────────────────────────────────────────────────────────
#  compare_estimators
# ─────────────────────────────────────────────────────────────────────────────
def test_compare_bundle():
    calls, puts = _synthetic_calls(spot=100.0)
    ests, T = compare_estimators(
        spot=100.0, calls=calls, puts=puts,
        iv_call_pct=20.0, iv_put_pct=22.0, realized_vol_pct=15.0,
        dte=1,
    )
    methods = {e.method for e in ests}
    assert "IV Gaussian" in methods
    assert "Skew-adjusted" in methods
    assert "Straddle MMM" in methods
    assert "Realized vol" in methods
    assert T == pytest.approx(1.0 / 365.0, rel=1e-6)


def test_compare_skips_missing():
    calls, puts = _synthetic_calls()
    # No realized vol, no put IV → only Gaussian + straddle
    ests, _ = compare_estimators(
        spot=100.0, calls=calls, puts=puts,
        iv_call_pct=20.0, iv_put_pct=None, realized_vol_pct=None, dte=1,
    )
    methods = {e.method for e in ests}
    assert "IV Gaussian" in methods
    assert "Skew-adjusted" not in methods
    assert "Realized vol" not in methods


# ─────────────────────────────────────────────────────────────────────────────
#  Probability cone
# ─────────────────────────────────────────────────────────────────────────────
def test_prob_cone_widens():
    cone = prob_cone(100.0, 20.0, dtes=(1, 4), sigmas=(1.0,))
    assert not cone.empty
    move_1d = cone[cone["dte"] == 1]["move"].iloc[0]
    move_4d = cone[cone["dte"] == 4]["move"].iloc[0]
    # √4 = 2× wider
    assert move_4d == pytest.approx(2.0 * move_1d, rel=1e-3)


# ─────────────────────────────────────────────────────────────────────────────
#  Risk-neutral density
# ─────────────────────────────────────────────────────────────────────────────
def test_rnd_integrates_to_one():
    calls, _ = _synthetic_calls(spot=100.0, n=61, iv=20.0)
    rnd = risk_neutral_density(calls, spot=100.0, dte=1, grid_points=201)
    assert rnd is not None
    dk = rnd["strike"].iloc[1] - rnd["strike"].iloc[0]
    area = float(np.sum(rnd["pdf"]) * dk)
    assert area == pytest.approx(1.0, abs=0.02)


def test_rnd_peak_near_spot():
    calls, _ = _synthetic_calls(spot=100.0, n=61, iv=20.0)
    rnd = risk_neutral_density(calls, spot=100.0, dte=1, grid_points=201)
    peak_strike = rnd.loc[rnd["pdf"].idxmax(), "strike"]
    # The mode of a near-symmetric smile should sit close to spot
    assert abs(peak_strike - 100.0) < 3.0


def test_rnd_insufficient_data():
    calls = pd.DataFrame({"Strike": [100, 101], "IV%": [20, 21]})
    assert risk_neutral_density(calls, spot=100.0, dte=1) is None


def test_rnd_stats_level_probs():
    calls, _ = _synthetic_calls(spot=100.0, n=61, iv=20.0)
    rnd = risk_neutral_density(calls, spot=100.0, dte=1, grid_points=201)
    stats = rnd_stats(rnd, spot=100.0,
                      levels={"put_wall": 97.0, "call_wall": 103.0})
    assert "mean" in stats and "std" in stats
    assert "skew" in stats and "excess_kurtosis" in stats
    lp = stats["level_probs"]
    assert "put_wall" in lp and "call_wall" in lp
    # P(below put_wall) + P(above put_wall) = 1
    assert lp["put_wall"]["p_below"] + lp["put_wall"]["p_above"] == pytest.approx(1.0, abs=1e-6)
    # Mean of a near-symmetric density ≈ spot
    assert abs(stats["mean"] - 100.0) < 2.0
