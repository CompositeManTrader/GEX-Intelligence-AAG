"""Trade-card builder — bull put / bear put vertical spreads.

Three concerns, kept separate so the math is unit-testable and the I/O is
optional:

  * ``spread_metrics``       — pure vertical-spread math (P/L, breakeven,
                               take-profit and stop levels + the underlying
                               price that triggers the stop).
  * ``build_payoff_figure``  — a Plotly payoff card (zones, TP/stop/BE/spot)
                               for the in-app live preview.
  * ``telegram_caption`` / ``send_to_telegram`` — compose + post to a group.

You type the strikes/premium/TP/stop; nothing here is auto-suggested. The
PNG export is best-effort (needs ``kaleido``); without it the sender falls
back to a formatted text message so the feature still works.

NOT financial advice — this only arranges the numbers you enter.
"""
from __future__ import annotations

from typing import Optional

import plotly.graph_objects as go

EMERALD = "#34d399"
ROSE = "#fb7185"
RED = "#f87171"
GOLD = "#fbbf24"
ORANGE = "#f97316"
INK = "#f0f0fb"
MUTE = "#7a7a98"
MONO = "JetBrains Mono, monospace"

STRATS = {
    "bull_put": "Bull Put Spread · venta de prima",
    "bear_put": "Bear Put Spread · débito",
}


def spread_metrics(strat: str, k_high: float, k_low: float, prem: float,
                   tp_pct: float = 50.0, stop_pct: float = 50.0,
                   contracts: int = 1) -> dict:
    """All numbers for a put vertical. Pure + testable.

    ``strat``: ``'bull_put'`` (credit) or ``'bear_put'`` (debit).
    ``k_high`` > ``k_low``. ``prem`` = credit (bull) or debit (bear), per share.

    Breakeven = ``k_high - prem`` for both put verticals. The stop is expressed
    as a fraction of the max loss and mapped to the underlying price that, at
    expiry, produces that loss: ``BE - loss`` for a bull put, ``BE + loss`` for
    a bear put. Raises ``ValueError`` on degenerate inputs.
    """
    kH, kL, prem = float(k_high), float(k_low), float(prem)
    width = kH - kL
    if width <= 0:
        raise ValueError("El strike superior debe ser mayor que el inferior.")
    if not (0 < prem < width):
        raise ValueError("La prima debe estar entre 0 y el ancho del spread.")

    bull = strat == "bull_put"
    max_profit = prem if bull else width - prem
    max_loss = (width - prem) if bull else prem
    breakeven = kH - prem

    tp_profit = max(0.0, min(tp_pct, 100.0)) / 100.0 * max_profit
    loss_stop = min(max(0.0, min(stop_pct, 100.0)) / 100.0 * max_loss, max_loss)
    stop_price = breakeven - loss_stop if bull else breakeven + loss_stop
    # Value to close the spread at the TP: buy it back cheaper (credit) or
    # sell it richer (debit).
    close_val = max(prem - tp_profit, 0.0) if bull else prem + tp_profit
    rr = (max_loss / max_profit) if max_profit > 0 else None
    n = max(1, int(contracts))

    return dict(
        strat=strat, bull=bull, k_high=kH, k_low=kL, prem=prem, width=width,
        max_profit=max_profit, max_loss=max_loss, breakeven=breakeven,
        tp_pct=float(tp_pct), tp_profit=tp_profit, close_val=close_val,
        stop_pct=float(stop_pct), loss_stop=loss_stop, stop_price=stop_price,
        rr=rr, contracts=n,
        gain_tp_usd=tp_profit * 100 * n,
        loss_stop_usd=loss_stop * 100 * n,
        risk_max_usd=max_loss * 100 * n,
    )


def _payoff(strat: str, S: float, kH: float, kL: float,
            max_profit: float, max_loss: float) -> float:
    """P/L per share at expiry for the underlying closing at ``S``."""
    if strat == "bull_put":
        if S >= kH:
            return max_profit
        if S <= kL:
            return -max_loss
        return max_profit - (kH - S)
    if S <= kL:
        return max_profit
    if S >= kH:
        return -max_loss
    return (kH - S) - max_loss


