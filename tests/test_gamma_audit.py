"""Tests del back-solve de T implícita en la gamma."""
from __future__ import annotations

import pytest

from quant import bs
from quant.gamma_audit import gamma_scale_factor, implied_T_from_gamma


def test_recovers_known_T_atm():
    S, K, iv, r = 5300.0, 5300.0, 0.15, 0.045
    for T_true in (0.000228, 0.00057, 0.00274, 0.01):
        g = float(bs.gamma(S, K, T_true, iv, r))
        T_rec = implied_T_from_gamma(g, S, K, iv, r)
        assert T_rec is not None
        assert T_rec == pytest.approx(T_true, rel=0.02)


def test_otm_ambiguous_returns_none_not_crash():
    # OTM lejano: gamma NO es monótona en T (dos raíces) → back-solve devuelve
    # None de forma segura (el diagnóstico usa el strike ATM más cercano).
    S, K, iv, r = 5300.0, 5450.0, 0.20, 0.045   # ~2.8% OTM
    g = float(bs.gamma(S, K, 0.00057, iv, r))
    # No debe crashear; el resultado puede ser None o una raíz — solo robustez.
    _ = implied_T_from_gamma(g, S, K, iv, r)


def test_scale_factor_detects_understatement():
    # Schwab gamma con T=1 día, modelo quiere T=2h intradía → factor > 1
    T_intraday = 2 * 3600 / (86400 * 365)
    T_schwab = 1.0 / 365
    f = gamma_scale_factor(T_intraday, T_schwab)
    # sqrt( (1/365) / (2h frac) ) ≈ sqrt(12) ≈ 3.46
    assert f == pytest.approx((T_schwab / T_intraday) ** 0.5, rel=1e-6)
    assert f > 3.0


def test_safe_on_bad_inputs():
    assert implied_T_from_gamma(0.0, 5300, 5300, 0.15) is None
    assert implied_T_from_gamma(0.03, 5300, 5300, 0.0) is None
    assert implied_T_from_gamma(None, 5300, 5300, 0.15) is None
    assert gamma_scale_factor(0.0, 0.001) is None
    assert gamma_scale_factor(0.001, None) is None
