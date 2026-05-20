"""Tests for quant/expected_move.py — bands, POT, prob_inside, IC suggester."""
from __future__ import annotations

import datetime

import numpy as np
import pytest

from quant.expected_move import (
    EMAnalysis, compute_em_bands, prob_inside, prob_of_touch,
    suggest_iron_condor,
)


# ─────────────────────────────────────────────────────────────────────────────
def test_prob_inside_full_real_line_is_one():
    p = prob_inside(spot=100.0, low=1e-6, high=1e6,
                    iv_pct=20.0, T=0.1)
    assert p == pytest.approx(1.0, abs=1e-6)


def test_prob_inside_symmetric_band_around_spot_is_about_68_for_1sigma():
    # 1σ symmetric band — by construction, ~68% mass under N(0,1).
    # With small (r-q-½σ²)T drift the answer is slightly off-center but
    # for T=0.05y, IV=20%, drift << 1σ so the value should be ~0.68.
    spot, iv, T = 100.0, 20.0, 0.05
    sigma_move = spot * (iv / 100.0) * np.sqrt(T)
    p = prob_inside(spot, spot - sigma_move, spot + sigma_move, iv, T)
    assert 0.65 < p < 0.71


def test_prob_inside_two_sigma_band_about_95():
    spot, iv, T = 100.0, 20.0, 0.05
    sigma_move = spot * (iv / 100.0) * np.sqrt(T)
    p = prob_inside(spot, spot - 2 * sigma_move, spot + 2 * sigma_move,
                    iv, T)
    assert 0.93 < p < 0.97


def test_prob_of_touch_higher_at_closer_strikes():
    far = prob_of_touch(100.0, 110.0, iv_pct=20.0, T=0.01)
    near = prob_of_touch(100.0, 102.0, iv_pct=20.0, T=0.01)
    assert near > far
    assert 0.0 <= far <= 1.0 and 0.0 <= near <= 1.0


def test_prob_of_touch_returns_zero_on_invalid():
    assert prob_of_touch(0, 100, 20, 0.01) == 0.0
    assert prob_of_touch(100, 0, 20, 0.01) == 0.0
    assert prob_of_touch(100, 100, 20, 0) == 0.0
    assert prob_of_touch(100, 100, 0, 0.1) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  compute_em_bands
# ─────────────────────────────────────────────────────────────────────────────
def test_em_bands_0dte_has_finite_width():
    """The user-reported bug: DTE=0 produced [spot, spot]. Verify the
    new analyzer gives finite-width bands using fractional T from BS."""
    # Pin `now` to mid-session (10:00 ET ≈ 14:00 UTC) so the fractional
    # hours-to-close path computes ~6h of T.
    now = datetime.datetime(2026, 5, 18, 14, 0, 0,
                            tzinfo=datetime.timezone.utc)
    a = compute_em_bands(spot=580.0, iv_call_pct=12.0, iv_put_pct=14.0,
                         dte=0, now=now)
    assert a is not None
    assert a.T > 0
    assert len(a.bands) == 4  # default sigmas
    b1 = next(b for b in a.bands if b.sigma == 1.0)
    assert b1.width > 0  # the actual bug-fix assertion
    assert b1.low < a.spot < b1.high


def test_em_bands_widen_with_sigma():
    a = compute_em_bands(spot=100.0, iv_call_pct=20.0, dte=7)
    widths = [b.width for b in a.bands]
    # Strictly increasing — bigger σ multiples → wider bands.
    assert widths == sorted(widths)


def test_em_bands_p_inside_increases_with_sigma():
    a = compute_em_bands(spot=100.0, iv_call_pct=20.0, dte=30)
    p_ins = [b.p_inside for b in a.bands]
    assert p_ins == sorted(p_ins)


def test_em_bands_skew_makes_lower_band_wider_when_put_iv_higher():
    a = compute_em_bands(spot=100.0, iv_call_pct=18.0, iv_put_pct=22.0,
                         dte=7, skew_adjust=True)
    assert a.skew_adjusted
    b1 = next(b for b in a.bands if b.sigma == 1.0)
    # Lower bound is further from spot than upper bound when put_IV > call_IV
    down = a.spot - b1.low
    up = b1.high - a.spot
    assert down > up


def test_em_bands_no_skew_when_disabled():
    a = compute_em_bands(spot=100.0, iv_call_pct=18.0, iv_put_pct=22.0,
                         dte=7, skew_adjust=False)
    assert not a.skew_adjusted
    b1 = next(b for b in a.bands if b.sigma == 1.0)
    # Symmetric → distances should match
    down = a.spot - b1.low
    up = b1.high - a.spot
    assert abs(down - up) < 1e-6


def test_em_bands_returns_none_on_invalid_input():
    assert compute_em_bands(spot=0, iv_call_pct=20.0) is None
    assert compute_em_bands(spot=100.0, iv_call_pct=None) is None


# ─────────────────────────────────────────────────────────────────────────────
#  suggest_iron_condor
# ─────────────────────────────────────────────────────────────────────────────
def test_ic_suggester_returns_strikes_outside_spot():
    a = compute_em_bands(spot=580.0, iv_call_pct=14.0, dte=0,
                         now=datetime.datetime(2026, 5, 18, 14, 0, 0,
                                               tzinfo=datetime.timezone.utc))
    ic = suggest_iron_condor(a, target_pop=0.70, wing_width=5.0)
    assert ic is not None
    assert ic.long_put < ic.short_put < a.spot < ic.short_call < ic.long_call
    assert ic.wing_width == 5.0


def test_ic_suggester_higher_target_pop_widens_strikes():
    a = compute_em_bands(spot=580.0, iv_call_pct=14.0, dte=0,
                         now=datetime.datetime(2026, 5, 18, 14, 0, 0,
                                               tzinfo=datetime.timezone.utc))
    ic_low = suggest_iron_condor(a, target_pop=0.50, wing_width=5.0)
    ic_high = suggest_iron_condor(a, target_pop=0.85, wing_width=5.0)
    width_low = ic_low.short_call - ic_low.short_put
    width_high = ic_high.short_call - ic_high.short_put
    assert width_high > width_low


def test_ic_suggester_prob_of_profit_in_range():
    a = compute_em_bands(spot=100.0, iv_call_pct=20.0, dte=7)
    ic = suggest_iron_condor(a, target_pop=0.70, wing_width=2.0)
    assert ic is not None
    # The realised POP should be within a reasonable distance of target
    # — exact match isn't possible after grid snapping.
    assert 0.55 < ic.prob_of_profit < 0.85


def test_ic_suggester_returns_none_on_invalid():
    assert suggest_iron_condor(None) is None
