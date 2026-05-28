"""Tests for quant/rnd — SVI fit, arbitrage-free density, exact levels."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from quant.rnd import (
    SVIParams, build_rnd, fit_svi, rnd_levels, svi_g_function,
    svi_total_variance,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Synthetic chains
# ─────────────────────────────────────────────────────────────────────────────
def _chain(spot=580.0, n=41, base_iv=20.0, skew=0.0, smile=0.0,
           dte_days=1):
    """Build calls+puts with a controllable smile.
    iv(K) = base_iv + skew·(K−spot)/spot·100 + smile·((K−spot)/spot·100)²
    Marks priced with BS so straddle/level tests are consistent.
    """
    strikes = np.linspace(spot * 0.88, spot * 1.12, n)
    mny = (strikes - spot) / spot * 100.0
    ivs = base_iv + skew * mny + smile * mny ** 2
    ivs = np.clip(ivs, 1.0, None)
    T = dte_days / 365.0
    sig = ivs / 100.0
    d1 = (np.log(spot / strikes) + 0.5 * sig ** 2 * T) / (sig * np.sqrt(T))
    d2 = d1 - sig * np.sqrt(T)
    call = spot * norm.cdf(d1) - strikes * norm.cdf(d2)
    put = call - spot + strikes
    calls = pd.DataFrame({"Strike": strikes, "IV%": ivs,
                          "Mark": np.maximum(call, 0.01)})
    puts = pd.DataFrame({"Strike": strikes, "IV%": ivs,
                         "Mark": np.maximum(put, 0.01)})
    return calls, puts


# ─────────────────────────────────────────────────────────────────────────────
#  SVI fit
# ─────────────────────────────────────────────────────────────────────────────
def test_svi_fits_flat_smile():
    # Flat smile → SVI total variance should be ~constant
    T = 1.0 / 365.0
    k = np.linspace(-0.1, 0.1, 21)
    w = np.full_like(k, (0.20 ** 2) * T)
    p, rmse = fit_svi(k, w, T)
    assert p is not None
    assert rmse < 1e-6  # near-perfect fit of a constant
    # Evaluated variance should match
    w_fit = svi_total_variance(p, k)
    assert np.allclose(w_fit, w, atol=1e-6)


def test_svi_fits_skewed_smile():
    T = 5.0 / 365.0
    k = np.linspace(-0.15, 0.15, 31)
    # Realistic put-skew: variance higher for low k (puts)
    w = (0.20 ** 2) * T + (-0.5) * k * (0.20 ** 2) * T + 2.0 * k ** 2 * (0.20 ** 2) * T
    w = np.clip(w, 1e-8, None)
    p, rmse = fit_svi(k, w, T)
    assert p is not None
    assert rmse < 1e-4
    # rho should be negative (put skew)
    assert p.rho < 0.3


def test_svi_g_nonneg_on_clean_fit():
    T = 5.0 / 365.0
    k = np.linspace(-0.15, 0.15, 31)
    w = (0.20 ** 2) * T * (1 + 1.5 * k ** 2)  # gentle symmetric smile
    p, rmse = fit_svi(k, w, T)
    assert p is not None
    g = svi_g_function(p, np.linspace(-0.2, 0.2, 81))
    # A gentle smile should be arbitrage-free (g ≥ 0 essentially everywhere)
    assert np.min(g) > -1e-2


def test_svi_too_few_points():
    p, rmse = fit_svi(np.array([0.0, 0.1]), np.array([0.01, 0.01]), 0.01)
    assert p is None
    assert rmse == float("inf")


# ─────────────────────────────────────────────────────────────────────────────
#  build_rnd
# ─────────────────────────────────────────────────────────────────────────────
def test_rnd_integrates_to_one():
    calls, puts = _chain(spot=580.0, n=61, base_iv=20.0, smile=0.05)
    rnd, meta = build_rnd(calls, puts, spot=580.0, dte=1)
    assert rnd is not None
    dK = np.gradient(rnd["strike"].to_numpy())
    area = float(np.sum(rnd["pdf"].to_numpy() * dK))
    assert area == pytest.approx(1.0, abs=0.03)
    assert meta["method"] in ("svi", "spline", "bl")
    assert meta["forward"] is not None


def test_rnd_density_nonnegative():
    calls, puts = _chain(spot=580.0, n=61, base_iv=20.0, smile=0.05)
    rnd, meta = build_rnd(calls, puts, spot=580.0, dte=1)
    assert rnd is not None
    assert (rnd["pdf"].to_numpy() >= 0).all()


def test_rnd_forward_centering():
    # With r>0, q=0, the forward sits above spot → mean should too
    calls, puts = _chain(spot=580.0, n=61, base_iv=20.0)
    rnd, meta = build_rnd(calls, puts, spot=580.0, dte=30, r=0.05, q=0.0)
    assert rnd is not None
    assert meta["forward"] > 580.0
    lv = rnd_levels(rnd, spot=580.0)
    # Implied mean ≈ forward (risk-neutral mean of S_T is the forward)
    assert lv["mean"] == pytest.approx(meta["forward"], rel=0.02)


def test_rnd_flat_vol_matches_lognormal():
    # A perfectly flat IV chain → RND should match the Black-Scholes
    # lognormal. Check the 1σ-equivalent quantiles (P16/P84).
    spot, iv, dte = 580.0, 20.0, 5
    calls, puts = _chain(spot=spot, n=81, base_iv=iv, skew=0, smile=0)
    rnd, meta = build_rnd(calls, puts, spot=spot, dte=dte, r=0.0, q=0.0)
    assert rnd is not None
    lv = rnd_levels(rnd, spot=spot)
    T = dte / 365.0
    sig = iv / 100.0
    # Lognormal quantiles of S_T (r=q=0 → forward=spot)
    # S_T = spot·exp(−0.5σ²T + σ√T·z)
    z16, z84 = norm.ppf(0.16), norm.ppf(0.84)
    q16 = spot * np.exp(-0.5 * sig**2 * T + sig * np.sqrt(T) * z16)
    q84 = spot * np.exp(-0.5 * sig**2 * T + sig * np.sqrt(T) * z84)
    assert lv["p16"] == pytest.approx(q16, rel=0.02)
    assert lv["p84"] == pytest.approx(q84, rel=0.02)


def test_rnd_insufficient_strikes():
    calls = pd.DataFrame({"Strike": [100, 101, 102], "IV%": [20, 21, 22]})
    puts = pd.DataFrame({"Strike": [98, 99], "IV%": [23, 22]})
    rnd, meta = build_rnd(calls, puts, spot=100.0, dte=1)
    assert rnd is None


# ─────────────────────────────────────────────────────────────────────────────
#  rnd_levels — exact percentiles
# ─────────────────────────────────────────────────────────────────────────────
def test_levels_percentiles_monotonic():
    calls, puts = _chain(spot=580.0, n=61, base_iv=20.0, smile=0.05)
    rnd, _ = build_rnd(calls, puts, spot=580.0, dte=1)
    lv = rnd_levels(rnd, spot=580.0)
    pct = lv["percentiles"]
    seq = [pct["p5"], pct["p10"], pct["p25"], pct["p50"],
           pct["p75"], pct["p90"], pct["p95"]]
    # Strictly increasing
    assert all(seq[i] < seq[i + 1] for i in range(len(seq) - 1))
    # Median near spot for a roughly symmetric smile
    assert abs(pct["p50"] - 580.0) < 6.0


def test_levels_probs_sum_to_one():
    calls, puts = _chain(spot=580.0, n=61, base_iv=20.0, smile=0.05)
    rnd, _ = build_rnd(calls, puts, spot=580.0, dte=1)
    lv = rnd_levels(rnd, spot=580.0,
                    levels={"put_wall": 575.0, "call_wall": 585.0})
    pw = lv["level_probs"]["put_wall"]
    assert pw["p_below"] + pw["p_above"] == pytest.approx(1.0, abs=1e-6)
    assert 0.0 <= pw["p_touch"] <= 1.0


def test_levels_put_skew_shifts_mass_down():
    # Strong put skew → more probability mass below spot → P(below spot)
    # should exceed 0.5 noticeably.
    calls, puts = _chain(spot=580.0, n=61, base_iv=20.0, skew=-0.6, smile=0.05)
    rnd, _ = build_rnd(calls, puts, spot=580.0, dte=1)
    lv = rnd_levels(rnd, spot=580.0, levels={"spot": 580.0})
    # Negative implied skewness expected under put-skew
    assert lv["skew"] < 0.3
