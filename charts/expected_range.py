"""
Expected-range visualisations — estimator comparison, probability cone,
risk-neutral density, IV-vs-realized.

All functions are pure: take the analytics output of
`quant.expected_range` and return a Plotly figure. No I/O.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from charts.theme import (
    AX_NOZERO, AX_ZERO, BASE, CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED,
)

_METHOD_COLOR = {
    "IV Gaussian":   "#a78bfa",
    "Skew-adjusted": "#f59e0b",
    "Straddle MMM":  "#06b6d4",
    "Realized vol":  "#94a3b8",
}


# ─────────────────────────────────────────────────────────────────────────────
#  1. Estimator comparison — horizontal range bars
# ─────────────────────────────────────────────────────────────────────────────
def chart_estimator_comparison(estimates: list, spot: float,
                               symbol: str = "") -> Optional[go.Figure]:
    """One horizontal bar per estimator spanning [low, high], with the
    spot marked as a vertical reference. Lets the trader see at a glance
    which model implies a wider/narrower or skewed range."""
    if not estimates or not spot or spot <= 0:
        return None
    fig = go.Figure()
    labels = []
    for i, e in enumerate(estimates):
        ed = e if isinstance(e, dict) else e.to_dict()
        method = ed.get("method", f"E{i}")
        low = float(ed.get("low", spot))
        high = float(ed.get("high", spot))
        color = _METHOD_COLOR.get(method, "#9090b0")
        labels.append(method)
        # The range bar (low → high) as a thick line with end caps
        fig.add_trace(go.Scatter(
            x=[low, high], y=[method, method],
            mode="lines+markers",
            line=dict(color=color, width=8),
            marker=dict(size=10, color=color, symbol="line-ns-open",
                        line=dict(width=2, color=color)),
            name=method, showlegend=False,
            hovertemplate=(
                f"<b>{method}</b><br>"
                f"Low ${low:,.2f}<br>High ${high:,.2f}<br>"
                f"EM ±${ed.get('em_dollars', 0):.2f} "
                f"({ed.get('em_pct', 0):.2f}%)<extra></extra>"
            ),
        ))
        # Annotate the EM% at the right end
        fig.add_annotation(
            x=high, y=method,
            text=f"  ±{ed.get('em_pct', 0):.2f}%",
            showarrow=False, xanchor="left",
            font=dict(size=10, color=color, family=FONT_MONO),
        )

    fig.add_vline(
        x=spot, line_dash="solid", line_color=ORANGE, line_width=2,
        annotation_text=f"SPOT ${spot:,.2f}",
        annotation_font=dict(size=11, color=ORANGE, family=FONT_MONO),
        annotation_position="top",
    )
    fig.update_layout(
        height=max(220, 70 + 55 * len(estimates)),
        title=dict(
            text=f"  EXPECTED RANGE  ·  {symbol}  ·  estimadores 1σ",
            font=dict(size=12, color="#c0c0d8", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO, title_text="Precio")
    fig.update_yaxes(**AX_NOZERO, autorange="reversed")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  2. Probability cone
# ─────────────────────────────────────────────────────────────────────────────
def chart_prob_cone(cone_df: pd.DataFrame, spot: float,
                    symbol: str = "") -> Optional[go.Figure]:
    """Expanding ±1σ / ±2σ cone across DTE horizons. X = DTE, Y = price."""
    if cone_df is None or cone_df.empty or not spot or spot <= 0:
        return None
    fig = go.Figure()
    # Plot each sigma as a shaded band (upper + lower)
    for k, (alpha, color) in zip(
        sorted(cone_df["sigma"].unique()),
        [(0.18, "rgba(167,139,250,0.18)"), (0.09, "rgba(167,139,250,0.09)")],
    ):
        sub = cone_df[cone_df["sigma"] == k].sort_values("dte")
        x = sub["dte"].tolist()
        fig.add_trace(go.Scatter(
            x=x + x[::-1],
            y=sub["high"].tolist() + sub["low"].tolist()[::-1],
            fill="toself", fillcolor=color,
            line=dict(width=0), name=f"±{k:.0f}σ",
            hoverinfo="skip", showlegend=True,
        ))
    # Center line at spot
    fig.add_hline(y=spot, line_dash="dot", line_color=ORANGE, line_width=1.5,
                  annotation_text=f"SPOT ${spot:,.2f}",
                  annotation_font=dict(size=10, color=ORANGE, family=FONT_MONO))
    # Mark the band edges with dots + labels
    for k in sorted(cone_df["sigma"].unique()):
        sub = cone_df[cone_df["sigma"] == k].sort_values("dte")
        fig.add_trace(go.Scatter(
            x=sub["dte"], y=sub["high"], mode="markers+text",
            marker=dict(size=5, color=PURPLE),
            text=[f"${v:,.0f}" for v in sub["high"]],
            textposition="top center",
            textfont=dict(size=8, color="#9090b0", family=FONT_MONO),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=sub["dte"], y=sub["low"], mode="markers+text",
            marker=dict(size=5, color=PURPLE),
            text=[f"${v:,.0f}" for v in sub["low"]],
            textposition="bottom center",
            textfont=dict(size=8, color="#9090b0", family=FONT_MONO),
            showlegend=False, hoverinfo="skip",
        ))
    fig.update_layout(
        height=380,
        title=dict(
            text=f"  PROBABILITY CONE  ·  {symbol}  ·  rango ±σ por horizonte",
            font=dict(size=12, color="#c0c0d8", family=FONT_MONO), x=0,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=9, color="#9090b0"),
                    bgcolor="rgba(0,0,0,0)"),
        **{k: v for k, v in BASE.items() if k != "legend"},
    )
    fig.update_xaxes(**AX_NOZERO, title_text="DTE", dtick=1)
    fig.update_yaxes(**AX_NOZERO, title_text="Precio")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  3. Risk-neutral density
# ─────────────────────────────────────────────────────────────────────────────
def chart_risk_neutral_density(rnd: pd.DataFrame, spot: float,
                               levels: Optional[dict] = None,
                               symbol: str = "",
                               rnd_levels_data: Optional[dict] = None,
                               method: Optional[str] = None) -> Optional[go.Figure]:
    """The implied PDF extracted from the chain (SVI → Breeden-Litzenberger).

    Overlays:
      · a matched-σ Gaussian (visual skew / fat-tail comparison)
      · the inter-quartile range (P25–P75) shaded — the "likely zone"
      · percentile markers P10 / P25 / P50 / P75 / P90 as vertical lines
      · key levels (walls) with their implied P(below)
    `rnd_levels_data` is the dict from `quant.rnd.rnd_levels`.
    """
    if rnd is None or rnd.empty:
        return None
    k = rnd["strike"].to_numpy()
    p = rnd["pdf"].to_numpy()

    fig = go.Figure()

    pct = (rnd_levels_data or {}).get("percentiles", {})

    # ── Inter-quartile shaded zone (P25–P75) — the likely close range
    p25 = pct.get("p25")
    p75 = pct.get("p75")
    if p25 is not None and p75 is not None:
        mask = (k >= p25) & (k <= p75)
        if mask.any():
            fig.add_trace(go.Scatter(
                x=k[mask], y=p[mask], mode="lines",
                line=dict(width=0),
                fill="tozeroy", fillcolor="rgba(34,197,94,0.16)",
                name="IQR (P25–P75)", hoverinfo="skip",
            ))

    # ── Implied density curve
    fig.add_trace(go.Scatter(
        x=k, y=p, mode="lines", name="Implied PDF (RND)",
        line=dict(color=CYAN, width=2.4),
        fill="tozeroy", fillcolor="rgba(6,182,212,0.10)",
        hovertemplate="K $%{x:,.1f}<br>dens %{y:.5f}<extra></extra>",
    ))

    # ── Matched-σ Gaussian overlay (skew/fat-tail comparison)
    dk = np.gradient(k)
    mean = float(np.sum(k * p * dk))
    var = float(np.sum((k - mean) ** 2 * p * dk))
    sd = float(np.sqrt(max(var, 1e-12)))
    if sd > 0:
        gauss = np.exp(-0.5 * ((k - mean) / sd) ** 2) / (sd * np.sqrt(2 * np.pi))
        fig.add_trace(go.Scatter(
            x=k, y=gauss, mode="lines", name="Gaussiana (mismo σ)",
            line=dict(color="#9090b0", width=1.2, dash="dot"),
            hovertemplate="K $%{x:,.1f}<br>normal %{y:.5f}<extra></extra>",
        ))

    # ── Percentile markers (P10/25/50/75/90)
    pct_specs = [
        ("p10", "#f59e0b", "P10"), ("p25", "#22c55e", "P25"),
        ("p50", "#e0e0f0", "P50 (mediana)"),
        ("p75", "#22c55e", "P75"), ("p90", "#f59e0b", "P90"),
    ]
    for key, color, label in pct_specs:
        v = pct.get(key)
        if v is None:
            continue
        fig.add_vline(
            x=v, line_dash="dot", line_color=color, line_width=1.0,
            annotation_text=f"{label} ${v:,.1f}",
            annotation_font=dict(size=8, color=color, family=FONT_MONO),
            annotation_position="top",
        )

    # ── Spot
    fig.add_vline(x=spot, line_dash="solid", line_color=ORANGE, line_width=2,
                  annotation_text=f"SPOT ${spot:,.1f}",
                  annotation_font=dict(size=10, color=ORANGE, family=FONT_MONO),
                  annotation_position="top")

    # ── Key levels (walls) with implied P(below)
    level_colors = {"call_wall": GREEN, "put_wall": RED,
                    "hvl": CYAN, "gamma_flip": PURPLE}
    level_labels = {"call_wall": "CW", "put_wall": "PW",
                    "hvl": "HVL", "gamma_flip": "Zero Γ"}
    lp = (rnd_levels_data or {}).get("level_probs", {})
    for key, lvl in (levels or {}).items():
        if lvl is None:
            continue
        try:
            lvl = float(lvl)
        except (TypeError, ValueError):
            continue
        prob_txt = ""
        if key in lp:
            prob_txt = f" · P&lt;{lp[key]['p_below']*100:.0f}%"
        fig.add_vline(
            x=lvl, line_dash="dash",
            line_color=level_colors.get(key, "#9090b0"), line_width=1.1,
            annotation_text=f"{level_labels.get(key, key)} ${lvl:,.0f}{prob_txt}",
            annotation_font=dict(size=8,
                                 color=level_colors.get(key, "#9090b0"),
                                 family=FONT_MONO),
            annotation_position="bottom",
        )

    method_tag = f"  ·  fit: {method.upper()}" if method else ""
    fig.update_layout(
        height=420,
        title=dict(
            text=f"  RISK-NEUTRAL DENSITY  ·  {symbol}  ·  "
                 f"distribución implícita{method_tag}",
            font=dict(size=12, color="#c0c0d8", family=FONT_MONO), x=0,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=9, color="#9090b0"),
                    bgcolor="rgba(0,0,0,0)"),
        **{k2: v for k2, v in BASE.items() if k2 != "legend"},
    )
    fig.update_xaxes(**AX_NOZERO, title_text="Precio al vencimiento")
    fig.update_yaxes(**AX_ZERO, title_text="Densidad")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  4. IV vs Realized comparison
# ─────────────────────────────────────────────────────────────────────────────
def chart_iv_vs_realized(iv_pct: Optional[float], hv_pct: Optional[float],
                         straddle_em: Optional[float],
                         gaussian_em: Optional[float],
                         symbol: str = "") -> Optional[go.Figure]:
    """Two grouped comparisons: IV vs Realized vol, and Straddle-implied
    EM vs Gaussian EM. Quick read on whether vol is rich and whether the
    market is over/under-pricing the move vs the model."""
    if iv_pct is None and hv_pct is None:
        return None
    fig = go.Figure()
    # Vol comparison
    vols = []
    vlabels = []
    vcolors = []
    if iv_pct is not None:
        vols.append(iv_pct); vlabels.append("IV (implícita)"); vcolors.append("#a78bfa")
    if hv_pct is not None:
        vols.append(hv_pct); vlabels.append("HV (realizada)"); vcolors.append("#94a3b8")
    if vols:
        fig.add_trace(go.Bar(
            x=vlabels, y=vols, marker_color=vcolors,
            text=[f"{v:.1f}%" for v in vols], textposition="outside",
            name="Vol", showlegend=False,
            hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
        ))
    fig.update_layout(
        height=300,
        title=dict(
            text=f"  IV vs REALIZED  ·  {symbol}",
            font=dict(size=12, color="#c0c0d8", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO, title_text="Vol anualizada (%)")
    return fig
