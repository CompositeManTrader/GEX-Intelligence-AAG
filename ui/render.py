"""
UI render modules — dashboard, connect screen, GEX + vol panels.

Thin orchestration layer over:
  - data.fetch / data.parse
  - quant.exposures / quant.levels / quant.vol
  - charts.gex / charts.vol / charts.intraday
  - ui.styles / ui.decision / ui.chain_table
"""
from __future__ import annotations

import datetime
import time
from typing import Optional

import pandas as pd
import streamlit as st

from auth.schwab import (
    build_auth_url, exchange_code, finish_oauth, get_secret, try_auto_connect,
)
from charts.gex import (
    chart_cum_gex, chart_cex_profile, chart_dex_profile, chart_gex_by_expiry,
    chart_gex_curve, chart_gex_profile, chart_vex_profile,
)
from charts.intraday import render_tv_chart
from charts.theme import CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED
from charts.vol import (
    chart_greeks, chart_iv_hv_history, chart_iv_skew, chart_iv_smile,
    chart_oi_volume, chart_returns_dist, chart_term_structure, chart_vol_cone,
)
from config import CDMX_TZ, ET_TZ, SS, get_logger, market_status_et, sanitize_symbol
from data.fetch import fetch_chain, fetch_intraday, fetch_price_history, fetch_quote
from data.parse import by_expiry, clean, parse_chain
from quant.exposures import (
    compute_cex_profile, compute_dex_profile, compute_gex_by_expiry,
    compute_gex_profile, compute_vex_profile, gex_curve_over_spot,
)
from quant.levels import (
    atm_iv_interp, expected_move, iv_skew, iv_smile_by_expiry, max_pain,
    put_call_ratio, skew_metrics, term_structure,
)
from quant.vol import vol_analytics
from ui.chain_table import build_table
from ui.decision import build_decision_panel
from ui.styles import CSS

log = get_logger("ui.render")


# ─────────────────────────────────────────────────────────────────────────────
#  KPI panel helper
# ─────────────────────────────────────────────────────────────────────────────
def _kv(label: str, value: str, color: str = "#e0e0f0",
        sub: Optional[str] = None) -> str:
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    return (f'<div class="kpi-item">'
            f'<div class="kpi-lbl">{label}</div>'
            f'<div class="kpi-val" style="color:{color}">{value}</div>'
            f'{sub_html}</div>')


