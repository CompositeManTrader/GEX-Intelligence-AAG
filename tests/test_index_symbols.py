"""Cash-index → Schwab API symbol translation (SPX/NDX/RUT/VIX)."""
from __future__ import annotations

from config import to_api_symbol, api_symbol_candidates


def test_index_roots_get_dollar_dot_x():
    assert to_api_symbol("SPX") == "$SPX.X"
    assert to_api_symbol("spx") == "$SPX.X"      # case-insensitive
    assert to_api_symbol("NDX") == "$NDX.X"
    assert to_api_symbol("RUT") == "$RUT.X"
    assert to_api_symbol("VIX") == "$VIX.X"


def test_equities_and_etfs_pass_through():
    for s in ("AAPL", "SPY", "QQQ", "BRK.B", "TSLA"):
        assert to_api_symbol(s) == s


def test_empty_symbol_safe():
    assert to_api_symbol("") == ""
    assert api_symbol_candidates("") == [""]


def test_candidates_try_both_index_formats():
    assert api_symbol_candidates("SPX") == ["$SPX.X", "$SPX"]
    assert api_symbol_candidates("VIX") == ["$VIX.X", "$VIX"]
    # Dow primary has no .X → alt appends it.
    assert api_symbol_candidates("DJX") == ["$DJI", "$DJI.X"]


def test_candidates_equity_is_single():
    assert api_symbol_candidates("AAPL") == ["AAPL"]
    assert api_symbol_candidates("SPY") == ["SPY"]
