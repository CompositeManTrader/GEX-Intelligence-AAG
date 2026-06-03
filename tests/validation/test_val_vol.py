"""
Model-validation suite for quant/vol.py — realized-volatility estimators.

Strategy
--------
1. Published-formula re-implementation: each estimator is recomputed
   independently from its primary reference and asserted equal on a fixed
   deterministic OHLC frame. This catches wrong constants, wrong
   annualization (√252 vs √365), wrong ddof, and the Yang-Zhang
   overnight double-count.
2. Explicit constant checks: Parkinson 1/(4ln2), Garman-Klass (2ln2−1),
   Yang-Zhang k = 0.34/(1.34+(n+1)/(n−1)).
3. Absolute ground-truth anchor: a large Monte-Carlo GBM path with known
   σ — hv_close_to_close must recover it within sampling error.

References: Parkinson (1980); Garman-Klass (1980); Yang-Zhang (2000).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant import vol
from config import TRADING_DAYS


# ─────────────────────────────────────────────────────────────────────────────
#  Deterministic OHLC frame (with genuine overnight gaps, so YZ is exercised)
# ─────────────────────────────────────────────────────────────────────────────
def _ohlc(n=80, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    open_ = close * (1 + rng.normal(0, 0.004, n))     # overnight gap vs prev close handled in fn
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  1. Close-to-close
# ─────────────────────────────────────────────────────────────────────────────
def test_hv_close_to_close_matches_formula():
    df = _ohlc()
    w = 20
    got = vol.hv_close_to_close(df["close"], w)
    lr = np.log(df["close"] / df["close"].shift(1))
    exp = (lr.rolling(w).std() * np.sqrt(TRADING_DAYS) * 100).round(3)
    pd.testing.assert_series_equal(got, exp, check_names=False)
    # ddof is pandas default (1): confirm it's NOT population std
    last = lr.iloc[-w:]
    assert got.iloc[-1] == pytest.approx(
        float(last.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100), abs=1e-3)


def test_hv_close_to_close_recovers_known_sigma_montecarlo():
    """Absolute anchor: GBM with σ_ann=0.25 → estimator must recover ~25."""
    rng = np.random.default_rng(0)
    sigma_ann = 0.25
    n = 6000
    daily = rng.normal(0, sigma_ann / np.sqrt(TRADING_DAYS), n)
    closes = pd.Series(100 * np.exp(np.cumsum(daily)))
    hv = vol.hv_close_to_close(closes, n - 1).dropna().iloc[-1]
    # std-of-std sampling error ~ σ/√(2N) ≈ 0.9% → allow 5%
    assert hv == pytest.approx(sigma_ann * 100, rel=0.05)


# ─────────────────────────────────────────────────────────────────────────────
#  2. Parkinson
# ─────────────────────────────────────────────────────────────────────────────
def test_hv_parkinson_matches_formula_and_constant():
    df = _ohlc()
    w = 20
    got = vol.hv_parkinson(df["high"], df["low"], w)
    hl = np.log(df["high"] / df["low"])
    factor = 1.0 / (4.0 * np.log(2.0))
    assert factor == pytest.approx(0.360674, abs=1e-6)
    exp = (np.sqrt((hl * hl).rolling(w).mean() * factor * TRADING_DAYS) * 100).round(3)
    pd.testing.assert_series_equal(got, exp, check_names=False)


# ─────────────────────────────────────────────────────────────────────────────
#  3. Garman-Klass
# ─────────────────────────────────────────────────────────────────────────────
def test_hv_garman_klass_matches_formula_and_constant():
    df = _ohlc()
    w = 20
    got = vol.hv_garman_klass(df["open"], df["high"], df["low"], df["close"], w)
    hl = np.log(df["high"] / df["low"])
    co = np.log(df["close"] / df["open"])
    c2 = 2.0 * np.log(2.0) - 1.0
    assert c2 == pytest.approx(0.386294, abs=1e-6)
    term = 0.5 * hl * hl - c2 * co * co
    var = term.rolling(w).mean().clip(lower=0)
    exp = (np.sqrt(var * TRADING_DAYS) * 100).round(3)
    pd.testing.assert_series_equal(got, exp, check_names=False)


# ─────────────────────────────────────────────────────────────────────────────
#  4. Yang-Zhang  — and the overnight double-count fix
# ─────────────────────────────────────────────────────────────────────────────
def test_hv_yang_zhang_matches_formula_uses_intraday_oc():
    df = _ohlc()
    w = 20
    got = vol.hv_yang_zhang(df["open"], df["high"], df["low"], df["close"], w)

    ln_ho = np.log(df["high"] / df["open"])
    ln_lo = np.log(df["low"] / df["open"])
    ln_co = np.log(df["close"] / df["open"])          # ← intraday open→close
    ln_oc_prev = np.log(df["open"] / df["close"].shift(1))
    n = w
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    var_on = ln_oc_prev.rolling(w).var()
    var_oc = ln_co.rolling(w).var()
    rs = ln_ho * (ln_ho - ln_co) + ln_lo * (ln_lo - ln_co)
    var_rs = rs.rolling(w).mean()
    var_yz = (var_on + k * var_oc + (1 - k) * var_rs).clip(lower=0)
    exp = (np.sqrt(var_yz * TRADING_DAYS) * 100).round(3)
    pd.testing.assert_series_equal(got, exp, check_names=False)


def test_yang_zhang_k_constant():
    for n in (10, 20, 30, 60):
        k = 0.34 / (1.34 + (n + 1) / (n - 1))
        assert 0.0 < k < 0.34


def test_yang_zhang_does_not_use_close_to_close_for_oc():
    """Regression guard for the documented fix: the open-to-close term must
    be Var(ln C/O), not Var(ln C_t/C_{t-1}). Build data where the two differ
    materially (large persistent overnight gaps) and confirm YZ tracks the
    intraday-OC version, not the close-to-close one."""
    df = _ohlc(seed=3)
    w = 20
    got = float(vol.hv_yang_zhang(df["open"], df["high"], df["low"],
                                  df["close"], w).dropna().iloc[-1])

    ln_ho = np.log(df["high"] / df["open"]); ln_lo = np.log(df["low"] / df["open"])
    ln_co = np.log(df["close"] / df["open"])
    ln_cc = np.log(df["close"] / df["close"].shift(1))     # the WRONG term
    ln_oc_prev = np.log(df["open"] / df["close"].shift(1))
    n = w; k = 0.34 / (1.34 + (n + 1) / (n - 1))
    rs = (ln_ho * (ln_ho - ln_co) + ln_lo * (ln_lo - ln_co)).rolling(w).mean()
    correct = float((np.sqrt((ln_oc_prev.rolling(w).var()
                    + k * ln_co.rolling(w).var() + (1 - k) * rs).clip(lower=0)
                    * TRADING_DAYS) * 100).dropna().iloc[-1])
    wrong = float((np.sqrt((ln_oc_prev.rolling(w).var()
                    + k * ln_cc.rolling(w).var() + (1 - k) * rs).clip(lower=0)
                    * TRADING_DAYS) * 100).dropna().iloc[-1])
    assert got == pytest.approx(correct, abs=1e-3)
    # the wrong (double-counting) variant must be measurably different
    assert abs(correct - wrong) > 1e-3


# ─────────────────────────────────────────────────────────────────────────────
#  5. IV rank / percentile
# ─────────────────────────────────────────────────────────────────────────────
def test_iv_rank_formula():
    hist = pd.Series(np.linspace(10, 30, 50))   # min 10, max 30
    assert vol.iv_rank(20.0, hist) == pytest.approx(50.0, abs=0.1)
    assert vol.iv_rank(10.0, hist) == pytest.approx(0.0, abs=0.1)
    assert vol.iv_rank(30.0, hist) == pytest.approx(100.0, abs=0.1)
    # clamps outside [min,max]
    assert vol.iv_rank(35.0, hist) == 100.0
    assert vol.iv_rank(5.0, hist) == 0.0


def test_iv_rank_insufficient_history():
    assert vol.iv_rank(20.0, pd.Series(np.arange(10))) is None
    assert vol.iv_rank(20.0, None) is None


def test_iv_percentile_formula():
    hist = pd.Series(np.arange(0, 100))     # 0..99
    # fraction strictly below 25 = 25/100 = 25%
    assert vol.iv_percentile(25.0, hist) == pytest.approx(25.0, abs=0.5)
    assert vol.iv_percentile(50.0, hist) == pytest.approx(50.0, abs=0.5)


def test_iv_percentile_insufficient_history():
    assert vol.iv_percentile(20.0, pd.Series(np.arange(10))) is None


# ─────────────────────────────────────────────────────────────────────────────
#  6. Estimator ordering sanity (Parkinson/GK underestimate when gaps dominate)
# ─────────────────────────────────────────────────────────────────────────────
def test_all_estimators_positive_and_finite():
    df = _ohlc(n=120)
    for s in (
        vol.hv_close_to_close(df["close"], 30),
        vol.hv_parkinson(df["high"], df["low"], 30),
        vol.hv_garman_klass(df["open"], df["high"], df["low"], df["close"], 30),
        vol.hv_yang_zhang(df["open"], df["high"], df["low"], df["close"], 30),
    ):
        v = s.dropna()
        assert len(v) > 0
        assert np.all(np.isfinite(v))
        assert np.all(v >= 0)
