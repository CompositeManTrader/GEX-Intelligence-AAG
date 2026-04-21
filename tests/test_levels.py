"""Key-level analytics: max pain, PCR, ATM IV interp, expected move, skew, term structure."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.levels import (
    atm_iv_interp, expected_move, iv_skew, max_pain, put_call_ratio,
    risk_reversal_25d, term_structure,
)


def test_max_pain_simple_case():
    # Heavy OI at 100 on both sides → max pain = 100
    calls = pd.DataFrame({"Strike": [95, 100, 105], "OI": [100, 5000, 100]})
    puts = pd.DataFrame({"Strike": [95, 100, 105], "OI": [100, 5000, 100]})
    assert max_pain(calls, puts) == 100.0


def test_max_pain_empty():
    assert max_pain(pd.DataFrame(), pd.DataFrame()) is None


def test_put_call_ratio():
    calls = pd.DataFrame({"Strike": [100], "OI": [1000]})
    puts = pd.DataFrame({"Strike": [100], "OI": [500]})
    assert put_call_ratio(calls, puts, field="OI") == pytest.approx(0.5, abs=1e-9)


def test_put_call_ratio_empty():
    assert put_call_ratio(pd.DataFrame(), pd.DataFrame()) is None


def test_atm_iv_interp_exact_strike():
    calls = pd.DataFrame({
        "Strike": [95.0, 100.0, 105.0],
        "IV%": [25.0, 20.0, 22.0],
        "DTE": [30, 30, 30],
    })
    # Spot on a strike → IV of that strike
    assert atm_iv_interp(calls, spot=100.0) == pytest.approx(20.0, abs=0.1)


def test_atm_iv_interp_between_strikes():
    calls = pd.DataFrame({
        "Strike": [95.0, 105.0],
        "IV%": [20.0, 30.0],
        "DTE": [30, 30],
    })
    # Midpoint spot → linear interp = 25
    assert atm_iv_interp(calls, spot=100.0) == pytest.approx(25.0, abs=0.1)


def test_atm_iv_interp_filters_stale_iv():
    # Stale IV (<=1%) must be filtered
    calls = pd.DataFrame({
        "Strike": [95.0, 100.0, 105.0],
        "IV%": [0.5, 20.0, 22.0],
        "DTE": [30, 30, 30],
    })
    iv = atm_iv_interp(calls, spot=100.0)
    assert iv is not None
    assert 19 <= iv <= 23


def test_expected_move_basic():
    lo, hi = expected_move(spot=100.0, iv_pct=20.0, dte=30)
    # Expected move ≈ S × σ × √(T) = 100 × 0.2 × √(30/365) ≈ 5.73
    assert lo == pytest.approx(100.0 - 5.73, abs=0.2)
    assert hi == pytest.approx(100.0 + 5.73, abs=0.2)


def test_expected_move_none_on_bad_input():
    assert expected_move(0, 20.0, 30) == (None, None)
    assert expected_move(100.0, None, 30) == (None, None)
    assert expected_move(100.0, 20.0, None) == (None, None)


def test_iv_skew_basic_columns():
    calls = pd.DataFrame({
        "Strike": [95.0, 100.0, 105.0], "IV%": [22.0, 20.0, 19.0],
        "DTE": [30, 30, 30],
    })
    puts = pd.DataFrame({
        "Strike": [95.0, 100.0, 105.0], "IV%": [28.0, 22.0, 20.0],
        "DTE": [30, 30, 30],
    })
    sk = iv_skew(calls, puts, spot=100.0)
    assert not sk.empty
    for col in ("Strike", "C_IV", "P_IV", "Skew", "Moneyness"):
        assert col in sk.columns
    # Skew = P − C, should be positive (puts richer)
    assert (sk["Skew"] > 0).all()


def test_risk_reversal_25d_positive_when_puts_rich():
    calls = pd.DataFrame({
        "Strike": [95.0, 100.0, 105.0],
        "Delta": [0.7, 0.5, 0.25],
        "IV%": [22.0, 20.0, 19.0],
        "DTE": [30, 30, 30],
    })
    puts = pd.DataFrame({
        "Strike": [95.0, 100.0, 105.0],
        "Delta": [-0.25, -0.5, -0.7],
        "IV%": [28.0, 22.0, 20.0],
        "DTE": [30, 30, 30],
    })
    rr = risk_reversal_25d(calls, puts)
    assert rr is not None
    # 25Δ put IV 28 − 25Δ call IV 19 = 9
    assert rr == pytest.approx(9.0, abs=0.1)


def test_term_structure_sorted_by_dte():
    calls = pd.DataFrame({
        "Strike": [100.0, 100.0, 100.0],
        "IV%": [22.0, 25.0, 20.0],
        "DTE": [30, 7, 90],
        "Expiry": ["A", "B", "C"],
    })
    ts = term_structure(calls, spot=100.0)
    assert not ts.empty
    assert list(ts["DTE"]) == sorted(ts["DTE"])
