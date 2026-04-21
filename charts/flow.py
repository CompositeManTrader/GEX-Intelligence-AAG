"""HIRO oscillator visualizations — per-strike bars + time-series panel."""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.theme import (
    AX_NOZERO, AX_ZERO, BASE, CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED, vline,
)


def chart_hiro_strike(flow_df: pd.DataFrame, spot: float,
                      symbol: str = "") -> Optional[go.Figure]:
    """Per-strike dealer-flow breakdown: call buy pressure vs put sell pressure."""
    if flow_df is None or flow_df.empty:
        return None
    # Focus around spot to keep chart legible
    df = flow_df[
        (flow_df["Strike"] >= spot * 0.90) & (flow_df["Strike"] <= spot * 1.10)
    ].copy()
    if df.empty:
        df = flow_df.copy()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=df["Strike"], x=df["C_Flow"], orientation="h",
        name="Call Flow (buy pressure)",
        marker=dict(color="rgba(34,197,94,0.78)", line=dict(width=0)),
        hovertemplate="Strike $%{y:.1f}<br>Call flow: %{x:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=df["Strike"], x=df["P_Flow"], orientation="h",
        name="Put Flow (sell pressure)",
        marker=dict(color="rgba(244,63,94,0.78)", line=dict(width=0)),
        hovertemplate="Strike $%{y:.1f}<br>Put flow: %{x:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        y=df["Strike"], x=df["Net_Flow"], mode="markers", name="Net HIRO",
        marker=dict(symbol="diamond", size=5, color="#fbbf24",
                    line=dict(width=1, color="#000")),
        hovertemplate="Strike $%{y:.1f}<br>Net HIRO: %{x:+,.0f}<extra></extra>",
    ))
    fig.add_hline(y=spot, line_dash="solid", line_color=ORANGE, line_width=2,
                  annotation_text=f"  SPOT ${spot:.2f}",
                  annotation_font_color=ORANGE, annotation_font_size=11,
                  annotation_position="top right")
    fig.update_layout(
        height=480, barmode="relative",
        title=dict(
            text=f"  HIRO BY STRIKE  ·  {symbol}  ·  Net dealer hedge pressure",
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        xaxis_title="Flow  (volume × |Δ|)",
        yaxis_title="Strike",
        **BASE,
    )
    fig.update_xaxes(**AX_ZERO)
    fig.update_yaxes(**AX_NOZERO)
    return fig


def chart_hiro_oscillator(history: list, symbol: str = "") -> Optional[go.Figure]:
    """Time-series HIRO oscillator — the SpotGamma-style panel.

    Panel 1: HIRO value (cumulative dealer-buy pressure across snapshots)
    Panel 2: Spot price overlay — correlation check
    """
    if not history or len(history) < 2:
        return None
    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    if df.empty:
        return None

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
        row_heights=[0.62, 0.38],
        subplot_titles=["HIRO  (Net dealer buy/sell pressure)",
                        "Spot price"],
    )

    # HIRO area
    clrs = ["rgba(34,197,94,0.6)" if v >= 0 else "rgba(244,63,94,0.6)"
            for v in df["hiro"]]
    fig.add_trace(go.Bar(
        x=df["timestamp"], y=df["hiro"], marker_color=clrs,
        marker_line_width=0, name="HIRO",
        hovertemplate="%{x|%H:%M:%S}<br>HIRO: %{y:+,.0f}<extra></extra>",
    ), row=1, col=1)
    # Smoothed line
    if len(df) >= 5:
        smooth = df["hiro"].rolling(5, min_periods=1).mean()
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=smooth, mode="lines", name="MA(5)",
            line=dict(color=PURPLE, width=1.5, dash="dot"),
            hovertemplate="%{x|%H:%M:%S}<br>MA5: %{y:+,.0f}<extra></extra>",
        ), row=1, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.15)",
                  row=1, col=1)

    # Spot
    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines+markers",
            name="Spot", line=dict(color=ORANGE, width=1.8),
            marker=dict(size=4),
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), row=2, col=1)

    fig.update_layout(
        height=430, showlegend=False,
        title=dict(
            text=f"  HIRO FLOW OSCILLATOR  ·  {symbol}  ·  "
                 f"{len(df)} snapshots",
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO, row=1, col=1,
                     title_text="Net flow")
    fig.update_yaxes(**AX_NOZERO, row=2, col=1, title_text="Spot ($)")
    for ann in fig.layout.annotations:
        ann.font.update(size=10, color="#606080", family=FONT_MONO)
    return fig
