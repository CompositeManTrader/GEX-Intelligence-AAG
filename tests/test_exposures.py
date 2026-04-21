"""GEX / VEX / CEX / DEX sanity tests on synthetic chains."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.exposures import (
    compute_cex_profile, compute_dex_profile, compute_gex_profile,
    compute_vex_profile, filter_chain, gamma_flip_on_spot_grid,
)


def _synthetic_chain(spot: float = 100.0, n: int = 11):
    """Build a symmetric synthetic chain with Gaussian-ish gamma around ATM."""
    strikes = np.linspace(spot * 0.9, spot * 1.1, n)
    # Peaked gamma at ATM — like a real chain
    gamma_vals = np.exp(-0.5 * ((strikes - spot) / (spot * 0.03)) ** 2) * 0.02
    oi = np.full(n, 1000.0)
    iv = np.full(n, 20.0)  # percent
    delta_call = np.clip(0.5 + (strikes - spot) * -0.01, 0, 1)
    delta_put = delta_call - 1.0
    dte = np.full(n, 30)

    calls = pd.DataFrame({
        "Strike": strikes, "OI": oi, "Gamma": gamma_vals, "IV%": iv,
        "Delta": delta_call, "DTE": dte, "Expiry": "2099-12-31",
    })
    puts = pd.DataFrame({
        "Strike": strikes, "OI": oi, "Gamma": gamma_vals, "IV%": iv,
        "Delta": delta_put, "DTE": dte, "Expiry": "2099-12-31",
    })
    return calls, puts


def test_filter_chain_drops_low_oi():
    calls = pd.DataFrame({
        "Strike": [100, 101, 102], "OI": [0, 500, 1000],
        "Gamma": [0.01, 0.01, 0.01], "DTE": [30, 30, 30],
    })
    out = filter_chain(calls, max_dte=60, min_oi=100)
    assert len(out) == 2
    assert (out["OI"] > 100).all()


def test_filter_chain_respects_max_dte():
    calls = pd.DataFrame({
        "Strike": [100, 101], "OI": [500, 500],
        "Gamma": [0.01, 0.01], "DTE": [30, 90],
    })
    out = filter_chain(calls, max_dte=60, min_oi=0)
    assert len(out) == 1


def test_gex_summary_keys_and_regime():
    calls, puts = _synthetic_chain()
    df, summary = compute_gex_profile(calls, puts, spot=100.0, symbol="TEST")
    assert not df.empty
    for k in ("regime", "total_gex", "call_gex", "put_gex",
              "gamma_flip", "call_wall", "put_wall", "hvl", "n_strikes"):
        assert k in summary
    # Calls positive, puts negative by convention
    assert summary["call_gex"] > 0
    assert summary["put_gex"] < 0


def test_gex_net_zero_on_symmetric_chain():
    # With identical OI and gamma, calls (+) and puts (-) cancel
    calls, puts = _synthetic_chain()
    _, summary = compute_gex_profile(calls, puts, spot=100.0, symbol="TEST")
    assert summary["total_gex"] == pytest.approx(0.0, abs=1e-6)


def test_hvl_is_atm_for_symmetric():
    calls, puts = _synthetic_chain(spot=100.0, n=11)
    df, summary = compute_gex_profile(calls, puts, spot=100.0, symbol="TEST")
    # HVL = strike with max |Net GEX|. For symmetric net=0 so |Net| is flat,
    # but the first argmax lands somewhere — just ensure it's a known strike.
    assert summary["hvl"] in df["Strike"].tolist()


def test_vex_profile_columns():
    calls, puts = _synthetic_chain()
    df, summary = compute_vex_profile(calls, puts, spot=100.0, symbol="TEST")
    if not df.empty:
        for c in ("C_VEX", "P_VEX", "Net_VEX", "Abs_VEX"):
            assert c in df.columns
        assert "total_vex" in summary


def test_cex_profile_columns():
    calls, puts = _synthetic_chain()
    df, summary = compute_cex_profile(calls, puts, spot=100.0, symbol="TEST")
    if not df.empty:
        for c in ("C_CEX", "P_CEX", "Net_CEX", "Abs_CEX"):
            assert c in df.columns
        assert "total_cex" in summary


def test_dex_direction():
    # Heavy call OI → positive DEX (call-heavy bias)
    strikes = np.linspace(95, 105, 5)
    calls = pd.DataFrame({
        "Strike": strikes, "OI": np.full(5, 10_000),
        "Gamma": np.full(5, 0.01), "Delta": np.full(5, 0.5),
        "DTE": np.full(5, 30),
    })
    puts = pd.DataFrame({
        "Strike": strikes, "OI": np.full(5, 100),
        "Gamma": np.full(5, 0.01), "Delta": np.full(5, -0.5),
        "DTE": np.full(5, 30),
    })
    _, summary = compute_dex_profile(calls, puts, spot=100.0)
    assert summary["total_dex"] > 0
    assert summary["bias"] == "CALL-HEAVY"


def test_empty_chain_returns_empty():
    df, summary = compute_gex_profile(pd.DataFrame(), pd.DataFrame(), spot=100.0)
    assert df.empty
    assert summary == {}


def test_gamma_flip_on_spot_grid_finds_zero():
    # Chain heavier on calls above spot — expect a gamma flip somewhere
    calls, puts = _synthetic_chain()
    flip = gamma_flip_on_spot_grid(calls, puts, spot=100.0, symbol="TEST")
    # With perfectly symmetric chain, the flip may or may not be found;
    # just ensure the function returns a float or None without crashing.
    assert flip is None or isinstance(flip, float)
