"""
Orderflow 3-panel time-series — gexbot-style.

Each panel shares the x-axis (timestamp) and overlays the spot price on a
secondary y-axis so the reader can see how dealer exposure correlates with
price in real time.

  · chart_dex_timeseries     — Call / Put / Net DEX  + spot
  · chart_gex_timeseries     — Call / Put / Net GEX  + spot  + walls
  · chart_convexity_timeseries — Net VEX (convexity) + spot
  · chart_orderflow_stack    — all three stacked in one figure

All numbers are expected in millions ($M) — `tick_orderflow` already scales.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.theme import (
    AX_NOZERO, AX_ZERO, BASE, CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED,
)

# Secondary-axis for the spot overlay: keep grid off so it doesn't conflict
# with the primary exposure grid. Built once without showgrid so spreading it
# into update_yaxes(...) can pass showgrid=False explicitly.
_AX_SECONDARY = {k: v for k, v in AX_NOZERO.items() if k != "showgrid"}


def _prepare(history: list) -> Optional[pd.DataFrame]:
    if not history or len(history) < 2:
        return None
    df = pd.DataFrame(history)
    if "timestamp" not in df.columns:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    if df.empty:
        return None
    # Convert to America/New_York for display — matches the rest of the UI.
    try:
        df["timestamp"] = df["timestamp"].dt.tz_convert("America/New_York")
    except Exception:
        pass
    return df


# ─────────────────────────────────────────────────────────────────────────────
#  Individual panels (kept as small helpers so callers can mix + match)
# ─────────────────────────────────────────────────────────────────────────────
def chart_dex_timeseries(history: list,
                         symbol: str = "") -> Optional[go.Figure]:
    df = _prepare(history)
    if df is None:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if "call_dex_mm" in df.columns and df["call_dex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["call_dex_mm"], mode="lines",
            name="Call DEX", line=dict(color=GREEN, width=1.3),
            hovertemplate="%{x|%H:%M:%S}<br>Call DEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)
    if "put_dex_mm" in df.columns and df["put_dex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["put_dex_mm"], mode="lines",
            name="Put DEX", line=dict(color=RED, width=1.3),
            hovertemplate="%{x|%H:%M:%S}<br>Put DEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)
    if "net_dex_mm" in df.columns and df["net_dex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_dex_mm"], mode="lines",
            name="Net DEX", line=dict(color="#e0e0f0", width=1.8),
            hovertemplate="%{x|%H:%M:%S}<br>Net DEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)

    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines", name="Spot",
            line=dict(color=ORANGE, width=1.2, dash="dot"),
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), secondary_y=True)

    fig.add_hline(y=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.15)", line_width=1)

    fig.update_layout(
        height=320,
        title=dict(
            text=f"  DEX  ·  Aggregate Delta Exposure  ·  {symbol}",
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO, title_text="DEX ($M)", secondary_y=False)
    fig.update_yaxes(**_AX_SECONDARY, title_text="Spot ($)",
                     secondary_y=True, showgrid=False)
    return fig


def chart_gex_timeseries(history: list,
                         symbol: str = "") -> Optional[go.Figure]:
    df = _prepare(history)
    if df is None:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if "call_gex_mm" in df.columns and df["call_gex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["call_gex_mm"], mode="lines",
            name="Call GEX", line=dict(color=GREEN, width=1.3),
            hovertemplate="%{x|%H:%M:%S}<br>Call GEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)
    if "put_gex_mm" in df.columns and df["put_gex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["put_gex_mm"], mode="lines",
            name="Put GEX", line=dict(color=RED, width=1.3),
            hovertemplate="%{x|%H:%M:%S}<br>Put GEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)
    if "net_gex_mm" in df.columns and df["net_gex_mm"].notna().any():
        # Sign-colored fill so regime (long Γ vs short Γ) is obvious.
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_gex_mm"], mode="lines",
            name="Net GEX", line=dict(color="#e0e0f0", width=2.0),
            fill="tozeroy", fillcolor="rgba(168,85,247,0.12)",
            hovertemplate="%{x|%H:%M:%S}<br>Net GEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)

    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines", name="Spot",
            line=dict(color=ORANGE, width=1.2, dash="dot"),
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), secondary_y=True)

    # Latest wall references (as thin horizontal rules on the spot axis)
    last = df.iloc[-1]
    for key, color, label in (
        ("call_wall", GREEN, "CW"),
        ("put_wall", RED, "PW"),
        ("gamma_flip", PURPLE, "GF"),
    ):
        val = last.get(key)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        fig.add_hline(
            y=v, line_dash="dash", line_color=color, line_width=1.0,
            annotation_text=f"  {label} ${v:.0f}",
            annotation_font=dict(size=9, color=color, family=FONT_MONO),
            annotation_position="right",
            secondary_y=True,
        )

    fig.add_hline(y=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.15)", line_width=1)

    fig.update_layout(
        height=340,
        title=dict(
            text=f"  NET GEX  ·  Dealer Gamma Exposure  ·  {symbol}",
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO, title_text="GEX ($M / 1%)", secondary_y=False)
    fig.update_yaxes(**_AX_SECONDARY, title_text="Spot ($)",
                     secondary_y=True, showgrid=False)
    return fig


def chart_convexity_timeseries(history: list,
                               symbol: str = "") -> Optional[go.Figure]:
    df = _prepare(history)
    if df is None:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if "net_vex_mm" in df.columns and df["net_vex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_vex_mm"], mode="lines",
            name="Net Convexity (VEX)", line=dict(color=CYAN, width=1.8),
            fill="tozeroy", fillcolor="rgba(6,182,212,0.14)",
            hovertemplate="%{x|%H:%M:%S}<br>Net VEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)
    if "call_vex_mm" in df.columns and df["call_vex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["call_vex_mm"], mode="lines",
            name="Call VEX", line=dict(color=GREEN, width=1.0, dash="dot"),
            hovertemplate="%{x|%H:%M:%S}<br>Call VEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)
    if "put_vex_mm" in df.columns and df["put_vex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["put_vex_mm"], mode="lines",
            name="Put VEX", line=dict(color=RED, width=1.0, dash="dot"),
            hovertemplate="%{x|%H:%M:%S}<br>Put VEX: $%{y:+.1f}M<extra></extra>",
        ), secondary_y=False)

    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines", name="Spot",
            line=dict(color=ORANGE, width=1.2, dash="dot"),
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), secondary_y=True)

    fig.add_hline(y=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.15)", line_width=1)

    fig.update_layout(
        height=320,
        title=dict(
            text=f"  CONVEXITY  ·  Net Vanna Exposure  ·  {symbol}",
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO, title_text="VEX ($M / +1 IV)", secondary_y=False)
    fig.update_yaxes(**_AX_SECONDARY, title_text="Spot ($)",
                     secondary_y=True, showgrid=False)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  Combined stacked view — visually matches the gexbot "orderflow" tab
# ─────────────────────────────────────────────────────────────────────────────
def chart_orderflow_stack(history: list,
                          symbol: str = "") -> Optional[go.Figure]:
    df = _prepare(history)
    if df is None:
        return None

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.045,
        row_heights=[0.34, 0.34, 0.32],
        specs=[[{"secondary_y": True}],
               [{"secondary_y": True}],
               [{"secondary_y": True}]],
        subplot_titles=[
            "DEX  ·  Aggregate Delta Exposure",
            "Net GEX  ·  Dealer Gamma",
            "Convexity  ·  Net Vanna (VEX)",
        ],
    )

    # ── Row 1: DEX ─────────────────────────────────────────────────────────
    if df.get("call_dex_mm") is not None and df["call_dex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["call_dex_mm"], mode="lines",
            name="Call DEX", line=dict(color=GREEN, width=1.2),
            hovertemplate="%{x|%H:%M:%S}<br>Call DEX: $%{y:+.1f}M<extra></extra>",
        ), row=1, col=1, secondary_y=False)
    if df.get("put_dex_mm") is not None and df["put_dex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["put_dex_mm"], mode="lines",
            name="Put DEX", line=dict(color=RED, width=1.2),
            hovertemplate="%{x|%H:%M:%S}<br>Put DEX: $%{y:+.1f}M<extra></extra>",
        ), row=1, col=1, secondary_y=False)
    if df.get("net_dex_mm") is not None and df["net_dex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_dex_mm"], mode="lines",
            name="Net DEX", line=dict(color="#e0e0f0", width=1.8),
            hovertemplate="%{x|%H:%M:%S}<br>Net DEX: $%{y:+.1f}M<extra></extra>",
        ), row=1, col=1, secondary_y=False)
    if df.get("spot") is not None and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines", name="Spot",
            line=dict(color=ORANGE, width=1.1, dash="dot"),
            showlegend=False,
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), row=1, col=1, secondary_y=True)

    # ── Row 2: Net GEX ─────────────────────────────────────────────────────
    if df.get("call_gex_mm") is not None and df["call_gex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["call_gex_mm"], mode="lines",
            name="Call GEX", line=dict(color=GREEN, width=1.2),
            hovertemplate="%{x|%H:%M:%S}<br>Call GEX: $%{y:+.1f}M<extra></extra>",
        ), row=2, col=1, secondary_y=False)
    if df.get("put_gex_mm") is not None and df["put_gex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["put_gex_mm"], mode="lines",
            name="Put GEX", line=dict(color=RED, width=1.2),
            hovertemplate="%{x|%H:%M:%S}<br>Put GEX: $%{y:+.1f}M<extra></extra>",
        ), row=2, col=1, secondary_y=False)
    if df.get("net_gex_mm") is not None and df["net_gex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_gex_mm"], mode="lines",
            name="Net GEX", line=dict(color="#e0e0f0", width=2.0),
            fill="tozeroy", fillcolor="rgba(168,85,247,0.12)",
            hovertemplate="%{x|%H:%M:%S}<br>Net GEX: $%{y:+.1f}M<extra></extra>",
        ), row=2, col=1, secondary_y=False)
    if df.get("spot") is not None and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines",
            line=dict(color=ORANGE, width=1.1, dash="dot"), showlegend=False,
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), row=2, col=1, secondary_y=True)

    # ── Row 3: Convexity (VEX) ─────────────────────────────────────────────
    if df.get("net_vex_mm") is not None and df["net_vex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_vex_mm"], mode="lines",
            name="Net VEX", line=dict(color=CYAN, width=1.8),
            fill="tozeroy", fillcolor="rgba(6,182,212,0.14)",
            hovertemplate="%{x|%H:%M:%S}<br>Net VEX: $%{y:+.1f}M<extra></extra>",
        ), row=3, col=1, secondary_y=False)
    if df.get("spot") is not None and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines",
            line=dict(color=ORANGE, width=1.1, dash="dot"), showlegend=False,
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), row=3, col=1, secondary_y=True)

    # Zero reference on each exposure axis
    for r in (1, 2, 3):
        fig.add_hline(y=0, line_dash="dot",
                      line_color="rgba(255,255,255,0.12)", line_width=1,
                      row=r, col=1, secondary_y=False)

    fig.update_layout(
        height=820,
        title=dict(
            text=f"  ORDERFLOW  ·  {symbol}  ·  {len(df)} snapshots",
            font=dict(size=12, color="#c0c0d8", family=FONT_MONO), x=0,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.04,
                    xanchor="right", x=1,
                    font=dict(size=9, color="#9090b0"),
                    bgcolor="rgba(0,0,0,0)"),
        **{k: v for k, v in BASE.items() if k != "legend"},
    )
    fig.update_xaxes(**AX_NOZERO)
    # Exposure y-axes
    fig.update_yaxes(**AX_ZERO, title_text="DEX $M", row=1, col=1, secondary_y=False)
    fig.update_yaxes(**AX_ZERO, title_text="GEX $M", row=2, col=1, secondary_y=False)
    fig.update_yaxes(**AX_ZERO, title_text="VEX $M", row=3, col=1, secondary_y=False)
    # Spot overlay axes
    for r in (1, 2, 3):
        fig.update_yaxes(**_AX_SECONDARY, title_text="Spot $",
                         row=r, col=1, secondary_y=True, showgrid=False)

    # Smaller subplot titles
    for ann in fig.layout.annotations:
        ann.font.update(size=10, color="#606080", family=FONT_MONO)
    return fig
