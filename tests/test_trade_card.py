"""Tests de la matemática de los verticales (bull put / bear put)."""
from __future__ import annotations

import pytest

from charts.trade_card import (
    _parse_chats, build_payoff_figure, spread_metrics, telegram_caption,
)


def test_parse_chats_dedupes_and_labels():
    result = [
        {"message": {"chat": {"id": -1001234567890, "type": "supergroup",
                              "title": "GEX Signals"}}},
        {"message": {"chat": {"id": -1001234567890, "type": "supergroup",
                              "title": "GEX Signals"}}},      # duplicado
        {"channel_post": {"chat": {"id": -100999, "type": "channel",
                                   "title": "Canal"}}},
        {"my_chat_member": {"chat": {"id": 42, "type": "private",
                                     "first_name": "Alberto"}}},
        {"edited_message": {"text": "sin chat"}},             # ignorado
    ]
    chats = _parse_chats(result)
    ids = {c["id"]: c for c in chats}
    assert set(ids) == {-1001234567890, -100999, 42}          # deduped
    assert ids[-1001234567890]["title"] == "GEX Signals"
    assert ids[42]["title"] == "Alberto"


def test_parse_chats_empty():
    assert _parse_chats(None) == []
    assert _parse_chats([]) == []


def test_bull_put_credit_metrics():
    m = spread_metrics("bull_put", 742, 740, 0.42, tp_pct=50, stop_pct=50,
                       contracts=10)
    assert m["max_profit"] == pytest.approx(0.42)
    assert m["max_loss"] == pytest.approx(1.58)
    assert m["breakeven"] == pytest.approx(741.58)
    assert m["tp_profit"] == pytest.approx(0.21)
    assert m["close_val"] == pytest.approx(0.21)        # recompra a la mitad
    assert m["loss_stop"] == pytest.approx(0.79)
    assert m["stop_price"] == pytest.approx(740.79)     # BE - loss
    assert m["rr"] == pytest.approx(1.58 / 0.42)
    assert m["risk_max_usd"] == pytest.approx(1.58 * 100 * 10)


def test_bear_put_debit_metrics():
    m = spread_metrics("bear_put", 745, 740, 1.70, tp_pct=50, stop_pct=50)
    assert m["max_profit"] == pytest.approx(3.30)
    assert m["max_loss"] == pytest.approx(1.70)
    assert m["breakeven"] == pytest.approx(743.30)
    assert m["tp_profit"] == pytest.approx(1.65)
    assert m["close_val"] == pytest.approx(3.35)         # vende más caro
    assert m["stop_price"] == pytest.approx(744.15)      # BE + loss
    assert m["rr"] == pytest.approx(1.70 / 3.30)


def test_2x_credit_stop_equals_credit_loss():
    # Un stop al 100% de... no: la "regla 2× crédito" = perder 1× el crédito.
    m = spread_metrics("bull_put", 742, 740, 0.40, stop_pct=0)
    width = 2.0
    # stop_pct tal que loss == credit (0.40) → pct = credit/maxLoss
    pct = 0.40 / (width - 0.40) * 100
    m2 = spread_metrics("bull_put", 742, 740, 0.40, stop_pct=pct)
    assert m2["loss_stop"] == pytest.approx(0.40)
    # recompra a 2× el crédito de salida (crédito + pérdida)
    assert m["max_profit"] == pytest.approx(0.40)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        spread_metrics("bull_put", 740, 742, 0.42)      # invertidos
    with pytest.raises(ValueError):
        spread_metrics("bull_put", 742, 740, 2.5)       # prima > ancho
    with pytest.raises(ValueError):
        spread_metrics("bull_put", 742, 740, 0.0)       # prima <= 0


def test_figure_and_caption_build():
    m = spread_metrics("bull_put", 742, 740, 0.42, contracts=5)
    fig = build_payoff_figure("SPY", 744.76, m)
    assert fig is not None and len(fig.data) >= 1
    cap = telegram_caption("SPY", 744.76, m, tesis="pin en HVL")
    assert "SPY" in cap and "Bull Put" in cap and "pin en HVL" in cap
    assert "asesoría financiera" in cap
