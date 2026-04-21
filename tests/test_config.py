"""Config-level helpers: symbol sanitizer, rate curve defaults, dividend lookup."""
from __future__ import annotations

from config import DIVIDEND_YIELDS, RATE_CURVE_DEFAULT, dividend_yield_for, sanitize_symbol


def test_sanitize_symbol_accepts_common_tickers():
    assert sanitize_symbol("SPY") == "SPY"
    assert sanitize_symbol("spy") == "SPY"
    assert sanitize_symbol(" AAPL ") == "AAPL"
    assert sanitize_symbol("BRK.B") == "BRK.B"
    assert sanitize_symbol("RDS-A") == "RDS-A"


def test_sanitize_symbol_rejects_junk():
    assert sanitize_symbol("") == ""
    assert sanitize_symbol("<script>") == ""
    assert sanitize_symbol("'; DROP TABLE") == ""
    assert sanitize_symbol("1ABC") == ""   # must start with letter
    assert sanitize_symbol("TOOLONGSYMBOL") == ""  # >10 chars
    assert sanitize_symbol(None) == ""


def test_dividend_yield_known_symbols():
    assert dividend_yield_for("SPY") == DIVIDEND_YIELDS["SPY"]
    assert dividend_yield_for("spy") == DIVIDEND_YIELDS["SPY"]


def test_dividend_yield_unknown_defaults_to_zero():
    assert dividend_yield_for("ZZZZ") == 0.0
    assert dividend_yield_for("") == 0.0


def test_rate_curve_has_common_tenors():
    for t in (7, 30, 60, 90, 180, 365):
        assert t in RATE_CURVE_DEFAULT
        assert 0 < RATE_CURVE_DEFAULT[t] < 0.20  # sane rate range
