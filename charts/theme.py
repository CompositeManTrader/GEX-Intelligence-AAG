"""Plotly dark theme — shared palette + base layout dicts."""
from __future__ import annotations

BG_DARK = "#0b0b14"
BG_PLOT = "#0e0e1a"
GRID_CLR = "rgba(255,255,255,0.04)"
ORANGE = "#F5A623"
GREEN = "#16C784"
RED = "#EA3943"
BLUE = "#3b82f6"
PURPLE = "#a855f7"
CYAN = "#06b6d4"
FONT_MONO = "JetBrains Mono, Courier New, monospace"


BASE = dict(
    # Transparent paper so the glassmorphism chart frame (CSS .stPlotlyChart)
    # shows through; a barely-there plot tint keeps the data area legible.
    plot_bgcolor="rgba(255,255,255,0.014)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(size=11, family=FONT_MONO, color="#7070a0"),
    margin=dict(l=55, r=24, t=42, b=36),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(size=10, color="#9090b0"), bgcolor="rgba(0,0,0,0)"),
    hoverlabel=dict(bgcolor="#1a1a2a", font_size=11, font_family=FONT_MONO,
                    bordercolor="#3a3a4a", font_color="#e0e0f0"),
)
AX = dict(
    showgrid=True, gridcolor=GRID_CLR,
    linecolor="#1a1a2a", linewidth=1, showline=True,
    tickfont=dict(size=10, family=FONT_MONO, color="#606080"),
    title_font=dict(size=10, color="#606080"),
)
AX_ZERO = dict(**AX, zeroline=True, zerolinecolor="rgba(255,255,255,0.08)", zerolinewidth=1)
AX_NOZERO = dict(**AX, zeroline=False)


def vline(fig, x, row=None, col=None, color=None, label=True, text=None):
    clr = color or "rgba(245,166,35,0.5)"
    kw = dict(x=x, line_dash="dot", line_color=clr, line_width=1.2)
    if label:
        kw.update(annotation_text=text or f"  ${x:.0f}",
                  annotation_font_size=9, annotation_font_color=clr)
    if row:
        kw.update(row=row, col=col)
    fig.add_vline(**kw)


def hline(fig, y, color, label, width=1, dash="dot", row=None, col=None):
    kw = dict(y=y, line_dash=dash, line_color=color, line_width=width,
              annotation_text=f"  {label}",
              annotation_font_size=9, annotation_font_color=color,
              annotation_position="top right")
    if row:
        kw.update(row=row, col=col)
    fig.add_hline(**kw)


def fmt_money(x: float) -> str:
    if abs(x) >= 1e9:
        return f"${x/1e9:+.2f}B"
    if abs(x) >= 1e6:
        return f"${x/1e6:+.0f}M"
    if abs(x) >= 1e3:
        return f"${x/1e3:+.0f}K"
    return f"${x:+.0f}"