# ─────────────────────────────────────────────────────────────────────────────
#  GEX module
# ─────────────────────────────────────────────────────────────────────────────
def render_gex_module(symbol: str, calls_all: pd.DataFrame, puts_all: pd.DataFrame,
                      spot: float, max_dte: int, min_oi: int, focus_pct: float,
                      dte_v: int, iv_atm: Optional[float],
                      em_lo: Optional[float], em_hi: Optional[float],
                      vol_regime: Optional[str] = None):
    gex_df, gex_sum = compute_gex_profile(calls_all, puts_all, spot,
                                          symbol=symbol, max_dte=max_dte, min_oi=min_oi)
    vex_df, vex_sum = compute_vex_profile(calls_all, puts_all, spot,
                                          symbol=symbol, max_dte=max_dte, min_oi=min_oi)
    cex_df, cex_sum = compute_cex_profile(calls_all, puts_all, spot,
                                          symbol=symbol, max_dte=max_dte, min_oi=min_oi)
    dex_df, dex_sum = compute_dex_profile(calls_all, puts_all, spot,
                                          max_dte=max_dte, min_oi=min_oi)
    exp_df = compute_gex_by_expiry(calls_all, puts_all, spot,
                                   max_dte=max_dte, min_oi=min_oi)

    if gex_df.empty:
        st.warning("No hay datos suficientes para calcular GEX. "
                   "Revisa el filtro DTE y min OI, o verifica que la cadena "
                   "tenga Gamma/OI válidos.")
        return None, None

    regime = gex_sum.get("regime", "NEUTRAL")
    r_color = GREEN if regime == "POSITIVE" else (RED if regime == "NEGATIVE" else ORANGE)
    total_bn = gex_sum.get("total_gex", 0) / 1e9
    call_bn = gex_sum.get("call_gex", 0) / 1e9
    put_bn = gex_sum.get("put_gex", 0) / 1e9
    gf = gex_sum.get("gamma_flip")
    cw = gex_sum.get("call_wall")
    pw = gex_sum.get("put_wall")
    hvl = gex_sum.get("hvl")
    flip_pct = gex_sum.get("flip_pct")

    hdr = '<div class="kpi-panel">'
    hdr += _kv("Régimen", f"{regime} Γ", r_color)
    hdr += _kv("Net GEX", f"${total_bn:+.2f}B", r_color, sub="per 1% move")
    hdr += _kv("Call GEX", f"${call_bn:+.2f}B", GREEN)
    hdr += _kv("Put GEX", f"${put_bn:+.2f}B", RED)
    hdr += _kv("Zero Γ", f"${gf:.0f}" if gf else "—", PURPLE,
               sub=f"{flip_pct:+.1f}% spot" if flip_pct is not None else None)
    hdr += _kv("Call Wall", f"${cw:.0f}" if cw else "—", GREEN)
    hdr += _kv("Put Wall", f"${pw:.0f}" if pw else "—", RED)
    hdr += _kv("HVL", f"${hvl:.0f}" if hvl else "—", CYAN, sub="attractor")
    hdr += '</div>'
    st.markdown(hdr, unsafe_allow_html=True)

    panel = build_decision_panel(spot, gex_sum, vex_sum, cex_sum, dex_sum,
                                 iv_atm, em_lo, em_hi, dte_v, vol_regime)
    st.markdown(panel, unsafe_allow_html=True)

    st.markdown('<p class="bb-header">GEX PROFILE  ·  Gamma Exposure por Strike</p>',
                unsafe_allow_html=True)
    st.caption(
        "Calls → derecha (verde), Puts → izquierda (rojo), Net GEX → diamantes "
        "amarillos. Líneas: SPOT (naranja), Call/Put Walls (verde/rojo), "
        "Zero Γ (morado), HVL (cyan). Unidad: $M per 1% move."
    )
    fig_gex = chart_gex_profile(gex_df, spot, gex_sum, symbol, focus_pct=focus_pct)
    if fig_gex:
        st.plotly_chart(fig_gex, use_container_width=True)

    col_l, col_r = st.columns([3, 2])
    with col_l:
        st.markdown('<p class="bb-header" style="margin-top:0.3rem">PERFIL ACUMULADO</p>',
                    unsafe_allow_html=True)
        st.caption("Cruce por cero = Zero Gamma (cambio de régimen).")
        fig_cum = chart_cum_gex(gex_df, spot, gex_sum)
        if fig_cum:
            st.plotly_chart(fig_cum, use_container_width=True)
    with col_r:
        st.markdown('<p class="bb-header" style="margin-top:0.3rem">GEX POR VENCIMIENTO</p>',
                    unsafe_allow_html=True)
        st.caption("Top 14 expiraciones por |Net GEX|.")
        fig_exp = chart_gex_by_expiry(exp_df)
        if fig_exp:
            st.plotly_chart(fig_exp, use_container_width=True)
        else:
            st.caption("Requiere ≥ 1 vencimiento con datos.")

    st.markdown('<p class="bb-header">VANNA EXPOSURE  ·  $ Delta por +1 pto IV</p>',
                unsafe_allow_html=True)
    st.caption(
        "**VEX(k) = Vanna × OI × 100 × S × 0.01 × sign**. "
        "Positivo → dealer compra spot si IV sube. Negativo → dealer vende spot "
        "en vol expansion. Clave en FOMC / CPI / earnings."
    )
    if not vex_df.empty:
        fig_vex = chart_vex_profile(vex_df, spot, vex_sum, symbol, focus_pct=focus_pct)
        if fig_vex:
            st.plotly_chart(fig_vex, use_container_width=True)
    else:
        st.caption("VEX requiere IV% y DTE válidos en la cadena.")

    st.markdown('<p class="bb-header">CHARM EXPOSURE  ·  $ Delta decay por día</p>',
                unsafe_allow_html=True)
    st.caption(
        "**CEX(k) = Charm × OI × 100 × S × sign**. Decaimiento del delta dealer "
        "por día calendario. Positivo → EOD buy-flow cerca vencimiento. "
        "Esencial para 0DTE y pin risk en OPEX."
    )
    if not cex_df.empty:
        fig_cex = chart_cex_profile(cex_df, spot, cex_sum, symbol, focus_pct=focus_pct)
        if fig_cex:
            st.plotly_chart(fig_cex, use_container_width=True)
    else:
        st.caption("CEX requiere IV% y DTE válidos en la cadena.")

    st.markdown('<p class="bb-header">DELTA EXPOSURE  ·  Sesgo direccional</p>',
                unsafe_allow_html=True)
    st.caption(
        "DEX = Σ Δ × OI × 100 × S. Call-heavy → soporte implícito. "
        "Put-heavy → resistencia implícita."
    )
    if not dex_df.empty:
        fig_dex = chart_dex_profile(dex_df, spot, dex_sum, symbol, focus_pct=focus_pct)
        if fig_dex:
            st.plotly_chart(fig_dex, use_container_width=True)

    return gex_sum, gex_df


