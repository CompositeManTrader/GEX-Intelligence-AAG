"""Black-Scholes sanity tests — put/call parity, limits, dividend handling."""
from __future__ import annotations

import math

import numpy as np
import pytest

from quant import bs


def test_d1_matches_hand_calc():
    # S=100, K=100, T=1, sigma=0.2, r=0.05, q=0
    # d1 = ((r + 0.5σ²)·T) / (σ·√T) = (0.07) / 0.2 = 0.35
    d1_val = float(bs.d1(100.0, 100.0, 1.0, 0.2, 0.05, 0.0))
    assert d1_val == pytest.approx(0.35, abs=1e-9)


def test_d1_returns_nan_on_invalid():
    assert math.isnan(float(bs.d1(100.0, 100.0, 0.0, 0.2, 0.05)))  # T=0
    assert math.isnan(float(bs.d1(100.0, 100.0, 1.0, 0.0, 0.05)))  # sigma=0
    assert math.isnan(float(bs.d1(-100.0, 100.0, 1.0, 0.2, 0.05)))  # S<0


def test_gamma_symmetric_call_put():
    # Gamma is the same for both sides (no `side` arg) and positive.
    # NOTE (model validation): the legacy assertion `g2 < g1` (claiming
    # dividends always reduce gamma) is FALSE in general — q shifts d1
    # as well as the e^(-qT) factor, so the net effect on φ(d1)/(Sσ√T)
    # is parameter-dependent. Gamma is validated against py_vollib in
    # tests/validation/test_val_bs.py; here we only assert positivity.
    g1 = float(bs.gamma(100.0, 100.0, 0.5, 0.25, 0.045, 0.0))
    g2 = float(bs.gamma(100.0, 100.0, 0.5, 0.25, 0.045, 0.02))
    assert g1 > 0 and g2 > 0


def test_delta_bounds():
    # Call delta in (0, 1), put delta in (-1, 0) with q=0
    c = float(bs.delta(100.0, 100.0, 0.5, 0.25, 0.05, 0.0, side="call"))
    p = float(bs.delta(100.0, 100.0, 0.5, 0.25, 0.05, 0.0, side="put"))
    assert 0.0 < c < 1.0
    assert -1.0 < p < 0.0
    # Put-call parity: Δ_call - Δ_put = e^{-qT}
    assert (c - p) == pytest.approx(1.0, abs=1e-6)


def test_delta_with_dividend():
    # With q>0: Δ_call - Δ_put = e^{-qT}
    c = float(bs.delta(100.0, 100.0, 1.0, 0.2, 0.05, 0.03, side="call"))
    p = float(bs.delta(100.0, 100.0, 1.0, 0.2, 0.05, 0.03, side="put"))
    assert (c - p) == pytest.approx(math.exp(-0.03), abs=1e-6)


def test_gamma_peaks_near_atm():
    # Gamma should be max ATM, fall off ITM/OTM
    S = 100.0
    g_atm = float(bs.gamma(S, 100.0, 0.25, 0.25, 0.045, 0.0))
    g_otm = float(bs.gamma(S, 120.0, 0.25, 0.25, 0.045, 0.0))
    g_itm = float(bs.gamma(S, 80.0, 0.25, 0.25, 0.045, 0.0))
    assert g_atm > g_otm and g_atm > g_itm


def test_vanna_sign_flips_around_atm():
    # Vanna has opposite signs ITM vs OTM (calls)
    v_itm = float(bs.vanna(100.0, 80.0, 0.5, 0.25, 0.045, 0.0))
    v_otm = float(bs.vanna(100.0, 120.0, 0.5, 0.25, 0.045, 0.0))
    assert v_itm * v_otm < 0


def test_charm_nonzero():
    c = float(bs.charm(100.0, 105.0, 0.25, 0.25, 0.045, 0.0, per="day"))
    assert math.isfinite(c)
    # Call charm OTM is typically negative on per-day basis
    assert c != 0.0


def test_time_to_expiry_zero_dte_intraday():
    # 0DTE — should return a small positive T (hours remaining fraction).
    # `time_to_expiry_years` is vectorised → returns an array; index [0]
    # before float() (numpy 2.x rejects float() on a 1-element array).
    t = float(bs.time_to_expiry_years(np.array([0]))[0])
    assert t > 0
    assert t < 1.0 / 365  # less than one full day


def test_time_to_expiry_nonzero():
    t = float(bs.time_to_expiry_years(np.array([30]))[0])
    assert t == pytest.approx(30.0 / 365.0, abs=1e-9)


def test_rate_for_dte_interp():
    r7 = float(bs.rate_for_dte(7))
    r30 = float(bs.rate_for_dte(30))
    r180 = float(bs.rate_for_dte(180))
    assert 0 < r180 < r30 <= r7 or r7 == r30  # decreasing curve in defaults
    # Extrapolation beyond tenor range clamps
    assert float(bs.rate_for_dte(1000)) == float(bs.rate_for_dte(365))


def test_broadcasting():
    # Vectorized evaluation over a strike grid
    S = 100.0
    Ks = np.array([80.0, 90.0, 100.0, 110.0, 120.0])
    gs = bs.gamma(S, Ks, 0.25, 0.25, 0.045, 0.0)
    assert gs.shape == Ks.shape
    assert np.all(gs >= 0)
    # Max should be ATM
    assert int(np.argmax(gs)) == 2
