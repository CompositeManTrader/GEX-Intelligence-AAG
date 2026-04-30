"""
UI render modules — dashboard, connect screen, GEX + vol panels.

Thin orchestration layer over:
  - data.fetch / data.parse
  - quant.exposures / quant.levels / quant.vol / quant.flow
  - charts.gex / charts.vol / charts.flow
  - ui.styles / ui.decision / ui.chain_table / ui.interpretations
"""
from __future__ import annotations

import datetime
import math
import time
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from auth.schwab import (
    build_auth_url, exchange_code, finish_oauth, get_secret, try_auto_connect,
)
from charts.flow import chart_hiro_oscillator, chart_hiro_strike
from charts.gex import (
    chart_cum_gex, chart_cex_profile, chart_dex_profile, chart_gex_by_expiry,
    chart_gex_curve, chart_gex_gexbot_style, chart_gex_profile,
    chart_vex_profile,
)
from charts.intraday import chart_session_profile, render_intraday_chart
from charts.orderflow import (
    chart_convexity_timeseries, chart_dex_timeseries, chart_gex_timeseries,
    chart_orderflow_stack,
)
from charts.theme import CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED
from charts.vol import (
    chart_greeks, chart_iv_hv_history, chart_iv_skew, chart_iv_smile,
    chart_oi_volume, chart_returns_dist, chart_term_structure, chart_vol_cone,
)
from config import (
    CDMX_TZ, ET_TZ, FUTURES_PREFER_INDEX, SS, dollars_per_point,
    future_spec, get_logger, is_future, market_status_et, points_distance,
    resolve_chain_symbol, sanitize_symbol,
)
from data.fetch import fetch_chain, fetch_intraday, fetch_price_history, fetch_quote
from data.parse import by_expiry, clean, parse_chain
from data.persistence import (
    available_replay_dates, db_stats, load_daily_snapshots,
    load_hiro_history, load_orderflow_history, load_recent_hiro,
    load_recent_orderflow, persist_daily_snapshot, persist_hiro_tick,
    persist_orderflow_tick,
)
from quant.exposures import (
    compute_cex_profile, compute_dex_profile, compute_gex_by_expiry,
    compute_gex_profile, compute_vex_profile, gex_curve_over_spot,
)
from quant.backtest import (
    BacktestStats, Trade, compute_stats, run_backtest, trades_dataframe,
)
from quant.flow import (
    compute_hiro_by_strike, compute_hiro_snapshot, hiro_zscore,
    tick_hiro, update_hiro_history,
)
from quant.orderflow import tick_orderflow, update_orderflow_history
from quant.signals import _ensure_et, generate_signals as gen_signals
from quant.levels import (
    atm_iv_interp, expected_move, iv_skew, iv_smile_by_expiry, max_pain,
    put_call_ratio, skew_metrics, term_structure,
)
from quant.vol import vol_analytics
from ui.auth_gate import current_user, logout, require_login
from ui.chain_table import build_table
from ui.decision import build_decision_panel
from ui.interpretations import (
    interpret_0dte, interpret_cex, interpret_dex, interpret_gex_profile,
    interpret_hiro, interpret_oi, interpret_orderflow_convexity,
    interpret_orderflow_dex, interpret_orderflow_gex,
    interpret_orderflow_summary, interpret_scenario, interpret_smile,
    interpret_term_structure, interpret_vex, interpret_vol_analytics,
)
from ui.styles import CSS
from ui.widgets import (
    flip_zone_widget, levels_strip, position_sizer, trade_setup_card,
    trading_hero,
)

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