# ─────────────────────────────────────────────────────────────────────────────
#  Volatility module
# ─────────────────────────────────────────────────────────────────────────────
def render_vol_module(symbol: str, atm_iv: Optional[float], spot: float,
                      price_df: pd.DataFrame) -> Optional[str]:
    if price_df is None or price_df.empty:
        st.caption("No se pudo cargar el historial para el análisis de vol.")
        return None
    analytics = vol_analytics(price_df, atm_iv)
    if not analytics:
        st.caption("Datos insuficientes.")
        return None

    hv20 = analytics.get("hv20"); hv30 = analytics.get("hv30")
    hv60 = analytics.get("hv60")
    ratio = analytics.get("iv_hv_ratio"); spread = analytics.get("iv_hv_spread")
    iv_rank = analytics.get("iv_rank")
    regime = analytics.get("vol_regime", "—")
    skew = analytics.get("skewness"); kurt = analytics.get("kurtosis")

    regime_clr = (RED if regime == "IV CARA" else
                  (GREEN if regime == "IV BARATA" else ORANGE))

    hdr = '<div class="kpi-panel">'
    hdr += _kv("Régimen vol", regime, regime_clr)
    hdr += _kv("ATM IV", f"{atm_iv:.1f}%" if atm_iv else "—")
    hdr += _kv("HV20", f"{hv20:.1f}%" if hv20 else "—", sub="20d")
    hdr += _kv("HV30", f"{hv30:.1f}%" if hv30 else "—", sub="30d")
    hdr += _kv("HV60", f"{hv60:.1f}%" if hv60 else "—", sub="60d")
    hdr += _kv("IV / HV30", f"{ratio:.2f}x" if ratio else "—", regime_clr,
               sub=">1.30 cara · <0.80 barata")
    hdr += _kv(
        "IV − HV30",
        (f"+{spread:.1f}%" if (spread is not None and spread >= 0)
         else (f"{spread:.1f}%" if spread is not None else "—")),
        RED if (spread or 0) > 0 else GREEN,
    )
    hdr += _kv("IV Rank", f"{iv_rank:.0f}" if iv_rank is not None else "—",
               sub="0-100 (requiere IV history)")
    hdr += _kv("Skew", f"{skew:.3f}" if skew is not None else "—",
               RED if (skew or 0) < -0.5 else "#e0e0f0")
    hdr += _kv("Kurt ex.", f"{kurt:.3f}" if kurt is not None else "—")
    hdr += '</div>'
    st.markdown(hdr, unsafe_allow_html=True)

    if ratio is not None:
        if ratio > 1.3:
            interp = (f"📛 <b>IV cara</b> — opciones cotizan {ratio:.1f}x la HV30. "
                      "Ventaja estadística: venta de vol (credit spreads, iron condors).")
        elif ratio < 0.8:
            interp = (f"💚 <b>IV barata</b> — opciones cotizan {ratio:.1f}x la HV30. "
                      "Ventaja: compra de vol (straddles, debit spreads, calendars).")
        else:
            interp = f"🟡 <b>IV neutral</b> — {ratio:.1f}x la HV30. Prioriza direccionales."
    else:
        interp = "Datos insuficientes."

    st.markdown(
        f'<p style="font-size:0.73rem;color:#7070a0;font-family:{FONT_MONO};'
        f'margin:0 0 1rem;line-height:1.6">{interp}</p>',
        unsafe_allow_html=True,
    )

    c_cone, c_hist = st.columns([3, 2])
    with c_cone:
        st.markdown('<p class="bb-header" style="margin-top:0">VOLATILITY CONE</p>',
                    unsafe_allow_html=True)
        fig_cone = chart_vol_cone(analytics, atm_iv, symbol)
        if fig_cone:
            st.plotly_chart(fig_cone, use_container_width=True)
    with c_hist:
        st.markdown('<p class="bb-header" style="margin-top:0">HV30 vs ATM IV</p>',
                    unsafe_allow_html=True)
        fig_hv = chart_iv_hv_history(analytics, atm_iv)
        if fig_hv:
            st.plotly_chart(fig_hv, use_container_width=True)

    st.markdown('<p class="bb-header">DISTRIBUCIÓN DE RETORNOS</p>',
                unsafe_allow_html=True)
    fig_rd = chart_returns_dist(analytics, symbol)
    if fig_rd:
        st.plotly_chart(fig_rd, use_container_width=True)

    return regime