def build_payoff_figure(symbol: str, spot: float, m: dict) -> go.Figure:
    """Plotly payoff card: profit/loss zones, zero line, strikes, breakeven,
    spot, the take-profit level and the stop (price + P/L). Solid dark bg so
    the PNG export has a proper background."""
    bull = m["bull"]
    kH, kL = m["k_high"], m["k_low"]
    mp, ml, be = m["max_profit"], m["max_loss"], m["breakeven"]
    sp = float(spot)
    stop, tp, ls = m["stop_price"], m["tp_profit"], m["loss_stop"]

    lo = min(kL, sp, stop)
    hi = max(kH, sp, stop)
    pad = max((hi - lo) * 0.4, (kH - kL) * 0.6, 1.5)
    xmin, xmax = lo - pad, hi + pad
    xs = [xmin, kL, kH, xmax]
    ys = [_payoff(m["strat"], x, kH, kL, mp, ml) for x in xs]
    accent = EMERALD if bull else ROSE

    fig = go.Figure()
    # Profit / loss zones (split at breakeven).
    g_x0, g_x1 = (be, xmax) if bull else (xmin, be)
    r_x0, r_x1 = (xmin, be) if bull else (be, xmax)
    fig.add_vrect(x0=g_x0, x1=g_x1, fillcolor="rgba(52,211,153,0.13)",
                  line_width=0, layer="below")
    fig.add_vrect(x0=r_x0, x1=r_x1, fillcolor="rgba(251,113,133,0.12)",
                  line_width=0, layer="below")

    fig.add_hline(y=0, line_color="rgba(255,255,255,0.22)", line_width=1,
                  line_dash="dash")
    for k in (kL, kH):
        fig.add_vline(x=k, line_color="rgba(255,255,255,0.28)", line_width=1,
                      line_dash="dot")
    # Take-profit P/L level (no price line — it's reached via theta).
    fig.add_hline(y=tp, line_color=EMERALD, line_width=1, line_dash="dash",
                  annotation_text=f" TP +${tp:.2f} ({m['tp_pct']:.0f}%)",
                  annotation_font_color=EMERALD, annotation_font_size=11,
                  annotation_position="top left")
    # Stop: both the loss level and the trigger price.
    fig.add_hline(y=-ls, line_color=RED, line_width=1, line_dash="dash")
    fig.add_vline(x=stop, line_color=RED, line_width=1.4,
                  annotation_text=f"stop ${stop:.2f}", annotation_font_color=RED,
                  annotation_font_size=11, annotation_position="bottom")
    fig.add_vline(x=be, line_color=GOLD, line_width=1, line_dash="dot",
                  annotation_text=f"BE ${be:.2f}", annotation_font_color=GOLD,
                  annotation_font_size=11, annotation_position="top")
    fig.add_vline(x=sp, line_color="rgba(249,115,22,0.6)", line_width=1,
                  line_dash="dot")

    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                             line=dict(color=INK, width=2.6), hoverinfo="skip",
                             showlegend=False))
    sy = _payoff(m["strat"], sp, kH, kL, mp, ml)
    fig.add_trace(go.Scatter(x=[sp], y=[sy], mode="markers",
                             marker=dict(color=ORANGE, size=12,
                                         line=dict(color="#0b0b14", width=2)),
                             hoverinfo="skip", showlegend=False))
    # Plateau value labels.
    fig.add_annotation(x=(xmax if bull else xmin), y=mp, text=f"+${mp:.2f}",
                       showarrow=False, yshift=11,
                       xanchor=("right" if bull else "left"),
                       font=dict(color=EMERALD, size=12, family=MONO))
    fig.add_annotation(x=(xmin if bull else xmax), y=-ml, text=f"−${ml:.2f}",
                       showarrow=False, yshift=-11,
                       xanchor=("left" if bull else "right"),
                       font=dict(color=ROSE, size=12, family=MONO))
    fig.add_annotation(x=sp, y=sy, text="spot", showarrow=False, yshift=16,
                       font=dict(color=ORANGE, size=11, family=MONO))

    legs = (f"Vende PUT {kH:g} · Compra PUT {kL:g}" if bull
            else f"Compra PUT {kH:g} · Vende PUT {kL:g}")
    prima = (f"crédito +${m['prem']:.2f}" if bull else f"débito ${m['prem']:.2f}")
    rr = f"  ·  R:R 1:{m['rr']:.1f}" if m["rr"] else ""
    sub = (f"{legs}  ·  {prima}  ·  gana ${mp:.2f}  ·  pierde ${ml:.2f}{rr}")
    fig.update_layout(
        title=dict(
            text=(f"<b>{symbol} ${sp:.2f}</b>  ·  {STRATS[m['strat']]}"
                  f"<br><span style='font-size:11px;color:{MUTE}'>{sub}</span>"),
            x=0.02, xanchor="left",
            font=dict(size=15, color=INK, family=MONO)),
        height=560, paper_bgcolor="#0b0b14", plot_bgcolor="#0e0e1a",
        font=dict(family=MONO, color="#8a8ab0", size=11),
        margin=dict(l=52, r=26, t=74, b=42), showlegend=False,
        xaxis=dict(title="precio al cierre", tickvals=[kL, kH],
                   gridcolor="rgba(255,255,255,0.04)", zeroline=False),
        yaxis=dict(title="P/L por acción ($)",
                   gridcolor="rgba(255,255,255,0.04)", zeroline=False),
    )
    return fig


