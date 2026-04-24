"""
Automatic chart interpretations — data-driven narrative text boxes.

Each `interpret_*` function returns an HTML snippet ready to be rendered
under its chart with `st.markdown(..., unsafe_allow_html=True)`.

Design rules:
  - Actionable, not descriptive. Say "what to do" not "what is".
  - Always mention the ≥2 highest-signal data points.
  - Use ↑/↓/→ arrows + color chips to scan quickly.
  - Spanish (user-facing).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
#  Visual helpers
# ─────────────────────────────────────────────────────────────────────────────
_BOX = (
    '<div style="background:rgba(20,20,36,0.55);border-left:3px solid {clr};'
    'padding:0.6rem 0.9rem;margin:0.3rem 0 1rem;border-radius:4px;'
    'font-family:JetBrains Mono,monospace;font-size:0.76rem;line-height:1.55;'
    'color:#c0c0d8;">{body}</div>'
)


def _box(body: str, tone: str = "info") -> str:
    clr = {
        "bull": "#22c55e", "bear": "#f43f5e", "warn": "#f59e0b",
        "info": "#3b82f6", "neutral": "#8b8ba7",
    }.get(tone, "#8b8ba7")
    return _BOX.format(clr=clr, body=body)


def _chip(text: str, clr: str) -> str:
    return (
        f'<span style="background:rgba({clr},0.18);color:rgb({clr});'
        f'padding:1px 7px;border-radius:3px;font-weight:700;font-size:0.7rem;'
        f'margin:0 2px;">{text}</span>'
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GEX profile
# ─────────────────────────────────────────────────────────────────────────────
def interpret_gex_profile(gex_sum: dict, spot: float) -> str:
    if not gex_sum:
        return _box("Sin datos suficientes para interpretar el perfil GEX.", "neutral")
    regime = gex_sum.get("regime", "NEUTRAL")
    total_bn = gex_sum.get("total_gex", 0) / 1e9
    cw = gex_sum.get("call_wall")
    pw = gex_sum.get("put_wall")
    gf = gex_sum.get("gamma_flip")
    hvl = gex_sum.get("hvl")

    parts: list[str] = []
    # Regime thesis
    if regime == "POSITIVE":
        parts.append(
            f"<b>Régimen LONG GAMMA</b> (Net GEX {_chip(f'${total_bn:+.2f}B', '34,197,94')}). "
            "Dealer vende rallies / compra dips → <b>baja volatilidad realizada</b>. "
            "Favorece estrategias de venta de vol (iron condors, credit spreads)."
        )
    elif regime == "NEGATIVE":
        parts.append(
            f"<b>Régimen SHORT GAMMA</b> (Net GEX {_chip(f'${total_bn:+.2f}B', '244,63,94')}). "
            "Dealer amplifica movimiento → <b>alta volatilidad realizada</b>. "
            "Riesgo de <b>gamma squeeze</b>. Considera compra de vol o direccionales."
        )
    else:
        parts.append(
            f"<b>Régimen NEUTRAL</b> (Net GEX {_chip(f'${total_bn:+.2f}B', '249,115,22')}). "
            "Flujo de hedging mixto, régimen transicional."
        )
    # Levels
    if cw and pw:
        rng = f"${pw:.0f} – ${cw:.0f}"
        parts.append(
            f"📍 <b>Rango esperado:</b> {rng}. Put wall actúa como soporte, "
            f"call wall como resistencia."
        )
    elif cw:
        parts.append(f"📍 Resistencia clave: <b>${cw:.0f}</b> (call wall).")
    elif pw:
        parts.append(f"📍 Soporte clave: <b>${pw:.0f}</b> (put wall).")
    # Zero gamma
    if gf and spot:
        flip_pct = (gf - spot) / spot * 100
        if abs(flip_pct) < 0.3:
            parts.append(
                f"⚠️ <b>Zero Γ a ${gf:.0f}</b> (muy cerca, {flip_pct:+.2f}%). "
                "Cambio de régimen inminente si el spot lo cruza."
            )
        else:
            side = "arriba" if flip_pct > 0 else "abajo"
            parts.append(
                f"Zero Γ en <b>${gf:.0f}</b> ({flip_pct:+.1f}% {side}). "
                f"Cruzarlo alternaría el régimen a "
                f"{'NEGATIVE' if regime == 'POSITIVE' else 'POSITIVE'}."
            )
    # HVL
    if hvl:
        parts.append(f"🎯 HVL (imán gamma): <b>${hvl:.0f}</b>.")
    tone = "bull" if regime == "POSITIVE" else ("bear" if regime == "NEGATIVE" else "warn")
    return _box(" ".join(parts), tone)


# ─────────────────────────────────────────────────────────────────────────────
#  VEX
# ─────────────────────────────────────────────────────────────────────────────
def interpret_vex(vex_sum: dict) -> str:
    if not vex_sum:
        return _box("Sin datos VEX.", "neutral")
    total = vex_sum.get("total_vex", 0) / 1e6
    call_v = vex_sum.get("call_vex", 0) / 1e6
    put_v = vex_sum.get("put_vex", 0) / 1e6
    if total > 100:
        msg = (
            f"<b>LONG VANNA</b> (+${total:.0f}M por +1 pt IV). Si la IV sube, "
            "dealer <b>compra spot</b> → amplifica rallies en vol expansion. "
            "Pre-FOMC / pre-CPI típicamente + vanna."
        )
        tone = "bull"
    elif total < -100:
        msg = (
            f"<b>SHORT VANNA</b> (${total:.0f}M por +1 pt IV). Si la IV sube, "
            "dealer <b>vende spot</b> → amplifica caídas en vol spikes. "
            "Setup peligroso ante shocks."
        )
        tone = "bear"
    else:
        msg = f"Vanna neutral (${total:.0f}M). Hedge flow poco sensible a IV."
        tone = "neutral"
    msg += (
        f" &nbsp;|&nbsp; Calls: ${call_v:+.0f}M &nbsp; Puts: ${put_v:+.0f}M."
    )
    return _box(msg, tone)


# ─────────────────────────────────────────────────────────────────────────────
#  CEX
# ─────────────────────────────────────────────────────────────────────────────
def interpret_cex(cex_sum: dict, dte: int = 0) -> str:
    if not cex_sum:
        return _box("Sin datos CEX.", "neutral")
    total = cex_sum.get("total_cex", 0) / 1e6
    if total > 50:
        msg = (
            f"<b>POSITIVE CHARM</b> (+${total:.0f}M/día). El decay de delta "
            "produce <b>EOD buy-flow</b> del dealer. Típico cerca de OPEX, "
            "refuerza pin risk al alza."
        )
        tone = "bull"
    elif total < -50:
        msg = (
            f"<b>NEGATIVE CHARM</b> (${total:.0f}M/día). Dealer vende al "
            "cierre — <b>EOD sell-flow</b>. Bajista en días previos a OPEX."
        )
        tone = "bear"
    else:
        msg = f"Charm neutral (${total:.0f}M/día)."
        tone = "neutral"
    if dte <= 2:
        msg += " &nbsp;⚠️ <b>DTE ≤ 2</b>: charm acelera geométricamente."
    return _box(msg, tone)


# ─────────────────────────────────────────────────────────────────────────────
#  DEX
# ─────────────────────────────────────────────────────────────────────────────
def interpret_dex(dex_sum: dict) -> str:
    if not dex_sum:
        return _box("Sin datos DEX.", "neutral")
    total = dex_sum.get("total_dex", 0) / 1e6
    bias = dex_sum.get("bias", "NEUTRAL")
    if bias == "CALL-HEAVY":
        msg = (
            f"<b>CALL-HEAVY</b> (DEX ${total:+.0f}M). Posicionamiento bullish: "
            "más call delta abierto que put delta. <b>Soporte implícito</b> al "
            "alza — dealer ya es largo delta."
        )
        tone = "bull"
    elif bias == "PUT-HEAVY":
        msg = (
            f"<b>PUT-HEAVY</b> (DEX ${total:+.0f}M). Posicionamiento bearish / "
            "de hedge. <b>Resistencia implícita</b> — dealer ya es corto delta."
        )
        tone = "bear"
    else:
        msg = f"DEX balanceado (${total:+.0f}M). Sin sesgo direccional claro."
        tone = "neutral"
    return _box(msg, tone)


# ─────────────────────────────────────────────────────────────────────────────
#  Term structure
# ─────────────────────────────────────────────────────────────────────────────
def interpret_term_structure(ts_df: pd.DataFrame) -> str:
    if ts_df is None or ts_df.empty:
        return _box("Sin term structure disponible.", "neutral")
    front = float(ts_df["ATM_IV"].iloc[0])
    back = float(ts_df["ATM_IV"].iloc[-1])
    net = back - front
    front_dte = int(ts_df["DTE"].iloc[0])
    back_dte = int(ts_df["DTE"].iloc[-1])
    if net > 1.0:
        msg = (
            f"<b>CONTANGO</b> — IV sube con el tiempo (+{net:.1f} pts de "
            f"{front_dte}d a {back_dte}d). Mercado pricing <b>expansión de vol "
            "futura</b>. Favorece calendars (long back / short front)."
        )
        tone = "bull"
    elif net < -1.0:
        msg = (
            f"<b>BACKWARDATION</b> — IV cae con el tiempo ({net:+.1f} pts de "
            f"{front_dte}d a {back_dte}d). <b>Riesgo inminente</b> priced-in "
            "(earnings, FOMC). Favorece venta de front-month."
        )
        tone = "bear"
    else:
        msg = (
            f"Curva <b>FLAT</b> ({net:+.1f} pts). Sin distorsión entre "
            "vencimientos, régimen estable."
        )
        tone = "neutral"
    # Kink detection
    if len(ts_df) >= 3:
        diffs = ts_df["ATM_IV"].diff().dropna()
        if diffs.max() > 2.5:
            kink_idx = int(diffs.idxmax())
            kink_exp = str(ts_df.iloc[kink_idx]["Expiry"])[:10]
            msg += f" &nbsp;🔺 Pico notable cerca de <b>{kink_exp}</b>."
        if diffs.min() < -2.5:
            dip_idx = int(diffs.idxmin())
            dip_exp = str(ts_df.iloc[dip_idx]["Expiry"])[:10]
            msg += f" &nbsp;🔻 Caída notable en <b>{dip_exp}</b>."
    return _box(msg, tone)


# ─────────────────────────────────────────────────────────────────────────────
#  IV Smile
# ─────────────────────────────────────────────────────────────────────────────
def interpret_smile(metrics: dict, expiry: str) -> str:
    if not metrics:
        return _box("Sin métricas de smile.", "neutral")
    atm = metrics.get("atm_iv")
    rr = metrics.get("rr25")
    bf = metrics.get("bf25")
    slope = metrics.get("slope_90_110")
    parts = [f"<b>Expiry {str(expiry)[:10]}</b>:"]
    if atm is not None:
        parts.append(f"ATM {atm:.1f}%")
    tone = "neutral"
    if rr is not None:
        if rr > 3:
            parts.append(
                f"<b>RR25 {_chip(f'{rr:+.1f}', '244,63,94')}</b> → "
                "fuerte <b>demanda de puts</b> (protección cara, miedo)."
            )
            tone = "bear"
        elif rr < -3:
            parts.append(
                f"<b>RR25 {_chip(f'{rr:+.1f}', '34,197,94')}</b> → "
                "<b>call skew</b> (persiguiendo el rally)."
            )
            tone = "bull"
        else:
            parts.append(f"RR25 {rr:+.1f} (skew neutral).")
    if bf is not None:
        if bf > 3:
            parts.append(f"BF25 {bf:+.1f} → <b>colas gordas</b>, tail risk alto.")
        elif bf < -1:
            parts.append(f"BF25 {bf:+.1f} → sonrisa plana.")
        else:
            parts.append(f"BF25 {bf:+.1f}.")
    if slope is not None:
        parts.append(f"Slope 90/110: {slope:+.1f} pts.")
    return _box(" ".join(parts), tone)


# ─────────────────────────────────────────────────────────────────────────────
#  HIRO
# ─────────────────────────────────────────────────────────────────────────────
def interpret_hiro(hiro_snap: dict, zscore: Optional[float] = None,
                   history_len: int = 0) -> str:
    if not hiro_snap:
        return _box("HIRO en construcción. Se necesitan ≥3 snapshots.", "neutral")
    h = hiro_snap.get("hiro", 0)
    ratio = hiro_snap.get("ratio", 0.5)
    call_f = hiro_snap.get("call_flow", 0)
    put_f = hiro_snap.get("put_flow", 0)
    parts = []
    if h > 0:
        parts.append(
            f"<b>BUY PRESSURE dealer</b> (+{h:,.0f}). Calls dominan el flujo "
            f"({ratio*100:.0f}%). Sesgo implícito: <b>alcista</b>."
        )
        tone = "bull"
    elif h < 0:
        parts.append(
            f"<b>SELL PRESSURE dealer</b> ({h:,.0f}). Puts dominan el flujo "
            f"({(1-ratio)*100:.0f}%). Sesgo implícito: <b>bajista</b>."
        )
        tone = "bear"
    else:
        parts.append("Flujo equilibrado.")
        tone = "neutral"
    if zscore is not None:
        if abs(zscore) >= 2:
            parts.append(
                f"&nbsp;📛 <b>Z-score {zscore:+.1f}</b> — movimiento "
                f"extremo vs ventana reciente ({history_len} obs)."
            )
        else:
            parts.append(f"&nbsp;Z-score {zscore:+.1f} (normal).")
    parts.append(
        f"&nbsp;|&nbsp; Calls: {call_f:,.0f}  ·  Puts: {put_f:,.0f}"
    )
    return _box(" ".join(parts), tone)


# ─────────────────────────────────────────────────────────────────────────────
#  Open Interest / Volume
# ─────────────────────────────────────────────────────────────────────────────
def interpret_oi(calls: pd.DataFrame, puts: pd.DataFrame,
                 spot: float) -> str:
    if (calls is None or calls.empty) and (puts is None or puts.empty):
        return _box("Sin cadena para analizar.", "neutral")
    parts = []
    # Top call OI strike
    if calls is not None and not calls.empty and "OI" in calls.columns:
        top_c = calls.loc[calls["OI"].idxmax()]
        oi_c = int(top_c["OI"])
        k_c = float(top_c["Strike"])
        tag = "ITM" if k_c < spot else ("ATM" if abs(k_c - spot) < spot * 0.01 else "OTM")
        parts.append(
            f"Max <b>Call OI</b>: <b>${k_c:.0f}</b> ({oi_c:,}) · {tag}."
        )
    if puts is not None and not puts.empty and "OI" in puts.columns:
        top_p = puts.loc[puts["OI"].idxmax()]
        oi_p = int(top_p["OI"])
        k_p = float(top_p["Strike"])
        tag = "ITM" if k_p > spot else ("ATM" if abs(k_p - spot) < spot * 0.01 else "OTM")
        parts.append(
            f"Max <b>Put OI</b>: <b>${k_p:.0f}</b> ({oi_p:,}) · {tag}."
        )
    # Vol concentration
    if calls is not None and not calls.empty and "Volume" in calls.columns:
        top_v = calls.loc[calls["Volume"].idxmax()]
        if int(top_v["Volume"]) > 0:
            parts.append(
                f"&nbsp;Hot call <b>${float(top_v['Strike']):.0f}</b> "
                f"(vol {int(top_v['Volume']):,})."
            )
    return _box(" ".join(parts), "info")


# ─────────────────────────────────────────────────────────────────────────────
#  Vol Analytics (HV / IV / cone)
# ─────────────────────────────────────────────────────────────────────────────
def interpret_vol_analytics(analytics: dict, atm_iv: Optional[float]) -> str:
    if not analytics:
        return _box("Sin analytics de vol.", "neutral")
    regime = analytics.get("vol_regime", "—")
    ratio = analytics.get("iv_hv_ratio")
    hv30 = analytics.get("hv30")
    rank = analytics.get("iv_rank")
    skew = analytics.get("skewness")
    parts = []
    if ratio is not None:
        if ratio > 1.3:
            parts.append(
                f"<b>IV CARA</b> ({ratio:.2f}x HV30). Vende vol: iron condors, "
                "credit spreads, short strangles."
            )
            tone = "bull"
        elif ratio < 0.8:
            parts.append(
                f"<b>IV BARATA</b> ({ratio:.2f}x HV30). Compra vol: "
                "straddles, calendars, debit spreads."
            )
            tone = "bear"
        else:
            parts.append(f"IV neutral ({ratio:.2f}x HV30). Prioriza direccionales.")
            tone = "neutral"
    else:
        parts.append(f"Régimen {regime}.")
        tone = "neutral"
    if rank is not None:
        if rank > 70:
            parts.append(f"&nbsp;IV Rank <b>{rank:.0f}</b> (alto).")
        elif rank < 30:
            parts.append(f"&nbsp;IV Rank <b>{rank:.0f}</b> (bajo).")
    if skew is not None and abs(skew) > 0.8:
        parts.append(
            f"&nbsp;Skew de retornos {skew:+.2f} "
            f"→ cola {'izquierda' if skew < 0 else 'derecha'} gorda."
        )
    return _box(" ".join(parts), tone)


# ─────────────────────────────────────────────────────────────────────────────
#  GEX Scenario
# ─────────────────────────────────────────────────────────────────────────────
def interpret_scenario(curve_df: pd.DataFrame, gex_sum: dict,
                       spot: float) -> str:
    if curve_df is None or curve_df.empty or not gex_sum:
        return _box("Sin datos para scenario.", "neutral")
    gf = gex_sum.get("gamma_flip")
    max_gex = float(curve_df["GEX"].max()) / 1e9
    min_gex = float(curve_df["GEX"].min()) / 1e9
    max_spot = float(curve_df.loc[curve_df["GEX"].idxmax(), "Spot"])
    min_spot = float(curve_df.loc[curve_df["GEX"].idxmin(), "Spot"])
    parts = [
        f"Máx GEX: {_chip(f'${max_gex:+.2f}B', '34,197,94')} "
        f"en spot <b>${max_spot:.0f}</b>.",
        f"Mín GEX: {_chip(f'${min_gex:+.2f}B', '244,63,94')} "
        f"en spot <b>${min_spot:.0f}</b>.",
    ]
    if gf:
        dist_pct = (gf - spot) / spot * 100
        parts.append(
            f"Zero Γ dinámico en <b>${gf:.0f}</b> "
            f"({dist_pct:+.1f}% vs spot actual)."
        )
    return _box(" ".join(parts), "info")


# ─────────────────────────────────────────────────────────────────────────────
#  0DTE
# ─────────────────────────────────────────────────────────────────────────────
def interpret_0dte(zdte_sum: dict, spot: float) -> str:
    if not zdte_sum:
        return _box("Sin strikes 0DTE.", "neutral")
    total_m = zdte_sum.get("total_gex", 0) / 1e6
    hvl = zdte_sum.get("hvl")
    cw = zdte_sum.get("call_wall")
    pw = zdte_sum.get("put_wall")
    parts = [f"0DTE Net GEX: <b>${total_m:+.0f}M</b>."]
    if hvl:
        dist_pct = (hvl - spot) / spot * 100
        parts.append(
            f"<b>Pin strike</b>: ${hvl:.0f} ({dist_pct:+.2f}% del spot). "
            "Alta probabilidad de cierre aquí en ausencia de catalyst."
        )
    if cw and pw:
        parts.append(
            f"Rango 0DTE: <b>${pw:.0f} – ${cw:.0f}</b>. "
            "Cruzar estos niveles dispara gamma hedging explosivo."
        )
    if total_m > 200:
        tone = "bull"
        parts.append("<b>LONG Γ 0DTE</b> → pinning ATM, baja vol intradía.")
    elif total_m < -200:
        tone = "bear"
        parts.append("<b>SHORT Γ 0DTE</b> → riesgo de squeeze intradía.")
    else:
        tone = "warn"
    return _box(" ".join(parts), tone)


# ─────────────────────────────────────────────────────────────────────────────
#  Orderflow — per-panel market commentary
# ─────────────────────────────────────────────────────────────────────────────
def _slope(series: list) -> Optional[float]:
    """Simple last-vs-first delta of the latest N values."""
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None
    return vals[-1] - vals[0]


def interpret_orderflow_dex(history: list) -> str:
    """What the DEX time-series is telling us right now."""
    if not history:
        return _box("Sin datos de DEX.", "neutral")
    last = history[-1]
    net = last.get("net_dex_mm")
    if net is None:
        return _box("Net DEX no disponible (cadena sin Δ/OI).", "neutral")
    recent = [h.get("net_dex_mm") for h in history[-10:]]
    slope = _slope(recent)
    parts = [f"<b>Net DEX actual: ${net:+.1f}M</b> por 1% de movimiento."]
    if net > 0:
        parts.append(
            "🟢 <b>Call-heavy</b>: el dealer está largo delta — vende en rallies "
            "(resistencia implícita arriba) y compra en caídas (soporte abajo). "
            "Esto <b>suaviza la acción del precio</b>."
        )
        tone = "bull"
    else:
        parts.append(
            "🔴 <b>Put-heavy</b>: el dealer está corto delta — compra en rallies "
            "(acelera al alza) y vende en caídas (acelera a la baja). "
            "<b>Amplifica la volatilidad direccional</b>."
        )
        tone = "bear"
    if slope is not None and abs(slope) > 5:
        if slope > 0:
            parts.append(
                f"📈 Tendencia ↑ (+${slope:.1f}M en los últimos ticks) → "
                "compradores de calls acumulan, dealer se vuelve más direccional al alza."
            )
        else:
            parts.append(
                f"📉 Tendencia ↓ ({slope:+.1f}M en los últimos ticks) → "
                "compradores de puts acumulan, presión bajista en crecimiento."
            )
    return _box(" ".join(parts), tone)


def interpret_orderflow_gex(history: list, spot: Optional[float] = None) -> str:
    """Commentary for the GEX time-series panel."""
    if not history:
        return _box("Sin datos de GEX.", "neutral")
    last = history[-1]
    net = last.get("net_gex_mm")
    if net is None:
        return _box("Net GEX no disponible.", "neutral")
    cw = last.get("call_wall")
    pw = last.get("put_wall")
    gf = last.get("gamma_flip")
    recent = [h.get("net_gex_mm") for h in history[-10:]]
    slope = _slope(recent)
    parts = [f"<b>Net GEX: ${net:+.1f}M</b> por 1% ("
             f"{'<b>LONG Γ</b>' if net >= 0 else '<b>SHORT Γ</b>'})."]
    if net >= 0:
        parts.append(
            "🟢 Régimen <b>positivo</b>: los dealers compran caídas y venden "
            "rallies. Expectativa de <b>mean-reversion</b>, rangos comprimidos "
            "y vol realizada baja. Las paredes actúan como imán."
        )
        tone = "bull"
    else:
        parts.append(
            "🔴 Régimen <b>negativo</b>: los dealers venden caídas y compran "
            "rallies. Expectativa de <b>trending + momentum</b>, rangos más "
            "amplios. Si el spot cruza el gamma flip, el hedging acelera el move."
        )
        tone = "bear"
    if spot and cw and pw:
        parts.append(
            f"📌 Paredes: Call ${cw:.0f} (tope) · Put ${pw:.0f} (suelo). "
            f"Spot ${spot:.2f} → "
            f"{'dentro' if pw <= spot <= cw else '<b>FUERA</b>'} del canal GEX."
        )
    if spot and gf:
        dist_pct = (gf - spot) / spot * 100
        if abs(dist_pct) < 0.5:
            parts.append(
                f"⚠️ <b>Spot rozando Zero-Γ</b> (${gf:.0f}, {dist_pct:+.2f}%): "
                "cualquier ruptura detona switching de régimen y expande volatilidad."
            )
            tone = "warn"
    if slope is not None and abs(slope) > 50:
        trend = "subiendo" if slope > 0 else "cayendo"
        parts.append(
            f"Net GEX {trend} ({slope:+.1f}M) → el régimen se está "
            f"{'consolidando' if (slope > 0) == (net >= 0) else 'degradando'}."
        )
    return _box(" ".join(parts), tone)


def interpret_orderflow_convexity(history: list) -> str:
    """Commentary for the Convexity (net VEX) panel."""
    if not history:
        return _box("Sin datos de convexity.", "neutral")
    last = history[-1]
    net = last.get("net_vex_mm")
    if net is None:
        return _box("Net VEX no disponible (cadena sin IV válida).", "neutral")
    recent = [h.get("net_vex_mm") for h in history[-10:]]
    slope = _slope(recent)
    parts = [f"<b>Net Convexity (VEX): ${net:+.1f}M</b> por +1 punto de IV."]
    if net > 0:
        parts.append(
            "🟢 Dealer <b>long vanna</b>: si la IV sube, el dealer <b>compra spot</b> "
            "(flujo comprador en vol expansion — típico de eventos tipo earnings "
            "o FOMC con sesgo alcista)."
        )
        tone = "bull"
    elif net < 0:
        parts.append(
            "🔴 Dealer <b>short vanna</b>: si la IV sube, el dealer <b>vende spot</b> "
            "(cascada bajista en spike de VIX; clave para entender sell-offs "
            "en IV expansion)."
        )
        tone = "bear"
    else:
        parts.append("Vanna dealer ~0 — IV no mueve el hedge direccional hoy.")
        tone = "neutral"
    if slope is not None and abs(slope) > 2:
        trend = "↑" if slope > 0 else "↓"
        parts.append(
            f"Convexity {trend} ({slope:+.1f}M) — "
            f"{'más exposición a vol' if slope > 0 else 'exposición a vol decreciendo'}."
        )
    return _box(" ".join(parts), tone)


def interpret_orderflow_summary(history: list,
                                spot: Optional[float] = None) -> str:
    """One-box summary combining DEX bias + GEX regime + Vanna direction."""
    if not history:
        return _box("Esperando primer tick de orderflow…", "neutral")
    last = history[-1]
    dex = last.get("net_dex_mm")
    gex = last.get("net_gex_mm")
    vex = last.get("net_vex_mm")
    msgs = []
    if gex is not None:
        msgs.append(
            f"Régimen {'<b>LONG Γ</b>' if gex >= 0 else '<b>SHORT Γ</b>'} "
            f"(${gex:+.1f}M)"
        )
    if dex is not None:
        msgs.append(
            f"Bias {'<b>alcista</b>' if dex >= 0 else '<b>bajista</b>'} "
            f"(DEX ${dex:+.1f}M)"
        )
    if vex is not None:
        if abs(vex) > 1:
            msgs.append(
                f"Vanna {'<b>+</b>' if vex > 0 else '<b>−</b>'} (${vex:+.1f}M/+1IV)"
            )
    if not msgs:
        return _box("Orderflow sin datos suficientes.", "neutral")
    headline = "  ·  ".join(msgs)
    if spot is not None:
        headline = f"Spot ${spot:.2f}  ·  {headline}"
    tone = "bull" if (gex or 0) >= 0 and (dex or 0) >= 0 else \
           ("bear" if (gex or 0) < 0 and (dex or 0) < 0 else "warn")
    return _box(headline, tone)