def _render_md(html: str) -> None:
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────────────────────────────────────
def show_dashboard() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

    today = datetime.date.today()

    # ── TOP BAR ─────────────────────────────────────────────────────────────
    b1, b2, b3, b4, b5, b8, b6, b7 = st.columns(
        [1.0, 1.4, 1.6, 0.9, 0.9, 0.9, 0.6, 0.7]
    )
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
            placeholder="SPY · ES · NQ · AAPL…", label_visibility="collapsed",
        )
        display_root = sanitize_symbol(raw_sym)
        if raw_sym and not display_root:
            st.warning("Símbolo inválido. Usa mayúsculas, puntos o guiones (ej. BRK.B).")
        # Resolve futures roots (ES/NQ/RTY/YM/MES/MNQ/M2K/MYM) → chain symbol.
        prefer_idx = st.session_state.get(SS.PREFER_INDEX, FUTURES_PREFER_INDEX)
        symbol, fut_spec = resolve_chain_symbol(display_root, prefer_index=prefer_idx)
        st.session_state[SS.FUTURE_ROOT] = display_root if fut_spec else None
        if fut_spec:
            chain_label = fut_spec.underlying if prefer_idx else fut_spec.etf_proxy
            st.markdown(
                f"<div style='font-family:JetBrains Mono,monospace;font-size:0.62rem;"
                f"color:#06b6d4;letter-spacing:0.10em;line-height:1;margin-top:-0.4rem;'>"
                f"▸ {display_root} → {chain_label} · ${fut_spec.point_value:.2f}/pt"
                f"</div>",
                unsafe_allow_html=True,
            )
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
    with b8:
        trading_mode = st.toggle(
            "🎯 Trading", value=False, key=SS.TRADING_MODE,
            help="Pantalla única para operar en vivo: precio gigante, niveles "
                 "en puntos del futuro, position sizer y mini-chart.",
        )
    with b6:
        if st.button("EXIT", use_container_width=True,
                     help="Cerrar sesión Schwab (mantiene login de app)"):
            keys = [SS.TOKENS, SS.CONNECTED, SS.CHAIN_DATA, SS.LAST_SYM,
                    SS.LAST_STRIKES, SS.SYMBOL, SS.APP_KEY, SS.APP_SECRET,
                    SS.CALLBACK_URL, SS.OAUTH_PENDING, SS.OAUTH_CODE,
                    SS.ALL_EXPS, SS.SEL_EXP, SS.REFRESH_COUNT,
                    SS.HIRO_HISTORY, SS.ORDERFLOW_HISTORY]
            for k in keys:
                st.session_state.pop(k, None)
            for k in [k for k in list(st.session_state.keys())
                      if k.startswith("intra_") or k.startswith("ph_")]:
                st.session_state.pop(k, None)
            st.rerun()
    with b7:
        who = current_user()
        if st.button(f"🔒 {who}"[:10] if who else "🔒 LOGOUT",
                     use_container_width=True,
                     help="Cerrar sesión de la app completa (requerirá contraseña)"):
            logout()
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
        # Futures-specific toggle
        if fut_spec is not None:
            prev = st.session_state.get(SS.PREFER_INDEX, FUTURES_PREFER_INDEX)
            new = st.toggle(
                f"📊 Usar cadena del índice ({fut_spec.underlying}) en vez del ETF "
                f"({fut_spec.etf_proxy})",
                value=prev,
                help="Activa si tu cuenta Schwab tiene acceso a opciones de índice. "
                     "ETF proxy es más confiable; índice cash refleja mejor el GEX dealer.",
            )
            if new != prev:
                st.session_state[SS.PREFER_INDEX] = new
                st.session_state.pop(SS.CHAIN_DATA, None)
                st.rerun()

    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)

    # ── AUTO-REFRESH HANDLER (must run BEFORE chain load) ──────────────────
    # Wiring the pop here means the in-flight rerun (started by
    # st_autorefresh) immediately re-fetches the chain and re-renders.
    # That avoids the double-rerun cycle (= visible flicker) the previous
    # version had, AND keeps the data current within the same 30s window.
    if auto_refresh:
        try:
            from streamlit_autorefresh import st_autorefresh
            _ar_count = st_autorefresh(interval=30_000, key="chain_autorefresh")
            if _ar_count and _ar_count != st.session_state.get(SS.REFRESH_COUNT):
                st.session_state[SS.REFRESH_COUNT] = _ar_count
                st.session_state.pop(SS.CHAIN_DATA, None)
        except ImportError:
            pass

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
        # Detect whether we're switching symbols (vs auto-refreshing same one)
        prev_sym = st.session_state.get(SS.LAST_SYM)
        symbol_changed = prev_sym != symbol

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
        # Reset HIRO + Orderflow history when symbol changes (per-symbol series)
        if symbol_changed:
            st.session_state.pop(SS.HIRO_HISTORY, None)
            st.session_state.pop(SS.ORDERFLOW_HISTORY, None)
            # Also drop the previously-selected expiry — it belonged to
            # the old chain and `by_expiry` would otherwise return empty
            # for the new symbol, blanking every panel until the user
            # manually re-selects an expiry.
            st.session_state.pop(SS.SEL_EXP, None)
            # Only rerun on a true symbol change so the SEL_EXP selectbox
            # picks up the new ALL_EXPS list. Auto-refreshes on the same
            # symbol skip this rerun → no flicker, no widget-state reset.
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

    # Spot reference: prefer last traded price, then mark only when bid/ask
    # are both populated (otherwise mark can be (0+stale_ask)/2 — a stale
    # reference that mis-prices walls / EM / pct-distances across the panel).
    _last = ul.get("last")
    _mark = ul.get("mark")
    _bid, _ask = ul.get("bid"), ul.get("ask")
    if _last and float(_last) > 0:
        spot = float(_last)
    elif _mark and _bid and _ask and float(_bid) > 0 and float(_ask) > 0:
        spot = float(_mark)
    else:
        spot = float(ul.get("close") or 0)
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

    # Blend put-side IV when available (OCC convention) — see levels.py.
    iv_atm = (atm_iv_interp(calls_all, spot, p=puts_all)
              or atm_iv_interp(calls, spot, p=puts))
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

    # ── HIRO: tick every chain refresh (persistent rolling history) ─────────
    hiro_snap = compute_hiro_snapshot(calls_all, puts_all)
    hiro_tick = tick_hiro(calls_all, puts_all, spot)
    hist = st.session_state.get(SS.HIRO_HISTORY, [])
    # Seed from SQLite on cold start so we don't lose the morning's data when
    # the dashboard is reopened mid-session.
    if not hist:
        hist = load_recent_hiro(symbol, hours=8, limit=500)
    hist = update_hiro_history(hist, hiro_tick, max_len=500)
    st.session_state[SS.HIRO_HISTORY] = hist
    hiro_z = hiro_zscore(hist)
    # Best-effort persist (won't crash UI on DB lock)
    persist_hiro_tick(symbol, hiro_tick)

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
        d8.metric("HIRO history", len(hist))
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

    # ── Vol regime (for decision panel) ─────────────────────────────────────
    vol_regime_str = None
    analytics_full = None
    if not price_df.empty and iv_atm:
        analytics_full = vol_analytics(price_df, iv_atm)
        if analytics_full:
            vol_regime_str = analytics_full.get("vol_regime")

    # ── Pre-compute exposures once (reused across tabs) ─────────────────────
    gex_df, gex_sum = compute_gex_profile(
        calls_all, puts_all, spot, symbol=symbol,
        max_dte=max_dte, min_oi=min_oi,
    )
    vex_df, vex_sum = compute_vex_profile(
        calls_all, puts_all, spot, symbol=symbol,
        max_dte=max_dte, min_oi=min_oi,
    )
    cex_df, cex_sum = compute_cex_profile(
        calls_all, puts_all, spot, symbol=symbol,
        max_dte=max_dte, min_oi=min_oi,
    )
    dex_df, dex_sum = compute_dex_profile(
        calls_all, puts_all, spot, max_dte=max_dte, min_oi=min_oi,
    )
    exp_df = compute_gex_by_expiry(
        calls_all, puts_all, spot, max_dte=max_dte, min_oi=min_oi,
    )

    # ── ORDERFLOW: rolling history of dealer exposures (gexbot-style) ───────
    of_tick = tick_orderflow(spot, gex_sum, dex_sum, vex_sum)
    of_hist = st.session_state.get(SS.ORDERFLOW_HISTORY, [])
    if not of_hist:
        of_hist = load_recent_orderflow(symbol, hours=8, limit=1000)
    of_hist = update_orderflow_history(of_hist, of_tick, max_len=1000)
    st.session_state[SS.ORDERFLOW_HISTORY] = of_hist
    persist_orderflow_tick(symbol, of_tick)
    # Roll a daily snapshot row (idempotent upsert) so post-mortems work.
    persist_daily_snapshot(symbol, spot, gex_sum, mp, iv_atm,
                           extra={"display_root": display_root,
                                  "future_root": st.session_state.get(SS.FUTURE_ROOT)})

    # ─────────────────────────────────────────────────────────────────────────
    #  TRADING MODE  —  single-screen view, futures-ready
    # ─────────────────────────────────────────────────────────────────────────
    if trading_mode:
        regime_now = (gex_sum or {}).get("regime", "NEUTRAL")
        net_bn_now = (gex_sum or {}).get("total_gex", 0) / 1e9 if gex_sum else None

        # 1. Hero
        chain_label = symbol
        _render_md(trading_hero(
            display_root=display_root or symbol,
            chain_symbol=chain_label,
            spot=spot, fut_spec=fut_spec,
            regime=regime_now,
            net_gex_bn=net_bn_now,
            hiro_z=hiro_z,
        ))

        # 2. Levels strip + intraday chart side by side
        tcol_levels, tcol_chart = st.columns([1.05, 2.0])
        with tcol_levels:
            _render_md(levels_strip(
                spot=spot, fut_spec=fut_spec,
                cw=(gex_sum or {}).get("call_wall"),
                pw=(gex_sum or {}).get("put_wall"),
                gf=(gex_sum or {}).get("gamma_flip"),
                hvl=(gex_sum or {}).get("hvl"),
                mp=mp,
            ))
            # Distance to flip in $ + pct
            gf_now = (gex_sum or {}).get("gamma_flip")
            if gf_now and spot:
                dist_pct = (spot - gf_now) / spot * 100
                dist_pts = (spot - gf_now) * (fut_spec.etf_ratio if fut_spec else 1.0)
                color = "#22c55e" if dist_pct > 0.3 else (
                    "#f43f5e" if dist_pct < -0.3 else "#f59e0b")
                pt_lbl = (f"{fut_spec.root}pts" if fut_spec else "$pts")
                st.markdown(
                    f'<div style="font-family:JetBrains Mono,monospace;'
                    f'font-size:0.78rem;color:#9ca3af;margin-top:0.4rem;'
                    f'padding:0.5rem 0.7rem;background:rgba(15,17,24,0.7);'
                    f'border-radius:4px;border-left:3px solid {color}">'
                    f'Distancia a Zero Γ: '
                    f'<span style="color:{color};font-weight:700">'
                    f'{dist_pct:+.2f}% · {dist_pts:+.1f} {pt_lbl}'
                    f'</span></div>',
                    unsafe_allow_html=True,
                )

        with tcol_chart:
            # Mini intraday chart with horizontal levels — bust cache every 15s
            # (matches the trading-mode autorefresh cadence below).
            mini_bust = int(time.time() // 15)
            mini_df, mini_err = fetch_intraday(
                symbol, freq_min=5, days=1, cache_bust=mini_bust,
            )
            if mini_err or mini_df.empty:
                st.info(f"Sin datos intraday: {mini_err or 'cerrado'}")
            else:
                fig_int = render_intraday_chart(
                    mini_df, spot, gex_sum, mp=mp,
                    em_lo=em_lo, em_hi=em_hi, freq_min=5, symbol=symbol,
                )
                if fig_int is not None:
                    # Stable key → Plotly does smooth in-place data diff
                    # instead of remounting the iframe (no flicker).
                    st.plotly_chart(
                        fig_int, use_container_width=True,
                        key=f"trading_mode_chart_{symbol}",
                    )
                else:
                    fig_sp = chart_session_profile(mini_df, spot)
                    if fig_sp is not None:
                        st.plotly_chart(
                            fig_sp, use_container_width=True,
                            key=f"trading_mode_session_{symbol}",
                        )

        # 3. Position sizer (only meaningful for futures)
        if fut_spec is not None:
            ps1, ps2, ps3 = st.columns(3)
            with ps1:
                acct = st.number_input(
                    "💼 Tamaño de cuenta ($)",
                    min_value=1000, max_value=10_000_000,
                    value=int(st.session_state.get("trading_acct", 25000)),
                    step=1000, key="trading_acct",
                )
            with ps2:
                risk = st.slider(
                    "🎯 Riesgo por trade (%)",
                    0.1, 5.0,
                    value=float(st.session_state.get("trading_risk", 1.0)),
                    step=0.1, key="trading_risk",
                )
            with ps3:
                # Default stop = distance to nearest wall
                cw_now = (gex_sum or {}).get("call_wall")
                pw_now = (gex_sum or {}).get("put_wall")
                default_stop = 10.0
                if fut_spec and cw_now and pw_now and spot:
                    nearest = min(abs(cw_now - spot), abs(pw_now - spot))
                    default_stop = max(2.0, nearest * fut_spec.etf_ratio)
                stop = st.number_input(
                    f"🛑 Stop ({fut_spec.root} pts)",
                    min_value=0.25, max_value=200.0,
                    value=float(default_stop),
                    step=0.25, key="trading_stop",
                )
            _render_md(position_sizer(float(acct), float(risk),
                                       float(stop), fut_spec))

        # 4. Trade setup card (compact)
        iv_hv_ratio = (analytics_full or {}).get("iv_hv_ratio") if analytics_full else None
        _render_md(trade_setup_card(
            symbol=symbol, spot=spot,
            gex_sum=gex_sum, vex_sum=vex_sum, cex_sum=cex_sum, dex_sum=dex_sum,
            hiro_snap=hiro_snap, hiro_z=hiro_z,
            atm_iv=iv_atm, iv_hv_ratio=iv_hv_ratio,
            em_lo=em_lo, em_hi=em_hi, dte=dte_v,
        ))

        # Footer + auto-refresh in trading mode
        st.markdown(
            f'<p class="footer" style="margin-top:1.5rem">TRADING MODE · '
            f'{display_root or symbol} · '
            f'{last_refresh.strftime("%H:%M:%S")} UTC</p>',
            unsafe_allow_html=True,
        )
        if auto_refresh:
            try:
                from streamlit_autorefresh import st_autorefresh
                count = st_autorefresh(interval=15_000, key="trading_autorefresh")
                if count and count != st.session_state.get(SS.REFRESH_COUNT):
                    st.session_state[SS.REFRESH_COUNT] = count
                    st.session_state.pop(SS.CHAIN_DATA, None)
                    # No st.rerun() — the autorefresh tick is itself a rerun.
            except ImportError:
                pass
        return

    # ─────────────────────────────────────────────────────────────────────────
    #  TABS  (named for readability — order here controls UI order)
    # ─────────────────────────────────────────────────────────────────────────
    TAB_LABELS = [
        "🎯 Overview",
        "📈 Intraday",
        "🤖 Signals",
        "📊 GEX Total",
        "🌀 Orderflow",
        "🔥 GEX 0DTE",
        "💎 Vanna (VEX)",
        "⏳ Charm (CEX)",
        "📈 Delta (DEX)",
        "🌊 HIRO Flow",
        "📐 Term Structure",
        "📉 IV Skew & Smile",
        "💰 Open Interest",
        "📊 Vol Analytics",
        "📋 Chain",
        "🕰️ Replay",
    ]
    tabs = st.tabs(TAB_LABELS)
    (tab_overview, tab_intra, tab_signals, tab_gex, tab_orderflow, tab_0dte,
     tab_vex, tab_cex, tab_dex, tab_hiro, tab_ts, tab_smile, tab_oi, tab_vol,
     tab_chain, tab_replay) = tabs

    # ── OVERVIEW ────────────────────────────────────────────────────────────
    with tab_overview:
        # 1. TRADE SETUP CARD — lo primero que ve el trader
        iv_hv_ratio = (analytics_full or {}).get("iv_hv_ratio") if analytics_full else None
        _render_md(trade_setup_card(
            symbol=symbol, spot=spot,
            gex_sum=gex_sum, vex_sum=vex_sum, cex_sum=cex_sum, dex_sum=dex_sum,
            hiro_snap=hiro_snap, hiro_z=hiro_z,
            atm_iv=iv_atm, iv_hv_ratio=iv_hv_ratio,
            em_lo=em_lo, em_hi=em_hi, dte=dte_v,
        ))

        # 2. GEX FLIP ZONE — thermometer tactico
        _render_md(flip_zone_widget(spot, gex_sum))

        # 3. DECISION PANEL legacy
        _render_md('<p class="bb-header">DECISION PANEL  ·  Flow-weighted thesis</p>')
        panel = build_decision_panel(spot, gex_sum, vex_sum, cex_sum, dex_sum,
                                     iv_atm, em_lo, em_hi, dte_v, vol_regime_str)
        _render_md(panel)
        # Quick KPI row
        if gex_sum:
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
            _render_md(hdr)

            # ── Futures-points overlay ─────────────────────────────────────
            if fut_spec is not None and spot > 0:
                ratio = fut_spec.etf_ratio
                ppt = fut_spec.point_value
                def _pts(level):
                    if level is None:
                        return None
                    return (level - spot) * ratio
                def _fmt(pts):
                    if pts is None:
                        return "—"
                    return f"{pts:+.1f} pts"
                def _fmt_dollar(pts):
                    if pts is None:
                        return None
                    return f"${pts*ppt:+,.0f}/contrato"
                pts_panel = '<div class="kpi-panel">'
                pts_panel += _kv(f"{display_root} ≈",
                                 f"{spot*ratio:,.1f}", CYAN,
                                 sub=f"{fut_spec.name}")
                pts_panel += _kv("Δ Call Wall", _fmt(_pts(cw)), GREEN,
                                 sub=_fmt_dollar(_pts(cw)))
                pts_panel += _kv("Δ Put Wall", _fmt(_pts(pw)), RED,
                                 sub=_fmt_dollar(_pts(pw)))
                pts_panel += _kv("Δ Zero Γ", _fmt(_pts(gf)), PURPLE,
                                 sub=_fmt_dollar(_pts(gf)))
                pts_panel += _kv("Δ HVL", _fmt(_pts(hvl)), CYAN,
                                 sub=_fmt_dollar(_pts(hvl)))
                pts_panel += _kv("Tick", f"${fut_spec.tick_value:.2f}",
                                 "#9ca3af",
                                 sub=f"{fut_spec.tick_size} pt")
                pts_panel += '</div>'
                _render_md(pts_panel)

        _render_md(interpret_gex_profile(gex_sum, spot))
        _render_md(interpret_hiro(hiro_snap, hiro_z, len(hist)))

    # ── INTRADAY ────────────────────────────────────────────────────────────
    with tab_intra:
        _render_md('<p class="bb-header">'
                   'PRECIO INTRADAY  ·  Candlestick + niveles GEX dinámicos</p>')
        st.caption(
            "Velas nativas (Plotly) con líneas horizontales de <b>SPOT · CW · PW · "
            "GF · HVL · MP · EM±</b>. Los niveles se recalculan cada refresh "
            "usando la cadena actual. VWAP anclado a la apertura en línea discontinua."
        )
        c_ctrl1, c_ctrl2, c_ctrl3, c_ctrl4 = st.columns([1, 1, 1, 3])
        with c_ctrl1:
            intra_freq = st.selectbox(
                "Frecuencia", [1, 5, 15, 30], index=0,
                format_func=lambda x: f"{x} min", key="intra_freq",
            )
        with c_ctrl2:
            intra_days = st.selectbox(
                "Días", [1, 2, 3, 5], index=0, key="intra_days",
            )
        with c_ctrl3:
            intra_auto = st.selectbox(
                "Auto-refresh",
                [0, 10, 20, 30, 60],
                index=2,
                format_func=lambda x: "OFF" if x == 0 else f"{x}s",
                key="intra_auto_sec",
                help="Actualización automática dentro de la tab intraday.",
            )

        # ── Per-tab auto-refresh (independiente del global) ────────────────
        if intra_auto:
            try:
                from streamlit_autorefresh import st_autorefresh
                st_autorefresh(interval=int(intra_auto) * 1000,
                               key="intra_tab_autorefresh")
            except ImportError:
                pass

        # cache_bust rotates every `intra_auto` seconds (or every 30s by
        # default if auto is off) → guarantees a real Schwab refetch even
        # if Streamlit's TTL eviction lags.
        bust_window = max(int(intra_auto) if intra_auto else 30, 5)
        bust = int(time.time() // bust_window)
        with st.spinner(f"Cargando velas {intra_freq}min…"):
            intra_df, intra_err = fetch_intraday(
                symbol, intra_freq, intra_days,
                include_extended=False, cache_bust=bust,
            )

        m_status, now_et_m = market_status_et()
        last_tick = (intra_df["date"].iloc[-1]
                     if not intra_df.empty and "date" in intra_df.columns else None)
        last_tick_str = (pd.Timestamp(last_tick).tz_convert(ET_TZ).strftime("%H:%M:%S ET")
                         if last_tick is not None else "—")
        st.caption(
            f"Estado mercado: <b style='color:"
            f"{'#22c55e' if m_status == 'OPEN' else '#f59e0b'}'>"
            f"{m_status}</b> · Frec {intra_freq}m · {intra_days}d · "
            f"Última vela: <b>{last_tick_str}</b> · "
            f"Ahora: {now_et_m.strftime('%H:%M:%S ET')}",
            unsafe_allow_html=True,
        )

        if not intra_df.empty:
            fig_intra = render_intraday_chart(
                intra_df, spot, gex_sum, mp=mp,
                em_lo=em_lo, em_hi=em_hi,
                freq_min=intra_freq, symbol=symbol,
            )
            if fig_intra:
                # Stable key → Plotly does an in-place data diff every
                # rerun. The figure object itself is rebuilt each time
                # (with fresh bars from fetch_intraday) so the chart
                # updates smoothly without remounting the iframe.
                chart_key = f"intra_chart_{symbol}_{intra_freq}"
                st.plotly_chart(fig_intra, use_container_width=True, key=chart_key)
            # Session profile below candles
            _render_md('<p class="bb-header" style="margin-top:0.6rem">'
                       'SESSION PROFILE  ·  Volumen por bucket 30m (ET)</p>')
            st.caption(
                "Distribución del volumen a lo largo del día. El pico identifica "
                "la hora en que se definió el rango intradía."
            )
            fig_sp = chart_session_profile(intra_df, symbol)
            if fig_sp:
                st.plotly_chart(
                    fig_sp, use_container_width=True,
                    key=f"sp_chart_{symbol}",
                )
            # Manual refresh button
            if st.button("↺ Refresh velas ahora", key="intra_refresh_btn"):
                try:
                    fetch_intraday.clear()
                    fetch_quote.clear()
                except Exception:
                    pass
                st.rerun()
        else:
            st.caption(
                "Datos intraday no disponibles. " +
                (f"Error: `{intra_err}`" if intra_err
                 else "Mercado cerrado o símbolo sin datos.")
            )

    # ── SIGNALS — live engine + walk-forward backtest ───────────────────────
    with tab_signals:
        _render_md('<p class="bb-header">'
                   'SIGNALS  ·  Mean reversion en +Γ · Trend en −Γ</p>')
        st.caption(
            "Motor determinístico que dispara entradas según el régimen GEX. "
            "<b>+Γ</b>: fade del VWAP cuando el spot se estira ±1.5σ. "
            "<b>−Γ</b>: ruptura del Opening Range (primeros 30m). "
            "Stops 0.5×ATR(14) o opposite-end OR. TP1 = VWAP/wall · TP2 = HVL/2×OR. "
            "Salida forzada 15:50 ET — sin overnight.",
            unsafe_allow_html=True,
        )

        # ── Live signals (latest bar) ──────────────────────────────────────
        sig_bust = int(time.time() // 30)
        live_df, live_err = fetch_intraday(
            symbol, freq_min=1, days=1, cache_bust=sig_bust,
        )

        sigs_now: list = []
        if not live_df.empty:
            try:
                sigs_now = gen_signals(
                    live_df, gex_sum, symbol=symbol, hiro_z=hiro_z,
                )
            except Exception as exc:
                log.exception("live signal generation failed")
                st.error(f"Signal engine error: {exc}")

        if sigs_now:
            _render_md('<p class="bb-header" style="margin-top:0.6rem">'
                       'SEÑALES ACTIVAS  ·  última vela</p>')
            for s in sigs_now:
                side_color = "#22c55e" if s.side == "LONG" else "#f43f5e"
                strat_label = ("Mean Reversion" if s.strategy == "mean_reversion"
                               else "Trend Breakout")
                conf_pct = int(s.confidence * 100)
                st.markdown(
                    f'<div style="background:rgba(15,17,24,0.85);'
                    f'border:1px solid #1e2230;border-left:4px solid {side_color};'
                    f'border-radius:6px;padding:0.9rem 1.1rem;margin:0.4rem 0;'
                    f'font-family:JetBrains Mono,monospace">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;margin-bottom:0.5rem">'
                    f'<div>'
                    f'<span style="color:{side_color};font-weight:800;'
                    f'font-size:1.1rem;letter-spacing:0.05em">{s.side}</span>'
                    f'<span style="color:#9ca3af;margin-left:0.6rem;'
                    f'font-size:0.85rem">{strat_label}</span>'
                    f'</div>'
                    f'<div style="color:#06b6d4;font-size:0.78rem">'
                    f'confidence {conf_pct}%</div></div>'
                    f'<div style="display:grid;grid-template-columns:repeat(5,1fr);'
                    f'gap:0.6rem;font-size:0.78rem">'
                    f'<div><span style="color:#6b7280;font-size:0.62rem;'
                    f'letter-spacing:0.12em;text-transform:uppercase">Entry</span>'
                    f'<br><b style="color:#e5e7eb">${s.entry:.2f}</b></div>'
                    f'<div><span style="color:#6b7280;font-size:0.62rem;'
                    f'letter-spacing:0.12em;text-transform:uppercase">Stop</span>'
                    f'<br><b style="color:#f43f5e">${s.stop:.2f}</b></div>'
                    f'<div><span style="color:#6b7280;font-size:0.62rem;'
                    f'letter-spacing:0.12em;text-transform:uppercase">TP1</span>'
                    f'<br><b style="color:#22c55e">${s.target1:.2f}</b>'
                    f'<span style="color:#6b7280"> · {s.rr_target1:.1f}R</span></div>'
                    f'<div><span style="color:#6b7280;font-size:0.62rem;'
                    f'letter-spacing:0.12em;text-transform:uppercase">TP2</span>'
                    f'<br><b style="color:#22c55e">${s.target2:.2f}</b>'
                    f'<span style="color:#6b7280"> · {s.rr_target2:.1f}R</span></div>'
                    f'<div><span style="color:#6b7280;font-size:0.62rem;'
                    f'letter-spacing:0.12em;text-transform:uppercase">1R</span>'
                    f'<br><b style="color:#a855f7">${s.r_unit:.2f}</b></div>'
                    f'</div>'
                    f'<div style="color:#9ca3af;font-size:0.72rem;margin-top:0.6rem">'
                    f'{s.rationale}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info(
                "Sin señales activas en esta vela. El motor evalúa cada bar de "
                "1 min y solo dispara cuando se cumple la confluencia régimen + "
                "estiramiento + filtro HIRO."
            )

        # ── Backtest panel ─────────────────────────────────────────────────
        st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)
        _render_md('<p class="bb-header">'
                   'BACKTEST  ·  walk-forward sobre sesiones guardadas</p>')
        st.caption(
            "Replay bar-por-bar usando los snapshots SQLite. Sin look-ahead: "
            "cada vela usa el último orderflow tick ≤ ese momento. Las salidas "
            "asumen que si el bar tocó stop Y target en el mismo minuto, sale "
            "primero el stop (conservador)."
        )

        bt_dates = available_replay_dates(symbol, lookback_days=60)
        bt1, bt2, bt3 = st.columns([2, 1, 1])
        with bt1:
            sel_days = st.multiselect(
                "📅 Días a backtestear",
                options=bt_dates,
                default=bt_dates[:5] if bt_dates else [],
                help="Necesitas días con orderflow guardado. Deja varios para "
                     "una muestra estadísticamente útil.",
                key="bt_days",
            )
        with bt2:
            bt_use_t2 = st.toggle(
                "Usar TP2 (trail)", value=True,
                help="Si ON: la operación cierra solo en TP2 o stop. "
                     "Si OFF: cierra en TP1 (~1.5R por ganador).",
                key="bt_use_t2",
            )
        with bt3:
            run_bt = st.button("▶ Correr backtest",
                               type="primary",
                               use_container_width=True,
                               key="bt_run")

        if run_bt and sel_days:
            with st.spinner(f"Backtesting {len(sel_days)} días…"):
                all_trades: list[Trade] = []
                for d in sorted(sel_days):
                    of_day = load_orderflow_history(symbol, date=d, limit=5000)
                    if not of_day:
                        continue
                    # We only have today's intraday in cache reliably; for
                    # historical days we depend on Schwab returning N days.
                    # Pull a wide window (10 days) and let backtest filter.
                    bt_bust = int(time.time() // 60)
                    bars_df, _err = fetch_intraday(
                        symbol, freq_min=1, days=10,
                        cache_bust=bt_bust,
                    )
                    if bars_df.empty:
                        continue
                    # Filter to the requested day
                    et_df = _ensure_et(bars_df)
                    target_date = pd.to_datetime(d).date()
                    day_df = et_df[et_df["_et"].dt.date == target_date]
                    if day_df.empty:
                        st.warning(
                            f"No hay velas en cache para {d}. "
                            f"Los días a backtestear deben estar dentro de "
                            f"los últimos 10 días que devuelve Schwab."
                        )
                        continue
                    trades, _ = run_backtest(
                        day_df, of_day, symbol=symbol,
                        use_target2=bt_use_t2,
                    )
                    all_trades.extend(trades)

                stats = compute_stats(all_trades)

            if not all_trades:
                st.warning(
                    "No se generaron operaciones. Posibles causas: pocos "
                    "snapshots de orderflow, régimen siempre NEUTRAL, o el "
                    "spot no estiró nunca ±1.5σ."
                )
            else:
                # ── Headline stats ─────────────────────────────────────────
                k1, k2, k3, k4, k5, k6 = st.columns(6)
                k1.metric("Trades", stats.trades)
                k2.metric("Win rate",
                          f"{stats.win_rate*100:.1f}%",
                          f"{stats.wins}W / {stats.losses}L")
                k3.metric("Avg R", f"{stats.avg_r:+.2f}R",
                          help="Expectancy por trade en R-multiples.")
                k4.metric("Sum R", f"{stats.sum_r:+.2f}R",
                          help="Total cumulativo (= P&L en unidades de 1R).")
                pf_str = (f"{stats.profit_factor:.2f}"
                          if math.isfinite(stats.profit_factor) else "∞")
                k5.metric("Profit factor", pf_str,
                          help="|gross win| / |gross loss|. >1.5 ya es bueno.")
                k6.metric("Sharpe (R)",
                          f"{stats.sharpe:+.2f}",
                          help="mean(R) / std(R) × √N — Sharpe-like sobre R.")

                k7, k8, k9, k10 = st.columns(4)
                k7.metric("Max drawdown", f"-{stats.max_drawdown_r:.2f}R")
                k8.metric("Best trade", f"{stats.best_trade_r:+.2f}R")
                k9.metric("Worst trade", f"{stats.worst_trade_r:+.2f}R")
                k10.metric("Avg bars held", f"{stats.avg_bars_held:.0f} min")

                # ── Equity curve ───────────────────────────────────────────
                if stats.equity_curve:
                    eq_fig = go.Figure()
                    eq_fig.add_trace(go.Scatter(
                        x=list(range(1, len(stats.equity_curve) + 1)),
                        y=stats.equity_curve,
                        mode="lines+markers",
                        line=dict(color="#06b6d4", width=2),
                        marker=dict(size=5),
                        fill="tozeroy",
                        fillcolor="rgba(6,182,212,0.1)",
                        name="Cumulative R",
                    ))
                    eq_fig.update_layout(
                        title="Equity curve (cumulative R-multiples)",
                        height=320,
                        paper_bgcolor="#0a0d14",
                        plot_bgcolor="#0e1019",
                        font=dict(family="JetBrains Mono", color="#e5e7eb",
                                  size=11),
                        margin=dict(l=40, r=40, t=40, b=40),
                        xaxis=dict(title="Trade #",
                                   gridcolor="rgba(255,255,255,0.05)"),
                        yaxis=dict(title="Cumulative R",
                                   gridcolor="rgba(255,255,255,0.05)",
                                   zerolinecolor="rgba(255,255,255,0.2)"),
                    )
                    st.plotly_chart(eq_fig, use_container_width=True,
                                    key="bt_equity_curve")

                # ── Breakdown tables ───────────────────────────────────────
                br1, br2 = st.columns(2)
                with br1:
                    st.markdown("**Por estrategia**")
                    if stats.by_strategy:
                        st.dataframe(
                            pd.DataFrame(stats.by_strategy).T.reset_index().rename(
                                columns={"index": "strategy"}),
                            use_container_width=True, hide_index=True,
                        )
                with br2:
                    st.markdown("**Por régimen**")
                    if stats.by_regime:
                        st.dataframe(
                            pd.DataFrame(stats.by_regime).T.reset_index().rename(
                                columns={"index": "regime"}),
                            use_container_width=True, hide_index=True,
                        )

                # ── R-multiple histogram ───────────────────────────────────
                rs = [t.r_multiple for t in all_trades]
                hist_fig = go.Figure()
                hist_fig.add_trace(go.Histogram(
                    x=rs,
                    nbinsx=30,
                    marker=dict(
                        color=["rgba(244,63,94,0.7)" if r < 0
                               else "rgba(34,197,94,0.7)" for r in rs],
                        line=dict(color="rgba(255,255,255,0.1)", width=1),
                    ),
                ))
                hist_fig.update_layout(
                    title="Distribución de R-multiples",
                    height=300,
                    paper_bgcolor="#0a0d14",
                    plot_bgcolor="#0e1019",
                    font=dict(family="JetBrains Mono", color="#e5e7eb",
                              size=11),
                    margin=dict(l=40, r=40, t=40, b=40),
                    xaxis=dict(title="R-multiple",
                               gridcolor="rgba(255,255,255,0.05)"),
                    yaxis=dict(title="Frecuencia",
                               gridcolor="rgba(255,255,255,0.05)"),
                )
                st.plotly_chart(hist_fig, use_container_width=True,
                                key="bt_r_histogram")

                # ── Trade log ──────────────────────────────────────────────
                _render_md('<p class="bb-header" style="margin-top:1rem">'
                           'TRADE LOG</p>')
                trades_df = trades_dataframe(all_trades)
                # Friendly column order
                cols_keep = ["timestamp_open", "timestamp_close", "side",
                             "strategy", "regime", "entry", "stop",
                             "target1", "target2", "exit_price",
                             "exit_reason", "r_multiple", "pnl_pts",
                             "bars_held"]
                cols_keep = [c for c in cols_keep if c in trades_df.columns]
                st.dataframe(trades_df[cols_keep], use_container_width=True,
                             hide_index=True)

                # CSV export
                csv_bytes = trades_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Descargar trade log (CSV)",
                    data=csv_bytes,
                    file_name=f"backtest_{symbol}_{datetime.date.today()}.csv",
                    mime="text/csv",
                    key="bt_csv_download",
                )

    # ── 1. GEX TOTAL ────────────────────────────────────────────────────────
    with tab_gex:
        _render_md('<p class="bb-header">GEX PROFILE  ·  Gamma Exposure por Strike</p>')
        st.caption(
            "Calls → derecha (verde), Puts → izquierda (rojo), Net GEX → puntos "
            "azules. Walls: Call (verde dashed), Put (rojo dashed), Spot (blanco "
            "sólido), Zero Γ (morado dotted). Modo GexBot superpone la curva del "
            "spot intradía en cyan."
        )

        # ── Style + view + zoom controls ───────────────────────────────────
        # Defensive widget-state pattern: read the last-known value from
        # session_state and pass it as the explicit `index=` so the
        # selection survives every rerun (auto-refresh, button click, etc).
        # `key=` alone is supposed to handle this, but Streamlit 1.x has
        # known edge cases when widgets re-render inside a tab + columns
        # layout — the explicit index is a belt-and-suspenders guarantee.
        STYLE_OPTS = ["gexbot", "classic"]
        VIEW_OPTS = ["all", "net", "call", "put"]
        ZOOM_OPTS = ["tight", "near", "mid", "wide", "all"]

        prev_style = st.session_state.get("gex_style_mode", "gexbot")
        prev_view = st.session_state.get("gex_view_mode", "all")
        prev_zoom = st.session_state.get("gex_zoom_mode")
        if prev_zoom not in ZOOM_OPTS:
            prev_zoom = "tight" if prev_style == "gexbot" else "mid"

        cgx0, cgx1, cgx2 = st.columns([1.3, 1.5, 1.8])
        with cgx0:
            gex_style = st.radio(
                "Estilo",
                options=STYLE_OPTS,
                format_func=lambda s: {"gexbot": "GexBot", "classic": "Clásico"}[s],
                horizontal=True,
                index=STYLE_OPTS.index(prev_style),
                key="gex_style_mode",
                help="GexBot: barras horizontales con precio intradía superpuesto. "
                     "Clásico: barras horizontales sin overlay de precio.",
            )
        with cgx1:
            gex_view = st.radio(
                "Vista",
                options=VIEW_OPTS,
                format_func=lambda v: {
                    "all": "Todos", "net": "Solo Net",
                    "call": "Solo Call", "put": "Solo Put",
                }[v],
                horizontal=True,
                index=VIEW_OPTS.index(prev_view),
                key="gex_view_mode",
            )
        with cgx2:
            gex_zoom = st.radio(
                "Zoom",
                options=ZOOM_OPTS,
                format_func=lambda z: {
                    "tight": "Tight ±3%", "near": "Near ±5%",
                    "mid": "Mid ±10%", "wide": "Wide ±20%",
                    "all": "All strikes",
                }[z],
                horizontal=True,
                index=ZOOM_OPTS.index(prev_zoom),
                key="gex_zoom_mode",
            )
        gex_pct = {
            "tight": 0.03, "near": 0.05, "mid": 0.10, "wide": 0.20, "all": None,
        }[gex_zoom]

        if not gex_df.empty and gex_sum:
            if gex_style == "gexbot":
                # Bust cache every 30s to match the global auto-refresh.
                gex_bust = int(time.time() // 30)
                intra_for_gex, _ierr = fetch_intraday(
                    symbol, 5, 1, cache_bust=gex_bust,
                )
                fig_gex = chart_gex_gexbot_style(
                    gex_df, spot, gex_sum, symbol,
                    intraday_df=intra_for_gex,
                    focus_pct=gex_pct, view=gex_view,
                )
            else:
                fig_gex = chart_gex_profile(
                    gex_df, spot, gex_sum, symbol,
                    focus_pct=gex_pct, view=gex_view,
                )
            if fig_gex:
                # Stable component key: tied ONLY to the symbol + style.
                # Changing view/zoom no longer remounts (Plotly diffs
                # the trace list). Auto-refresh ALSO no longer remounts
                # because the key doesn't include any time-rotating value.
                st.plotly_chart(
                    fig_gex, use_container_width=True,
                    key=f"gex_chart_{symbol}_{gex_style}",
                )
            _render_md(interpret_gex_profile(gex_sum, spot))
        else:
            st.warning("No hay datos suficientes para GEX. Ajusta DTE o min OI.")

        col_l, col_r = st.columns([3, 2])
        with col_l:
            _render_md('<p class="bb-header" style="margin-top:0.3rem">PERFIL ACUMULADO</p>')
            st.caption("Cruce por cero = Zero Gamma dinámico.")
            if not gex_df.empty and gex_sum:
                fig_cum = chart_cum_gex(gex_df, spot, gex_sum)
                if fig_cum:
                    st.plotly_chart(fig_cum, use_container_width=True)
        with col_r:
            _render_md('<p class="bb-header" style="margin-top:0.3rem">GEX POR VENCIMIENTO</p>')
            st.caption("Top 14 expiraciones por |Net GEX|.")
            fig_exp = chart_gex_by_expiry(exp_df)
            if fig_exp:
                st.plotly_chart(fig_exp, use_container_width=True)
            else:
                st.caption("Requiere ≥ 1 vencimiento con datos.")

        # Scenario curve (reprice gamma over hypothetical spot grid)
        _render_md('<p class="bb-header">GAMMA SCENARIO  ·  Net GEX(S\')</p>')
        st.caption(
            "Reprice dealer gamma sobre un grid de spot hipotético usando los "
            "strikes+IV+DTE actuales. Cruce por cero = Zero Gamma dinámico."
        )
        curve_df = gex_curve_over_spot(
            calls_all, puts_all, spot, symbol=symbol,
            max_dte=max_dte, min_oi=min_oi, grid_pct=0.10, n_points=81,
        )
        if not curve_df.empty and gex_sum:
            fig_curve = chart_gex_curve(curve_df, spot, gex_sum)
            if fig_curve:
                st.plotly_chart(fig_curve, use_container_width=True)
            _render_md(interpret_scenario(curve_df, gex_sum, spot))
        else:
            st.caption("Scenario requiere IV% y DTE válidos en la cadena.")

    # ── ORDERFLOW (3-panel time-series, gexbot-style) ───────────────────────
    with tab_orderflow:
        _render_md('<p class="bb-header">'
                   'ORDERFLOW  ·  DEX / GEX / Convexity en tiempo real</p>')
        st.caption(
            "Tres paneles apilados sobre el mismo eje temporal. Cada snapshot "
            "agrega un tick al historial (hasta 500). <b>DEX</b> = bias direccional. "
            "<b>Net GEX</b> = régimen de gamma con paredes (CW/PW/GF). "
            "<b>Convexity</b> = vanna neta — cambia si IV se mueve. "
            "La línea naranja punteada es el spot sobre el eje derecho."
        )

        c_of1, c_of2, c_of3, c_of4 = st.columns(4)
        c_of1.metric("Snapshots", f"{len(of_hist)}")
        last_of = of_hist[-1] if of_hist else {}
        c_of2.metric(
            "Net DEX",
            (f"${last_of.get('net_dex_mm'):+.1f}M"
             if last_of.get("net_dex_mm") is not None else "—"),
        )
        c_of3.metric(
            "Net GEX",
            (f"${last_of.get('net_gex_mm'):+.1f}M"
             if last_of.get("net_gex_mm") is not None else "—"),
        )
        c_of4.metric(
            "Net VEX",
            (f"${last_of.get('net_vex_mm'):+.1f}M"
             if last_of.get("net_vex_mm") is not None else "—"),
        )

        # Top-line summary always visible — works with 1+ snapshots.
        _render_md(interpret_orderflow_summary(of_hist, spot))

        if of_hist:
            if len(of_hist) == 1:
                st.caption(
                    "⏳ Único snapshot. El panel dibuja los valores actuales "
                    "como puntos; al siguiente refresh (o con <b>Auto 30s</b> "
                    "activo) se empieza a construir la serie temporal.",
                    unsafe_allow_html=True,
                )

            of_view = st.radio(
                "Vista",
                options=["stacked", "separate"],
                format_func=lambda v: {
                    "stacked": "Panel único (3 filas)",
                    "separate": "Paneles separados + comentario",
                }[v],
                horizontal=True, index=1, key="of_view_mode",
            )
            if of_view == "stacked":
                fig_of = chart_orderflow_stack(of_hist, symbol)
                if fig_of:
                    st.plotly_chart(
                        fig_of, use_container_width=True,
                        key=f"of_stack_{symbol}_{len(of_hist)}",
                    )
                # Also render the three commentary boxes below the stacked chart
                _render_md(interpret_orderflow_dex(of_hist))
                _render_md(interpret_orderflow_gex(of_hist, spot))
                _render_md(interpret_orderflow_convexity(of_hist))
            else:
                # DEX panel + commentary
                _render_md('<p class="bb-header" style="margin-top:0.4rem">'
                           'DEX  ·  Aggregate Delta Exposure</p>')
                fig_dex_ts = chart_dex_timeseries(of_hist, symbol)
                if fig_dex_ts:
                    st.plotly_chart(
                        fig_dex_ts, use_container_width=True,
                        key=f"of_dex_{symbol}_{len(of_hist)}",
                    )
                _render_md(interpret_orderflow_dex(of_hist))

                # GEX panel + commentary
                _render_md('<p class="bb-header" style="margin-top:0.8rem">'
                           'NET GEX  ·  Dealer Gamma Exposure</p>')
                fig_gex_ts = chart_gex_timeseries(of_hist, symbol)
                if fig_gex_ts:
                    st.plotly_chart(
                        fig_gex_ts, use_container_width=True,
                        key=f"of_gex_{symbol}_{len(of_hist)}",
                    )
                _render_md(interpret_orderflow_gex(of_hist, spot))

                # Convexity / Vanna panel + commentary
                _render_md('<p class="bb-header" style="margin-top:0.8rem">'
                           'CONVEXITY  ·  Net Vanna Exposure</p>')
                fig_vex_ts = chart_convexity_timeseries(of_hist, symbol)
                if fig_vex_ts:
                    st.plotly_chart(
                        fig_vex_ts, use_container_width=True,
                        key=f"of_vex_{symbol}_{len(of_hist)}",
                    )
                _render_md(interpret_orderflow_convexity(of_hist))
        else:
            st.caption(
                "🔄 Orderflow vacío. Se empieza a acumular en cuanto se "
                "carga la primera cadena. Activa <b>Auto 30s</b> "
                "en la barra superior para construir el historial rápidamente.",
                unsafe_allow_html=True,
            )

    # ── 2. GEX 0DTE ─────────────────────────────────────────────────────────
    with tab_0dte:
        # 0DTE filter — force numeric DTE first so the comparison works even
        # when Schwab returns DTE as string/object.
        if "DTE" in calls_all.columns:
            _c_dte = pd.to_numeric(calls_all["DTE"], errors="coerce")
            zdte_c = calls_all[_c_dte == 0]
        else:
            zdte_c = pd.DataFrame()
        if "DTE" in puts_all.columns:
            _p_dte = pd.to_numeric(puts_all["DTE"], errors="coerce")
            zdte_p = puts_all[_p_dte == 0]
        else:
            zdte_p = pd.DataFrame()

        _render_md('<p class="bb-header">0DTE GAMMA  ·  Today-only dealer flow</p>')
        st.caption(
            "Filtro DTE = 0. Relevante para SPX/SPY/QQQ en horas finales: "
            "charm colapsa a cero y gamma se concentra en el ATM. "
            "Se ignora el min-OI global porque los contratos 0DTE típicamente "
            "tienen OI bajo pero volumen y gamma altos."
        )
        if not zdte_c.empty or not zdte_p.empty:
            # min_oi=0 for 0DTE: filtering by OI hides the most active 0DTE
            # strikes (they have huge volume but low carry-over OI).
            # Spot-grid flip ON: for a single-DTE bucket, the true zero-gamma
            # crossing is well-defined and more accurate than the
            # strike-cumulative fallback.
            zdte_df, zdte_sum = compute_gex_profile(
                zdte_c, zdte_p, spot, symbol=symbol,
                max_dte=0, min_oi=0,
                use_spot_grid_flip=True,
            )
            if not zdte_df.empty and zdte_sum:
                total_m = zdte_sum.get("total_gex", 0) / 1e6
                z1, z2, z3, z4 = st.columns(4)
                z1.metric(
                    "0DTE Net GEX",
                    f"${total_m:+.1f}M",
                    "LONG Γ" if total_m >= 0 else "SHORT Γ",
                )
                z2.metric(
                    "0DTE Call Wall",
                    (f"${zdte_sum['call_wall']:.0f}"
                     if zdte_sum.get("call_wall") else "—"),
                )
                z3.metric(
                    "0DTE Put Wall",
                    (f"${zdte_sum['put_wall']:.0f}"
                     if zdte_sum.get("put_wall") else "—"),
                )
                z4.metric(
                    "0DTE HVL (pin)",
                    (f"${zdte_sum['hvl']:.0f}"
                     if zdte_sum.get("hvl") else "—"),
                )
                # Secondary row: gamma flip + strike counts
                z5, z6, z7, z8 = st.columns(4)
                gf = zdte_sum.get("gamma_flip")
                z5.metric(
                    "Zero Γ (0DTE)",
                    f"${gf:.0f}" if gf else "—",
                    (f"{(gf - spot)/spot*100:+.2f}% vs spot"
                     if gf and spot else None),
                )
                z6.metric("# strikes", f"{zdte_sum.get('n_strikes', 0)}")
                z7.metric("# calls 0DTE", f"{len(zdte_c)}")
                z8.metric("# puts 0DTE", f"{len(zdte_p)}")
                # Tighter focus for 0DTE — strikes are dense around ATM
                fig_z = chart_gex_profile(
                    zdte_df, spot, zdte_sum, f"{symbol} 0DTE",
                    focus_pct=min(0.03, focus_pct),
                )
                if fig_z:
                    st.plotly_chart(
                        fig_z, use_container_width=True,
                        key=f"0dte_chart_{symbol}",
                    )
                _render_md(interpret_0dte(zdte_sum, spot))
            else:
                st.caption(
                    "Sin datos 0DTE procesables (gamma = 0 o cadena vacía)."
                )
        else:
            st.caption(
                "No hay strikes con DTE = 0 en la cadena. "
                "Este módulo solo aplica a símbolos con expiraciones diarias "
                "(SPY/QQQ/SPX). En SPX el filtro se activa solo de lunes a viernes."
            )

    # ── 3. VANNA ────────────────────────────────────────────────────────────
    with tab_vex:
        _render_md('<p class="bb-header">VANNA EXPOSURE  ·  $ Delta por +1 pto IV</p>')
        st.caption(
            "<b>VEX(k) = Vanna × OI × 100 × S × 0.01 × sign</b>. "
            "Positivo → dealer compra spot si IV sube. Negativo → dealer vende spot "
            "en vol expansion. Clave en FOMC / CPI / earnings."
        )
        if not vex_df.empty and vex_sum:
            fig_vex = chart_vex_profile(vex_df, spot, vex_sum, symbol, focus_pct=focus_pct)
            if fig_vex:
                st.plotly_chart(fig_vex, use_container_width=True)
            _render_md(interpret_vex(vex_sum))
        else:
            st.caption("VEX requiere IV% y DTE válidos en la cadena.")

    # ── 4. CHARM ────────────────────────────────────────────────────────────
    with tab_cex:
        _render_md('<p class="bb-header">CHARM EXPOSURE  ·  $ Delta decay por día</p>')
        st.caption(
            "<b>CEX(k) = Charm × OI × 100 × S × sign</b>. Decaimiento del delta dealer "
            "por día calendario. Positivo → EOD buy-flow cerca vencimiento. "
            "Esencial para 0DTE y pin risk en OPEX."
        )
        if not cex_df.empty and cex_sum:
            fig_cex = chart_cex_profile(cex_df, spot, cex_sum, symbol, focus_pct=focus_pct)
            if fig_cex:
                st.plotly_chart(fig_cex, use_container_width=True)
            _render_md(interpret_cex(cex_sum, dte_v))
        else:
            st.caption("CEX requiere IV% y DTE válidos en la cadena.")

    # ── 5. DELTA ────────────────────────────────────────────────────────────
    with tab_dex:
        _render_md('<p class="bb-header">DELTA EXPOSURE  ·  Sesgo direccional</p>')
        st.caption(
            "DEX = Σ Δ × OI × 100 × S. Call-heavy → soporte implícito. "
            "Put-heavy → resistencia implícita."
        )
        if not dex_df.empty and dex_sum:
            fig_dex = chart_dex_profile(dex_df, spot, dex_sum, symbol, focus_pct=focus_pct)
            if fig_dex:
                st.plotly_chart(fig_dex, use_container_width=True)
            _render_md(interpret_dex(dex_sum))
        else:
            st.caption("DEX requiere Δ y OI válidos en la cadena.")

    # ── 6. HIRO FLOW ────────────────────────────────────────────────────────
    with tab_hiro:
        _render_md(
            '<p class="bb-header">HIRO  ·  Hedging Impact Real-time Oscillator</p>'
        )
        st.caption(
            "Flujo de hedging implícito por volumen × |Δ|. "
            "<b>Cliente compra call</b> → dealer short call → dealer <b>compra spot</b> "
            "(BULLISH). <b>Cliente compra put</b> → dealer short put → dealer <b>vende spot</b> "
            "(BEARISH). HIRO = call_flow − put_flow."
        )
        h1, h2, h3, h4 = st.columns(4)
        h1.metric("HIRO now",
                  f"{hiro_snap.get('hiro', 0):+,.0f}",
                  ("BUY" if hiro_snap.get("hiro", 0) >= 0 else "SELL") + " pressure")
        h2.metric("Call flow", f"{hiro_snap.get('call_flow', 0):,.0f}")
        h3.metric("Put flow", f"{hiro_snap.get('put_flow', 0):,.0f}")
        h4.metric("Z-score", f"{hiro_z:+.2f}" if hiro_z is not None else "—",
                  f"{len(hist)} obs")

        hiro_strike_df = compute_hiro_by_strike(calls_all, puts_all, spot)
        if not hiro_strike_df.empty:
            fig_hs = chart_hiro_strike(hiro_strike_df, spot, symbol)
            if fig_hs:
                st.plotly_chart(fig_hs, use_container_width=True)
        else:
            st.caption("HIRO per-strike: volumen o Δ no disponibles en la cadena.")

        if len(hist) >= 2:
            fig_osc = chart_hiro_oscillator(hist, symbol)
            if fig_osc:
                st.plotly_chart(fig_osc, use_container_width=True)
        else:
            st.caption(
                "🔄 Oscilador HIRO: necesita ≥ 2 snapshots. Se van acumulando "
                "automáticamente al refrescar la cadena. Actívalo con Auto 30s."
            )
        _render_md(interpret_hiro(hiro_snap, hiro_z, len(hist)))

    # ── 7. TERM STRUCTURE ───────────────────────────────────────────────────
    with tab_ts:
        _render_md('<p class="bb-header">TERM STRUCTURE  (IV por vencimiento)</p>')
        st.caption(
            "Curva de volatilidad implícita por DTE. <b>Contango</b> → mercado "
            "espera expansión de vol. <b>Backwardation</b> → riesgo inmediato priced-in."
        )
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
                _render_md("".join(tbl))
            _render_md(interpret_term_structure(ts_df))
        else:
            st.caption("Term Structure no disponible.")

    # ── 8. IV SKEW & SMILE ──────────────────────────────────────────────────
    with tab_smile:
        _render_md('<p class="bb-header">IV SKEW  &  VOLATILITY SMILE</p>')
        st.caption(
            "Curva ámbar = <b>Market smile</b> (OTM puts abajo de spot + OTM calls arriba). "
            "Puntos diamante = ATM IV. <b>RR25</b> = put-wing − call-wing (sesgo a puts si +). "
            "<b>BF25</b> = convexidad."
        )
        exps_avail = st.session_state.get(SS.ALL_EXPS, []) or []
        exp_options = ["(vencimiento seleccionado arriba)"] + [str(e) for e in exps_avail]
        default_idx = 0
        if sel_exp and str(sel_exp) in exps_avail:
            default_idx = exps_avail.index(str(sel_exp)) + 1
        smile_exp_label = st.selectbox(
            "Expiry del smile", options=exp_options, index=default_idx,
            key="smile_exp", label_visibility="collapsed",
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
            if metrics:
                _render_md(interpret_smile(metrics, str(smile_exp)))
        else:
            st.caption("IV Smile: el vencimiento seleccionado no tiene IV válido en calls y puts.")

        # Greeks at selected expiry (moved here — naturally related to IV surface)
        _render_md('<p class="bb-header">GREEKS  (vencimiento seleccionado)</p>')
        st.plotly_chart(chart_greeks(calls, puts, spot), use_container_width=True)

    # ── 9. OPEN INTEREST ────────────────────────────────────────────────────
    with tab_oi:
        _render_md('<p class="bb-header">OPEN INTEREST  &  VOLUME</p>')
        st.caption(
            "OI = contratos abiertos (posicionamiento acumulado). "
            "Volume = contratos tradeados hoy (flujo nuevo)."
        )
        st.plotly_chart(chart_oi_volume(calls, puts, spot, em_lo, em_hi),
                        use_container_width=True)
        _render_md(interpret_oi(calls, puts, spot))

    # ── 10. VOL ANALYTICS ───────────────────────────────────────────────────
    with tab_vol:
        _render_md('<p class="bb-header">VOLATILITY ANALYSIS  ·  HV · IV Rank · Cone</p>')
        if not price_df.empty and analytics_full:
            hv20 = analytics_full.get("hv20"); hv30 = analytics_full.get("hv30")
            hv60 = analytics_full.get("hv60")
            ratio = analytics_full.get("iv_hv_ratio")
            spread = analytics_full.get("iv_hv_spread")
            iv_rank = analytics_full.get("iv_rank")
            regime = analytics_full.get("vol_regime", "—")
            skew = analytics_full.get("skewness"); kurt = analytics_full.get("kurtosis")
            regime_clr = (RED if regime == "IV CARA" else
                          (GREEN if regime == "IV BARATA" else ORANGE))
            hdr = '<div class="kpi-panel">'
            hdr += _kv("Régimen vol", regime, regime_clr)
            hdr += _kv("ATM IV", f"{iv_atm:.1f}%" if iv_atm else "—")
            hdr += _kv("HV20", f"{hv20:.1f}%" if hv20 else "—", sub="20d")
            hdr += _kv("HV30", f"{hv30:.1f}%" if hv30 else "—", sub="30d")
            hdr += _kv("HV60", f"{hv60:.1f}%" if hv60 else "—", sub="60d")
            hdr += _kv("IV / HV30", f"{ratio:.2f}x" if ratio else "—", regime_clr)
            hdr += _kv(
                "IV − HV30",
                (f"+{spread:.1f}%" if (spread is not None and spread >= 0)
                 else (f"{spread:.1f}%" if spread is not None else "—")),
                RED if (spread or 0) > 0 else GREEN,
            )
            hdr += _kv("IV Rank", f"{iv_rank:.0f}" if iv_rank is not None else "—")
            hdr += _kv("Skew", f"{skew:.3f}" if skew is not None else "—",
                       RED if (skew or 0) < -0.5 else "#e0e0f0")
            hdr += _kv("Kurt ex.", f"{kurt:.3f}" if kurt is not None else "—")
            hdr += '</div>'
            _render_md(hdr)
            _render_md(interpret_vol_analytics(analytics_full, iv_atm))

            c_cone, c_hist = st.columns([3, 2])
            with c_cone:
                _render_md('<p class="bb-header" style="margin-top:0">VOLATILITY CONE</p>')
                fig_cone = chart_vol_cone(analytics_full, iv_atm, symbol)
                if fig_cone:
                    st.plotly_chart(fig_cone, use_container_width=True)
            with c_hist:
                _render_md('<p class="bb-header" style="margin-top:0">HV30 vs ATM IV</p>')
                fig_hv = chart_iv_hv_history(analytics_full, iv_atm)
                if fig_hv:
                    st.plotly_chart(fig_hv, use_container_width=True)

            _render_md('<p class="bb-header">DISTRIBUCIÓN DE RETORNOS</p>')
            fig_rd = chart_returns_dist(analytics_full, symbol)
            if fig_rd:
                st.plotly_chart(fig_rd, use_container_width=True)
        else:
            st.caption(
                "Análisis no disponible. " +
                (f"Error: `{price_err}`" if price_err else "")
            )

    # ── 11. CHAIN ───────────────────────────────────────────────────────────
    with tab_chain:
        _render_md('<p class="bb-header">OPTIONS CHAIN  (vencimiento seleccionado)</p>')
        mode = st.radio("Vista", ["both", "calls", "puts"], index=0, horizontal=True,
                        key="chain_mode", label_visibility="collapsed")
        _render_md(build_table(calls, puts, spot, mode))

    # ── REPLAY MODE ─────────────────────────────────────────────────────────
    with tab_replay:
        _render_md('<p class="bb-header">REPLAY  ·  Sesiones guardadas en SQLite local</p>')
        st.caption(
            "Cada tick de Orderflow + HIRO se persiste en `~/.options_terminal/intraday.db`. "
            "Selecciona un día anterior para revivir cómo evolucionaron walls + spot. "
            "Útil para post-mortems y entrenar tu lectura de niveles."
        )

        rep_dates = available_replay_dates(symbol, lookback_days=60)
        if not rep_dates:
            st.info(
                f"Aún no hay datos guardados para **{symbol}**. "
                "Mantén el dashboard abierto durante una sesión y vuelve mañana — "
                "los ticks se acumulan automáticamente.",
                icon="📭",
            )
        else:
            r1, r2, r3 = st.columns([1.5, 1.5, 1])
            with r1:
                today_str = datetime.date.today().isoformat()
                # Pick most recent that ISN'T today (replay = past, not live)
                default_idx = 0
                for i, d in enumerate(rep_dates):
                    if d != today_str:
                        default_idx = i
                        break
                sel_date = st.selectbox(
                    "📅 Día a revivir",
                    options=rep_dates,
                    index=default_idx,
                    format_func=lambda d: f"{d}  ({'HOY' if d == today_str else d})",
                    key=SS.REPLAY_DATE,
                )
            with r2:
                rep_view = st.selectbox(
                    "Vista",
                    ["Orderflow stack", "DEX timeseries", "GEX timeseries",
                     "Convexity (VEX)"],
                    key="replay_view",
                )
            with r3:
                st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
                refresh = st.button("🔄 Recargar", use_container_width=True)
                if refresh:
                    st.rerun()

            of_rep = load_orderflow_history(symbol, date=sel_date, limit=5000)
            hi_rep = load_hiro_history(symbol, date=sel_date, limit=5000)

            if not of_rep:
                st.warning(f"No hay ticks de orderflow guardados para {symbol} en {sel_date}.")
            else:
                first_ts = of_rep[0]["timestamp"]
                last_ts = of_rep[-1]["timestamp"]
                rsum1, rsum2, rsum3, rsum4 = st.columns(4)
                rsum1.metric("Ticks orderflow", f"{len(of_rep):,}")
                rsum2.metric("Ticks HIRO", f"{len(hi_rep):,}")
                rsum3.metric("Inicio (UTC)", first_ts[11:19] if first_ts else "—")
                rsum4.metric("Fin (UTC)", last_ts[11:19] if last_ts else "—")

                if rep_view == "Orderflow stack":
                    fig = chart_orderflow_stack(of_rep, symbol=symbol)
                elif rep_view == "DEX timeseries":
                    fig = chart_dex_timeseries(of_rep, symbol=symbol)
                elif rep_view == "GEX timeseries":
                    fig = chart_gex_timeseries(of_rep, symbol=symbol)
                else:
                    fig = chart_convexity_timeseries(of_rep, symbol=symbol)

                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True,
                                    key=f"replay_{sel_date}_{rep_view}")
                else:
                    st.info("Vista no disponible para esta sesión.")

        # ── Daily snapshots table ──────────────────────────────────────────
        _render_md(
            '<p class="bb-header" style="margin-top:1.5rem">'
            'DAILY SNAPSHOTS  ·  últimos 30 días</p>'
        )
        snaps = load_daily_snapshots(symbol, days=30)
        if not snaps:
            st.info("Sin snapshots diarios todavía.")
        else:
            snap_df = pd.DataFrame(snaps)
            keep_cols = ["date", "spot_close", "regime", "total_gex",
                         "call_wall", "put_wall", "gamma_flip", "hvl",
                         "max_pain", "iv_atm"]
            snap_df = snap_df[[c for c in keep_cols if c in snap_df.columns]]
            # Friendly formatting
            if "total_gex" in snap_df.columns:
                snap_df["total_gex_$B"] = (snap_df["total_gex"] / 1e9).round(2)
                snap_df = snap_df.drop(columns=["total_gex"])
            st.dataframe(snap_df, use_container_width=True, hide_index=True)

        # ── DB stats panel ─────────────────────────────────────────────────
        _render_md(
            '<p class="bb-header" style="margin-top:1.5rem">'
            'STORAGE  ·  estadísticas del DB local</p>'
        )
        stats = db_stats()
        if stats:
            s1, s2, s3, s4, s5 = st.columns(5)
            s1.metric("Orderflow rows", f"{stats.get('orderflow_rows', 0):,}")
            s2.metric("HIRO rows", f"{stats.get('hiro_rows', 0):,}")
            s3.metric("Daily rows", f"{stats.get('daily_rows', 0):,}")
            s4.metric("Símbolos", stats.get("symbols", 0))
            s5.metric("Tamaño", f"{stats.get('size_mb', 0):.2f} MB")
            st.caption(f"📂 `{stats.get('path', '')}`")

    # ── FOOTER ──────────────────────────────────────────────────────────────
    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)
    st.markdown(
        f'<p class="footer">OPTIONS TERMINAL  ·  {symbol}  ·  '
        f'{last_refresh.strftime("%Y-%m-%d %H:%M:%S")} UTC'
        f'  ·  Charles Schwab API  ·  Datos en tiempo real'
        f'  ·  No constituye asesoramiento financiero</p>',
        unsafe_allow_html=True,
    )

    # ── AUTO-REFRESH FOOTER  ────────────────────────────────────────────────
    # All the refresh logic is handled at the top of the function (right
    # after the chain symbol is resolved) so the pop+fetch+render happens
    # in a single rerun. We just print a status caption here.
    if auto_refresh:
        st.caption("🔄 Auto-refresh activo cada 30s · sin parpadeo.")


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
    # Password gate (Streamlit Secrets-driven, editable sin redeploy)
    st.markdown(CSS, unsafe_allow_html=True)
    if not require_login():
        return
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
