"""
Model-validation suite for quant/exposures.py  (GEX / VEX / CEX / DEX).

Independent verification strategy
---------------------------------
The greeks themselves (gamma, vanna, charm, delta) are validated against
py_vollib + finite differences in `test_val_bs.py`. THIS suite validates the
*exposure assembly layer* on top of them — the dollar-scaling, the dealer
sign convention, the per-strike grouping, the gamma-flip zero finder and the
wall detector — none of which `test_val_bs.py` touches.

Three independent angles per quantity:
  1. Hand-recomputation: rebuild the documented formula element-by-element
     and assert the profile column matches to machine precision.
  2. Economic finite-difference: re-derive the GEX dollar-scale from the
     *definition* ("$ the dealer must trade per 1% move") via a central
     difference of dealer delta — completely independent of bs.gamma.
  3. Invariants/properties: sign conventions, regime classification, flip
     zero-crossing, wall peak location, DTE-bucket boundaries.

Documented convention under test (SqueezeMetrics / GEXbot — dealer long
calls, short puts):
    GEX(k) = Γ·OI·100·S²·0.01·sign      sign(call)=+1, sign(put)=-1
    VEX(k) = Vanna·OI·100·S·0.01·sign
    CEX(k) = Charm·OI·100·S·sign        (Charm per calendar day)
    DEX(k) = Δ·OI·100·S                 (raw delta sign: call>0, put<0;
                                         NO dealer flip — see test below)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant import bs, exposures
from config import dividend_yield_for, MIN_IV_PCT, CALENDAR_DAYS


# ─────────────────────────────────────────────────────────────────────────────
#  Synthetic chain builder — internally consistent greeks via the (validated)
#  bs module, so the assembly layer is the only thing under test.
# ─────────────────────────────────────────────────────────────────────────────
def _build_side(spot, strikes, dte, iv_pct, oi, side, q=0.0, expiry="2026-07-17"):
    K = np.asarray(strikes, dtype=float)
    iv = np.asarray(iv_pct, dtype=float) / 100.0
    T = bs.time_to_expiry_years(np.full_like(K, dte))
    r = bs.rate_for_dte(np.full_like(K, dte))
    gamma = bs.gamma(spot, K, T, iv, r, q)
    delta = bs.delta(spot, K, T, iv, r, q, side=side)
    return pd.DataFrame({
        "Strike": K,
        "OI": np.asarray(oi, dtype=float),
        "Gamma": gamma,
        "Delta": delta,
        "IV%": np.asarray(iv_pct, dtype=float),
        "DTE": float(dte),
        "Expiry": expiry,
    })


def _standard_chain(spot=580.0, dte=30, q=0.0):
    """Calls clustered above + ATM, puts clustered below + ATM."""
    cstrikes = [575, 580, 585, 590, 595, 600]
    pstrikes = [560, 565, 570, 575, 580, 585]
    civ = [19, 18, 17.5, 17, 16.5, 16]
    piv = [22, 21, 20, 19, 18.5, 18]
    coi = [1200, 3000, 2500, 1800, 1500, 900]
    poi = [800, 1400, 2600, 3200, 2000, 1100]
    calls = _build_side(spot, cstrikes, dte, civ, coi, "call", q)
    puts = _build_side(spot, pstrikes, dte, piv, poi, "put", q)
    return calls, puts


# ─────────────────────────────────────────────────────────────────────────────
#  1. GEX — hand-recomputation of the dollar scale + sign convention
# ─────────────────────────────────────────────────────────────────────────────
def test_gex_scale_and_sign_hand_recompute():
    spot = 580.0
    calls, puts = _standard_chain(spot)
    df, summ = exposures.compute_gex_profile(
        calls, puts, spot, symbol="", use_spot_grid_flip=False)

    SCALE = 100.0 * spot * spot * 0.01
    # Expected per-strike call / put GEX, grouped by strike.
    exp_c = (calls.set_index("Strike")["Gamma"] * calls.set_index("Strike")["OI"]
             * SCALE * (+1.0))
    exp_p = (puts.set_index("Strike")["Gamma"] * puts.set_index("Strike")["OI"]
             * SCALE * (-1.0))

    got = df.set_index("Strike")
    for K, v in exp_c.items():
        assert got.loc[K, "C_GEX"] == pytest.approx(v, rel=1e-12, abs=1e-6)
    for K, v in exp_p.items():
        assert got.loc[K, "P_GEX"] == pytest.approx(v, rel=1e-12, abs=1e-6)

    # Net = C + P; calls add (+), puts subtract (−) — dealer long calls/short puts
    assert (got["Net_GEX"] == got["C_GEX"] + got["P_GEX"]).all()
    # Put legs must be negative, call legs positive (positive gamma, signed)
    assert (got["P_GEX"] <= 0).all()
    assert (got["C_GEX"] >= 0).all()
    # Summary totals consistent with the frame
    assert summ["total_gex"] == pytest.approx(float(df["Net_GEX"].sum()), rel=1e-12)
    assert summ["call_gex"] == pytest.approx(float(df["C_GEX"].sum()), rel=1e-12)
    assert summ["put_gex"] == pytest.approx(float(df["P_GEX"].sum()), rel=1e-12)


def test_gex_dollar_scale_is_economically_correct():
    """The '$ per 1% move' claim, validated from first principles.

    A dealer holding the call OI is long Δ·OI·100 shares of delta. To stay
    hedged through a price move he trades d(Δ·OI·100)/dS · dS shares; the
    DOLLAR notional traded for a +1% move (dS = 0.01·S) is

        $ = [dΔ/dS] · OI · 100 · (0.01·S) · S  =  Γ · OI · 100 · S² · 0.01.

    We estimate dΔ/dS with a *central finite difference of delta* (never
    touching bs.gamma), and confirm it reproduces C_GEX. This independently
    pins the SCALE = 100·S²·0.01 used in exposures.py.
    """
    spot = 580.0
    dte, iv_pct, oi = 30, 18.0, 3000.0
    K = 585.0
    T = float(bs.time_to_expiry_years(np.array([dte]))[0])
    r = float(bs.rate_for_dte(dte))

    h = spot * 1e-4
    d_up = float(bs.delta(spot + h, K, T, iv_pct / 100.0, r, 0.0, side="call"))
    d_dn = float(bs.delta(spot - h, K, T, iv_pct / 100.0, r, 0.0, side="call"))
    gamma_fd = (d_up - d_dn) / (2 * h)
    gex_fd = gamma_fd * oi * 100.0 * spot * spot * 0.01

    calls = _build_side(spot, [K], dte, [iv_pct], [oi], "call")
    puts = calls.iloc[:0].copy()
    df, _ = exposures.compute_gex_profile(calls, puts, spot, symbol="",
                                          use_spot_grid_flip=False)
    gex_code = float(df.set_index("Strike").loc[K, "C_GEX"])
    # FD vs analytic-gamma assembly agree to ~1e-5 relative
    assert gex_code == pytest.approx(gex_fd, rel=1e-4)


def test_gex_regime_classification():
    spot = 580.0
    # Call-dominated chain → POSITIVE; put-dominated → NEGATIVE.
    calls, puts = _standard_chain(spot)
    big_calls = calls.copy()
    big_calls["OI"] *= 50
    df, summ = exposures.compute_gex_profile(big_calls, puts, spot,
                                             use_spot_grid_flip=False)
    assert summ["regime"] == "POSITIVE"
    assert summ["total_gex"] > 0

    big_puts = puts.copy()
    big_puts["OI"] *= 50
    df2, summ2 = exposures.compute_gex_profile(calls, big_puts, spot,
                                               use_spot_grid_flip=False)
    assert summ2["regime"] == "NEGATIVE"
    assert summ2["total_gex"] < 0


# ─────────────────────────────────────────────────────────────────────────────
#  2. VEX — hand recompute against bs.vanna
# ─────────────────────────────────────────────────────────────────────────────
def test_vex_hand_recompute():
    spot = 580.0
    calls, puts = _standard_chain(spot)
    df, summ = exposures.compute_vex_profile(calls, puts, spot, symbol="SPY")

    q = dividend_yield_for("SPY")
    SCALE = 100.0 * spot * 0.01

    def expected(side_df, sign):
        K = side_df["Strike"].to_numpy(float)
        iv = side_df["IV%"].to_numpy(float) / 100.0
        dte = side_df["DTE"].to_numpy(float)
        T = bs.time_to_expiry_years(dte)
        r = bs.rate_for_dte(dte)
        v = bs.vanna(spot, K, T, iv, r, q)
        return pd.Series(v * side_df["OI"].to_numpy(float) * SCALE * sign,
                         index=K)

    exp_c = expected(calls, +1.0)
    exp_p = expected(puts, -1.0)
    got = df.set_index("Strike")
    for K, v in exp_c.items():
        assert got.loc[K, "C_VEX"] == pytest.approx(v, rel=1e-10, abs=1e-6)
    for K, v in exp_p.items():
        assert got.loc[K, "P_VEX"] == pytest.approx(v, rel=1e-10, abs=1e-6)
    assert summ["total_vex"] == pytest.approx(float(df["Net_VEX"].sum()), rel=1e-12)


# ─────────────────────────────────────────────────────────────────────────────
#  3. CEX — hand recompute against bs.charm, EXERCISING the put-side q sign
# ─────────────────────────────────────────────────────────────────────────────
def test_cex_hand_recompute_with_dividend():
    """With q>0 (SPY) the put-side charm adjustment (−q·e^{-qT}) is active,
    so this test guards the charm sign fix at the exposure layer."""
    spot = 580.0
    calls, puts = _standard_chain(spot, q=dividend_yield_for("SPY"))
    df, summ = exposures.compute_cex_profile(calls, puts, spot, symbol="SPY")

    q = dividend_yield_for("SPY")
    SCALE = 100.0 * spot

    def expected(side_df, sign, side):
        K = side_df["Strike"].to_numpy(float)
        iv = side_df["IV%"].to_numpy(float) / 100.0
        dte = side_df["DTE"].to_numpy(float)
        T = bs.time_to_expiry_years(dte)
        r = bs.rate_for_dte(dte)
        ch = bs.charm(spot, K, T, iv, r, q, per="day", side=side)
        return pd.Series(ch * side_df["OI"].to_numpy(float) * SCALE * sign,
                         index=K)

    exp_c = expected(calls, +1.0, "call")
    exp_p = expected(puts, -1.0, "put")
    got = df.set_index("Strike")
    for K, v in exp_c.items():
        assert got.loc[K, "C_CEX"] == pytest.approx(v, rel=1e-10, abs=1e-6)
    for K, v in exp_p.items():
        assert got.loc[K, "P_CEX"] == pytest.approx(v, rel=1e-10, abs=1e-6)


def test_cex_put_side_uses_corrected_sign():
    """Direct guard: CEX put leg must use charm(side='put'), which differs
    from charm(side='call') by exactly −q·e^{-qT}·OI·SCALE·(−1)."""
    spot = 580.0
    q = dividend_yield_for("SPY")
    K, dte, iv_pct, oi = 575.0, 30, 20.0, 2600.0
    puts = _build_side(spot, [K], dte, [iv_pct], [oi], "put", q)
    calls = puts.iloc[:0].copy()
    df, _ = exposures.compute_cex_profile(calls, puts, spot, symbol="SPY")

    T = float(bs.time_to_expiry_years(np.array([dte]))[0])
    r = float(bs.rate_for_dte(dte))
    charm_put = float(bs.charm(spot, K, T, iv_pct / 100.0, r, q,
                               per="day", side="put"))
    SCALE = 100.0 * spot
    expected = charm_put * oi * SCALE * (-1.0)
    assert float(df.set_index("Strike").loc[K, "P_CEX"]) == pytest.approx(
        expected, rel=1e-10)

    # And it must NOT equal the (wrong) call-charm assembly when q>0.
    charm_call = float(bs.charm(spot, K, T, iv_pct / 100.0, r, q,
                                per="day", side="call"))
    wrong = charm_call * oi * SCALE * (-1.0)
    assert abs(expected - wrong) > 0  # q>0 ⇒ genuinely different


# ─────────────────────────────────────────────────────────────────────────────
#  4. DEX — convention test: raw delta sign, NO dealer flip
# ─────────────────────────────────────────────────────────────────────────────
def test_dex_hand_recompute_and_convention():
    """DEX uses the RAW option delta sign (call δ>0 → +, put δ<0 → −) and
    does NOT apply the dealer long-call/short-put flip that GEX/VEX/CEX use.
    It is therefore a 'net delta imbalance of OI' (call-heavy vs put-heavy),
    a directional-positioning proxy — NOT a dealer-inventory delta. This test
    documents and locks that convention."""
    spot = 580.0
    calls, puts = _standard_chain(spot)
    df, summ = exposures.compute_dex_profile(calls, puts, spot)

    SCALE = 100.0 * spot
    exp_c = (calls.set_index("Strike")["Delta"].clip(0, 1)
             * calls.set_index("Strike")["OI"] * SCALE)
    exp_p = (puts.set_index("Strike")["Delta"].clip(-1, 0)
             * puts.set_index("Strike")["OI"] * SCALE)
    got = df.set_index("Strike")
    for K, v in exp_c.items():
        assert got.loc[K, "C_DEX"] == pytest.approx(v, rel=1e-10, abs=1e-6)
    for K, v in exp_p.items():
        assert got.loc[K, "P_DEX"] == pytest.approx(v, rel=1e-10, abs=1e-6)

    # Convention: call deltas contribute POSITIVE, put deltas NEGATIVE.
    assert (got["C_DEX"] >= 0).all()
    assert (got["P_DEX"] <= 0).all()
    assert summ["bias"] in ("CALL-HEAVY", "PUT-HEAVY", "NEUTRAL")


# ─────────────────────────────────────────────────────────────────────────────
#  5. Gamma flip — zero-crossing self-consistency with gex_curve_over_spot
# ─────────────────────────────────────────────────────────────────────────────
def test_gamma_flip_is_a_true_zero_crossing():
    spot = 580.0
    calls, puts = _standard_chain(spot)
    flip = exposures.gamma_flip_on_spot_grid(calls, puts, spot, symbol="SPY")
    assert flip is not None

    curve = exposures.gex_curve_over_spot(calls, puts, spot, symbol="SPY")
    # GEX evaluated just below and just above the flip must bracket zero.
    eps = spot * 1e-3
    below = np.interp(flip - eps, curve["Spot"], curve["GEX"])
    above = np.interp(flip + eps, curve["Spot"], curve["GEX"])
    assert below * above < 0, "flip must separate opposite-sign GEX regions"
    # GEX at the flip itself ≈ 0 relative to the curve's scale.
    at = abs(np.interp(flip, curve["Spot"], curve["GEX"]))
    scale = float(np.max(np.abs(curve["GEX"]))) + 1e-9
    assert at / scale < 0.05


def test_gamma_flip_none_when_no_crossing():
    # All-call chain (pure positive gamma) → no sign change → None.
    spot = 580.0
    calls, _ = _standard_chain(spot)
    empty = calls.iloc[:0].copy()
    flip = exposures.gamma_flip_on_spot_grid(calls, empty, spot)
    assert flip is None


# ─────────────────────────────────────────────────────────────────────────────
#  6. Wall detection — constructed peak / trough
# ─────────────────────────────────────────────────────────────────────────────
def test_find_wall_locates_peak_and_trough():
    spot = 580.0
    strikes = np.array([560, 565, 570, 575, 580, 585, 590, 595, 600], float)
    # Clear positive peak at 595 (above spot), negative trough at 565 (below).
    net = np.array([-2, -9, -3, -1, 0, 1, 3, 10, 2], float) * 1e6
    call_wall = exposures._find_wall(strikes, net, sign=+1, spot=spot)
    put_wall = exposures._find_wall(strikes, net, sign=-1, spot=spot)
    assert call_wall == 595.0
    assert put_wall == 565.0


def test_find_wall_respects_spot_side_constraint():
    spot = 580.0
    strikes = np.array([570, 575, 585, 590], float)
    # Largest positive value is BELOW spot (575); constrained call wall must
    # pick the largest positive ABOVE spot instead.
    net = np.array([1, 9, 4, 5], float) * 1e6
    call_wall = exposures._find_wall(strikes, net, sign=+1, spot=spot)
    assert call_wall in (585.0, 590.0)
    assert call_wall > spot


def test_find_wall_rejects_weak_peak():
    # No peak exceeds 50% of the max → None (here the single peak IS the max,
    # so use a flat series where nothing is a real wall: all equal).
    strikes = np.array([570, 575, 580, 585, 590], float)
    net = np.zeros_like(strikes)
    assert exposures._find_wall(strikes, net, sign=+1) is None


# ─────────────────────────────────────────────────────────────────────────────
#  7. filter_chain — DTE bucket boundaries & OI/Gamma/IV filters
# ─────────────────────────────────────────────────────────────────────────────
def test_filter_chain_dte_boundaries_inclusive():
    df = pd.DataFrame({
        "Strike": [1, 2, 3, 4, 5],
        "OI": [10, 10, 10, 10, 10],
        "Gamma": [0.1, 0.1, 0.1, 0.1, 0.1],
        "DTE": [0, 1, 7, 8, 60],
    })
    # 0DTE only
    z = exposures.filter_chain(df, min_dte=0, max_dte=0)
    assert set(z["DTE"]) == {0}
    # front-week excl 0DTE
    wk = exposures.filter_chain(df, min_dte=1, max_dte=7)
    assert set(wk["DTE"]) == {1, 7}
    # monthly bucket inclusive of 8 and 60
    mo = exposures.filter_chain(df, min_dte=8, max_dte=60)
    assert set(mo["DTE"]) == {8, 60}
    # buckets are disjoint and exhaustive over 0..60
    assert len(z) + len(wk) + len(mo) == 5


def test_filter_chain_drops_zero_oi_and_nonpositive_gamma():
    df = pd.DataFrame({
        "Strike": [1, 2, 3, 4],
        "OI": [0, 5, 5, 5],          # OI=0 dropped (OI > min_oi, min_oi=0)
        "Gamma": [0.1, 0.0, -0.1, 0.2],  # gamma 0 and <0 dropped
        "DTE": [10, 10, 10, 10],
    })
    out = exposures.filter_chain(df)
    assert list(out["Strike"]) == [4]


def test_filter_chain_require_iv_threshold():
    df = pd.DataFrame({
        "Strike": [1, 2, 3],
        "OI": [5, 5, 5],
        "Gamma": [0.1, 0.1, 0.1],
        "DTE": [10, 10, 10],
        "IV%": [MIN_IV_PCT - 0.5, MIN_IV_PCT, 20.0],  # only >MIN_IV_PCT kept
    })
    out = exposures.filter_chain(df, require_iv=True)
    assert list(out["Strike"]) == [3]


# ─────────────────────────────────────────────────────────────────────────────
#  8. Grouping — duplicate strikes are summed
# ─────────────────────────────────────────────────────────────────────────────
def test_group_strike_sums_duplicates():
    spot = 580.0
    calls = _build_side(spot, [585, 585, 590], 30, [18, 18, 17], [1000, 500, 800], "call")
    puts = calls.iloc[:0].copy()
    df, _ = exposures.compute_gex_profile(calls, puts, spot,
                                          use_spot_grid_flip=False)
    # Two 585 rows collapsed into one summed row
    assert (df["Strike"] == 585).sum() == 1
    SCALE = 100.0 * spot * spot * 0.01
    g585 = bs.gamma(spot, 585.0,
                    float(bs.time_to_expiry_years(np.array([30]))[0]),
                    0.18, float(bs.rate_for_dte(30)), 0.0)
    expected = float(g585) * (1000 + 500) * SCALE
    assert float(df.set_index("Strike").loc[585, "C_GEX"]) == pytest.approx(
        expected, rel=1e-10)


# ─────────────────────────────────────────────────────────────────────────────
#  9. Empty / degenerate inputs never raise
# ─────────────────────────────────────────────────────────────────────────────
def test_empty_inputs_return_empty():
    empty = pd.DataFrame(columns=["Strike", "OI", "Gamma", "IV%", "DTE", "Delta"])
    for fn in (exposures.compute_gex_profile, exposures.compute_vex_profile,
               exposures.compute_cex_profile):
        df, summ = fn(empty, empty, 580.0)
        assert df.empty and summ == {}
    d, s = exposures.compute_dex_profile(empty, empty, 580.0)
    assert d.empty and s == {}


def test_nonpositive_spot_returns_empty():
    calls, puts = _standard_chain(580.0)
    for fn in (exposures.compute_gex_profile, exposures.compute_vex_profile,
               exposures.compute_cex_profile, exposures.compute_dex_profile):
        df, summ = fn(calls, puts, 0.0)
        assert df.empty and summ == {}
