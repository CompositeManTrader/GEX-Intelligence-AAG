"""
Decision-engine HTML panel — builds an actionable trade-bias block based on
GEX regime, VEX (vanna) and CEX (charm) sign and magnitude, plus IV context.
"""
from __future__ import annotations

from typing import Optional

from charts.theme import GREEN, ORANGE, RED


def build_decision_panel(spot: float,
                         gex_sum: dict,
                         vex_sum: dict,
                         cex_sum: dict,
                         dex_sum: dict,
                         iv_atm: Optional[float],
                         em_lo: Optional[float],
                         em_hi: Optional[float],
                         dte_v: int,
                         vol_regime: Optional[str] = None) -> str:
    regime = gex_sum.get("regime", "NEUTRAL")
    gf = gex_sum.get("gamma_flip")
    cw = gex_sum.get("call_wall")
    pw = gex_sum.get("put_wall")
    hvl = gex_sum.get("hvl")
    flip_pct = gex_sum.get("flip_pct")

    vex_total = (vex_sum or {}).get("total_vex", 0) / 1e6
    cex_total = (cex_sum or {}).get("total_cex", 0) / 1e6

    # ── Regime thesis ───────────────────────────────────────────────────────
    if regime == "POSITIVE":
        reg_color = GREEN
        reg_title = "🟢 LONG GAMMA  (régimen estabilizador)"
        reg_thesis = (
            "Los dealers están <b>long gamma</b>: compran en caídas y venden en rallies. "
            "Esperá <b>rangos estrechos</b>, <b>mean-reversion intradía</b>, "
            "y <b>compresión de realized vol</b>. El spot tiende a ser atraído hacia el "
            f"<b>HVL en <code>${hvl:.0f}</code></b> (máximo hedging dealer)."
            if hvl else
            "Dealers long gamma — espera rangos estrechos y mean-reversion intradía."
        )
    elif regime == "NEGATIVE":
        reg_color = RED
        reg_title = "🔴 SHORT GAMMA  (régimen amplificador)"
        reg_thesis = (
            "Los dealers están <b>short gamma</b>: compran en rallies y venden en caídas, "
            "<b>amplificando</b> los movimientos. Esperá <b>volatilidad realizada alta</b>, "
            "<b>extension de trends</b>, y <b>potencial gap-through</b> de niveles clave. "
            f"Cruces por el <b>Zero Gamma (<code>${gf:.0f}</code>)</b> cambian el régimen."
            if gf else
            "Dealers short gamma — trend-following, momentum se acelera, risk-off elevado."
        )
    else:
        reg_color = ORANGE
        reg_title = "🟡 NEUTRAL / TRANSITIONAL"
        reg_thesis = ("Mercado en equilibrio cerca del flip-point. "
                      "Espera transición inminente.")

    # ── Playbook ────────────────────────────────────────────────────────────
    if regime == "POSITIVE":
        trade_bias = (
            f"<b>Estrategias favorecidas:</b> iron condors y credit spreads al ATM, "
            f"venta de straddles/strangles intradía, fade de los bordes del rango "
            f"(<code>${pw:.0f}</code> — <code>${cw:.0f}</code>). "
            f"<b>Evitar:</b> long gamma / long straddles; te decaen sin movimiento."
        ) if (cw and pw) else (
            "<b>Estrategias favorecidas:</b> condors/credit spreads al ATM, "
            "fade de los extremos del rango. <b>Evitar:</b> compra de vol sin catalizador."
        )
    elif regime == "NEGATIVE":
        trade_bias = (
            f"<b>Estrategias favorecidas:</b> compra de volatilidad (long straddle/strangle ATM), "
            f"debit spreads direccionales con stop en Zero Gamma, <b>breakouts</b> de "
            f"<code>${cw:.0f}</code> (upside) o <code>${pw:.0f}</code> (downside). "
            f"<b>Evitar:</b> vender premium cerca de strikes con alto OI — "
            f"dealer hedging te perforará."
        ) if (cw and pw) else (
            "<b>Estrategias favorecidas:</b> long straddle/strangle ATM, debit spreads. "
            "<b>Evitar:</b> venta de premium — el hedging amplifica movimientos."
        )
    else:
        trade_bias = (
            "Evita tomar posiciones direccionales hasta que el régimen se defina. "
            f"Vigilar cruce de spot sobre/bajo <code>${gf:.0f}</code> para confirmar."
            if gf else
            "Evita direccionales hasta que el régimen se defina."
        )

    # ── Vanna / Charm context ───────────────────────────────────────────────
    vanna_msg = ""
    if abs(vex_total) > 1:
        if vex_total > 0:
            vanna_msg = (f"<b>Vanna positiva (${vex_total:+.0f}M/vol pt):</b> "
                         f"si la IV sube (ej. VIX expansion), los dealers "
                         f"<b>compran spot</b> — flow de soporte. Si la IV baja "
                         f"(vol crush post-evento), <b>venden spot</b>.")
        else:
            vanna_msg = (f"<b>Vanna negativa (${vex_total:+.0f}M/vol pt):</b> "
                         f"si la IV sube, los dealers <b>venden spot</b> — "
                         f"amplifica sell-offs con vol expansion. Si la IV baja, "
                         f"<b>compran spot</b> — rally on vol crush.")

    def _mday(v):
        # Compact $M figure: 11211.8 → '+11.2B' (the raw 'M' read terribly)
        return (f"{v/1000:+,.1f}B" if abs(v) >= 1000 else f"{v:+,.1f}M")

    charm_msg = ""
    if abs(cex_total) > 0.5:
        if cex_total > 0:
            charm_msg = (f"<b>Charm positivo (${_mday(cex_total)}/día):</b> "
                         f"con el paso del tiempo, los dealers acumulan delta positiva "
                         f"y <b>compran</b> en los últimos minutos (bullish EOD flow). "
                         f"Especialmente notable en 0DTE y vencimiento.")
        else:
            charm_msg = (f"<b>Charm negativo (${_mday(cex_total)}/día):</b> "
                         f"dealers pierden delta con el tiempo, <b>venden spot</b> al cierre. "
                         f"Sell-flow conforme se acerca el vencimiento.")

    # ── Levels ──────────────────────────────────────────────────────────────
    levels = []
    if cw:
        levels.append(f"<li><b>Call Wall</b> <code>${cw:.0f}</code> — "
                      f"resistencia; rally suele fallar/pausar aquí.</li>")
    if pw:
        levels.append(f"<li><b>Put Wall</b> <code>${pw:.0f}</code> — "
                      f"soporte; caída suele encontrar hedging dealer que amortigua.</li>")
    if gf:
        if flip_pct is not None:
            levels.append(f"<li><b>Zero Gamma</b> <code>${gf:.0f}</code> "
                          f"({flip_pct:+.1f}% del spot) — cruce cambia el régimen.</li>")
        else:
            levels.append(f"<li><b>Zero Gamma</b> <code>${gf:.0f}</code> — "
                          f"cruce cambia el régimen.</li>")
    if hvl and regime == "POSITIVE":
        levels.append(f"<li><b>HVL</b> <code>${hvl:.0f}</code> — "
                      f"punto de atracción del hedging en régimen long-gamma.</li>")
    if em_lo and em_hi:
        levels.append(f"<li><b>1σ Expected Move ({dte_v}d)</b> "
                      f"<code>${em_lo:.0f} — ${em_hi:.0f}</code> — rango estadístico esperado.</li>")
    levels_html = "".join(levels)

    vol_html = ""
    if vol_regime and vol_regime != "—":
        vol_html = f'<p style="margin:0.6rem 0 0">🎯 <b>IV context:</b> {vol_regime}.</p>'

    panel = f"""
    <div class="decision-card">
      <div class="decision-title" style="color:{reg_color}">{reg_title}</div>
      <div class="decision-body">
        <p style="margin:0 0 0.7rem">{reg_thesis}</p>
        <p style="margin:0 0 0.5rem">📍 <b>Niveles clave:</b></p>
        <ul style="margin:0 0 0.7rem 1.4rem;padding:0;line-height:1.7">{levels_html}</ul>
        <p style="margin:0 0 0.5rem">⚡ <b>Playbook:</b></p>
        <p style="margin:0 0 0.7rem;padding-left:0.5rem;border-left:2px solid {reg_color}80">{trade_bias}</p>
        {'<p style="margin:0 0 0.5rem">📈 ' + vanna_msg + '</p>' if vanna_msg else ''}
        {'<p style="margin:0 0 0.5rem">⏰ ' + charm_msg + '</p>' if charm_msg else ''}
        {vol_html}
      </div>
    </div>
    """
    return panel
