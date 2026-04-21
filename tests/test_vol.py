"""Volatility estimators + iv rank / percentile tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.vol import (
    hv_close_to_close, hv_garman_klass, hv_parkinson, hv_yang_zhang,
    iv_percentile, iv_rank, vol_analytics,
)


def _synthetic_ohlc(n: int = 120, sigma_daily: float = 0.012, seed: int = 7):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, sigma_daily, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.002, n)))
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high,
        "low": low, "close": close, "volume": np.full(n, 1e6),
    })


def test_hv_close_to_close_positive():
    df = _synthetic_ohlc(120, 0.015)
    hv = hv_close_to_close(df["close"], 30).dropna()
    assert len(hv) > 0
    # Annualized vol of ~1.5% daily returns ≈ 23.8%
    assert 15.0 < float(hv.iloc[-1]) < 35.0


def test_parkinson_vs_close_to_close():
    # Parkinson should be close to (but slightly different from) C2C
    df = _synthetic_ohlc(120, 0.015)
    hv_c = float(hv_close_to_close(df["close"], 30).dropna().iloc[-1])
    hv_p = float(hv_parkinson(df["high"], df["low"], 30).dropna().iloc[-1])
    assert hv_p > 0
    # Both should be in the same ballpark (±50%)
    assert 0.3 < hv_p / hv_c < 3.0


def test_garman_klass_positive():
    df = _synthetic_ohlc(120, 0.015)
    hv = hv_garman_klass(df["open"], df["high"], df["low"], df["close"], 30).dropna()
    assert float(hv.iloc[-1]) > 0


def test_yang_zhang_positive():
    df = _synthetic_ohlc(120, 0.015)
    hv = hv_yang_zhang(df["open"], df["high"], df["low"], df["close"], 30).dropna()
    assert float(hv.iloc[-1]) > 0


def test_iv_rank_scaling():
    history = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0] * 10)  # range 10–50
    assert iv_rank(10.0, history) == pytest.approx(0.0, abs=0.1)
    assert iv_rank(50.0, history) == pytest.approx(100.0, abs=0.1)
    assert iv_rank(30.0, history) == pytest.approx(50.0, abs=0.1)


def test_iv_rank_insufficient_history():
    assert iv_rank(20.0, pd.Series([20.0] * 5)) is None
    assert iv_rank(20.0, None) is None


def test_iv_percentile():
    history = pd.Series(list(range(1, 101)))  # 1..100, n=100
    # 50 should be ~49% (49 values strictly less)
    assert iv_percentile(50, history) == pytest.approx(49.0, abs=1.0)
    assert iv_percentile(1, history) == pytest.approx(0.0, abs=1.0)
    assert iv_percentile(100, history) == pytest.approx(99.0, abs=1.0)


def test_vol_analytics_bundle_keys():
    df = _synthetic_ohlc(120, 0.015)
    out = vol_analytics(df, atm_iv=22.0)
    assert out  # non-empty
    for k in ("hv20", "hv30", "hv60", "iv_hv_ratio", "iv_hv_spread",
              "cone", "log_returns", "vol_regime"):
        assert k in out
    assert out["hv30"] is not None


def test_vol_analytics_empty_input():
    assert vol_analytics(pd.DataFrame(), atm_iv=20.0) == {}
    short = pd.DataFrame({"close": [100.0, 101.0]})
    assert vol_analytics(short, atm_iv=20.0) == {}
