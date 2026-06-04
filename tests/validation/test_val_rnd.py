"""
Model-validation suite for quant/rnd.py — the CENTRAL Expected-Range model.

This is the model that, ultimately, sizes real trades. It receives the
heaviest scrutiny. We validate it against *closed-form ground truth* and the
defining axioms of a risk-neutral density, not against itself.

Independent checks
------------------
A. Defining axioms of an RND  f(K):
     (1) ∫ f(K) dK = 1                         (proper density)
     (2) f(K) ≥ 0                              (no butterfly arbitrage)
     (3) E_Q[S_T] = ∫ K·f(K) dK = F = S·e^{(r−q)T}
         ← THE martingale / forward-pricing property. The mean must equal
           the FORWARD, never spot. A model that returns spot here is wrong.
B. Closed-form recovery: feed a FLAT IV smile (σ const). The recovered RND
   MUST equal the Black-Scholes lognormal density analytically:
       f_LN(K) = φ(d2) / (K·σ·√T),  d2 = (ln(F/K) − ½σ²T)/(σ√T)
   and the CDF-inverted percentiles must equal the lognormal quantiles
       K_p = F·exp(−½σ²T + σ√T·z_p).
C. SVI internals: svi_total_variance vs the raw formula; svi_g_function's
   analytic w',w'' vs central finite differences; fit_svi round-trip.
D. _black76_call vs py_vollib.black (independent Black-76 implementation).
E. Skew sign: an equity put-skew smile must yield a left-skewed RND.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from quant import rnd

warnings.filterwarnings("ignore")

try:
    import py_vollib.black as ref_black
    _HAS_VOLLIB = True
except Exception:
    _HAS_VOLLIB = False


# ─────────────────────────────────────────────────────────────────────────────
#  Chain builders
# ─────────────────────────────────────────────────────────────────────────────
def _flat_chain(spot=580.0, iv_pct=20.0, lo=0.80, hi=1.20, step=2.5):
    F_approx = spot
    strikes = np.arange(round(lo * F_approx), round(hi * F_approx) + step, step)
    calls = pd.DataFrame({"Strike": strikes, "IV%": np.full_like(strikes, iv_pct, float)})
    puts = pd.DataFrame({"Strike": strikes, "IV%": np.full_like(strikes, iv_pct, float)})
    return calls, puts


def _skew_chain(spot=580.0, atm_iv=20.0, slope=-0.06, lo=0.80, hi=1.20, step=2.5):
    """Linear-in-log-moneyness put skew: IV rises for low strikes."""
    strikes = np.arange(round(lo * spot), round(hi * spot) + step, step).astype(float)
    k = np.log(strikes / spot)
    iv = atm_iv * (1.0 + slope * (k / 0.10))  # ~slope per 10% moneyness
    iv = np.clip(iv, 5.0, 80.0)
    calls = pd.DataFrame({"Strike": strikes, "IV%": iv})
    puts = pd.DataFrame({"Strike": strikes, "IV%": iv})
    return calls, puts


# ─────────────────────────────────────────────────────────────────────────────
#  A. Defining axioms of a risk-neutral density
# ─────────────────────────────────────────────────────────────────────────────
def test_rnd_integrates_to_one():
    calls, puts = _skew_chain()
    rnd_df, meta = rnd.build_rnd(calls, puts, spot=580.0, dte=30, r=0.045, q=0.0)
    assert rnd_df is not None
    K = rnd_df["strike"].to_numpy()
    pdf = rnd_df["pdf"].to_numpy()
    area = np.trapezoid(pdf, K) if hasattr(np, "trapezoid") else np.trapz(pdf, K)
    assert area == pytest.approx(1.0, abs=1e-3)
    # CDF ends at 1, starts at 0, monotone non-decreasing
    cdf = rnd_df["cdf"].to_numpy()
    assert cdf[0] == pytest.approx(0.0, abs=1e-6)
    assert cdf[-1] == pytest.approx(1.0, abs=1e-6)
    assert np.all(np.diff(cdf) >= -1e-9)


def test_rnd_nonnegative():
    calls, puts = _skew_chain()
    rnd_df, _ = rnd.build_rnd(calls, puts, spot=580.0, dte=30, r=0.045, q=0.0)
    assert (rnd_df["pdf"].to_numpy() >= 0).all()


def test_rnd_is_a_martingale_mean_equals_forward():
    """E_Q[S_T] must equal the forward F = S·e^{(r−q)T}, NOT spot."""
    spot, r, q, dte = 580.0, 0.045, 0.0, 30
    calls, puts = _skew_chain(spot=spot)
    rnd_df, meta = rnd.build_rnd(calls, puts, spot=spot, dte=dte, r=r, q=q)
    K = rnd_df["strike"].to_numpy()
    pdf = rnd_df["pdf"].to_numpy()
    mean = np.trapezoid(K * pdf, K) if hasattr(np, "trapezoid") else np.trapz(K * pdf, K)

    F = spot * np.exp((r - q) * (dte / 365.0))
    assert meta["forward"] == pytest.approx(F, rel=1e-6)
    # Forward-pricing identity holds to BL discretization error (<0.3%)
    assert mean == pytest.approx(F, rel=3e-3)
    # And the mean is distinctly NOT spot (sanity that we centred on forward)
    assert abs(mean - F) < abs(mean - spot) or F == pytest.approx(spot, abs=1e-9)


def test_rnd_martingale_with_dividend_shifts_forward_below_spot():
    """With q > r the forward sits below spot; the RND mean must follow."""
    spot, r, q, dte = 580.0, 0.02, 0.05, 45
    calls, puts = _skew_chain(spot=spot)
    rnd_df, meta = rnd.build_rnd(calls, puts, spot=spot, dte=dte, r=r, q=q)
    F = spot * np.exp((r - q) * (dte / 365.0))
    assert F < spot                       # q>r ⇒ forward below spot
    K = rnd_df["strike"].to_numpy(); pdf = rnd_df["pdf"].to_numpy()
    mean = np.trapezoid(K * pdf, K) if hasattr(np, "trapezoid") else np.trapz(K * pdf, K)
    assert mean == pytest.approx(F, rel=4e-3)
    assert mean < spot


# ─────────────────────────────────────────────────────────────────────────────
#  B. Closed-form lognormal recovery (flat vol)  — the gold-standard test
# ─────────────────────────────────────────────────────────────────────────────
def test_rnd_recovers_lognormal_under_flat_vol():
    spot, r, q, dte, sigma = 580.0, 0.045, 0.0, 30, 0.20
    calls, puts = _flat_chain(spot=spot, iv_pct=sigma * 100)
    rnd_df, meta = rnd.build_rnd(calls, puts, spot=spot, dte=dte, r=r, q=q)
    assert rnd_df is not None
    assert meta["method"] == "svi"
    assert meta["arb_free"] is True       # flat smile ⇒ g(k)≈1 > 0

    T = dte / 365.0
    F = meta["forward"]
    K = rnd_df["strike"].to_numpy()
    pdf_model = rnd_df["pdf"].to_numpy()

    # Analytic Black-Scholes lognormal density in the forward measure
    d2 = (np.log(F / K) - 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))
    pdf_ln = norm.pdf(d2) / (K * sigma * np.sqrt(T))

    # Compare on the interior (avoid gradient edge effects in truncated tails)
    kk = np.log(K / F)
    interior = np.abs(kk) < 2.5 * sigma * np.sqrt(T)
    num = np.abs(pdf_model[interior] - pdf_ln[interior])
    denom = pdf_ln[interior].max()
    assert np.max(num) / denom < 0.02     # <2% of peak, pointwise


def test_rnd_percentiles_match_lognormal_quantiles():
    spot, r, q, dte, sigma = 580.0, 0.045, 0.0, 30, 0.20
    calls, puts = _flat_chain(spot=spot, iv_pct=sigma * 100)
    rnd_df, meta = rnd.build_rnd(calls, puts, spot=spot, dte=dte, r=r, q=q)
    T = dte / 365.0
    F = meta["forward"]
    lv = rnd.rnd_levels(rnd_df, spot=spot,
                        percentiles=(5, 10, 16, 25, 50, 75, 84, 90, 95))
    for p in (5, 10, 16, 25, 50, 75, 84, 90, 95):
        z = norm.ppf(p / 100.0)
        K_analytic = F * np.exp(-0.5 * sigma ** 2 * T + sigma * np.sqrt(T) * z)
        K_model = lv["percentiles"][f"p{p}"]
        assert K_model == pytest.approx(K_analytic, rel=2e-3), f"p{p}"

    # Median of S_T is F·e^{-½σ²T}, strictly below the forward (mean)
    assert lv["percentiles"]["p50"] < F


def test_rnd_std_matches_lognormal_under_flat_vol():
    spot, r, q, dte, sigma = 580.0, 0.045, 0.0, 30, 0.20
    calls, puts = _flat_chain(spot=spot, iv_pct=sigma * 100)
    rnd_df, meta = rnd.build_rnd(calls, puts, spot=spot, dte=dte, r=r, q=q)
    T = dte / 365.0
    F = meta["forward"]
    lv = rnd.rnd_levels(rnd_df, spot=spot)
    # Var[S_T] = F²·(e^{σ²T} − 1) for a lognormal forward
    std_analytic = F * np.sqrt(np.exp(sigma ** 2 * T) - 1.0)
    assert lv["std"] == pytest.approx(std_analytic, rel=1e-2)


# ─────────────────────────────────────────────────────────────────────────────
#  C. SVI internals
# ─────────────────────────────────────────────────────────────────────────────
def test_svi_total_variance_formula():
    p = rnd.SVIParams(a=0.04, b=0.4, rho=-0.3, m=0.0, sigma=0.1)
    k = np.array([-0.2, -0.05, 0.0, 0.05, 0.2])
    expected = p.a + p.b * (p.rho * (k - p.m) + np.sqrt((k - p.m) ** 2 + p.sigma ** 2))
    np.testing.assert_allclose(rnd.svi_total_variance(p, k), expected, rtol=1e-14)


def test_svi_g_function_matches_finite_difference():
    """svi_g_function uses analytic w', w''. Validate them with HIGH-accuracy
    pointwise central differences (h=1e-4) — not a coarse np.gradient grid,
    whose O(h²) second-derivative truncation would swamp the comparison —
    then reassemble Gatheral's g(k) and confirm the analytic version matches.
    This independently verifies both the derivative formulas AND the algebra
    of svi_g_function."""
    p = rnd.SVIParams(a=0.04, b=0.4, rho=-0.35, m=0.02, sigma=0.12)
    k = np.linspace(-0.3, 0.3, 61)
    h = 1e-4
    w0 = rnd.svi_total_variance(p, k)
    wp_fd = (rnd.svi_total_variance(p, k + h) - rnd.svi_total_variance(p, k - h)) / (2 * h)
    wpp_fd = (rnd.svi_total_variance(p, k + h) - 2 * w0
              + rnd.svi_total_variance(p, k - h)) / (h * h)
    g_ref = ((1.0 - k * wp_fd / (2.0 * w0)) ** 2
             - (wp_fd ** 2 / 4.0) * (1.0 / w0 + 0.25) + wpp_fd / 2.0)
    g_an = rnd.svi_g_function(p, k)
    np.testing.assert_allclose(g_an, g_ref, rtol=1e-5, atol=1e-6)


def test_fit_svi_roundtrip():
    """Generate w from known params, refit, confirm w(k) is reproduced."""
    p_true = rnd.SVIParams(a=0.035, b=0.5, rho=-0.4, m=0.01, sigma=0.10)
    k = np.linspace(-0.25, 0.25, 25)
    w = rnd.svi_total_variance(p_true, k)
    T = 0.0822
    p_fit, rmse = rnd.fit_svi(k, w, T)
    assert p_fit is not None
    w_fit = rnd.svi_total_variance(p_fit, k)
    np.testing.assert_allclose(w_fit, w, rtol=1e-3, atol=1e-5)
    assert rmse < 1e-3


def test_fit_svi_too_few_points():
    p, rmse = rnd.fit_svi(np.array([0.0, 0.1, 0.2]), np.array([0.04, 0.04, 0.05]), 0.1)
    assert p is None and rmse == float("inf")


# ─────────────────────────────────────────────────────────────────────────────
#  D. _black76_call vs py_vollib (independent Black-76)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _HAS_VOLLIB, reason="py_vollib not installed")
def test_black76_call_vs_pyvollib():
    F, T, r = 582.0, 0.0822, 0.045
    for K in [520.0, 560.0, 582.0, 600.0, 640.0]:
        for sigma in [0.12, 0.20, 0.35]:
            ours = float(rnd._black76_call(F, np.array([K]), T, np.array([sigma]), r)[0])
            ref = ref_black.black("c", F, K, T, r, sigma)
            assert ours == pytest.approx(ref, rel=1e-9, abs=1e-9)


def test_black76_call_put_parity_via_forward():
    """C − P = e^{-rT}(F − K). Build P from the same formula by symmetry to
    confirm the discounting/forward structure is internally consistent."""
    F, T, r, K, sigma = 582.0, 0.0822, 0.045, 600.0, 0.22
    c = float(rnd._black76_call(F, np.array([K]), T, np.array([sigma]), r)[0])
    # Put via parity should equal Black-76 put computed independently
    d1 = (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    p_independent = np.exp(-r * T) * (K * norm.cdf(-d2) - F * norm.cdf(-d1))
    assert (c - p_independent) == pytest.approx(np.exp(-r * T) * (F - K), abs=1e-7)


# ─────────────────────────────────────────────────────────────────────────────
#  E. Skew sign + OTM blend
# ─────────────────────────────────────────────────────────────────────────────
def test_put_skew_yields_left_skewed_rnd():
    calls, puts = _skew_chain(spot=580.0, slope=-0.10)   # strong put skew
    rnd_df, meta = rnd.build_rnd(calls, puts, spot=580.0, dte=30, r=0.045, q=0.0)
    lv = rnd.rnd_levels(rnd_df, spot=580.0)
    assert lv["skew"] < 0, "equity put-skew must produce a left-skewed density"


def test_otm_blend_selects_otm_wing():
    forward = 582.0
    # puts cheaper-IV but should be used below forward; calls above.
    calls = pd.DataFrame({"Strike": [560, 580, 600, 620], "IV%": [21, 20, 19, 18.5]})
    puts = pd.DataFrame({"Strike": [540, 560, 580, 600], "IV%": [25, 24, 23, 22]})
    blend = rnd._otm_blend(calls, puts, forward)
    assert blend is not None
    got = dict(zip(blend["Strike"], blend["iv"]))
    # K<forward → from puts; K≥forward → from calls
    assert got[540] == pytest.approx(0.25)   # put
    assert got[560] == pytest.approx(0.24)   # put (560<582)
    assert got[600] == pytest.approx(0.19)   # call (600≥582)
    assert got[620] == pytest.approx(0.185)  # call


def test_steep_0dte_smile_uses_svi_via_wing_repair():
    """Steep 0DTE smiles (inflated OTM IVs) make the raw smile
    non-arbitrage-free, so SVI is rejected → spline (tail artifacts). The
    wing-repair must cap the wings and recover an arb-free SVI fit."""
    spot = 7580.0
    strikes = np.arange(7505.0, 7660.0, 5.0)
    kk = np.log(strikes / spot)
    # ATM ~14%, very steep wings (~78% at ±1%) — the characteristic 0DTE tent.
    iv = np.clip(0.14 + 46.0 * np.abs(kk) - 18.0 * kk, 0.08, 1.5)
    c = pd.DataFrame({"Strike": strikes, "IV%": iv * 100})
    rnd_df, meta = rnd.build_rnd(c, c.copy(), spot=spot, dte=0, r=0.045, q=0.0)
    assert rnd_df is not None
    assert meta["method"] == "svi", meta.get("svi_reject")
    assert meta["arb_free"] is True
    assert meta["wing_capped"] is not None        # the repair fired
    # density still integrates to 1 and is non-negative
    K = rnd_df["strike"].to_numpy(); pdf = rnd_df["pdf"].to_numpy()
    area = np.trapezoid(pdf, K) if hasattr(np, "trapezoid") else np.trapz(pdf, K)
    assert area == pytest.approx(1.0, abs=1e-3)
    assert (pdf >= 0).all()


def test_wing_repair_does_not_fire_on_clean_smile():
    """A well-behaved (longer-dated) smile must fit SVI directly — the
    wing-repair must NOT trigger and must not alter the clean path."""
    spot = 580.0
    strikes = np.arange(520.0, 641.0, 2.5)
    kk = np.log(strikes / spot)
    iv = np.clip(0.18 * (1 - 0.5 * kk / 0.1) + 0.4 * kk * kk, 0.05, 0.7)
    c = pd.DataFrame({"Strike": strikes, "IV%": iv * 100})
    _, meta = rnd.build_rnd(c, c.copy(), spot=spot, dte=30, r=0.045, q=0.0)
    assert meta["method"] == "svi"
    assert meta["wing_capped"] is None


def test_build_rnd_rejects_bad_inputs():
    calls, puts = _flat_chain()
    # non-positive spot
    df, meta = rnd.build_rnd(calls, puts, spot=0.0, dte=30)
    assert df is None
    # too few strikes
    tiny = pd.DataFrame({"Strike": [580, 585], "IV%": [20, 20]})
    df2, meta2 = rnd.build_rnd(tiny, tiny, spot=580.0, dte=30)
    assert df2 is None


# ─────────────────────────────────────────────────────────────────────────────
#  F. level_probs / probability-of-touch reflection bound
# ─────────────────────────────────────────────────────────────────────────────
def test_level_probs_and_touch_bound():
    calls, puts = _flat_chain()
    rnd_df, _ = rnd.build_rnd(calls, puts, spot=580.0, dte=30, r=0.045, q=0.0)
    F = 580.0 * np.exp(0.045 * 30 / 365.0)
    lv = rnd.rnd_levels(rnd_df, spot=580.0,
                        levels={"up": F * 1.03, "dn": F * 0.97})
    up = lv["level_probs"]["up"]
    dn = lv["level_probs"]["dn"]
    # p_below + p_above = 1
    assert up["p_below"] + up["p_above"] == pytest.approx(1.0, abs=1e-6)
    # p_touch = 2·min(tail), capped at 1, and ≥ the one-sided tail prob
    assert up["p_touch"] == pytest.approx(min(1.0, 2 * min(up["p_below"], up["p_above"])), abs=1e-6)
    assert up["p_touch"] >= up["p_above"] - 1e-9
    assert 0.0 <= up["p_touch"] <= 1.0 and 0.0 <= dn["p_touch"] <= 1.0