def figure_to_png(fig: go.Figure, width: int = 1000, height: int = 620,
                  scale: int = 2) -> Optional[bytes]:
    """PNG bytes via kaleido, or ``None`` if static export isn't available."""
    try:
        return fig.to_image(format="png", width=width, height=height,
                            scale=scale)
    except Exception:
        return None


def telegram_caption(symbol: str, spot: float, m: dict, tesis: str = "") -> str:
    """The structured text message (Telegram HTML parse mode)."""
    bull = m["bull"]
    kH, kL = m["k_high"], m["k_low"]
    legs = (f"Vende PUT {kH:g} / Compra PUT {kL:g}" if bull
            else f"Compra PUT {kH:g} / Vende PUT {kL:g}")
    prima = (f"Crédito +{m['prem']:.2f}" if bull else f"Débito {m['prem']:.2f}")
    rr = f"1:{m['rr']:.1f}" if m["rr"] else "—"
    bias = "ALCISTA" if bull else "BAJISTA"
    body = tesis.strip() or (
        f"Apuesta a que {symbol} cierra ≥ {kH:g}." if bull
        else f"Apuesta a que {symbol} cae bajo {kL:g}.")
    close_action = "recompra" if bull else "vende"
    return "\n".join([
        "⚡ <b>GEX · TRADE IDEA · 0DTE</b>",
        f"<b>{symbol}</b>  ${spot:.2f}  ·  {bias}",
        "",
        f"🎯 <b>{STRATS[m['strat']]}</b>",
        f"   {legs}",
        "",
        (f"📊 {prima} · gana máx {m['max_profit']:.2f} · "
         f"pierde máx {m['max_loss']:.2f} · R:R {rr}"),
        (f"🟢 TP {m['tp_pct']:.0f}% → +{m['tp_profit']:.2f} "
         f"({close_action} ~{m['close_val']:.2f})"),
        f"⛔ Stop → {m['stop_price']:.2f}  ({-m['loss_stop']:.2f})",
        "",
        f"🧠 {body}",
        "",
        "⚠ No es asesoría financiera",
    ])


def _parse_chats(result: Optional[list]) -> list[dict]:
    """Distinct chats from a ``getUpdates`` result payload (pure + testable).

    Walks every update kind that carries a ``chat`` object and dedupes by id,
    keeping a friendly label. The bot must have *seen* a message in the chat
    (privacy mode off, or mentioned) for it to show up here."""
    seen: dict = {}
    for upd in result or []:
        if not isinstance(upd, dict):
            continue
        for key in ("message", "channel_post", "edited_message",
                    "edited_channel_post", "my_chat_member"):
            obj = upd.get(key)
            if isinstance(obj, dict) and isinstance(obj.get("chat"), dict):
                c = obj["chat"]
                label = (c.get("title") or c.get("username")
                         or c.get("first_name") or "(privado)")
                seen[c["id"]] = {"id": c["id"], "title": label,
                                 "type": c.get("type", "")}
    return list(seen.values())


def telegram_get_chats(bot_token: str, timeout: int = 15):
    """Chats the bot has seen via ``getUpdates``. Returns ``(chats, error)``.

    ``error`` is ``None`` on success. Empty list usually means the bot hasn't
    seen a message yet (add it to the group + post there, or disable privacy)."""
    import requests

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            timeout=timeout)
        j = r.json()
        if not j.get("ok"):
            return [], j.get("description", "error desconocido")
        return _parse_chats(j.get("result")), None
    except Exception as e:
        return [], str(e)


def send_to_telegram(bot_token: str, chat_id: str, caption: str,
                     png: Optional[bytes] = None, timeout: int = 20):
    """Post to a Telegram chat. ``sendPhoto`` when a PNG is supplied, else
    ``sendMessage``. Returns ``(ok: bool, detail: str)``."""
    import requests

    base = f"https://api.telegram.org/bot{bot_token}"
    try:
        if png:
            r = requests.post(
                f"{base}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption,
                      "parse_mode": "HTML"},
                files={"photo": ("trade_card.png", png, "image/png")},
                timeout=timeout)
        else:
            r = requests.post(
                f"{base}/sendMessage",
                data={"chat_id": chat_id, "text": caption,
                      "parse_mode": "HTML"},
                timeout=timeout)
        j = r.json()
        if j.get("ok"):
            return True, "enviado"
        return False, j.get("description", "error desconocido")
    except Exception as e:  # network / JSON / timeout
        return False, str(e)
