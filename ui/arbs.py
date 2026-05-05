"""
Arbs panel — quick USD/MXN-converted quote lookup.

The trader types a US-listed ticker, the panel fetches a live quote
from the existing Schwab `data.fetch.fetch_quote` and the live USDMXN
rate from `data.fx`, and renders a side-by-side comparison so an
arbitrage between the local broker and a Mexican one is one click away.

Public surface:
  · render_arbs_panel(default_symbol: str = "")  — Streamlit widget
"""
from __future__ import annotations

import datetime
from typing import Optional

import streamlit as st

from config import sanitize_symbol
from data.fetch import fetch_quote
from data.fx import usdmxn_with_meta


# ─────────────────────────────────────────────────────────────────────────────
#  HTML helpers — keep markup in one place so re-skinning is easy.
# ─────────────────────────────────────────────────────────────────────────────
def _quote_card(label: str, usd: Optional[float], mxn: Optional[float],
                color: str, sub: str = "") -> str:
    """Render a bid/ask/last cell with both USD and MXN values."""
    if usd is None:
        usd_str = "—"
        mxn_str = "—"
    else:
        usd_str = f"${usd:,.2f}"
        mxn_str = (f"${mxn:,.2f} MXN" if mxn is not None else "MXN —")
    return (
        f'<div style="flex:1;background:rgba(15,17,24,0.85);'
        f'border:1px solid #1e2230;border-left:4px solid {color};'
        f'border-radius:6px;padding:0.7rem 0.95rem;'
        f'font-family:JetBrains Mono,monospace">'
        f'<div style="color:#7070a0;font-size:0.62rem;letter-spacing:0.14em;'
        f'text-transform:uppercase">{label}</div>'
        f'<div style="color:{color};font-size:1.35rem;font-weight:700;'
        f'line-height:1.1;margin-top:0.15rem">{usd_str}</div>'
        f'<div style="color:#9090b0;font-size:0.85rem;margin-top:0.15rem">'
        f'{mxn_str}</div>'
        + (f'<div style="color:#606080;font-size:0.62rem;margin-top:0.2rem">'
           f'{sub}</div>' if sub else '') +
        '</div>'
    )


def _spread_chip(bid: Optional[float], ask: Optional[float]) -> str:
    """Display the bid/ask spread + spread as % of mid. Wider spread =
    more friction for an arb; this lets the trader judge feasibility
    without doing arithmetic."""
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return ""
    spread = ask - bid
    mid = (ask + bid) / 2.0
    pct = (spread / mid * 100) if mid > 0 else 0
    color = "#22c55e" if pct < 0.05 else ("#f59e0b" if pct < 0.2 else "#f43f5e")
    return (
        f'<div style="display:inline-block;padding:0.25rem 0.6rem;'
        f'background:rgba(15,17,24,0.85);border:1px solid {color}55;'
        f'border-radius:4px;font-family:JetBrains Mono,monospace;'
        f'font-size:0.74rem;color:{color};margin:0.3rem 0">'
        f'spread ${spread:.4f} · {pct:.3f}%</div>'
    )