# ─────────────────────────────────────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────────────────────────────────────
def show_dashboard() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

    today = datetime.date.today()

    # ── TOP BAR ─────────────────────────────────────────────────────────────
    b1, b2, b3, b4, b5, b6 = st.columns([1.0, 1.4, 1.8, 1.0, 1.0, 0.6])
    with b1:
        st.markdown(
            "<span style='font-family:JetBrains Mono,monospace;font-size:1rem;"
            "font-weight:800;color:#f97316;letter-spacing:0.12em;line-height:2.4;"
            "display:block'>▤ OPTIONS</span>",
            unsafe_allow_html=True,
        )
    with b2:
        raw_sym = st.text_input(
            "sym", value=st.session_state.get(SS.SYMBOL, "SPY"),
            placeholder="SPY, AAPL, QQQ…", label_visibility="collapsed",
        )
        symbol = sanitize_symbol(raw_sym)
        if raw_sym and not symbol:
            st.warning("Símbolo inválido. Usa mayúsculas, puntos o guiones (ej. BRK.B).")
    with b3:
        all_exps = st.session_state.get(SS.ALL_EXPS, ["—"])
        st.selectbox("exp", options=all_exps, label_visibility="collapsed",
                     key=SS.SEL_EXP)
    with b4:
        strike_count = st.selectbox(
            "strikes", options=[10, 15, 20, 25, 30, 40, 50, 60],
            index=4, label_visibility="collapsed",
        )
    with b5:
        auto_refresh = st.toggle("Auto 30s", value=False, key=SS.AUTO_REFRESH)
    with b6:
        if st.button("EXIT", use_container_width=True):
            keys = [SS.TOKENS, SS.CONNECTED, SS.CHAIN_DATA, SS.LAST_SYM,
                    SS.LAST_STRIKES, SS.SYMBOL, SS.APP_KEY, SS.APP_SECRET,
                    SS.CALLBACK_URL, SS.OAUTH_PENDING, SS.OAUTH_CODE,
                    SS.ALL_EXPS, SS.SEL_EXP, SS.REFRESH_COUNT]
            for k in keys:
                st.session_state.pop(k, None)
            for k in [k for k in list(st.session_state.keys())
                      if k.startswith("intra_") or k.startswith("ph_")]:
                st.session_state.pop(k, None)
            st.rerun()

    if not symbol:
        return

    # ── ADVANCED FILTERS ────────────────────────────────────────────────────
    with st.expander("⚙️ Filtros avanzados (GEX calibration)", expanded=False):
        f1, f2, f3 = st.columns(3)
        with f1:
            max_dte = st.slider(
                "Max DTE (para exposures)", 7, 365, 60, step=1,
                help="Filtra opciones con DTE > este valor. 45-60d = estándar gexbot.",
            )
        with f2:
            min_oi = st.slider(
                "Min OI por strike", 0, 1000, 0, step=50,
                help="Filtra strikes ilíquidos. 100+ para SPY/QQQ, 0 para small-caps.",
            )
        with f3:
            focus_pct = st.slider(
                "Focus ± % del spot", 3, 25, 8, step=1, format="±%d%%",
                help="Rango de strikes en los charts. 8-10% estándar para índices.",
            ) / 100.0

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── LOAD CHAIN ──────────────────────────────────────────────────────────
    need_load = symbol and (
        st.session_state.get(SS.LAST_SYM) != symbol
        or st.session_state.get(SS.LAST_STRIKES) != strike_count
        or SS.CHAIN_DATA not in st.session_state
    )
    if need_load:
        with st.spinner(f"Fetching {symbol}…"):
            data, err = fetch_chain(
                symbol, strike_count,
                today.strftime("%Y-%m-%d"),
                (today + datetime.timedelta(days=180)).strftime("%Y-%m-%d"),
            )
        if err:
            st.error(f"❌ {err}")
            return
        if not data or data.get("status") == "FAILED":
            st.warning(f"No se encontraron opciones para **{symbol}**.")
            return
        st.session_state[SS.CHAIN_DATA] = data
        st.session_state[SS.LAST_SYM] = symbol
        st.session_state[SS.LAST_STRIKES] = strike_count
        st.session_state[SS.SYMBOL] = symbol
        st.session_state[SS.LAST_REFRESH] = datetime.datetime.now()
        calls_r, _, _ = parse_chain(data)
        calls_c = clean(calls_r)
        exps = sorted(set(
            calls_c["Expiry"].tolist()
            if not calls_c.empty and "Expiry" in calls_c.columns else []
        ))
        st.session_state[SS.ALL_EXPS] = exps
        for k in list(st.session_state.keys()):
            if k.startswith("intra_") and not k.startswith(f"intra_{symbol}_"):
                del st.session_state[k]
        st.rerun()

    if SS.CHAIN_DATA not in st.session_state:
        st.markdown(
            '<p style="color:#404060;text-align:center;margin-top:3rem;'
            'font-family:JetBrains Mono,monospace;font-size:0.85rem;">'
            'Ingresa un símbolo para comenzar</p>',
            unsafe_allow_html=True,
        )
        return

    # ── PARSE ───────────────────────────────────────────────────────────────
    data = st.session_state[SS.CHAIN_DATA]
    calls_raw, puts_raw, ul = parse_chain(data)
    calls_all = clean(calls_raw)
    puts_all = clean(puts_raw)

    sel_exp = st.session_state.get(SS.SEL_EXP,
                                   (st.session_state.get(SS.ALL_EXPS) or [""])[0])
    calls = by_expiry(calls_all, sel_exp).sort_values("Strike") if not calls_all.empty else calls_all
    puts = by_expiry(puts_all, sel_exp).sort_values("Strike") if not puts_all.empty else puts_all

    spot = float(ul.get("mark") or ul.get("last") or ul.get("close") or 0)
    chg = float(ul.get("netChange", 0) or 0)
    chg_p = float(ul.get("percentChange", 0) or 0)
    bid_u = float(ul.get("bid", 0) or 0)
    ask_u = float(ul.get("ask", 0) or 0)
    vol_u = int(ul.get("totalVolume", 0) or 0)

    # ── ANALYTICS ───────────────────────────────────────────────────────────
    dte_v = 0
    if not calls.empty and "DTE" in calls.columns:
        dte_vals = calls["DTE"].dropna()
        if len(dte_vals) > 0:
            try:
                dte_v = int(float(str(dte_vals.values[0]).split(".")[0]))
            except Exception:
                dte_v = 0

    iv_atm = atm_iv_interp(calls_all, spot) or atm_iv_interp(calls, spot)
    p_c = put_call_ratio(calls, puts)
    mp = max_pain(calls, puts)
    em_lo, em_hi = expected_move(spot, iv_atm, dte_v)
    skew_df = iv_skew(calls_all, puts_all, spot)
    ts_df = term_structure(calls_all, spot, puts_all)
    last_refresh = st.session_state.get(SS.LAST_REFRESH, datetime.datetime.now())

    _, _top_gex_sum = compute_gex_profile(calls_all, puts_all, spot,
                                          symbol=symbol, max_dte=max_dte, min_oi=min_oi)
    total_gex_bn = _top_gex_sum.get("total_gex", 0) / 1e9 if _top_gex_sum else None

    # Price history — cached per symbol/day
    ph_key = f"ph_{symbol}_{today}"
    if ph_key not in st.session_state:
        ph_df, ph_err = fetch_price_history(symbol)
        st.session_state[ph_key] = ph_df
        st.session_state[ph_key + "_err"] = ph_err
    price_df = st.session_state.get(ph_key, pd.DataFrame())
    price_err = st.session_state.get(ph_key + "_err", "")

    # ── DIAGNOSTICS ─────────────────────────────────────────────────────────
    with st.expander("🔍 Diagnóstico", expanded=False):
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("calls_all", len(calls_all))
        d2.metric("puts_all", len(puts_all))
        d3.metric("ATM IV", f"{iv_atm:.1f}%" if iv_atm else "None ⚠️")
        d4.metric("price rows", len(price_df))
        d5, d6, d7, d8 = st.columns(4)
        iv_c = int((calls_all["IV%"] > 1.0).sum() if "IV%" in calls_all.columns else 0)
        iv_p = int((puts_all["IV%"] > 1.0).sum() if "IV%" in puts_all.columns else 0)
        d5.metric("IV válidos calls", iv_c)
        d6.metric("IV válidos puts", iv_p)
        d7.metric("skew rows", len(skew_df))
        d8.metric("ts rows", len(ts_df))
        if price_err:
            st.error(f"Price history: {price_err}")

    # ── METRICS ROW ─────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
    m1.metric("PRECIO", f"${spot:.2f}", f"{chg:+.2f}  {chg_p:+.1f}%")
    m2.metric("BID / ASK", f"{bid_u:.2f} / {ask_u:.2f}")
    m3.metric("VOLUMEN", f"{vol_u:,}")
    m4.metric("DTE", f"{dte_v}d")
    m5.metric("ATM IV", f"{iv_atm:.1f}%" if iv_atm else "—")
    m6.metric("P/C RATIO", f"{p_c:.2f}" if p_c else "—")
    m7.metric("MAX PAIN", f"${mp:.0f}" if mp else "—")
    m8.metric(
        "NET GEX",
        f"${total_gex_bn:+.2f}B" if total_gex_bn is not None else "—",
        "LONG Γ" if (total_gex_bn or 0) >= 0 else "SHORT Γ",
    )

    if em_lo and em_hi:
        move_pct = round((em_hi - spot) / spot * 100, 1)
        st.markdown(
            f'<p style="font-size:0.72rem;color:#404060;'
            f'font-family:JetBrains Mono,monospace;margin:0.3rem 0 0;">'
            f'1σ Expected Move ({dte_v}d): '
            f'<span style="color:#a855f7">${em_lo:.2f} — ${em_hi:.2f}</span>'
            f'  <span style="color:#505070">(±{move_pct}%)</span>'
            f'  &nbsp;·&nbsp; Actualizado: {last_refresh.strftime("%H:%M:%S")}'
            f'</p>',
            unsafe_allow_html=True,
        )

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── VOL REGIME (forwarded to GEX decision panel) ───────────────────────
    vol_regime_str = None
    if not price_df.empty and iv_atm:
        analytics = vol_analytics(price_df, iv_atm)
        if analytics:
            vol_regime_str = analytics.get("vol_regime")

    # ── GEX MODULE ──────────────────────────────────────────────────────────
    st.markdown('<p class="bb-header">GAMMA EXPOSURE MODULE  ·  Dealer Flow Analytics</p>',
                unsafe_allow_html=True)
    gex_sum, _ = render_gex_module(
        symbol, calls_all, puts_all, spot,
        max_dte=max_dte, min_oi=min_oi, focus_pct=focus_pct,
        dte_v=dte_v, iv_atm=iv_atm, em_lo=em_lo, em_hi=em_hi,
        vol_regime=vol_regime_str,
    )

    # ── GAMMA SCENARIO CURVE (GEX vs hypothetical spot) ─────────────────────
    st.markdown('<p class="bb-header">GAMMA SCENARIO  ·  Net GEX(S\')</p>',
                unsafe_allow_html=True)
    st.caption(
        "Reprice dealer gamma sobre un grid de spot hipotético usando los "
        "strikes+IV+DTE actuales. Cruce por cero = Zero Gamma dinámico. "
        "Positivo = dealer vende en rallies / compra en dips (pinning). "
        "Negativo = dealer amplifica movimientos (gamma squeeze)."
    )
    curve_df = gex_curve_over_spot(
        calls_all, puts_all, spot, symbol=symbol,
        max_dte=max_dte, min_oi=min_oi, grid_pct=0.10, n_points=81,
    )
    if not curve_df.empty and gex_sum:
        fig_curve = chart_gex_curve(curve_df, spot, gex_sum)
        if fig_curve:
            st.plotly_chart(fig_curve, use_container_width=True)
    else:
        st.caption("Scenario requiere IV% y DTE válidos en la cadena (mismo requisito que VEX).")

    # ── 0DTE MODULE ─────────────────────────────────────────────────────────
    zdte_c = calls_all[calls_all.get("DTE", pd.Series(dtype=int)) == 0] if "DTE" in calls_all.columns else pd.DataFrame()
    zdte_p = puts_all[puts_all.get("DTE", pd.Series(dtype=int)) == 0] if "DTE" in puts_all.columns else pd.DataFrame()
    if not zdte_c.empty or not zdte_p.empty:
        st.markdown('<p class="bb-header">0DTE GAMMA  ·  Today-only dealer flow</p>',
                    unsafe_allow_html=True)
        st.caption(
            "Filtro DTE = 0. Relevante para SPX/SPY/QQQ en horas finales: "
            "el charm colapsa a cero y el gamma se concentra alrededor del ATM."
        )
        zdte_df, zdte_sum = compute_gex_profile(
            zdte_c, zdte_p, spot, symbol=symbol, max_dte=0, min_oi=min_oi,
            use_spot_grid_flip=False,
        )
        if not zdte_df.empty and zdte_sum:
            z1, z2, z3, z4 = st.columns(4)
            z1.metric("0DTE Net GEX",
                      f"${zdte_sum['total_gex']/1e6:+.0f}M",
                      "LONG Γ" if zdte_sum["total_gex"] >= 0 else "SHORT Γ")
            z2.metric("0DTE Call Wall",
                      f"${zdte_sum['call_wall']:.0f}" if zdte_sum.get("call_wall") else "—")
            z3.metric("0DTE Put Wall",
                      f"${zdte_sum['put_wall']:.0f}" if zdte_sum.get("put_wall") else "—")
            z4.metric("0DTE HVL (pin)",
                      f"${zdte_sum['hvl']:.0f}" if zdte_sum.get("hvl") else "—")
            fig_z = chart_gex_profile(zdte_df, spot, zdte_sum, f"{symbol} 0DTE",
                                      focus_pct=min(0.05, focus_pct))
            if fig_z:
                st.plotly_chart(fig_z, use_container_width=True)
        else:
            st.caption("Sin datos 0DTE disponibles (mercado cerrado o sin strikes 0DTE).")

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── INTRADAY CHART ──────────────────────────────────────────────────────
    st.markdown('<p class="bb-header">PRECIO INTRADAY  ·  CANDLESTICK + NIVELES GEX</p>',
                unsafe_allow_html=True)
    st.caption(
        "Interactiva: rueda=pan · Ctrl+rueda=zoom · doble-click=reset. "
        "Niveles: SPOT · CW · PW · GF · HVL · MP · EM±. Eje X: hora ET del mercado. "
        "Reloj live ET + CDMX."
    )
    c_ctrl1, c_ctrl2, c_ctrl3, c_ctrl4 = st.columns([1, 1, 1, 3])
    with c_ctrl1:
        intra_freq = st.selectbox(
            "Frecuencia", [1, 5, 15, 30], index=0,
            format_func=lambda x: f"{x} min", key="intra_freq",
        )
    with c_ctrl2:
        intra_days = st.selectbox("Días", [1, 2, 3, 5], index=0, key="intra_days")
    with c_ctrl3:
        live_tick = st.toggle(
            "Live 15s", value=True, key="live_tick_toggle",
            help=("Refresca el quote cada 15s (rerun del dashboard). "
                  "Apágalo si notas el UI lento."),
        )

    # Cache-key granularidad: 1 min (alineada con la frecuencia mínima que la UI pide)
    now_et = datetime.datetime.now(ET_TZ)
    bucket_min = max(1, int(intra_freq))
    bucket = (now_et.minute // bucket_min) * bucket_min
    now_bucket = now_et.strftime("%Y%m%d_%H") + f"{bucket:02d}"
    intra_key = f"intra_{symbol}_{intra_freq}_{intra_days}_{now_bucket}"
    intra_err_key = intra_key + "_err"

    stale = [k for k in list(st.session_state.keys())
             if k.startswith(f"intra_{symbol}_")
             and k not in (intra_key, intra_err_key)]
    for k in stale:
        del st.session_state[k]

    if intra_key not in st.session_state:
        with st.spinner(f"Cargando velas {intra_freq}min…"):
            intra_df, intra_err = fetch_intraday(symbol, intra_freq, intra_days)
        st.session_state[intra_key] = intra_df
        st.session_state[intra_err_key] = intra_err
    intra_df = st.session_state.get(intra_key, pd.DataFrame())
    intra_err = st.session_state.get(intra_err_key, "")

    # Live quote (cached 8s) — feeds ticker header
    live_q = {}
    if live_tick:
        live_q, qerr = fetch_quote(symbol)
    m_status, _now_et = market_status_et()

    _, col_ref = st.columns([5, 1])
    with col_ref:
        if st.button("↺ Refresh", key="intra_refresh"):
            for k in [intra_key, intra_key + "_err"]:
                st.session_state.pop(k, None)
            fetch_quote.clear()
            fetch_intraday.clear()
            st.rerun()

    if not intra_df.empty and gex_sum:
        render_tv_chart(intra_df, spot, gex_sum, mp, em_lo, em_hi,
                        freq_min=intra_freq, live_quote=live_q,
                        market_status=m_status)
    else:
        if not intra_df.empty:
            st.caption("GEX data no disponible para proyectar niveles en el chart.")
        else:
            st.caption(
                "Datos intraday no disponibles. " +
                (f"Error: `{intra_err}`" if intra_err
                 else "Mercado cerrado o símbolo sin datos.")
            )

    # Autorefresh ligero del chart cuando live_tick está ON — no toca la chain
    if live_tick:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=15_000, key="intra_live_tick")
        except ImportError:
            pass

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── GREEKS ──────────────────────────────────────────────────────────────
    st.markdown('<p class="bb-header">GREEKS SURFACE  (vencimiento seleccionado)</p>',
                unsafe_allow_html=True)
    st.plotly_chart(chart_greeks(calls, puts, spot), use_container_width=True)

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── IV SKEW & VOLATILITY SMILE ──────────────────────────────────────────
    st.markdown('<p class="bb-header">IV SKEW  &  VOLATILITY SMILE</p>',
                unsafe_allow_html=True)
    st.caption(
        "Curva ámbar = <b>Market smile</b> (OTM puts abajo de spot + OTM calls arriba). "
        "Puntos diamante = ATM IV. <b>RR25</b> = put-wing − call-wing (sesgo a puts si +). "
        "<b>BF25</b> = convexidad. Panel derecho: Put IV − Call IV por strike.",
    )
    exps_avail = st.session_state.get(SS.ALL_EXPS, []) or []
    exp_options = ["(vencimiento seleccionado arriba)"] + [str(e) for e in exps_avail]
    default_idx = 0
    if sel_exp and str(sel_exp) in exps_avail:
        default_idx = exps_avail.index(str(sel_exp)) + 1
    smile_exp_label = st.selectbox(
        "Expiry del smile",
        options=exp_options,
        index=default_idx,
        key="smile_exp",
        label_visibility="collapsed",
        help="Selecciona un vencimiento para construir el smile sin mezclar DTEs.",
    )
    smile_exp = sel_exp if smile_exp_label.startswith("(") else smile_exp_label
    smile_df = iv_smile_by_expiry(calls_all, puts_all, spot, smile_exp)
    if not smile_df.empty:
        dte_smile = 0
        try:
            dte_smile = int(calls_all[calls_all["Expiry"] == smile_exp]["DTE"].iloc[0])
        except Exception:
            pass
        metrics = skew_metrics(calls_all, puts_all, spot, smile_exp)
        fig_smile = chart_iv_smile(smile_df, spot, str(smile_exp), dte_smile, metrics)
        if fig_smile:
            st.plotly_chart(fig_smile, use_container_width=True)
        # Compact term-level skew strip
        if metrics:
            rr = metrics.get("rr25")
            bf = metrics.get("bf25")
            sl = metrics.get("slope_90_110")
            atm = metrics.get("atm_iv")
            st.markdown(
                f'<p style="font-size:0.72rem;color:#7070a0;font-family:{FONT_MONO};margin:0 0 0.6rem">'
                f'<b>Expiry:</b> {str(smile_exp)[:10]}  ·  '
                f'<b>ATM:</b> {atm:.1f}% · '
                f'<b>RR25:</b> <span style="color:{RED if (rr or 0) > 0 else GREEN}">{rr:+.2f} pts</span> · '
                f'<b>BF25:</b> {bf:+.2f} pts · '
                f'<b>Slope(90/110):</b> {sl:+.2f} pts'
                f'</p>' if (atm and rr is not None and bf is not None and sl is not None)
                else '',
                unsafe_allow_html=True,
            )
    else:
        st.caption("IV Smile: el vencimiento seleccionado no tiene IV válido en calls y puts.")

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── TERM STRUCTURE ──────────────────────────────────────────────────────
    st.markdown('<p class="bb-header">TERM STRUCTURE  (IV por vencimiento)</p>',
                unsafe_allow_html=True)
    if not ts_df.empty:
        c_ts, c_ts_tbl = st.columns([3, 1])
        with c_ts:
            fig_ts = chart_term_structure(ts_df)
            if fig_ts:
                st.plotly_chart(fig_ts, use_container_width=True)
        with c_ts_tbl:
            st.markdown("<br>", unsafe_allow_html=True)
            tbl = ['<table style="font-family:JetBrains Mono,monospace;'
                   'font-size:0.72rem;width:100%;">',
                   '<tr><th style="color:#505070;text-align:left;padding:2px 6px">Exp</th>'
                   '<th style="color:#505070;text-align:right;padding:2px 6px">DTE</th>'
                   '<th style="color:#505070;text-align:right;padding:2px 6px">ATM IV</th></tr>']
            for _, row in ts_df.iterrows():
                iv_c = (GREEN if row["ATM_IV"] < 30 else
                        (RED if row["ATM_IV"] > 60 else ORANGE))
                tbl.append(
                    f'<tr>'
                    f'<td style="color:#7070a0;padding:2px 6px">{str(row["Expiry"])[:10]}</td>'
                    f'<td style="text-align:right;color:#9090b0;padding:2px 6px">'
                    f'{int(row["DTE"])}</td>'
                    f'<td style="text-align:right;color:{iv_c};padding:2px 6px">'
                    f'{row["ATM_IV"]:.1f}%</td></tr>'
                )
            tbl.append("</table>")
            st.markdown("".join(tbl), unsafe_allow_html=True)
    else:
        st.caption("Term Structure no disponible.")

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── OI / VOLUME ─────────────────────────────────────────────────────────
    st.markdown('<p class="bb-header">OPEN INTEREST  &  VOLUME</p>',
                unsafe_allow_html=True)
    st.plotly_chart(chart_oi_volume(calls, puts, spot, em_lo, em_hi),
                    use_container_width=True)

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── VOL ANALYSIS ────────────────────────────────────────────────────────
    st.markdown('<p class="bb-header">VOLATILITY ANALYSIS  ·  HV · IV Rank · Cone · Returns</p>',
                unsafe_allow_html=True)
    if not price_df.empty:
        render_vol_module(symbol, iv_atm, spot, price_df)
    else:
        st.caption(
            "Análisis no disponible. " +
            (f"Error: `{price_err}`" if price_err else "")
        )

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── CHAIN TABLE ─────────────────────────────────────────────────────────
    st.markdown('<p class="bb-header">OPTIONS CHAIN  (vencimiento seleccionado)</p>',
                unsafe_allow_html=True)
    mode = st.radio("Vista", ["both", "calls", "puts"], index=0, horizontal=True,
                    key="chain_mode", label_visibility="collapsed")
    st.markdown(build_table(calls, puts, spot, mode), unsafe_allow_html=True)

    # ── FOOTER ──────────────────────────────────────────────────────────────
    st.markdown(
        f'<p class="footer">OPTIONS TERMINAL  ·  {symbol}  ·  '
        f'{last_refresh.strftime("%Y-%m-%d %H:%M:%S")} UTC'
        f'  ·  Charles Schwab API  ·  Datos en tiempo real'
        f'  ·  No constituye asesoramiento financiero</p>',
        unsafe_allow_html=True,
    )

    # ── AUTO-REFRESH ────────────────────────────────────────────────────────
    if auto_refresh:
        try:
            from streamlit_autorefresh import st_autorefresh
            count = st_autorefresh(interval=30_000, key="chain_autorefresh")
            if count and count != st.session_state.get(SS.REFRESH_COUNT):
                st.session_state[SS.REFRESH_COUNT] = count
                st.session_state.pop(SS.CHAIN_DATA, None)
                st.rerun()
            st.caption("🔄 Auto-refresh activo cada 30s (no bloqueante).")
        except ImportError:
            elapsed = (datetime.datetime.now() - last_refresh).seconds
            remaining = max(0, 30 - elapsed)
            if remaining == 0:
                st.session_state.pop(SS.CHAIN_DATA, None)
                st.rerun()
            else:
                st.caption(f"🔄 Actualizando en {remaining}s…")
                time.sleep(1)
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  Connect screen
# ─────────────────────────────────────────────────────────────────────────────
def show_connect_screen() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.2, 1])
    has_secrets = bool(get_secret("APP_KEY") and get_secret("APP_SECRET"))
    is_expired = has_secrets and not st.session_state.get(SS.CONNECTED)
    with col:
        if is_expired:
            st.markdown("""
            <span class="conn-logo">⚠</span>
            <h1 class="conn-title" style="color:#f43f5e">TOKEN EXPIRADO</h1>
            <p class="conn-sub">Tu refresh token expiró (válido 7 días). Re-autoriza una vez y copia el nuevo token a Secrets.</p>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <span class="conn-logo">▤</span>
            <h1 class="conn-title">OPTIONS TERMINAL</h1>
            <p class="conn-sub">Primera configuración — Solo necesitas hacer esto una vez.</p>
            """, unsafe_allow_html=True)

        if not has_secrets:
            st.markdown('<div class="step-card">', unsafe_allow_html=True)
            st.markdown(
                '<span class="step-num">0</span>'
                '<span class="step-label"> Credenciales (primera vez):</span>',
                unsafe_allow_html=True,
            )
            app_key = st.text_input("APP KEY", placeholder="developer.schwab.com → tu app")
            app_secret = st.text_input("APP SECRET", type="password", placeholder="••••••••••")
            callback = st.text_input(
                "CALLBACK URL", value="https://127.0.0.1",
                help="Streamlit Cloud → URL de tu app  |  Local → https://127.0.0.1",
            )
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            app_key = get_secret("APP_KEY")
            app_secret = get_secret("APP_SECRET")
            callback = get_secret("CALLBACK_URL", "https://127.0.0.1")
            st.info(f"✓ Credenciales cargadas desde Secrets. Callback: `{callback}`", icon="🔑")

        if not has_secrets:
            if st.button("SIGUIENTE → GENERAR ENLACE", type="primary",
                         use_container_width=True):
                if not app_key or not app_secret:
                    st.error("Completa App Key y App Secret.")
                    return
                st.session_state.update({
                    SS.APP_KEY: app_key.strip(),
                    SS.APP_SECRET: app_secret.strip(),
                    SS.CALLBACK_URL: callback.strip(),
                    SS.OAUTH_PENDING: True,
                })
                st.rerun()
            if SS.OAUTH_PENDING not in st.session_state:
                return
        else:
            st.session_state[SS.APP_KEY] = app_key
            st.session_state[SS.APP_SECRET] = app_secret
            st.session_state[SS.CALLBACK_URL] = callback

        auth_url = build_auth_url(st.session_state[SS.APP_KEY],
                                  st.session_state[SS.CALLBACK_URL])
        st.markdown('<div class="step-card">', unsafe_allow_html=True)
        st.markdown(
            '<span class="step-num">1</span>'
            '<span class="step-label"> Autoriza en Schwab:</span>',
            unsafe_allow_html=True,
        )
        st.link_button("🔐  AUTORIZAR EN SCHWAB", auth_url, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        callback = st.session_state.get(SS.CALLBACK_URL, "")
        is_cloud = "streamlit.app" in callback or "streamlit.io" in callback
        if is_cloud:
            st.info(
                "✅ **Flujo automático activo.** Al autorizar en Schwab serás "
                "redirigido y el código se captura solo.",
                icon="🚀",
            )
        else:
            st.warning("⚡ **Actúa rápido** — el código expira en ~30 segundos.", icon="⏱")
            st.markdown('<div class="step-card">', unsafe_allow_html=True)
            st.markdown(
                '<span class="step-num">2</span>'
                '<span class="step-label"> Pega la URL de redirección:</span>',
                unsafe_allow_html=True,
            )
            redirect_url = st.text_input(
                "redirect", label_visibility="collapsed",
                placeholder="https://127.0.0.1?code=Xxxx&session=...",
            )
            st.markdown('</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("← Cancelar", use_container_width=True):
                    for k in (SS.OAUTH_PENDING, SS.APP_KEY,
                              SS.APP_SECRET, SS.CALLBACK_URL):
                        st.session_state.pop(k, None)
                    st.rerun()
            with c2:
                if st.button("CONECTAR →", type="primary", use_container_width=True):
                    if not redirect_url:
                        st.error("Pega la URL de redirección.")
                        return
                    if finish_oauth(redirect_url.strip()):
                        tok = st.session_state.get(SS.TOKENS, {})
                        st.success("✅ Autenticado correctamente.")
                        st.code(
                            f'REFRESH_TOKEN = "{tok.get("refresh_token", "")}"',
                            language="toml",
                        )
                        st.caption("Guarda este token en Streamlit Secrets para auto-connect.")
                        if st.button("ENTRAR AL DASHBOARD →", type="primary",
                                     use_container_width=True):
                            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point helpers
# ─────────────────────────────────────────────────────────────────────────────
def handle_oauth_query_param() -> bool:
    """Capture `?code=` from URL on redirect. Returns True if we handled a rerun."""
    if "code" in st.query_params:
        if (not st.session_state.get(SS.CONNECTED)
                and SS.OAUTH_CODE not in st.session_state):
            st.session_state[SS.OAUTH_CODE] = st.query_params["code"]
        st.query_params.clear()
        st.rerun()
        return True
    return False


def handle_oauth_code_exchange() -> bool:
    """Process a previously captured OAuth code. Returns True if the UI was rendered."""
    if (SS.OAUTH_CODE not in st.session_state
            or st.session_state.get(SS.CONNECTED)):
        return False
    code = st.session_state.pop(SS.OAUTH_CODE)
    st.markdown(CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        with st.spinner("Autenticando…"):
            ok = exchange_code(code)
        if ok:
            tok = st.session_state.get(SS.TOKENS, {})
            st.success("✅ Conectado.")
            st.code(f'REFRESH_TOKEN = "{tok.get("refresh_token", "")}"',
                    language="toml")
            if st.button("ENTRAR →", type="primary", use_container_width=True):
                st.rerun()
        else:
            if st.button("← VOLVER", use_container_width=True):
                st.rerun()
    return True


def run() -> None:
    if handle_oauth_query_param():
        return
    if handle_oauth_code_exchange():
        return
    if not st.session_state.get(SS.CONNECTED):
        try_auto_connect()
    if st.session_state.get(SS.CONNECTED):
        show_dashboard()
    else:
        show_connect_screen()
