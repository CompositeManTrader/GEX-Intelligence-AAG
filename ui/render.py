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
    chart_gex_curve, chart_gex_profile, chart_vex_profile,
)
from charts.intraday import chart_session_profile, render_intraday_chart
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
    load_recent_hiro, load_recent_orderflow,
    persist_daily_snapshot, persist_hiro_tick, persist_orderflow_tick,
)
from quant.exposures import (
    compute_cex_profile, compute_dex_profile, compute_gex_by_expiry,
    compute_gex_profile, compute_vex_profile, gex_curve_over_spot,
)
from quant.flow import (
    compute_hiro_by_strike, compute_hiro_snapshot, hiro_zscore,
    tick_hiro, update_hiro_history,
)
from quant.orderflow import tick_orderflow, update_orderflow_history
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
    flip_zone_widget, levels_strip, market_header, position_sizer,
    trade_setup_card, trading_hero,
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
    # Command bar: brand mark · symbol · (spacer) · auto · trading · exit · user.
    # Expiry + strike-count moved into the "Parámetros" panel below to declutter.
    b_brand, b_sym, b_spc, b5, b8, b6, b7 = st.columns(
        [1.8, 2.3, 2.4, 1.0, 1.1, 0.7, 0.8]
    )
    with b_brand:
        st.markdown(
            '<div class="brand">'
            '<div class="brand-line"><span class="brand-prompt">❯</span>'
            '<span class="brand-word">GEX</span>'
            '<span class="brand-cursor"></span></div>'
            '<div class="brand-tag">INTELLIGENCE TERMINAL</div></div>',
            unsafe_allow_html=True,
        )
    with b_sym:
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

    # ── PARÁMETROS ──────────────────────────────────────────────────────────
    # The actual widgets live in the "⚙ Ajustes" tab (rendered later). Their
    # values are read HERE from session_state so the chain load + exposures
    # downstream see them. Streamlit updates session_state the moment a widget
    # changes and reruns top-to-bottom, so there is no one-cycle lag.
    st.session_state.setdefault("p_strikes", 30)
    st.session_state.setdefault("p_max_dte", 60)
    st.session_state.setdefault("p_min_oi", 0)
    st.session_state.setdefault("p_focus", 8)
    strike_count = int(st.session_state["p_strikes"])
    max_dte = int(st.session_state["p_max_dte"])
    min_oi = int(st.session_state["p_min_oi"])
    focus_pct = float(st.session_state["p_focus"]) / 100.0

    # ── AUTO-REFRESH HANDLER (must run BEFORE chain load) ──────────────────
    # Wiring the pop here means the in-flight rerun (started by
    # st_autorefresh) immediately re-fetches the chain and re-renders.
    # That avoids the double-rerun cycle (= visible flicker) the previous
    # version had, AND keeps the data current within the same 30s window.
    if auto_refresh:
        try:
            from streamlit_autorefresh import st_autorefresh
            # Adaptive cadence: the orderflow tab computes a session-vol
            # score and writes the recommended interval into session state.
            # Default 30s if not yet computed (first render / orderflow tab
            # not yet visited). Clamp to [15s, 60s] for safety.
            adapt_secs = int(st.session_state.get("_of_adaptive_secs", 30))
            adapt_secs = max(15, min(60, adapt_secs))
            _ar_count = st_autorefresh(interval=adapt_secs * 1000,
                                       key="chain_autorefresh")
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

    # Invalidate SEL_EXP when the previously-selected expiry no longer
    # exists in the current chain. Without this, after a weekly expires
    # the selectbox holds a stale value, `by_expiry` returns empty, and
    # every per-expiry panel silently blanks even though the chain is
    # full of valid contracts.
    _all_exps_now = st.session_state.get(SS.ALL_EXPS) or []
    _prev_sel = st.session_state.get(SS.SEL_EXP)
    if _prev_sel is not None and _all_exps_now and _prev_sel not in _all_exps_now:
        st.session_state.pop(SS.SEL_EXP, None)

    sel_exp = st.session_state.get(SS.SEL_EXP,
                                   (_all_exps_now or [""])[0])
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
    # Parse DTE explicitly (pd.to_numeric → mode/min) instead of the
    # legacy `int(float(str(...).split(".")[0]))` chain wrapped in a
    # bare except. Non-numeric DTE was silently swallowed to 0, then
    # downstream narratives ("DTE 0d" → "charm acelera") fired wrongly.
    dte_v = 0
    if not calls.empty and "DTE" in calls.columns:
        dte_clean = pd.to_numeric(calls["DTE"], errors="coerce").dropna()
        if not dte_clean.empty:
            # Use the modal DTE inside the selected expiry (defensive
            # against per-row noise in Schwab payload).
            try:
                dte_v = int(dte_clean.mode().iloc[0])
            except Exception:
                dte_v = int(dte_clean.iloc[0])

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

    # ── MARKET HEADER (terminal-style strip) ────────────────────────────────
    # Replaces the legacy 8× st.metric row + EM caption with one cohesive
    # panel. Pure presentation — same values, no model change. Shown FIRST so
    # it owns the prime real estate; diagnostics demoted below it.
    _mh_status, _ = market_status_et()
    _render_md(market_header(
        symbol=symbol, spot=spot, chg=chg, chg_p=chg_p,
        bid=bid_u, ask=ask_u, vol=vol_u,
        iv_atm=iv_atm, p_c=p_c, mp=mp, net_gex_bn=total_gex_bn,
        em_lo=em_lo, em_hi=em_hi,
        updated=last_refresh.strftime("%H:%M:%S"),
        market_status=_mh_status,
    ))

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
    # 0DTE-only GEX (régimen intradía) — calculado a nivel de función para que
    # el Overview pueda comparar el régimen agregado vs el de hoy y dejar elegir
    # el alcance del decision panel. Vacío si el símbolo no tiene 0DTE.
    _gex_df_0dte, gex_sum_0dte = compute_gex_profile(
        calls_all, puts_all, spot, symbol=symbol,
        max_dte=0, min_dte=0, min_oi=min_oi,
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

    # ── Gamma zones (P1/P2/P3) — top-K clusters with width + score ──────────
    # Computed once from the aggregate GEX profile and threaded into every
    # chart/widget that wants them (overview panel, profile chart bands,
    # intraday hrects, persistence). Direction-agnostic ranking by
    # integrated |GEX| — see quant.zones for the algorithm.
    from quant.zones import find_gamma_zones, zones_to_records
    gamma_zones = find_gamma_zones(gex_df, spot=spot, top_n=3)

    # ── ORDERFLOW: rolling history + per-DTE buckets + per-strike heatmap ──
    # Per-DTE-bucket exposures: 0DTE/week/month. Computed once, reused for
    # both the tick payload (aggregate persistence) and the per-strike
    # heatmap persistence.
    from quant.orderflow_buckets import (
        compute_dex_buckets, compute_gex_buckets, compute_vex_buckets,
        flatten_to_tick,
    )
    from quant.orderflow import should_persist_tick
    from data.persistence import (
        latest_two_strike_snapshots, persist_strike_tick,
    )
    gex_buckets = compute_gex_buckets(calls_all, puts_all, spot,
                                      symbol=symbol, min_oi=min_oi)
    dex_buckets = compute_dex_buckets(calls_all, puts_all, spot,
                                      min_oi=min_oi)
    vex_buckets = compute_vex_buckets(calls_all, puts_all, spot,
                                      symbol=symbol, min_oi=min_oi)
    bucket_flat = flatten_to_tick(gex_buckets, dex_buckets, vex_buckets)
    of_tick = tick_orderflow(spot, gex_sum, dex_sum, vex_sum,
                             bucket_fields=bucket_flat, cex_sum=cex_sum)
    of_hist = st.session_state.get(SS.ORDERFLOW_HISTORY, [])
    if not of_hist:
        of_hist = load_recent_orderflow(symbol, hours=8, limit=1000)
    of_hist = update_orderflow_history(of_hist, of_tick, max_len=1000)
    st.session_state[SS.ORDERFLOW_HISTORY] = of_hist

    # Delta-based persistence — only write to SQLite if something *moved*
    # vs the last persisted tick. Reduces row volume 3-5× during quiet
    # markets without losing chart-relevant transitions.
    last_persisted = st.session_state.get("_last_persisted_of_tick")
    if should_persist_tick(last_persisted, of_tick):
        persist_orderflow_tick(symbol, of_tick)
        # Per-strike snapshot for the month bucket (most general — keeps
        # the heatmap useful for swing traders). 0DTE is so noisy and
        # volume-heavy that storing it every tick blows up the table; we
        # only persist 0DTE strikes when within the last 60 min of session.
        for bname, (gdf, _gsum) in gex_buckets.items():
            if bname == "month" and gdf is not None and not gdf.empty:
                persist_strike_tick(
                    symbol, of_tick["timestamp"], bname, gdf,
                    dex_df=dex_buckets.get(bname, (None, {}))[0],
                    vex_df=vex_buckets.get(bname, (None, {}))[0],
                )
        # Persist gamma zones snapshot — top-N P1/P2/P3 ranges with score.
        if gamma_zones:
            from data.persistence import persist_zones_tick
            persist_zones_tick(symbol, of_tick["timestamp"],
                               zones_to_records(gamma_zones))
        st.session_state["_last_persisted_of_tick"] = of_tick
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
            if gf_now and spot and spot > 0:
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
    #  Shared RND (the crown-jewel model) — memoised per render so the Overview
    #  mini-panel and the Expected Range tab never recompute the same horizon.
    #  Streamlit executes every tab body each run, so this is the single source.
    # ─────────────────────────────────────────────────────────────────────────
    from quant.rnd import build_rnd as _build_rnd, rnd_levels as _rnd_levels
    from quant.bs import rate_for_dte as _rate_for_dte
    from config import dividend_yield_for as _div_yield_for
    _rnd_memo: dict = {}

    def _get_rnd(dte: int):
        dte = int(dte)
        if dte not in _rnd_memo:
            try:
                _r = float(np.atleast_1d(_rate_for_dte(dte))[0])
            except Exception:
                _r = 0.045
            try:
                _df, _meta = _build_rnd(calls, puts, spot=spot, dte=dte,
                                        r=_r, q=_div_yield_for(symbol))
            except Exception as _exc:
                log.warning("build_rnd(dte=%s) failed: %s", dte, _exc)
                _df, _meta = None, {}
            _lv = {}
            if _df is not None and not _df.empty:
                _lv = _rnd_levels(_df, spot=spot, levels={
                    "call_wall": (gex_sum or {}).get("call_wall"),
                    "put_wall": (gex_sum or {}).get("put_wall"),
                    "hvl": (gex_sum or {}).get("hvl"),
                    "gamma_flip": (gex_sum or {}).get("gamma_flip"),
                })
            _rnd_memo[dte] = (_df, _meta, _lv)
        return _rnd_memo[dte]

    # ─────────────────────────────────────────────────────────────────────────
    #  TABS  (named for readability — order here controls UI order)
    # ─────────────────────────────────────────────────────────────────────────
    TAB_LABELS = [
        "🎯 Overview",
        "🔥 GEX 0DTE",
        "🗺️ Niveles",
        "📊 GEX Total",
        "🌀 Orderflow",
        "📐 Expected Range",
        "💎 Vanna (VEX)",
        "⏳ Charm (CEX)",
        "📈 Delta (DEX)",
        "🌊 HIRO Flow",
        "📐 Term Structure",
        "📉 IV Skew & Smile",
        "💰 Open Interest",
        "📊 Vol Analytics",
        "📋 Chain",
        "⚙ Ajustes",
    ]
    tabs = st.tabs(TAB_LABELS)
    (tab_overview, tab_0dte, tab_levels, tab_gex, tab_orderflow,
     tab_erange, tab_vex, tab_cex, tab_dex, tab_hiro, tab_ts, tab_smile,
     tab_oi, tab_vol, tab_chain, tab_settings) = tabs

    # ── 🗺️ NIVELES — price & GEX levels map + key-levels panel ──────────────
    with tab_levels:
        _render_md('<p class="bb-header">PRICE &amp; GEX LEVELS  ·  '
                   'mapa de niveles por alcance DTE</p>')

        # DTE-scope selector — two scopes: 0DTE vs everything else.
        SCOPE_OPTS = ["0DTE", "Resto"]
        scope = st.radio(
            "Alcance DTE",
            options=SCOPE_OPTS,
            format_func=lambda s: {
                "0DTE": "0DTE (vence hoy)",
                "Resto": f"Resto de expiraciones (1–{max_dte}d)",
            }[s],
            horizontal=True, index=0, key="levels_scope",
            help="0DTE = solo la gamma que vence hoy (la que mueve el pinning "
                 "intradía). Resto = todas las demás expiraciones agregadas "
                 "(muros estructurales del libro, excluyendo 0DTE).",
        )
        st.caption(
            "Líneas horizontales = niveles de gamma dealer (call/put wall · "
            "gamma flip · HVL · clusters P1/P2/P3) del alcance elegido. Línea "
            "cyan = precio intradía. Banda azul = rango actual. Verde = "
            "resistencia · rojo = soporte · naranja = flip · morado = pin. "
            "<b>Niveles de flujo</b> (punteado): <b>VT-C/VT-P</b> = strike de "
            "mayor <b>volumen</b> call/put de HOY (no OI) · <b>Call Bridge</b> = "
            "strike de mayor OI total (liquidez). El panel muestra la "
            "dominancia de volumen calls vs puts.",
            unsafe_allow_html=True,
        )

        from charts.levels_map import chart_price_levels
        from ui.widgets import key_levels_panel
        from quant.zones import find_gamma_zones as _find_zones

        # Resolve (summary, zones) for the chosen DTE scope.
        # Both scopes compute fresh with the SPOT-GRID gamma flip (the true
        # zero-gamma level). The cached 0DTE bucket uses the crude
        # cumulative-crossing method, which — verified empirically — diverges
        # from the spot-grid and can even fail (None) or fly far from spot for
        # near-zero-net 0DTE books. The map must show the real zero-gamma.
        if scope == "0DTE":
            _lo, _hi = 0, 0
        else:
            _lo, _hi = 1, max_dte          # "Resto" = all but today's expiry
        _bdf, _bsum = compute_gex_profile(
            calls_all, puts_all, spot, symbol=symbol,
            max_dte=_hi, min_dte=_lo, min_oi=min_oi,
            use_spot_grid_flip=True,
        )
        lvl_sum = _bsum or {}
        lvl_zones = (_find_zones(_bdf, spot=spot, top_n=3)
                     if _bdf is not None and not _bdf.empty else [])

        try:
            lvl_df, _lvl_err = fetch_intraday(
                symbol, freq_min=5, days=1,
                cache_bust=int(time.time() // 30),
            )
        except Exception as _exc:
            log.warning("levels map intraday fetch failed: %s", _exc)
            lvl_df = pd.DataFrame()

        lc_chart, lc_panel = st.columns([2.7, 1.0])
        with lc_chart:
            try:
                fig_lvl = chart_price_levels(
                    spot, lvl_sum, zones=lvl_zones, intra_df=lvl_df,
                    symbol=symbol,
                )
            except Exception as _exc:
                log.exception("chart_price_levels crashed")
                fig_lvl = None
            if fig_lvl is not None:
                st.plotly_chart(fig_lvl, use_container_width=True,
                                key=f"levels_map_{symbol}_{scope}")
            else:
                st.info(
                    f"Sin niveles GEX en el alcance **{scope}** "
                    f"(¿no hay contratos en ese rango de DTE hoy?)."
                )
        with lc_panel:
            _render_md(key_levels_panel(spot, lvl_sum, lvl_zones))

    # ── ⚙ AJUSTES — parámetros + diagnóstico (movidos fuera del header) ─────
    with tab_settings:
        _render_md('<p class="bb-header">PARÁMETROS  ·  expiración · strikes · '
                   'calibración GEX</p>')
        st.caption(
            "Estos controles alimentan el modelo: la <b>expiración</b> filtra "
            "Chain · Greeks · Open Interest · Max Pain · Expected Range; "
            "<b>Max DTE / Min OI</b> calibran las exposiciones GEX/VEX/CEX/DEX.",
            unsafe_allow_html=True,
        )
        sa, sb = st.columns([1.6, 1.0])
        with sa:
            all_exps = st.session_state.get(SS.ALL_EXPS, ["—"])
            st.selectbox(
                "Expiración",
                options=all_exps, key=SS.SEL_EXP,
            )
        with sb:
            st.selectbox(
                "Strikes a cargar",
                options=[10, 15, 20, 25, 30, 40, 50, 60], key="p_strikes",
            )
        sf1, sf2, sf3 = st.columns(3)
        with sf1:
            st.slider(
                "Max DTE (exposures)", 7, 365, step=1, key="p_max_dte",
                help="Filtra opciones con DTE > este valor. 45-60d = estándar gexbot.",
            )
        with sf2:
            st.slider(
                "Min OI por strike", 0, 1000, step=50, key="p_min_oi",
                help="Filtra strikes ilíquidos. 100+ para SPY/QQQ, 0 para small-caps.",
            )
        with sf3:
            st.slider(
                "Focus ± % del spot", 3, 25, step=1, format="±%d%%", key="p_focus",
                help="Rango de strikes en los charts. 8-10% estándar para índices.",
            )
        if fut_spec is not None:
            prev = st.session_state.get(SS.PREFER_INDEX, FUTURES_PREFER_INDEX)
            new = st.toggle(
                f"📊 Usar cadena del índice ({fut_spec.underlying}) en vez del ETF "
                f"({fut_spec.etf_proxy})",
                value=prev, key="prefer_index_toggle",
                help="Activa si tu cuenta Schwab tiene acceso a opciones de índice. "
                     "ETF proxy es más confiable; índice cash refleja mejor el GEX dealer.",
            )
            if new != prev:
                st.session_state[SS.PREFER_INDEX] = new
                st.session_state.pop(SS.CHAIN_DATA, None)
                st.rerun()

        st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)
        _render_md('<p class="bb-header">DIAGNÓSTICO  ·  estado del pipeline</p>')
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

        # ── VALIDACIÓN DE GAMMA — ¿con qué T calcula Schwab su gamma 0DTE? ──
        # El perfil GEX usa la gamma REPORTADA por Schwab. Aquí comparamos, en
        # los strikes near-ATM del menor DTE disponible, la gamma de Schwab vs
        # bs.gamma con la T intradía real vs con T=1 día. Si Schwab floorea la
        # T, su gamma ≈ la de 1 día → el GEX 0DTE estaría subvaluado.
        with st.expander("🔬 Validación de gamma · Schwab vs recalculada (0DTE)"):
            import numpy as _np
            from quant import bs as _bs
            from quant.gamma_audit import implied_T_from_gamma

            def _smallest_dte_atm(df):
                if df is None or df.empty or "DTE" not in df.columns:
                    return None, None
                d = pd.to_numeric(df["DTE"], errors="coerce")
                dmin = int(d.min()) if d.notna().any() else None
                if dmin is None:
                    return None, None
                sub = df[d == dmin].copy()
                sub["_m"] = (pd.to_numeric(sub["Strike"], errors="coerce")
                             - spot).abs()
                return dmin, sub.nsmallest(6, "_m")

            dmin_c, near_c = _smallest_dte_atm(calls_all)
            now_et = datetime.datetime.now(ET_TZ)
            T_intra = float(_np.atleast_1d(bs.time_to_expiry_years(0))[0])
            secs_close = T_intra * 86400.0 * 365.0
            T_1day = 1.0 / 365.0
            st.caption(
                f"Hora ET: **{now_et:%H:%M:%S}** · menor DTE disponible: "
                f"**{dmin_c}** · T intradía del modelo = **{T_intra:.2e} años** "
                f"(~{secs_close/3600:.2f} h al cierre) · T 1-día = {T_1day:.2e}."
            )
            if near_c is None or near_c.empty:
                st.info("Sin cadena de calls para auditar.")
            else:
                _q = dividend_yield_for(symbol)
                rows = []
                ratios_intra, ratios_1d = [], []
                for _, rr in near_c.iterrows():
                    K = float(rr["Strike"]); g_sch = float(rr.get("Gamma") or 0)
                    iv = float(rr.get("IV%") or 0) / 100.0
                    if iv <= 0 or g_sch <= 0:
                        continue
                    r_ = float(_np.atleast_1d(bs.rate_for_dte(dmin_c))[0])
                    g_intra = float(bs.gamma(spot, K, T_intra, iv, r_, _q))
                    g_1d = float(bs.gamma(spot, K, T_1day, iv, r_, _q))
                    ti = implied_T_from_gamma(g_sch, spot, K, iv, r_, _q)
                    if g_intra > 0:
                        ratios_intra.append(g_sch / g_intra)
                    if g_1d > 0:
                        ratios_1d.append(g_sch / g_1d)
                    rows.append({
                        "Strike": K, "IV%": rr.get("IV%"),
                        "γ Schwab": round(g_sch, 5),
                        "γ bs(T intradía)": round(g_intra, 5),
                        "γ bs(T 1día)": round(g_1d, 5),
                        "T implícita (días)": (round(ti * 365, 3)
                                               if ti else None),
                    })
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True,
                                 hide_index=True)
                    med_i = float(_np.median(ratios_intra)) if ratios_intra else None
                    med_d = float(_np.median(ratios_1d)) if ratios_1d else None
                    msg = (f"Mediana γSchwab/γ(T intradía) = "
                           f"**{med_i:.2f}** · γSchwab/γ(T 1día) = "
                           f"**{med_d:.2f}**.")
                    if med_i is not None and abs(med_i - 1) < 0.25:
                        verdict = ("✅ Schwab usa una T ≈ intradía → la magnitud "
                                   "del GEX 0DTE es razonable (solo conviene "
                                   "recalcular por consistencia).")
                    elif med_d is not None and abs(med_d - 1) < 0.30:
                        verdict = ("🔴 Schwab usa ≈ T de 1 día (floor) → el GEX "
                                   "0DTE está SUBVALUADO ~"
                                   f"{(1/med_i if med_i else 0):.1f}× intradía. "
                                   "Hay que recalcular la gamma.")
                    else:
                        verdict = ("⚠ Convención de Schwab no concluyente — "
                                   "revisar la tabla manualmente.")
                    st.markdown(msg + "  \n" + verdict)
                else:
                    st.info("Sin strikes con IV/gamma válidas para comparar.")

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

        # 1b. IMPLIED DISTRIBUTION (RND) — the crown-jewel model, compact.
        # New info on Overview (full implied distribution + skew), not a
        # repeat of the header's simple 1σ EM bar. Shares the memoised compute.
        from ui.widgets import rnd_mini_panel
        _rnd_ov, _rnd_ov_meta, _rnd_ov_lv = _get_rnd(0)
        _mini = rnd_mini_panel(_rnd_ov, _rnd_ov_lv, _rnd_ov_meta, spot)
        if _mini:
            _render_md(_mini)

        # 2. GEX FLIP ZONE — thermometer tactico
        _render_md(flip_zone_widget(spot, gex_sum))

        # 3. GAMMA ZONES — P1/P2/P3 ranked clusters with width + score
        from ui.widgets import panel_zones_html
        _render_md(panel_zones_html(gamma_zones, spot=spot))

        # 4. DECISION PANEL — con selector de alcance (agregado vs 0DTE) y
        #    comparación de régimen lado a lado (alerta si divergen).
        from ui.widgets import regime_compare_panel
        _render_md(regime_compare_panel(gex_sum, gex_sum_0dte))
        dp_scope = st.radio(
            "Alcance del decision panel",
            options=["Agregado", "0DTE"],
            format_func=lambda s: ("Agregado (0–60d · estructural)"
                                   if s == "Agregado" else "0DTE (hoy · intradía)"),
            horizontal=True, index=0, key="dp_scope",
            help="Agregado = régimen estructural de todo el libro. 0DTE = el "
                 "régimen que gobierna la sesión (pesa más hacia el cierre).",
        )
        _dp_gex = (gex_sum_0dte if (dp_scope == "0DTE" and gex_sum_0dte)
                   else gex_sum)
        _scope_lbl = ("0DTE · hoy" if (dp_scope == "0DTE" and gex_sum_0dte)
                      else "Agregado · 0–60d")
        if dp_scope == "0DTE" and not gex_sum_0dte:
            st.caption("⚠ Sin 0DTE para este símbolo — mostrando el agregado.")
        _render_md('<p class="bb-header">DECISION PANEL  ·  Flow-weighted thesis '
                   f'<span style="color:#6c6c90;font-size:0.7rem">· {_scope_lbl}</span></p>')
        panel = build_decision_panel(spot, _dp_gex, vex_sum, cex_sum, dex_sum,
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

        # NOTE (live-audit): the GEX narrative bar was removed from Overview —
        # it repeated, word for word, what the decision panel right above it
        # already says (regime + walls + flip + HVL). It still renders in its
        # own tab (GEX Total), where it isn't redundant. The HIRO bar stays:
        # its z-score and call/put volume counts appear nowhere else here.
        _render_md(interpret_hiro(hiro_snap, hiro_z, len(hist)))

    # ── 1. GEX TOTAL ────────────────────────────────────────────────────────
    with tab_gex:
        _render_md('<p class="bb-header">GEX PROFILE  ·  Gamma Exposure por Strike</p>')
        st.caption(
            "Calls → derecha (verde), Puts → izquierda (rojo), Net GEX → puntos "
            "azules. Walls: Call (verde dashed), Put (rojo dashed), Spot (blanco "
            "sólido), Zero Γ (morado dotted). Bandas semitransparentes = zonas "
            "gamma P1/P2/P3 (verde call-dominant · rojo put-dominant · ámbar mixed)."
        )

        # ── View + zoom controls ───────────────────────────────────────────
        # Defensive widget-state pattern: read the last-known value from
        # session_state and pass it as the explicit `index=` so the
        # selection survives every rerun.
        VIEW_OPTS = ["all", "net", "call", "put"]
        ZOOM_OPTS = ["tight", "near", "mid", "wide", "all"]

        prev_view = st.session_state.get("gex_view_mode", "all")
        prev_zoom = st.session_state.get("gex_zoom_mode", "mid")
        if prev_view not in VIEW_OPTS:
            prev_view = "all"
        if prev_zoom not in ZOOM_OPTS:
            prev_zoom = "mid"

        cgx1, cgx2 = st.columns([1.5, 2.0])
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
            fig_gex = chart_gex_profile(
                gex_df, spot, gex_sum, symbol,
                focus_pct=gex_pct, view=gex_view,
                zones=gamma_zones,
            )
            if fig_gex:
                # Stable component key: tied ONLY to the symbol. Changing
                # view/zoom no longer remounts (Plotly diffs the trace list).
                st.plotly_chart(
                    fig_gex, use_container_width=True,
                    key=f"gex_chart_{symbol}",
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

    # ── ORDERFLOW (PRO multi-panel) ──────────────────────────────────────────
    with tab_orderflow:
        # Session-first redesign: the tab is built on the CONTINUOUS
        # snapshot history (GitHub-Actions recorder → Neon, every ~10 min
        # of market hours), so it shows a full session even if the app was
        # never open — the old session-only view was empty most of the time
        # (Streamlit Cloud's disk is ephemeral and ticks only accrued while
        # watching). Live ticks are appended on top for minute-level detail.
        from charts.of_session import (
            chart_session_trajectory, chart_strike_flow, chart_walls_timeline,
        )
        from quant.orderflow_derived import (
            adaptive_refresh_seconds, session_changes, session_vol_score,
            strike_activity,
        )
        from ui.widgets import of_session_digest_panel
        from data import of_store

        _render_md('<p class="bb-header">'
                   'ORDERFLOW  ·  SESIÓN CONTINUA</p>')
        st.caption(
            "Historia grabada por el <b>recorder headless</b> cada ~10 min "
            "de mercado (GitHub Actions → Neon) — ya no depende de tener la "
            "app abierta. Responde 4 preguntas: ¿qué cambió desde que no "
            "miro? · ¿el régimen está girando? · ¿los muros se mueven? · "
            "¿dónde pega el flujo ahora?",
            unsafe_allow_html=True,
        )

        # ── Continuous history + live session ticks (newer than last snap) ──
        try:
            cont_ticks = of_store.load_ticks(symbol, hours=9)
        except Exception as _exc:
            log.warning("of_store.load_ticks failed: %s", _exc)
            cont_ticks = []
        last_cont_ts = cont_ticks[-1]["ts"] if cont_ticks else ""
        live_new = [t for t in (of_hist or [])
                    if str(t.get("timestamp", "")) > str(last_cont_ts)]
        combined = (cont_ticks or []) + live_new

        _backend = of_store.backend_info()
        if cont_ticks:
            st.caption(
                f"📡 {len(cont_ticks)} snapshots del recorder "
                f"({_backend['backend']}) + {len(live_new)} ticks en vivo."
            )
        else:
            st.caption(
                f"📡 Sin snapshots del recorder todavía "
                f"({_backend['backend']}). El workflow «Orderflow Recorder» "
                f"graba cada ~10 min de mercado; mientras tanto se usa la "
                f"sesión en vivo ({len(of_hist)} ticks)."
            )

        # Adaptive-refresh plumbing (consumed by the global Auto toggle).
        vol_score = session_vol_score(of_hist, intraday_df=None)
        st.session_state["_of_adaptive_secs"] = adaptive_refresh_seconds(vol_score)

        # 1 ── ¿Qué cambió en la sesión?
        _render_md(of_session_digest_panel(session_changes(combined)))

        # 2 ── ¿El régimen está girando?
        fig_traj = chart_session_trajectory(combined, symbol)
        if fig_traj is not None:
            st.plotly_chart(fig_traj, use_container_width=True,
                            key=f"of_traj_{symbol}")

        # 3 ── ¿Los muros se están moviendo?
        fig_walls = chart_walls_timeline(combined, symbol)
        if fig_walls is not None:
            st.plotly_chart(fig_walls, use_container_width=True,
                            key=f"of_walls_{symbol}")

        # 4 ── ¿Dónde pega el flujo AHORA? (0DTE · Δvolumen por strike)
        try:
            srows = of_store.load_strikes(symbol, hours=9)
        except Exception as _exc:
            log.warning("of_store.load_strikes failed: %s", _exc)
            srows = []
        act = strike_activity(srows, window_minutes=30)
        fig_flow = chart_strike_flow(act, symbol, spot=spot)
        if fig_flow is not None:
            st.plotly_chart(fig_flow, use_container_width=True,
                            key=f"of_flow_{symbol}")
            st.caption(
                "Δvolumen = contratos operados por strike en la ventana (el "
                "volumen del chain es acumulado del día). Nota honesta: la "
                "OI solo se actualiza overnight (regla OCC), así que el "
                "volumen ES el proxy de flujo intradía — no existe ΔOI en vivo."
            )
        if not combined and not srows:
            st.info(
                "Aún no hay datos. El recorder se activa en la próxima "
                "ventana de mercado; o activa **Auto 30s** arriba para "
                "acumular ticks en vivo ahora."
            )

        # ── Vista avanzada — los charts anteriores, sin duplicar lo de
        # arriba. (El radio pro/legacy se eliminó: las variantes legacy
        # eran redundantes con la composición PRO.)
        with st.expander("📊 Vista avanzada — composición call/put · "
                         "hedge flow · heatmap"):
            from charts.orderflow_pro import (
                chart_cum_hedge_flow, chart_orderflow_pro_stack,
                chart_strike_heatmap, panel_wall_stability_html,
            )
            from data.persistence import load_strike_history
            if of_hist:
                _render_md(panel_wall_stability_html(of_hist))
                _render_md(interpret_orderflow_summary(of_hist, spot))
                fig_pro = chart_orderflow_pro_stack(of_hist, symbol)
                if fig_pro is not None:
                    st.plotly_chart(fig_pro, use_container_width=True,
                                    key=f"of_pro_{symbol}")
                fig_cum = chart_cum_hedge_flow(of_hist, symbol)
                if fig_cum is not None:
                    st.plotly_chart(fig_cum, use_container_width=True,
                                    key=f"of_cum_{symbol}")
                strikes_long = load_strike_history(symbol, bucket="month")
                fig_hm = chart_strike_heatmap(
                    strikes_long, symbol=symbol,
                    metric="gex_mm", spot_history=of_hist, bucket="month",
                )
                if fig_hm is not None:
                    st.plotly_chart(fig_hm, use_container_width=True,
                                    key=f"of_heatmap_{symbol}")
                _render_md(interpret_orderflow_dex(of_hist))
                _render_md(interpret_orderflow_gex(of_hist, spot))
                _render_md(interpret_orderflow_convexity(of_hist))
            else:
                st.caption(
                    "🔄 Sesión en vivo vacía — estos charts usan los ticks "
                    "en vivo. Activa <b>Auto 30s</b> arriba.",
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

        if zdte_c.empty and zdte_p.empty:
            st.caption(
                "No hay strikes con DTE = 0 en la cadena. "
                "Este módulo solo aplica a símbolos con expiraciones diarias "
                "(SPY/QQQ/SPX). En SPX el filtro se activa solo de lunes a viernes."
            )
        else:
            # ── Compute the four 0DTE exposure profiles. min_oi=0 because
            # 0DTE volume often dwarfs OI; spot-grid flip ON for accuracy
            # on this single-bucket slice.
            zdte_df, zdte_sum = compute_gex_profile(
                zdte_c, zdte_p, spot, symbol=symbol,
                max_dte=0, min_oi=0, use_spot_grid_flip=True,
            )
            zdte_vex_df, zdte_vex_sum = compute_vex_profile(
                zdte_c, zdte_p, spot, symbol=symbol, max_dte=0, min_oi=0,
            )
            zdte_cex_df, zdte_cex_sum = compute_cex_profile(
                zdte_c, zdte_p, spot, symbol=symbol, max_dte=0, min_oi=0,
            )
            zdte_dex_df, zdte_dex_sum = compute_dex_profile(
                zdte_c, zdte_p, spot, max_dte=0, min_oi=0,
            )

            if not zdte_df.empty and zdte_sum:
                # 0DTE-specific gamma zones (P1/P2/P3) — independent from
                # the aggregate `gamma_zones` already computed for the
                # multi-DTE profile. 0DTE clusters often diverge from the
                # structural ones, which is the actionable insight.
                from quant.zones import find_gamma_zones, spot_in_zone
                from ui.widgets import panel_zones_html
                zdte_zones = find_gamma_zones(zdte_df, spot=spot, top_n=3)

                # ── EOD risk badge — minutes to 16:00 ET. In 0DTE the
                # charm and gamma dynamics accelerate geometrically in
                # the last 30-60 minutes, so a visible countdown matters.
                now_et = datetime.datetime.now(ET_TZ)
                close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
                minutes_to_close = max(0.0, (close_et - now_et).total_seconds() / 60.0)
                if now_et.time() >= datetime.time(16, 0):
                    risk_color, risk_label = "#7070a0", "MARKET CLOSED"
                elif minutes_to_close <= 30:
                    risk_color, risk_label = "#f43f5e", "EOD RISK · CHARM ACCELERATION"
                elif minutes_to_close <= 90:
                    risk_color, risk_label = "#f59e0b", "POWER HOUR"
                else:
                    risk_color, risk_label = "#22c55e", "REGULAR SESSION"
                eod_html = (
                    f'<div style="background:rgba(15,17,24,0.85);'
                    f'border:1px solid #1e2230;border-left:4px solid {risk_color};'
                    f'border-radius:0 4px 4px 0;padding:0.5rem 0.9rem;'
                    f'margin:0.4rem 0 0.6rem;font-family:JetBrains Mono,monospace;'
                    f'display:flex;justify-content:space-between;align-items:center">'
                    f'<div><div style="color:#6b7280;font-size:0.62rem;'
                    f'letter-spacing:0.14em">⏱ TIME TO CLOSE</div>'
                    f'<div style="color:{risk_color};font-size:1.1rem;'
                    f'font-weight:700">{int(minutes_to_close)} min</div></div>'
                    f'<div style="color:{risk_color};font-size:0.82rem;'
                    f'font-weight:700;letter-spacing:0.08em">{risk_label}</div>'
                    f'</div>'
                )
                _render_md(eod_html)

                # ── Headline metrics row 1: GEX / DEX / VEX / CEX 0DTE
                total_g_m = zdte_sum.get("total_gex", 0) / 1e6
                total_d_m = (zdte_dex_sum or {}).get("total_dex", 0) / 1e6
                total_v_m = (zdte_vex_sum or {}).get("total_vex", 0) / 1e6
                total_c_m = (zdte_cex_sum or {}).get("total_cex", 0) / 1e6
                z1, z2, z3, z4 = st.columns(4)
                z1.metric(
                    "0DTE Net GEX",
                    f"${total_g_m:+.1f}M",
                    "LONG Γ" if total_g_m >= 0 else "SHORT Γ",
                )
                z2.metric(
                    "0DTE Net DEX",
                    f"${total_d_m:+.1f}M",
                    ("CALL-HEAVY" if total_d_m > 0
                     else "PUT-HEAVY" if total_d_m < 0 else "NEUTRAL"),
                )
                z3.metric(
                    "0DTE Net VEX",
                    (f"${total_v_m/1000:+,.1f}B/vol pt" if abs(total_v_m) >= 1000
                     else f"${total_v_m:+.1f}M/vol pt"),
                    help="Cambio en delta dealer por +1 pt IV. En 0DTE "
                         "decae rápido (vanna → 0 con T → 0).",
                )
                z4.metric(
                    "0DTE Net CEX",
                    (f"${total_c_m/1000:+,.1f}B/día" if abs(total_c_m) >= 1000
                     else f"${total_c_m:+.1f}M/día"),
                    help="Delta decay del dealer por día. Geométricamente "
                         "grande en 0DTE — drives end-of-day flow.",
                )

                # Headline metrics row 2: walls + flip + counts
                z5, z6, z7, z8 = st.columns(4)
                z5.metric(
                    "Call Wall",
                    (f"${zdte_sum['call_wall']:.0f}"
                     if zdte_sum.get("call_wall") else "—"),
                )
                z6.metric(
                    "Put Wall",
                    (f"${zdte_sum['put_wall']:.0f}"
                     if zdte_sum.get("put_wall") else "—"),
                )
                gf = zdte_sum.get("gamma_flip")
                z7.metric(
                    "Zero Γ",
                    f"${gf:.0f}" if gf else "—",
                    (f"{(gf - spot)/spot*100:+.2f}% vs spot"
                     if gf and spot and spot > 0 else None),
                )
                z8.metric(
                    "HVL (pin)",
                    (f"${zdte_sum['hvl']:.0f}"
                     if zdte_sum.get("hvl") else "—"),
                    help="Strike con mayor |Net GEX|. Imán del pinning "
                         "en régimen LONG Γ.",
                )

                # ── Gamma zones panel — same widget as Overview, scoped
                # to the 0DTE profile.
                _render_md(panel_zones_html(zdte_zones, spot=spot))

                # ── Expected-Move analyzer (0DTE) ────────────────────────
                # The legacy 1σ EM in interpret_0dte stalled at [spot, spot]
                # when dte=0 (sqrt(0)=0). The new analyzer uses fractional
                # T from bs.time_to_expiry_years and produces multi-sigma
                # bands plus an iron-condor strike picker.
                from quant.expected_move import (
                    compute_em_bands, suggest_iron_condor,
                )
                from quant.levels import _interp_iv_one_side
                from charts.expected_move import chart_em_bands
                from ui.widgets import panel_em_table_html, panel_em_ic_html

                iv_call_zdte = _interp_iv_one_side(zdte_c, spot)
                iv_put_zdte = _interp_iv_one_side(zdte_p, spot)
                # Controls for the trader: target POP for the IC + wing width.
                _render_md(
                    '<p class="bb-header" style="margin-top:0.4rem">'
                    'EXPECTED MOVE 0DTE  ·  Bandas multi-σ + Iron Condor</p>'
                )
                cem1, cem2 = st.columns([1, 1])
                with cem1:
                    target_pop = st.slider(
                        "Target POP iron condor (%)",
                        min_value=50, max_value=90, value=70, step=5,
                        key="zdte_ic_target_pop",
                        help=("Probabilidad objetivo de que el spot termine "
                              "dentro del rango [short_put, short_call]. "
                              "Más alto = strikes más alejados = menor crédito."),
                    )
                with cem2:
                    wing_width = st.slider(
                        "Ancho del wing (pts)",
                        min_value=1.0, max_value=20.0, value=5.0, step=1.0,
                        key="zdte_ic_wing_width",
                        help=("Distancia entre short y long en cada lado. "
                              "Mayor wing = mayor crédito pero mayor max loss."),
                    )
                em_analysis = compute_em_bands(
                    spot=spot,
                    iv_call_pct=iv_call_zdte,
                    iv_put_pct=iv_put_zdte,
                    dte=0,
                )
                if em_analysis is not None:
                    ic_suggestion = suggest_iron_condor(
                        em_analysis,
                        target_pop=target_pop / 100.0,
                        wing_width=float(wing_width),
                    )
                    # Lay the two cards side by side using st.columns —
                    # more reliable than nested flexbox in a single
                    # markdown chunk (Streamlit's CommonMark renderer
                    # has been flaky with nested HTML flex layouts).
                    cem_l, cem_r = st.columns([1, 1])
                    with cem_l:
                        _render_md(panel_em_table_html(em_analysis))
                    with cem_r:
                        _render_md(panel_em_ic_html(ic_suggestion))
                    fig_em = chart_em_bands(
                        em_analysis, symbol=f"{symbol} 0DTE",
                        ic_suggestion=ic_suggestion,
                    )
                    if fig_em is not None:
                        st.plotly_chart(
                            fig_em, use_container_width=True,
                            key=f"0dte_em_{symbol}",
                        )
                else:
                    st.caption(
                        "Expected Move no disponible — IV ATM no se pudo "
                        "resolver. Asegúrate de que la cadena 0DTE tenga "
                        "strikes con IV%>1% cerca del spot."
                    )

                # ── View + Zoom controls (paridad con GEX Total) ────────
                VIEW_OPTS = ["all", "net", "call", "put"]
                ZOOM_OPTS = ["tight", "near", "mid", "wide", "all"]
                prev_view = st.session_state.get("zdte_view_mode", "all")
                prev_zoom = st.session_state.get("zdte_zoom_mode", "tight")
                if prev_view not in VIEW_OPTS:
                    prev_view = "all"
                if prev_zoom not in ZOOM_OPTS:
                    prev_zoom = "tight"
                c0z1, c0z2 = st.columns([1.5, 2.0])
                with c0z1:
                    zdte_view = st.radio(
                        "Vista",
                        options=VIEW_OPTS,
                        format_func=lambda v: {
                            "all": "Todos", "net": "Solo Net",
                            "call": "Solo Call", "put": "Solo Put",
                        }[v],
                        horizontal=True,
                        index=VIEW_OPTS.index(prev_view),
                        key="zdte_view_mode",
                    )
                with c0z2:
                    zdte_zoom = st.radio(
                        "Zoom",
                        options=ZOOM_OPTS,
                        format_func=lambda z: {
                            "tight": "Tight ±1.5%", "near": "Near ±3%",
                            "mid": "Mid ±5%", "wide": "Wide ±10%",
                            "all": "All strikes",
                        }[z],
                        horizontal=True,
                        index=ZOOM_OPTS.index(prev_zoom),
                        key="zdte_zoom_mode",
                    )
                zdte_pct = {
                    "tight": 0.015, "near": 0.03, "mid": 0.05,
                    "wide": 0.10, "all": None,
                }[zdte_zoom]

                # ── Main 0DTE GEX profile with zones overlay
                fig_z = chart_gex_profile(
                    zdte_df, spot, zdte_sum, f"{symbol} 0DTE",
                    focus_pct=zdte_pct, view=zdte_view,
                    zones=zdte_zones,
                )
                if fig_z:
                    st.plotly_chart(
                        fig_z, use_container_width=True,
                        key=f"0dte_chart_{symbol}",
                    )
                _render_md(interpret_0dte(zdte_sum, spot))

                # ── 0DTE Volatility Smile + IC strike picker ───────────────
                from quant.ic_picker import (
                    build_smile_blend, compare_wing_widths,
                    gex_gate_check, suggest_strikes_from_walls,
                )
                from charts.smile_0dte import chart_smile_0dte
                from ui.widgets import (
                    panel_gex_gate_html, panel_ic_strike_suggest_html,
                )
                _render_md(
                    '<p class="bb-header" style="margin-top:0.5rem">'
                    '0DTE VOLATILITY SMILE  ·  IV(K) blend OTM</p>'
                )
                st.caption(
                    "Sonrisa de IV por strike para 0DTE (no es term-structure). "
                    "IV reutilizada directamente de la cadena (columna IV% de "
                    "data.parse.clean). Market_IV usa la convención OTM: "
                    "put-IV para K&lt;S, call-IV para K≥S. Overlay de walls "
                    "GEX. Strikes en zona <b>rica</b> (IV &gt; μ+1σ) marcados "
                    "con anillo rojo."
                )
                # X-axis toggle + rich-zone σ slider
                csm0, csm1 = st.columns([2, 2])
                with csm0:
                    sm_xaxis = st.radio(
                        "Eje X",
                        options=["strike", "moneyness", "delta"],
                        format_func=lambda v: {
                            "strike": "Strike",
                            "moneyness": "Moneyness %",
                            "delta": "|Δ|",
                        }[v],
                        horizontal=True, index=0, key="0dte_sm_xaxis",
                    )
                with csm1:
                    rich_sigma = st.slider(
                        "Rich-zone threshold (σ)",
                        min_value=0.5, max_value=2.5, value=1.0, step=0.1,
                        key="0dte_sm_rich",
                    )
                # The 0DTE expiry as a string (first row of either side
                # post-DTE filter — they share the date)
                zdte_expiry = (
                    str(zdte_c["Expiry"].iloc[0]) if not zdte_c.empty
                    else str(zdte_p["Expiry"].iloc[0]) if not zdte_p.empty
                    else "0DTE"
                )
                smile_df_0dte = build_smile_blend(
                    zdte_c, zdte_p, spot=spot, expiry=zdte_expiry,
                )

                # GEX gate verdict + strike suggestion based on walls
                gate = gex_gate_check(
                    zdte_sum, spot=spot,
                    min_net_gex_usd=5e7,  # 0DTE Net GEX is smaller than aggregate
                    min_cushion_pct=0.25,
                )
                _render_md(panel_gex_gate_html(gate))
                suggestion = suggest_strikes_from_walls(
                    zdte_c, zdte_p, spot=spot, gex_sum=zdte_sum,
                    target_short_delta=0.16,
                    smile_df=smile_df_0dte,
                )
                _render_md(panel_ic_strike_suggest_html(
                    suggestion, walls=zdte_sum))

                # Render the smile chart with walls + IC overlay
                walls_for_chart = {
                    "call_wall": zdte_sum.get("call_wall"),
                    "put_wall": zdte_sum.get("put_wall"),
                    "hvl": zdte_sum.get("hvl"),
                    "gamma_flip": zdte_sum.get("gamma_flip"),
                }
                ic_strikes_overlay = (
                    {"short_put": suggestion["short_put"],
                     "short_call": suggestion["short_call"]}
                    if suggestion and suggestion.get("short_put")
                    and suggestion.get("short_call")
                    else None
                )
                fig_smile = chart_smile_0dte(
                    smile_df_0dte, spot=spot, walls=walls_for_chart,
                    x_axis=sm_xaxis, rich_sigma=float(rich_sigma),
                    ic_strikes=ic_strikes_overlay, symbol=symbol,
                    expiry=zdte_expiry,
                )
                if fig_smile is not None:
                    st.plotly_chart(
                        fig_smile, use_container_width=True,
                        key=f"0dte_smile_{symbol}",
                    )

                # Wing-width comparison table
                _render_md(
                    '<p class="bb-header" style="margin-top:0.4rem">'
                    'IRON CONDOR  ·  WING WIDTH COMPARISON</p>'
                )
                st.caption(
                    "Mantiene los strikes cortos fijos (sugeridos arriba) y "
                    "compara VRP neto por unidad de max-loss para varios "
                    "anchos de ala. La fila más eficiente queda arriba."
                )
                # Allow override of shorts manually
                cic0, cic1, cic2 = st.columns([1, 1, 2])
                default_sp = (suggestion.get("short_put") or
                              round(spot * 0.99, 0))
                default_sc = (suggestion.get("short_call") or
                              round(spot * 1.01, 0))
                with cic0:
                    sp_override = st.number_input(
                        "Short Put", value=float(default_sp), step=1.0,
                        key="0dte_ic_sp",
                    )
                with cic1:
                    sc_override = st.number_input(
                        "Short Call", value=float(default_sc), step=1.0,
                        key="0dte_ic_sc",
                    )
                with cic2:
                    widths_str = st.text_input(
                        "Anchos de ala (separados por coma)",
                        value="1, 3, 5, 10", key="0dte_ic_widths",
                    )
                try:
                    widths_tuple = tuple(
                        float(x.strip()) for x in widths_str.split(",")
                        if x.strip()
                    )
                except ValueError:
                    # User typed something non-numeric — fall back to
                    # defaults silently. Anything else (KeyError etc.)
                    # bubbles up as it should.
                    widths_tuple = (1.0, 3.0, 5.0, 10.0)
                if widths_tuple:
                    ic_table = compare_wing_widths(
                        zdte_c, zdte_p, spot=spot,
                        short_put=float(sp_override),
                        short_call=float(sc_override),
                        wing_widths=widths_tuple,
                        expiry=zdte_expiry,
                    )
                    if not ic_table.empty:
                        # Drop verbose / redundant cols for display
                        display_cols = [
                            "wing_width", "short_put", "long_put",
                            "short_call", "long_call",
                            "credit", "max_loss",
                            "vrp_put_side", "vrp_call_side",
                            "net_vrp_iv_points",
                            "vrp_per_max_loss", "credit_per_max_loss",
                            "p_touch_put", "p_touch_call", "pop",
                            "credit_source",
                        ]
                        cols_present = [c for c in display_cols
                                        if c in ic_table.columns]
                        st.dataframe(
                            ic_table[cols_present],
                            use_container_width=True, hide_index=True,
                        )
                    else:
                        st.caption(
                            "Sin filas: revisa que los strikes cortos "
                            "estén dentro del rango de la cadena 0DTE."
                        )

                # ── Cumulative GEX + Scenario curve (paridad con GEX Total) ─
                col_l, col_r = st.columns([1, 1])
                with col_l:
                    _render_md(
                        '<p class="bb-header" style="margin-top:0.3rem">'
                        '0DTE PERFIL ACUMULADO</p>'
                    )
                    st.caption(
                        "Cumulative Net GEX por strike. El cruce por cero = "
                        "Zero Gamma dinámico para hoy."
                    )
                    fig_cum_z = chart_cum_gex(zdte_df, spot, zdte_sum)
                    if fig_cum_z:
                        st.plotly_chart(
                            fig_cum_z, use_container_width=True,
                            key=f"0dte_cum_{symbol}",
                        )
                with col_r:
                    _render_md(
                        '<p class="bb-header" style="margin-top:0.3rem">'
                        '0DTE GAMMA SCENARIO</p>'
                    )
                    st.caption(
                        "Reprice 0DTE gamma sobre un grid de spot hipotético. "
                        "El cruce por cero da el flip dinámico que el "
                        "mercado vería si el spot saltara a ese precio."
                    )
                    try:
                        zdte_curve = gex_curve_over_spot(
                            zdte_c, zdte_p, spot, symbol=symbol,
                            max_dte=0, min_oi=0,
                            grid_pct=0.05, n_points=81,
                        )
                        fig_curve_z = chart_gex_curve(zdte_curve, spot, zdte_sum)
                        if fig_curve_z:
                            st.plotly_chart(
                                fig_curve_z, use_container_width=True,
                                key=f"0dte_curve_{symbol}",
                            )
                    except Exception as exc:
                        log.exception("0DTE scenario curve failed")
                        st.caption(f"Scenario no disponible: {exc}")

                # ── Top 0DTE strikes — most actionable single panel for
                # an intraday trader: where is the OI/volume/gamma actually
                # concentrated TODAY?
                _render_md(
                    '<p class="bb-header" style="margin-top:0.4rem">'
                    'TOP 0DTE STRIKES  ·  by |Net GEX|, OI y Volumen</p>'
                )
                # Build a combined view across calls + puts for the same
                # strike so the trader sees both sides at once.
                cs = (zdte_c[["Strike", "OI", "Volume", "Gamma"]]
                      .rename(columns={"OI": "C_OI", "Volume": "C_Vol",
                                       "Gamma": "C_Γ"})
                      if not zdte_c.empty else pd.DataFrame())
                ps = (zdte_p[["Strike", "OI", "Volume", "Gamma"]]
                      .rename(columns={"OI": "P_OI", "Volume": "P_Vol",
                                       "Gamma": "P_Γ"})
                      if not zdte_p.empty else pd.DataFrame())
                if not cs.empty and not ps.empty:
                    merged = cs.merge(ps, on="Strike", how="outer").fillna(0)
                else:
                    merged = cs if not cs.empty else ps
                # Bring in |Net GEX| from the computed profile to rank by it.
                if not merged.empty and not zdte_df.empty:
                    g_map = zdte_df.set_index("Strike")["Abs_GEX"].to_dict()
                    merged["AbsGEX_M"] = (
                        merged["Strike"].map(g_map).fillna(0) / 1e6
                    )
                    merged = merged.sort_values("AbsGEX_M", ascending=False).head(15)
                    merged["Dist %"] = (
                        (merged["Strike"] - spot) / spot * 100
                    ).round(2)
                    cols_order = ["Strike", "Dist %", "AbsGEX_M",
                                  "C_OI", "P_OI", "C_Vol", "P_Vol",
                                  "C_Γ", "P_Γ"]
                    cols_show = [c for c in cols_order if c in merged.columns]
                    st.dataframe(
                        merged[cols_show].reset_index(drop=True),
                        use_container_width=True, hide_index=True,
                    )

                # ── 0DTE Vanna + Charm narrative
                cvn1, cvn2 = st.columns(2)
                with cvn1:
                    _render_md(interpret_vex(zdte_vex_sum)
                               if zdte_vex_sum else "")
                with cvn2:
                    _render_md(interpret_cex(zdte_cex_sum, dte=0)
                               if zdte_cex_sum else "")
            else:
                st.caption(
                    "Sin datos 0DTE procesables (gamma = 0 o cadena vacía)."
                )

    # ── EXPECTED RANGE ───────────────────────────────────────────────────────
    with tab_erange:
        from quant.expected_range import compare_estimators, prob_cone
        from quant.levels import _interp_iv_one_side
        from charts.expected_range import (
            chart_estimator_comparison, chart_prob_cone,
            chart_risk_neutral_density,
        )
        from ui.widgets import panel_rnd_levels_html, panel_em_accuracy_html

        _render_md('<p class="bb-header">'
                   'EXPECTED RANGE  ·  distribución implícita (RND) + estimadores</p>')
        st.caption(
            "El modelo central es la <b>Risk-Neutral Density</b>: la "
            "distribución de probabilidad completa que el mercado de opciones "
            "cotiza para el cierre, extraída del chain vía SVI (Gatheral) + "
            "Breeden-Litzenberger, arbitrage-free y centrada en el forward. "
            "Los niveles salen por inversión exacta de la CDF. Debajo, cuatro "
            "estimadores clásicos del rango ±1σ como contraste."
        )

        # Horizon selector — radio pills.
        er_dte = st.radio(
            "Horizonte (DTE)", [0, 1, 2, 5, 7],
            index=0, key="er_dte", horizontal=True,
            format_func=lambda d: "0 · hoy" if d == 0 else f"{d}d",
            help="0 = hoy (intradía, fracción de día a las 16:00 ET).",
        )

        # IV inputs (feed the classical estimators in the expander).
        iv_call_side = _interp_iv_one_side(calls, spot) if not calls.empty else None
        iv_put_side = _interp_iv_one_side(puts, spot) if not puts.empty else None
        hv_realized = None
        if "analytics_full" in dir() and analytics_full:
            hv_realized = (analytics_full.get("hv30_yang_zhang")
                           or analytics_full.get("hv30"))
        iv_blend_er = None
        if iv_call_side is not None and iv_put_side is not None:
            iv_blend_er = (iv_call_side + iv_put_side) / 2.0
        elif iv_call_side is not None:
            iv_blend_er = iv_call_side
        elif iv_put_side is not None:
            iv_blend_er = iv_put_side

        if not spot or spot <= 0:
            st.warning("Expected Range requiere spot válido en la cadena.")
        else:
            # ── HERO: Risk-Neutral Density (the crown jewel, leads the tab) ──
            rnd, rnd_meta, lv = _get_rnd(int(er_dte))
            if rnd is not None and not rnd.empty:
                levels = {
                    "call_wall": (gex_sum or {}).get("call_wall"),
                    "put_wall": (gex_sum or {}).get("put_wall"),
                    "hvl": (gex_sum or {}).get("hvl"),
                    "gamma_flip": (gex_sum or {}).get("gamma_flip"),
                }
                _render_md(panel_rnd_levels_html(lv, spot, meta=rnd_meta))
                fig_rnd = chart_risk_neutral_density(
                    rnd, spot=spot, levels=levels, symbol=symbol,
                    rnd_levels_data=lv, method=rnd_meta.get("method"),
                    confidence=rnd_meta.get("confidence"),
                    forward=rnd_meta.get("forward"),
                )
                if fig_rnd is not None:
                    st.plotly_chart(fig_rnd, use_container_width=True,
                                    key=f"er_rnd_{symbol}")
            else:
                st.info(
                    "Risk-neutral density requiere ≥5 strikes con IV% válida en "
                    "este horizonte. Prueba SPY/SPX/QQQ o un DTE con más strikes."
                )

            # ── Classical estimators (contrast) — tucked in an expander ─────
            with st.expander("📐 Estimadores clásicos del rango ±1σ  ·  "
                             "IV-Gaussian · Straddle · Skew · Realized · cono"):
                if iv_call_side is None and iv_put_side is None:
                    st.caption("Sin IV ATM válida en la cadena para los "
                               "estimadores clásicos.")
                else:
                    estimates, _T = compare_estimators(
                        spot=spot, calls=calls, puts=puts,
                        iv_call_pct=iv_call_side, iv_put_pct=iv_put_side,
                        realized_vol_pct=hv_realized, dte=int(er_dte),
                    )
                    by_method = {e.method: e for e in estimates}

                    def _em_metric(col, method, label):
                        e = by_method.get(method)
                        col.metric(label, (f"±${e.em_dollars:.2f}" if e else "—"),
                                   (f"{e.em_pct:.2f}%" if e else None))
                    em1, em2, em3, em4 = st.columns(4)
                    _em_metric(em1, "IV Gaussian", "IV Gaussian 1σ")
                    _em_metric(em2, "Straddle MMM", "Straddle MMM 1σ")
                    _em_metric(em3, "Skew-adjusted", "Skew-adj 1σ")
                    _em_metric(em4, "Realized vol", "Realized 1σ")

                    fig_cmp = chart_estimator_comparison(estimates, spot, symbol)
                    if fig_cmp is not None:
                        st.plotly_chart(fig_cmp, use_container_width=True,
                                        key=f"er_cmp_{symbol}")

                    if iv_blend_er and hv_realized:
                        ratio = iv_blend_er / hv_realized
                        rich = ("IV CARA — favor vender vol" if ratio > 1.2
                                else "IV BARATA — favor comprar vol" if ratio < 0.9
                                else "IV ≈ realized")
                        rclr = ("#f59e0b" if ratio > 1.2 else
                                "#06b6d4" if ratio < 0.9 else "#9090b0")
                        _render_md(
                            f'<div style="background:rgba(15,17,24,0.85);'
                            f'border-left:3px solid {rclr};padding:0.5rem 0.8rem;'
                            f'border-radius:0 4px 4px 0;font-family:JetBrains '
                            f'Mono,monospace;font-size:0.82rem;margin:0.3rem 0">'
                            f'IV/HV = <b style="color:{rclr}">{ratio:.2f}×</b> · '
                            f'{rich}  <span style="color:#7070a0">(IV '
                            f'{iv_blend_er:.1f}% vs HV {hv_realized:.1f}%)</span>'
                            f'</div>'
                        )

                    cone = prob_cone(
                        spot, iv_blend_er or iv_call_side or iv_put_side,
                        dtes=(0, 1, 2, 5), sigmas=(1.0, 2.0))
                    if not cone.empty:
                        fig_cone = chart_prob_cone(cone, spot, symbol)
                        if fig_cone is not None:
                            st.plotly_chart(fig_cone, use_container_width=True,
                                            key=f"er_cone_{symbol}")

            # ── EM Accuracy tracker — calibration (auto-recorded headless) ──
            _render_md('<p class="bb-header" style="margin-top:0.5rem">'
                       'EM ACCURACY  ·  ¿el modelo acierta?</p>')
            try:
                from data import em_store
                from quant.em_tracker import accuracy_stats
                em_hist = em_store.load_history(symbol, limit=250)
                if em_hist:
                    stats = accuracy_stats(em_hist, only_clean=True)
                    _render_md(panel_em_accuracy_html(
                        stats, backend=em_store.backend_info().get("backend", "—")))
                else:
                    st.caption(
                        "Aún sin registros para este símbolo. El job headless "
                        "(GitHub Actions) graba una predicción cada apertura y "
                        "la liquida al cierre — ~10 sesiones para un veredicto. "
                        "Ver `docs/EM_TRACKER_SETUP.md`."
                    )
            except Exception as exc:
                log.warning("EM accuracy panel failed: %s", exc)
                st.caption(
                    "Tracker no disponible (¿DATABASE_URL configurado?). "
                    "Ver `docs/EM_TRACKER_SETUP.md`."
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

    # ── FOOTER ──────────────────────────────────────────────────────────────
    st.markdown('<hr class="bb-divider">', unsafe_allow_html=True)
    st.markdown(
        f'<p class="footer">❯ GEX · INTELLIGENCE TERMINAL  ·  {symbol}  ·  '
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
        # NOTE: no <h1> here on purpose — the global `h1{color:...!important}`
        # rule overrides any class colour, which is why the old .conn-title
        # rendered white/sans instead of the brand style.
        if is_expired:
            st.markdown("""
            <div style="text-align:center;font-size:2.2rem;margin:0.4rem 0 0.2rem;">⚠</div>
            <div style="text-align:center;font-family:'JetBrains Mono',monospace;font-size:1.55rem;font-weight:800;color:#f43f5e;letter-spacing:0.08em;margin-bottom:0.3rem;">TOKEN EXPIRADO</div>
            <p class="conn-sub">Tu refresh token expiró (válido 7 días). Re-autoriza una vez y copia el nuevo token a Secrets.</p>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="display:flex;justify-content:center;align-items:center;gap:11px;margin:0.6rem 0 0.45rem;">
            <span style="color:#f97316;font-family:'JetBrains Mono',monospace;font-size:2.1rem;font-weight:800;line-height:1;">&#10095;</span>
            <span style="color:#f5f5ff;font-family:'JetBrains Mono',monospace;font-size:2rem;font-weight:800;letter-spacing:0.12em;line-height:1;">GEX</span>
            <span class="brand-cursor" style="width:14px;height:1.75rem;"></span>
            </div>
            <div style="text-align:center;font-family:'JetBrains Mono',monospace;font-size:0.6rem;color:#5b5b80;letter-spacing:0.32em;margin-bottom:0.7rem;">INTELLIGENCE&nbsp;TERMINAL</div>
            <p class="conn-sub">Primera configuración — solo necesitas hacerlo una vez.</p>
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