def _empty_box(msg: str) -> str:
    return (
        '<div style="background:rgba(20,20,36,0.55);border-left:3px solid #8b8ba7;'
        'padding:0.6rem 0.9rem;margin:0.3rem 0;border-radius:4px;'
        'font-family:JetBrains Mono,monospace;font-size:0.78rem;'
        f'color:#a8a8c0;">{msg}</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Main entrypoint
# ─────────────────────────────────────────────────────────────────────────────
def render_arbs_panel(default_symbol: str = "") -> None:
    """Streamlit widget. Reads / writes its own session-state slots so it
    doesn't interfere with the main symbol selector elsewhere in render.py.
    """
    st.markdown(
        '<p class="bb-header">ARBS  ·  Quote USD ↔ MXN para operar el mismo '
        'subyacente en dos brókeres</p>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Escribe el ticker (ej. SPY, AAPL, NVDA). El panel jala bid/ask de "
        "Schwab y los multiplica por el USDMXN spot (Frankfurter / ECB). "
        "Útil para validar si el spread entre tu bróker mexicano y el "
        "estadounidense deja arb después de fees."
    )

    # ── FX rate ──────────────────────────────────────────────────────────────
    fx = usdmxn_with_meta()
    rate = fx.get("rate")
    fx_color = "#22c55e" if rate else "#f43f5e"
    fx_str = (f"${rate:.4f}" if rate else "—")
    src_lbl = (f" · {fx['source']}" if fx.get("source") else "")
    st.markdown(
        f'<div style="display:flex;gap:0.6rem;align-items:center;'
        f'margin:0.3rem 0 0.8rem">'
        f'<div style="color:#7070a0;font-size:0.66rem;letter-spacing:0.12em;'
        f'font-family:JetBrains Mono,monospace;text-transform:uppercase">'
        f'USDMXN spot{src_lbl}</div>'
        f'<div style="color:{fx_color};font-size:1.1rem;font-weight:700;'
        f'font-family:JetBrains Mono,monospace">{fx_str}</div>'
        f'<div style="color:#606080;font-size:0.62rem;font-family:JetBrains '
        f'Mono,monospace">'
        + (f'(refresh ≤ 60s)' if rate else f'⚠ {fx.get("error", "—")}')
        + '</div></div>',
        unsafe_allow_html=True,
    )

    # ── Symbol input + lookup ───────────────────────────────────────────────
    c1, c2 = st.columns([3, 1])
    with c1:
        raw = st.text_input(
            "Ticker (US)",
            value=st.session_state.get("arbs_sym", default_symbol or ""),
            placeholder="SPY · AAPL · NVDA · TSLA · ES (futuro proxy ETF)…",
            key="arbs_sym_input",
            label_visibility="collapsed",
        )
    with c2:
        do_fetch = st.button("🔍 Cotizar",
                             type="primary", use_container_width=True,
                             key="arbs_fetch_btn")

    sym = sanitize_symbol(raw)
    if not sym:
        if raw:
            st.markdown(
                _empty_box(f"⚠ Símbolo `{raw}` no válido. Sólo equity tickers "
                          "del mercado americano (1-10 caracteres alfanuméricos, "
                          "puntos o guiones)."),
                unsafe_allow_html=True,
            )
        return

    # Persist last symbol so a tab switch doesn't lose state.
    if do_fetch or sym != st.session_state.get("arbs_sym"):
        st.session_state["arbs_sym"] = sym

    # ── Fetch quote ──────────────────────────────────────────────────────────
    with st.spinner(f"Buscando {sym}…"):
        quote, err = fetch_quote(sym)

    if err:
        st.markdown(_empty_box(f"⚠ Error: `{err}`"), unsafe_allow_html=True)
        return
    if not quote:
        st.markdown(
            _empty_box(f"⚠ Sin datos para `{sym}`. Verifica que el símbolo "
                       "exista en Schwab (puede no estar disponible para "
                       "futuros — usa el ETF proxy: SPY/QQQ/IWM/DIA)."),
            unsafe_allow_html=True,
        )
        return

    bid = quote.get("bid")
    ask = quote.get("ask")
    last = quote.get("last")
    mark = quote.get("mark")
    open_p = quote.get("open")
    high = quote.get("high")
    low = quote.get("low")
    chg = quote.get("net_change")
    chg_pct = quote.get("pct_change")
    desc = quote.get("description") or sym

    def _to_mxn(v: Optional[float]) -> Optional[float]:
        if v is None or rate is None:
            return None
        try:
            return float(v) * float(rate)
        except (TypeError, ValueError):
            return None

    # ── Header strip ────────────────────────────────────────────────────────
    chg_color = "#9ca3af"
    if chg is not None:
        chg_color = "#22c55e" if chg >= 0 else "#f43f5e"
    chg_str = (f"{chg:+.2f}" if chg is not None else "—")
    chg_pct_str = (f"{chg_pct:+.2f}%" if chg_pct is not None else "")

    st.markdown(
        f'<div style="background:linear-gradient(135deg,#0a0d14 0%,#10131c 100%);'
        f'border:1px solid #1e2230;border-radius:8px;padding:1rem 1.2rem;'
        f'margin:0.6rem 0;font-family:JetBrains Mono,monospace">'
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:flex-end;gap:1rem;flex-wrap:wrap">'
        f'<div>'
        f'<div style="color:#6b7280;font-size:0.62rem;letter-spacing:0.18em;'
        f'text-transform:uppercase">{sym}</div>'
        f'<div style="color:#e5e7eb;font-size:1.5rem;font-weight:700">'
        f'{desc}</div></div>'
        f'<div style="text-align:right">'
        f'<div style="color:#6b7280;font-size:0.62rem;letter-spacing:0.14em;'
        f'text-transform:uppercase">Cambio del día</div>'
        f'<div style="color:{chg_color};font-size:1.3rem;font-weight:700">'
        f'{chg_str} <span style="font-size:0.85rem">{chg_pct_str}</span>'
        f'</div></div></div></div>',
        unsafe_allow_html=True,
    )

    # ── Bid / Ask / Last / Mark side-by-side ────────────────────────────────
    bid_mxn = _to_mxn(bid)
    ask_mxn = _to_mxn(ask)
    last_mxn = _to_mxn(last)
    mark_mxn = _to_mxn(mark)

    cards = (
        _quote_card("BID  (compra)", bid, bid_mxn, "#f43f5e",
                    "el precio al que el mercado COMPRA → tú vendes a este precio"),
        _quote_card("ASK  (venta)", ask, ask_mxn, "#22c55e",
                    "el precio al que el mercado VENDE → tú compras a este precio"),
        _quote_card("LAST", last, last_mxn, "#06b6d4",
                    "última transacción ejecutada"),
        _quote_card("MARK", mark, mark_mxn, "#a855f7",
                    "(bid+ask)/2 — referencia teórica"),
    )
    st.markdown(
        f'<div style="display:flex;gap:0.5rem;flex-wrap:wrap;'
        f'margin:0.3rem 0">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )

    # ── Spread chip ─────────────────────────────────────────────────────────
    spread_html = _spread_chip(bid, ask)
    if spread_html:
        st.markdown(spread_html, unsafe_allow_html=True)

    # ── Day range / open / volume ───────────────────────────────────────────
    vol = quote.get("volume")
    rows = []
    if open_p is not None:
        rows.append(("OPEN", f"${open_p:,.2f}", _to_mxn(open_p)))
    if high is not None:
        rows.append(("HIGH", f"${high:,.2f}", _to_mxn(high)))
    if low is not None:
        rows.append(("LOW", f"${low:,.2f}", _to_mxn(low)))
    if vol is not None:
        rows.append(("VOLUME", f"{int(vol):,}", None))

    if rows:
        cells = []
        for label, usd_txt, mxn_v in rows:
            mxn_str = (f"${mxn_v:,.2f} MXN" if mxn_v is not None else "")
            cells.append(
                f'<div style="flex:1;text-align:center;'
                f'background:rgba(15,17,24,0.7);border:1px solid #1e2230;'
                f'border-radius:4px;padding:0.45rem 0.4rem">'
                f'<div style="color:#7070a0;font-size:0.6rem;'
                f'letter-spacing:0.12em">{label}</div>'
                f'<div style="color:#e5e7eb;font-size:0.92rem;'
                f'font-weight:700;font-family:JetBrains Mono,monospace">'
                f'{usd_txt}</div>'
                f'<div style="color:#9090b0;font-size:0.66rem;'
                f'font-family:JetBrains Mono,monospace">{mxn_str}</div>'
                f'</div>'
            )
        st.markdown(
            f'<div style="display:flex;gap:0.4rem;margin:0.4rem 0">'
            f'{"".join(cells)}</div>',
            unsafe_allow_html=True,
        )

    # ── Lot-size calculator ────────────────────────────────────────────────
    st.markdown(
        '<p class="bb-header" style="margin-top:0.8rem">'
        'CALCULADORA DE LOTE  ·  cuánto MXN cuesta N acciones</p>',
        unsafe_allow_html=True,
    )
    cc1, cc2 = st.columns([1, 2])
    with cc1:
        n_shares = st.number_input(
            "Acciones",
            min_value=1, max_value=100_000, value=100, step=1,
            key="arbs_n_shares",
        )
    with cc2:
        if last is None or rate is None:
            st.caption("⚠ Falta last o FX para calcular el costo total.")
        else:
            cost_usd = float(last) * int(n_shares)
            cost_mxn = cost_usd * float(rate)
            st.markdown(
                f'<div style="background:rgba(15,17,24,0.85);border:1px solid '
                f'#1e2230;border-radius:6px;padding:0.7rem 1rem;'
                f'font-family:JetBrains Mono,monospace">'
                f'<div style="display:grid;grid-template-columns:repeat(3,1fr);'
                f'gap:0.6rem">'
                f'<div><span style="color:#7070a0;font-size:0.62rem;'
                f'letter-spacing:0.14em">A LAST</span>'
                f'<div style="color:#e5e7eb;font-size:0.95rem;font-weight:700">'
                f'${last:,.2f}</div></div>'
                f'<div><span style="color:#7070a0;font-size:0.62rem;'
                f'letter-spacing:0.14em">USD TOTAL</span>'
                f'<div style="color:#06b6d4;font-size:0.95rem;font-weight:700">'
                f'${cost_usd:,.2f}</div></div>'
                f'<div><span style="color:#7070a0;font-size:0.62rem;'
                f'letter-spacing:0.14em">MXN TOTAL</span>'
                f'<div style="color:#22c55e;font-size:0.95rem;font-weight:700">'
                f'${cost_mxn:,.2f}</div></div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

    st.caption(
        f"Datos: Schwab quotes (cache ≤8s) · USDMXN: {fx.get('source','—')} "
        f"(cache ≤60s). El bid/ask aplica a tu lado: vendes al **bid**, "
        f"compras al **ask**. Fees y conversiones del bróker mexicano NO "
        f"están descontadas."
    )
