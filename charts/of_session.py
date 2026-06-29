"""
Session-orderflow charts — built on the CONTINUOUS snapshot history
(data/of_store, fed by the GitHub-Actions recorder every ~10 min).

These answer the trader's session questions directly:
  · chart_session_trajectory — ¿el régimen está girando?  Net GEX
    (agregado + 0DTE) vs tiempo con el spot superpuesto y los cruces de
    régimen marcados con su hora.
  · chart_walls_timeline     — ¿los muros se están moviendo?  CW/PW/HVL
    como líneas escalonadas vs el precio.
  · chart_strike_flow        — ¿dónde está pegando el flujo AHORA?
    Δvolumen por strike (ventana reciente), calls vs puts.

All inputs are lists of tick dicts that may come from of_store rows
(key 'ts') or live session ticks (key 'timestamp') — both are accepted.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.theme import AX_NOZERO, BASE, CYAN, FONT_MONO, GREEN, ORANGE, RED

PURPLE = "#a855f7"


def _ticks_df(ticks: list[dict]) -> Optional[pd.DataFrame]:
    if not ticks:
        return None
    df = pd.DataFrame(ticks)
    ts = df["ts"] if "ts" in df.columns else df.get("timestamp")
    if ts is None:
        return None
    df["ts_dt"] = pd.to_datetime(ts, errors="coerce", utc=True)
    df = df.dropna(subset=["ts_dt"]).sort_values("ts_dt")
    if df.empty:
        return None
    df["ts_et"] = df["ts_dt"].dt.tz_convert("America/New_York")
    for col in ("spot", "net_gex_mm", "gex_0dte_mm", "call_wall", "put_wall",
                "hvl", "gamma_flip"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _layout(fig, height, title):
    base = {k: v for k, v in BASE.items() if k != "legend"}
    fig.update_layout(
        **base, height=height,
        title=dict(text=title, x=0,
                   font=dict(size=12, color="#c0c0d8", family=FONT_MONO)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right",
                    x=1, font=dict(size=9, color="#9090b0"),
                    bgcolor="rgba(0,0,0,0)"),
    )


# ─────────────────────────────────────────────────────────────────────────────
def chart_session_trajectory(ticks: list[dict],
                             symbol: str = "") -> Optional[go.Figure]:
    """Net GEX (agregado + 0DTE) vs tiempo, spot en eje secundario, y los
    cambios de régimen marcados verticalmente con su hora ET."""
    df = _ticks_df(ticks)
    if df is None or len(df) < 2 or "net_gex_mm" not in df.columns:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=df["ts_et"], y=df["net_gex_mm"], name="Net GEX (0–60d)",
        line=dict(color=ORANGE, width=2.0),
        fill="tozeroy", fillcolor="rgba(245,166,35,0.07)",
        hovertemplate="%{x|%H:%M} · $%{y:,.0f}M<extra>Net GEX</extra>",
    ), secondary_y=False)
    if "gex_0dte_mm" in df.columns and df["gex_0dte_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["ts_et"], y=df["gex_0dte_mm"], name="GEX 0DTE",
            line=dict(color=PURPLE, width=1.5, dash="dot"),
            hovertemplate="%{x|%H:%M} · $%{y:,.0f}M<extra>GEX 0DTE</extra>",
        ), secondary_y=False)
    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["ts_et"], y=df["spot"], name="spot",
            line=dict(color=CYAN, width=1.3),
            hovertemplate="%{x|%H:%M} · $%{y:,.2f}<extra>spot</extra>",
        ), secondary_y=True)

    # Zero line (the regime boundary) + regime-change markers
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.25)", line_width=1,
                  secondary_y=False)
    if "regime" in df.columns:
        prev = None
        for _, row in df.iterrows():
            cur = row.get("regime")
            if prev and cur and cur != prev:
                clr = GREEN if cur == "POSITIVE" else (
                    RED if cur == "NEGATIVE" else ORANGE)
                # Epoch-ms x: plotly's add_vline does arithmetic on x for the
                # annotation, which TypeErrors on pandas-3.x Timestamps.
                fig.add_vline(x=int(row["ts_et"].timestamp() * 1000),
                              line_dash="dash",
                              line_color=clr, line_width=1.2, opacity=0.85,
                              annotation_text=(f"{row['ts_et'].strftime('%H:%M')}"
                                               f" → {cur[:3]}"),
                              annotation_font=dict(size=8, color=clr,
                                                   family=FONT_MONO),
                              annotation_position="top")
            if cur:
                prev = cur

    _layout(fig, 360, f"TRAYECTORIA DE SESIÓN  ·  {symbol}  ·  "
                      "Net GEX + spot · cruces de régimen marcados")
    fig.update_yaxes(**AX_NOZERO, title_text="Net GEX ($M)",
                     secondary_y=False)
    fig.update_yaxes(showgrid=False, zeroline=False,
                     tickfont=dict(size=10, family=FONT_MONO, color=CYAN),
                     title_text="spot", secondary_y=True)
    fig.update_xaxes(**AX_NOZERO)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
def chart_walls_timeline(ticks: list[dict],
                         symbol: str = "") -> Optional[go.Figure]:
    """CW / PW / HVL como líneas escalonadas vs el spot — de un vistazo si
    los muros se están moviendo contra tu posición."""
    df = _ticks_df(ticks)
    if df is None or len(df) < 2:
        return None
    have_any = any(c in df.columns and df[c].notna().any()
                   for c in ("call_wall", "put_wall", "hvl"))
    if not have_any:
        return None

    fig = go.Figure()
    specs = [("call_wall", GREEN, "Call Wall"),
             ("put_wall", RED, "Put Wall"),
             ("hvl", PURPLE, "HVL")]
    for col, clr, name in specs:
        if col in df.columns and df[col].notna().any():
            fig.add_trace(go.Scatter(
                x=df["ts_et"], y=df[col], name=name,
                line=dict(color=clr, width=1.7, shape="hv"),
                hovertemplate="%{x|%H:%M} · $%{y:,.0f}<extra>" + name
                              + "</extra>",
            ))
    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["ts_et"], y=df["spot"], name="spot",
            line=dict(color=CYAN, width=1.4),
            hovertemplate="%{x|%H:%M} · $%{y:,.2f}<extra>spot</extra>",
        ))
    _layout(fig, 330, f"MUROS vs PRECIO  ·  {symbol}  ·  "
                      "líneas escalonadas = saltos del muro")
    fig.update_yaxes(**AX_NOZERO, title_text="Precio")
    fig.update_xaxes(**AX_NOZERO)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
def chart_strike_flow(activity: dict, symbol: str = "",
                      spot: Optional[float] = None) -> Optional[go.Figure]:
    """Δvolumen por strike en la ventana reciente — calls a la derecha
    (verde), puts a la izquierda (rojo). `activity` es el dict de
    quant.orderflow_derived.strike_activity."""
    rows = (activity or {}).get("rows") or []
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r["strike"])
    strikes = [r["strike"] for r in rows]
    d_call = [r["d_call_vol"] for r in rows]
    d_put = [-r["d_put_vol"] for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=strikes, x=d_call, orientation="h", name="Δvol calls",
        marker_color=GREEN, opacity=0.85,
        hovertemplate="$%{y:,.0f} · +%{x:,.0f} calls<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=strikes, x=d_put, orientation="h", name="Δvol puts",
        marker_color=RED, opacity=0.85,
        hovertemplate="$%{y:,.0f} · %{x:,.0f} puts<extra></extra>",
    ))
    if spot:
        fig.add_hline(y=spot, line_color=CYAN, line_width=1.4,
                      annotation_text=f" spot ${spot:,.2f}",
                      annotation_font=dict(size=9, color=CYAN,
                                           family=FONT_MONO))
    win = (activity or {}).get("window_min")
    win_lbl = f"últimos {win:.0f} min" if win else "volumen del día"
    _layout(fig, 380, f"FLUJO POR STRIKE  ·  {symbol}  ·  {win_lbl}  ·  "
                      "0DTE")
    fig.update_layout(barmode="relative", bargap=0.25)
    fig.update_xaxes(**AX_NOZERO, title_text="contratos (Δ ventana)")
    fig.update_yaxes(**AX_NOZERO, title_text="Strike")
    return fig
