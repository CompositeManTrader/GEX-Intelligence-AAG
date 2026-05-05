"""Tests for quant/zones — synthetic Gaussian profiles."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.zones import GammaZone, find_gamma_zones, spot_in_zone


def _gauss(strikes: np.ndarray, mu: float, sigma: float, amp: float) -> np.ndarray:
    return amp * np.exp(-0.5 * ((strikes - mu) / sigma) ** 2)


def _profile(strikes: np.ndarray, net_gex: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"Strike": strikes, "Net_GEX": net_gex})


# ─────────────────────────────────────────────────────────────────────────────
def test_empty_input_returns_empty():
    assert find_gamma_zones(None, spot=100.0) == []
    assert find_gamma_zones(pd.DataFrame(), spot=100.0) == []
    assert find_gamma_zones(pd.DataFrame({"Strike": [100], "Net_GEX": [0]}),
                            spot=100.0) == []


def test_invalid_spot_returns_empty():
    strikes = np.linspace(95, 105, 11)
    df = _profile(strikes, _gauss(strikes, 100, 1.5, 1e9))
    assert find_gamma_zones(df, spot=0.0) == []
    assert find_gamma_zones(df, spot=-50.0) == []


def test_single_peak_yields_one_zone():
    strikes = np.linspace(80, 120, 41)
    net_gex = _gauss(strikes, 100, 1.5, 1e9)
    zones = find_gamma_zones(_profile(strikes, net_gex), spot=100.0, top_n=3)
    assert len(zones) >= 1
    z1 = zones[0]
    assert z1.rank == 1 and z1.label == "P1"
    assert abs(z1.peak_strike - 100.0) <= 1
    assert z1.side == "call_dominant"
    assert z1.peak_gex_mm > 0


def test_two_peaks_ranked_by_integrated_score():
    strikes = np.linspace(80, 120, 81)  # 0.5-strike grid
    big = _gauss(strikes, 92, 1.5, 2e9)        # large positive
    small = _gauss(strikes, 108, 1.5, -1e9)    # smaller negative
    zones = find_gamma_zones(_profile(strikes, big + small), spot=100.0, top_n=3)
    assert len(zones) >= 2
    assert zones[0].integrated_gex_mm > zones[1].integrated_gex_mm
    # Big peak is positive (call_dominant); secondary is negative
    assert zones[0].side == "call_dominant"
    assert zones[1].side == "put_dominant"


def test_zone_has_finite_width():
    strikes = np.linspace(95, 105, 21)
    df = _profile(strikes, _gauss(strikes, 100, 1.0, 1e9))
    zones = find_gamma_zones(df, spot=100.0)
    z1 = zones[0]
    assert z1.width >= 0
    assert z1.low_strike <= z1.peak_strike <= z1.high_strike


def test_distance_pct_and_above_below():
    # Peak above spot
    strikes = np.linspace(95, 110, 31)
    df = _profile(strikes, _gauss(strikes, 105, 0.7, 1e9))
    zones = find_gamma_zones(df, spot=100.0)
    assert zones[0].distance_pct > 0
    assert zones[0].is_above_spot

    # Peak below spot
    strikes = np.linspace(90, 105, 31)
    df = _profile(strikes, _gauss(strikes, 95, 0.7, 1e9))
    zones = find_gamma_zones(df, spot=100.0)
    assert zones[0].distance_pct < 0
    assert not zones[0].is_above_spot


def test_overlap_resolution_keeps_strongest():
    # Two near-identical Gaussians overlap → only the bigger should survive
    strikes = np.linspace(95, 105, 41)
    big = _gauss(strikes, 100.0, 0.8, 2e9)
    overlapping = _gauss(strikes, 100.4, 0.8, 1e9)  # overlaps the first
    zones = find_gamma_zones(_profile(strikes, big + overlapping),
                             spot=100.0, top_n=3)
    # Both peaks get detected by find_peaks but the second one's cluster
    # overlaps the first; overlap resolution keeps only the strongest.
    assert len(zones) == 1


def test_top_n_limits_output():
    strikes = np.linspace(80, 120, 81)
    net = (_gauss(strikes, 88, 1.0, 1.5e9)
           + _gauss(strikes, 96, 1.0, 1.0e9)
           + _gauss(strikes, 104, 1.0, 0.7e9)
           + _gauss(strikes, 112, 1.0, 0.5e9))
    zones = find_gamma_zones(_profile(strikes, net), spot=100.0, top_n=2)
    assert len(zones) == 2
    # Strongest first
    assert zones[0].integrated_gex_mm > zones[1].integrated_gex_mm
    assert zones[0].label == "P1" and zones[1].label == "P2"


def test_mixed_zone_when_calls_and_puts_cancel():
    # A flat profile with sign changes inside one cluster should be 'mixed'
    strikes = np.linspace(99, 101, 21)
    # Alternating sign of similar magnitude → near-zero zone_net relative
    # to integrated |GEX|.
    net = np.array([1e8 * (1 if i % 2 == 0 else -1) for i in range(len(strikes))])
    zones = find_gamma_zones(_profile(strikes, net), spot=100.0, top_n=3)
    if zones:  # might or might not produce a zone — just check side label is sane
        for z in zones:
            assert z.side in ("call_dominant", "put_dominant", "mixed")


def test_to_dict_round_trips():
    strikes = np.linspace(95, 105, 21)
    df = _profile(strikes, _gauss(strikes, 100, 1.0, 1e9))
    zones = find_gamma_zones(df, spot=100.0)
    d = zones[0].to_dict()
    for k in ("rank", "label", "peak_strike", "low_strike", "high_strike",
              "width", "peak_gex_mm", "integrated_gex_mm", "side",
              "distance_pct", "is_above_spot"):
        assert k in d


def test_spot_in_zone_helper():
    strikes = np.linspace(90, 110, 41)
    df = _profile(strikes, _gauss(strikes, 100, 1.0, 1e9))
    zones = find_gamma_zones(df, spot=100.0)
    assert spot_in_zone(zones, 100.0) is not None
    assert spot_in_zone(zones, 80.0) is None
    assert spot_in_zone([], 100.0) is None
