"""
Price & GEX Levels map — a SpotGamma / Tier1Alpha-style key-levels chart.

Draws the structural dealer-gamma levels as horizontal rails (call wall,
put wall, gamma flip, HVL pin, and the P1/P2/P3 gamma clusters) with the
intraday price line overlaid and a shaded "current range" band, plus a
side panel that classifies each major level as resistance / support and
explains it in one line.

PURE PRESENTATION: every level here comes from values the quant model
already computed (`compute_gex_profile` summary + `find_gamma_zones`).
Nothing is recomputed; this module only *arranges and explains* them.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go

from charts.theme import (
    AX_NOZERO, BASE, BLUE, CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Level classification (shared by the chart and the side panel)
# ─────────────────────────────────────────────────────────────────────────────
def collect_price_levels(
    spot: float, gex_sum: Optional[dict], zones: Optional[list] = None,
) -> list[dict]:
    """Build a deduped, sorted list of price levels with role/colour/labels.

    Each level dict:
      price, role ('resistance'|'support'|'flip'|'pin'),
      color, dash, width, short (chart label), tag (panel label),
      desc (one-line explanation), major (bool — wall/flip/pin vs cluster)
    """
    if not spot or spot <= 0:
        return []
    gs = gex_sum or {}
    cw, pw = gs.get("call_wall"), gs.get("put_wall")
    gf, hvl = gs.get("gamma_flip"), gs.get("hvl")
    vt_c, vt_p = gs.get("vt_c"), gs.get("vt_p")
    cb = gs.get("call_bridge")

    out: list[dict] = []

    def add(price, role, color, dash, width, short, tag, desc, major):
        try:
            price = float(price)
        except (TypeError, ValueError):
            return
        if price and price > 0:
            out.append(dict(price=price, role=role, color=color, dash=dash,
                            width=width, short=short, tag=tag, desc=desc,
                            major=major))

    if cw:
        add(cw, "resistance", GREEN, "solid", 2.4, "Call wall · techo de γ",
            "CALL WALL", "Hedging del dealer suprime el alza", True)
    if pw:
        add(pw, "support", RED, "solid", 2.4, "Put wall · piso de γ",
            "PUT WALL", "Compradores esperados en tests", True)
    if gf:
        add(gf, "flip", ORANGE, "dash", 2.0, "Gamma flip · pivote",
            "GAMMA FLIP", "Arriba vol suprimida · abajo vol se expande", True)
    if hvl:
        add(hvl, "pin", PURPLE, "dot", 1.8, "HVL · imán de pinning",
            "HVL / PIN", "Precio atraído a este nivel (mayor |GEX|)", True)

    # ── Niveles de FLUJO / LIQUIDEZ (volumen de sesión + OI total) ──────────
    # Distintos de los muros (OI gamma): el VT es dinero entrando HOY.
    if vt_c:
        add(vt_c, "flow", "#fbbf24", "dashdot", 1.4, "VT-C · vol call activo",
            "VT-C", "Strike de mayor volumen CALL hoy (flujo activo al alza)",
            False)
    if vt_p:
        add(vt_p, "flow", "#EA3943", "dashdot", 1.4, "VT-P · vol put activo",
            "VT-P", "Strike de mayor volumen PUT hoy (flujo activo a la baja)",
            False)
    if cb:
        add(cb, "liquidity", "#60a5fa", "dot", 1.4, "Call Bridge · OI total",
            "CALL BRIDGE",
            "Strike de mayor OI total — liquidez / referencia institucional",
            False)

    for z in (zones or []):
        above = bool(getattr(z, "is_above_spot", z.peak_strike > spot))
        side = getattr(z, "side", "mixed")
        lbl = getattr(z, "label", "P?")
        if side == "call_dominant":
            color = GREEN if above else "#16a34a"
            short = f"Cluster +GEX ({lbl})"
            desc = ("Resistencia / imán de breakout" if above
                    else "Cluster +γ bajo spot — soporte")
        elif side == "put_dominant":
            color = RED if not above else "#dc2626"
            short = f"Cluster −GEX ({lbl})"
            desc = ("Defensores −γ activos en tests" if not above
                    else "Cluster −γ sobre spot — techo")
        else:
            color = ORANGE
            short = f"Cluster mixto ({lbl})"
            desc = "Zona de batalla (calls/puts equilibrados)"
        role = "resistance" if above else "support"
        add(z.peak_strike, role, color, "solid", 1.5, short,
            f"CLUSTER {lbl}", desc, False)

    # Dedupe near-equal prices; keep the more "major" / wider level.
    tol = max(spot * 0.0008, 0.05)
    deduped: list[dict] = []
    for lv in sorted(out, key=lambda d: d["price"]):
        if deduped and abs(lv["price"] - deduped[-1]["price"]) < tol:
            if lv["width"] > deduped[-1]["width"]:
                deduped[-1] = lv
            continue
        deduped.append(lv)
    return deduped


# ─────────────────────────────────────────────────────────────────────────────
#  Chart
# ─────────────────────────────────────────────────────────────────────────────
def chart_price_levels(
    spot: float, gex_sum: Optional[dict], zones: Optional[list] = None,
    intra_df: Optional[pd.DataFrame] = None, symbol: str = "",
) -> Optional[go.Figure]:
    """Render the price & GEX levels map. Returns None if no levels."""
    levels = collect_price_levels(spot, gex_sum, zones)
    if not levels:
        return None

    fig = go.Figure()

    # ── Intraday price line + spot dot ──────────────────────────────────────
    has_price = False
    price_min = price_max = None
    if (intra_df is not None and not intra_df.empty
            and {"date", "close"}.issubset(intra_df.columns)):
        try:
            from charts.intraday import _as_et
            t = _as_et(intra_df["date"])
            c = pd.to_numeric(intra_df["close"], errors="coerce")
            ok = t.notna() & c.notna()
            t, c = t[ok], c[ok]
            if len(c) >= 2:
                fig.add_trace(go.Scatter(
                    x=t, y=c, mode="lines", name="precio",
                    line=dict(color=CYAN, width=1.7),
                    hovertemplate="%{y:.2f}<extra></extra>"))
                fig.add_trace(go.Scatter(
                    x=[t.iloc[-1]], y=[float(c.iloc[-1])], mode="markers",
                    name="spot",
                    marker=dict(color=CYAN, size=12,
                                line=dict(color="#0b0b14", width=2)),
                    hovertemplate="spot %{y:.2f}<extra></extra>"))
                has_price = True
                price_min, price_max = float(c.min()), float(c.max())
        except Exception:
            has_price = False

    if not has_price:
        # No intraday → mark spot as a white dashed rail so the map still reads.
        fig.add_hline(y=spot, line_color="#f5f5ff", line_dash="dash",
                      line_width=1.4, opacity=0.8, layer="below")

    # ── Current-range band (nearest support ↔ nearest resistance) ───────────
    sup = [lv["price"] for lv in levels if lv["price"] < spot]
    res = [lv["price"] for lv in levels if lv["price"] > spot]
    if sup and res:
        fig.add_hrect(y0=max(sup), y1=min(res),
                      fillcolor="rgba(59,130,246,0.10)", line_width=0,
                      layer="below")

    # ── Level rails + left price label + mid description ─────────────────────
    for lv in levels:
        fig.add_hline(y=lv["price"], line_color=lv["color"],
                      line_dash=lv["dash"], line_width=lv["width"],
                      opacity=0.92, layer="below")
        fig.add_annotation(
            xref="paper", x=0.0, y=lv["price"], yref="y",
            text=f"<b>{lv['price']:.0f}</b>", showarrow=False,
            xanchor="right", xshift=-6,
            font=dict(color=lv["color"], size=12, family=FONT_MONO))
        fig.add_annotation(
            xref="paper", x=0.30, y=lv["price"], yref="y",
            text=f"{lv['short']} · {lv['price']:.0f}", showarrow=False,
            xanchor="left", yshift=8,
            font=dict(color=lv["color"], size=9, family=FONT_MONO),
            bgcolor="rgba(11,11,20,0.55)")

    # ── Y-range ─────────────────────────────────────────────────────────────
    pts = [lv["price"] for lv in levels] + [spot]
    if price_min is not None:
        pts += [price_min, price_max]
    ylo, yhi = min(pts), max(pts)
    pad = (yhi - ylo) * 0.10 or 1.0

    # ── Regime badge (top-right) ────────────────────────────────────────────
    gs = gex_sum or {}
    regime = gs.get("regime", "NEUTRAL")
    net_bn = (gs.get("total_gex", 0) or 0) / 1e9
    reg_clr = {"POSITIVE": GREEN, "NEGATIVE": RED}.get(regime, ORANGE)
    fig.add_annotation(
        xref="paper", yref="paper", x=1.0, y=1.06, xanchor="right",
        text=f"{regime} Γ · NET {net_bn:+.2f}B", showarrow=False,
        font=dict(color=reg_clr, size=11, family=FONT_MONO))

    # ── Legend (dummy traces) ───────────────────────────────────────────────
    for nm, clr, dash in [("resistencia", GREEN, "solid"),
                          ("soporte", RED, "solid"),
                          ("pin", PURPLE, "dot"), ("flip", ORANGE, "dash")]:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", name=nm,
                                 line=dict(color=clr, dash=dash, width=2)))
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name="rango",
                             marker=dict(color="rgba(59,130,246,0.55)", size=11,
                                         symbol="square")))

    base = {k: v for k, v in BASE.items() if k not in ("legend", "margin")}
    fig.update_layout(
        **base, height=470, showlegend=True,
        title=dict(text="price &amp; gex levels", x=0.0, xanchor="left",
                   font=dict(size=13, family=FONT_MONO, color="#8a8ab0")),
        legend=dict(orientation="h", yanchor="top", y=-0.06, xanchor="center",
                    x=0.5, font=dict(size=10, color="#9090b0"),
                    bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=52, r=20, t=52, b=44),
    )
    xax = {k: v for k, v in AX_NOZERO.items() if k != "showgrid"}
    fig.update_yaxes(**AX_NOZERO, range=[ylo - pad, yhi + pad],
                     showticklabels=False)
    fig.update_xaxes(**xax, showticklabels=has_price, showgrid=False)
    return fig
