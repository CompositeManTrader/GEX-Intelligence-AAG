"""GEX / VEX / CEX / DEX charts + cumulative + by-expiry + spot-grid curve."""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.theme import (
    AX_NOZERO, AX_ZERO, BASE, BG_DARK, BG_PLOT, CYAN, FONT_MONO, GREEN,
    ORANGE, PURPLE, RED, vline,
)


def _focus_range(df: pd.DataFrame, spot: float,
                 pct: Optional[float] = 0.10) -> pd.DataFrame:
    """Filter strikes to ±pct around spot. If pct is None → return everything.
    Falls back to the full df if the filter leaves <5 rows."""
    if df is None or df.empty:
        return pd.DataFrame()
    if pct is None or pct <= 0:
        return df
    lo, hi = spot * (1 - pct), spot * (1 + pct)
    fd = df[(df["Strike"] >= lo) & (df["Strike"] <= hi)]
    return fd if len(fd) >= 5 else df


# ─────────────────────────────────────────────────────────────────────────────
def chart_gex_profile(gex_df: pd.DataFrame, spot: float, summary: dict,
                      symbol: str,
                      focus_pct: Optional[float] = 0.08,
                      view: str = "all",
                      zones: Optional[list] = None,
                      ) -> Optional[go.Figure]:
    """
    view ∈ {"all", "net", "call", "put"} — controls which series are rendered.
    focus_pct: None → all strikes; float → ±pct window around spot.
    zones: optional list of `quant.zones.GammaZone` (or their dicts) to
           overlay as horizontal bands tagged P1/P2/P3.
    """
    if gex_df is None or gex_df.empty:
        return None
    df = _focus_range(gex_df, spot, focus_pct).copy()
    df["C_GEX_M"] = df["C_GEX"] / 1e6
    df["P_GEX_M"] = df["P_GEX"] / 1e6
    df["Net_GEX_M"] = df["Net_GEX"] / 1e6

    v = (view or "all").lower()
    show_call = v in ("all", "call")
    show_put = v in ("all", "put")
    show_net = v in ("all", "net")
    # In "net" mode, render Net as bars (more readable when it's the only series).
    net_as_bars = v == "net"

    # Glass-hero-consistent palette (emerald / rose / gold).
    C_CALL = "rgba(52,211,153,0.88)"
    C_PUT = "rgba(251,113,133,0.88)"
    C_GOLD = "#fbbf24"

    fig = go.Figure()

    # ── ATM focal band — a faint highlight around spot for instant anchoring ─
    atm_pad = max(spot * 0.0018, 0.2)
    fig.add_hrect(y0=spot - atm_pad, y1=spot + atm_pad,
                  fillcolor="rgba(249,115,22,0.06)", line_width=0, layer="below")

    if show_call:
        fig.add_trace(go.Bar(
            y=df["Strike"], x=df["C_GEX_M"], orientation="h", name="Call GEX",
            marker=dict(color=C_CALL, cornerradius=3,
                        line=dict(width=0.5, color="rgba(52,211,153,0.35)")),
            hovertemplate="<b>$%{y:.1f}</b>  ·  Call GEX $%{x:.1f}M<extra></extra>",
        ))
    if show_put:
        fig.add_trace(go.Bar(
            y=df["Strike"], x=df["P_GEX_M"], orientation="h", name="Put GEX",
            marker=dict(color=C_PUT, cornerradius=3,
                        line=dict(width=0.5, color="rgba(251,113,133,0.35)")),
            hovertemplate="<b>$%{y:.1f}</b>  ·  Put GEX $%{x:.1f}M<extra></extra>",
        ))
    if show_net:
        if net_as_bars:
            net_colors = [C_CALL if v >= 0 else C_PUT for v in df["Net_GEX_M"]]
            fig.add_trace(go.Bar(
                y=df["Strike"], x=df["Net_GEX_M"], orientation="h", name="Net GEX",
                marker=dict(color=net_colors, cornerradius=3, line=dict(width=0)),
                hovertemplate="<b>$%{y:.1f}</b>  ·  Net GEX $%{x:+.1f}M<extra></extra>",
            ))
        else:
            # Net as a smooth profile curve (gold) overlaying the call/put bars —
            # reads like a SpotGamma-style gamma profile, not scattered dots.
            dfo = df.sort_values("Strike")
            fig.add_trace(go.Scatter(
                y=dfo["Strike"], x=dfo["Net_GEX_M"], mode="lines", name="Net GEX",
                line=dict(color=C_GOLD, width=1.8, shape="spline", smoothing=0.6),
                fill="tozerox", fillcolor="rgba(251,191,36,0.07)",
                hovertemplate="<b>$%{y:.1f}</b>  ·  Net GEX $%{x:+.1f}M<extra></extra>",
            ))

    cw = summary.get("call_wall")
    pw = summary.get("put_wall")
    gf = summary.get("gamma_flip")
    hvl = summary.get("hvl")

    # ── Level rails as elegant pill badges in the right margin ──────────────
    # Subtle dotted rail across the plot + an outlined glass badge at the edge.
    # Single-line pills keep a low vertical footprint so adjacent strikes
    # (e.g. spot / HVL / put-wall within $1) don't stack into an unreadable mess.
    def _rail(y, label, color, dash="dot", width=1.1, op=0.5):
        fig.add_hline(y=y, line_dash=dash, line_color=color,
                      line_width=width, opacity=op)
        fig.add_annotation(
            xref="paper", x=1.0, y=y, yref="y", xanchor="left", xshift=8,
            text=f"{label} <b>${y:,.0f}</b>", showarrow=False, align="left",
            font=dict(size=8, color=color, family=FONT_MONO),
            bgcolor="rgba(11,11,20,0.85)", bordercolor=color,
            borderwidth=1, borderpad=2,
        )

    # SPOT — glow (thick translucent under-line) + bright core + solid pill.
    fig.add_hline(y=spot, line_color="rgba(249,115,22,0.22)", line_width=7)
    fig.add_hline(y=spot, line_color=ORANGE, line_width=1.8)
    fig.add_annotation(
        xref="paper", x=1.0, y=spot, yref="y", xanchor="left", xshift=8,
        text=f"SPOT <b>${spot:,.2f}</b>", showarrow=False, align="left",
        font=dict(size=8.5, color="#0b0b14", family=FONT_MONO),
        bgcolor=ORANGE, borderpad=2,
    )
    tol = max(spot * 0.0015, 0.2)  # ~0.15%: treat levels this close as coincident
    if cw is not None:
        _rail(cw, "CALL WALL", GREEN, dash="dashdot", width=1.3, op=0.6)
    if pw is not None:
        _rail(pw, "PUT WALL", RED, dash="dashdot", width=1.3, op=0.6)
    # `cw is None` rather than `not cw`: a legitimate strike of 0 on
    # penny underliers would have falsely suppressed the GF/HVL lines.
    if gf is not None and (cw is None or abs(gf - cw) > 0.5) and (pw is None or abs(gf - pw) > 0.5):
        _rail(gf, "ZERO Γ", PURPLE, dash="dot", width=1.4, op=0.6)
    # Skip the HVL pill when it sits on top of spot/CW/PW (redundant label).
    if (hvl is not None and abs(hvl - spot) > tol
            and (cw is None or abs(hvl - cw) > 0.5)
            and (pw is None or abs(hvl - pw) > 0.5)):
        _rail(hvl, "HVL · PIN", CYAN, dash="dot", width=1.1, op=0.55)

    # ── Gamma zones (P1/P2/P3) overlay ──────────────────────────────────
    # Horizontal bands spanning each zone's [low, high] strike range.
    # Stronger zones (P1) drawn with higher opacity. Side controls hue:
    #   call_dominant → green-ish, put_dominant → red, mixed → amber.
    if zones:
        # Per-side band colors with opacity scaled by rank (P1 = strongest)
        for z in zones:
            zd = z if isinstance(z, dict) else z.to_dict()
            rank = int(zd.get("rank") or 0)
            side = zd.get("side") or "mixed"
            label = zd.get("label") or f"P{rank}"
            low = float(zd.get("low_strike") or 0)
            high = float(zd.get("high_strike") or 0)
            peak = float(zd.get("peak_strike") or 0)
            score = float(zd.get("integrated_gex_mm") or 0)
            if low == 0 or high == 0:
                continue
            # Opacity ramp: P1 = 0.18, P2 = 0.12, P3+ = 0.07
            alpha = max(0.05, 0.20 - 0.06 * (rank - 1))
            if side == "call_dominant":
                fill = f"rgba(34,197,94,{alpha})"
                stroke = "#22c55e"
            elif side == "put_dominant":
                fill = f"rgba(244,63,94,{alpha})"
                stroke = "#f43f5e"
            else:
                fill = f"rgba(245,158,11,{alpha})"
                stroke = "#f59e0b"
            # Single-strike clusters (low == high) collapse `add_hrect`
            # to an invisible line. Same padding logic as intraday.py so
            # the band is at least visible. ~0.5% of spot is a sensible
            # half-width for an "atomic" cluster on equity-like underlyings.
            if abs(high - low) < 0.01:
                pad = max(0.25, abs(peak or spot) * 0.001)
                low_p, high_p = low - pad, high + pad
            else:
                low_p, high_p = low, high
            # The band: x spans the full GEX axis, y spans the strike cluster
            fig.add_hrect(
                y0=low_p, y1=high_p,
                fillcolor=fill, opacity=1.0,
                line=dict(color=stroke, width=0.6, dash="dot"),
                layer="below",
                annotation_text=(
                    f"{label} · ${peak:.0f} · ${score:+.0f}M"
                ),
                annotation_position="top left",
                annotation_font=dict(size=9, color=stroke, family=FONT_MONO),
            )

    fig.add_vline(x=0, line_dash="solid",
                  line_color="rgba(255,255,255,0.12)", line_width=1)

    regime = summary.get("regime", "NEUTRAL")
    total_bn = summary.get("total_gex", 0) / 1e9
    r_color = GREEN if regime == "POSITIVE" else (RED if regime == "NEGATIVE" else ORANGE)

    # Wider right margin so the level pills sit cleanly in the gutter.
    base = {k: v for k, v in BASE.items() if k != "margin"}
    fig.update_layout(
        height=640, barmode="overlay", bargap=0.14, hovermode="y unified",
        title=dict(
            text=(f"<b>{symbol}</b>  ·  <span style='color:{r_color}'>{regime} Γ"
                  f"</span>  ·  NET ${total_bn:+.2f}B  ·  DTE ≤ "
                  f"{summary.get('max_dte', 60)}d  ·  "
                  f"{summary.get('n_strikes', 0)} strikes"),
            font=dict(size=11.5, color="#8a8ab0", family=FONT_MONO), x=0.01,
        ),
        xaxis_title="Gamma Exposure  ·  $M per 1% move",
        yaxis_title=None,
        margin=dict(l=20, r=92, t=44, b=38),
        **base,
    )
    fig.update_xaxes(**AX_ZERO)
    fig.update_yaxes(**AX_NOZERO, tickformat="$,.0f", side="left")
    return fig



def chart_cum_gex(gex_df: pd.DataFrame, spot: float, summary: dict
                  ) -> Optional[go.Figure]:
    if gex_df is None or gex_df.empty or "CumGEX" not in gex_df.columns:
        return None
    df = gex_df.sort_values("Strike").copy()
    df["CumGEX_Bn"] = df["CumGEX"] / 1e9
    pos = df[df["CumGEX_Bn"] >= 0]
    neg = df[df["CumGEX_Bn"] < 0]
    fig = go.Figure()
    if not pos.empty:
        fig.add_trace(go.Scatter(
            x=pos["Strike"], y=pos["CumGEX_Bn"], mode="lines", name="+Cum GEX",
            line=dict(color=GREEN, width=2),
            fill="tozeroy", fillcolor="rgba(34,197,94,0.10)",
            hovertemplate="Strike $%{x}<br>Cum GEX: $%{y:+.2f}B<extra></extra>",
        ))
    if not neg.empty:
        fig.add_trace(go.Scatter(
            x=neg["Strike"], y=neg["CumGEX_Bn"], mode="lines", name="−Cum GEX",
            line=dict(color=RED, width=2),
            fill="tozeroy", fillcolor="rgba(244,63,94,0.10)",
            hovertemplate="Strike $%{x}<br>Cum GEX: $%{y:+.2f}B<extra></extra>",
        ))
    fig.add_hline(y=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.15)", line_width=1)
    vline(fig, spot, text=f"  SPOT ${spot:.2f}")
    gf = summary.get("gamma_flip")
    if gf:
        fig.add_vline(x=gf, line_dash="dot", line_color=PURPLE, line_width=1.4,
                      annotation_text=f"  ZERO Γ ${gf:.0f}",
                      annotation_font_size=10, annotation_font_color=PURPLE)
    fig.update_layout(height=240, xaxis_title="Strike",
                      yaxis_title="Cum GEX ($B)", **BASE)
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO)
    return fig


def chart_gex_curve(curve_df: pd.DataFrame, spot: float, summary: dict
                    ) -> Optional[go.Figure]:
    """Scenario chart: GEX(S') as spot varies ±10%. True gamma flip is the zero cross."""
    if curve_df is None or curve_df.empty:
        return None
    df = curve_df.copy()
    df["GEX_Bn"] = df["GEX"] / 1e9
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["Spot"], y=df["GEX_Bn"], mode="lines", name="GEX(S)",
        line=dict(color=CYAN, width=2), fill="tozeroy",
        fillcolor="rgba(6,182,212,0.08)",
        hovertemplate="Spot $%{x:.2f}<br>GEX: $%{y:+.2f}B<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)")
    vline(fig, spot, text=f"  SPOT ${spot:.2f}")
    gf = summary.get("gamma_flip")
    if gf:
        fig.add_vline(x=gf, line_dash="dot", line_color=PURPLE, line_width=1.4,
                      annotation_text=f"  ZERO Γ ${gf:.0f}",
                      annotation_font_size=10, annotation_font_color=PURPLE)
    fig.update_layout(height=260, xaxis_title="Spot hipotético",
                      yaxis_title="GEX agregado ($B)", **BASE)
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO)
    return fig


def chart_vex_profile(vex_df: pd.DataFrame, spot: float, summary: dict,
                      symbol: str, focus_pct: float = 0.10) -> Optional[go.Figure]:
    if vex_df is None or vex_df.empty:
        return None
    df = _focus_range(vex_df, spot, focus_pct).copy()
    df["C_VEX_M"] = df["C_VEX"] / 1e6
    df["P_VEX_M"] = df["P_VEX"] / 1e6
    df["Net_VEX_M"] = df["Net_VEX"] / 1e6
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["Strike"], y=df["C_VEX_M"], name="Call VEX",
        marker=dict(color="rgba(34,197,94,0.72)", line=dict(width=0)),
        hovertemplate="Strike $%{x:.1f}<br>Call VEX: $%{y:+.2f}M<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=df["Strike"], y=df["P_VEX_M"], name="Put VEX",
        marker=dict(color="rgba(244,63,94,0.72)", line=dict(width=0)),
        hovertemplate="Strike $%{x:.1f}<br>Put VEX: $%{y:+.2f}M<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["Strike"], y=df["Net_VEX_M"], name="Net VEX",
        mode="lines+markers",
        line=dict(color="#fbbf24", width=2),
        marker=dict(size=5, color="#fbbf24", line=dict(width=1, color="#000")),
        hovertemplate="Strike $%{x:.1f}<br>Net VEX: $%{y:+.2f}M<extra></extra>",
    ))
    vline(fig, spot, text=f"  SPOT ${spot:.2f}")
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.12)")

    total_mn = summary.get("total_vex", 0) / 1e6
    regime = summary.get("regime", "NEUTRAL")
    r_color = GREEN if total_mn > 0 else (RED if total_mn < 0 else ORANGE)
    fig.update_layout(
        height=320, barmode="relative",
        title=dict(
            text=f"  VANNA EXPOSURE  ·  {symbol}  ·  {regime}  ·  "
                 f"Net: ${total_mn:+.1f}M per +1 vol pt",
            font=dict(size=11, color=r_color, family=FONT_MONO), x=0
        ),
        xaxis_title="Strike", yaxis_title="VEX ($M per +1 vol point)",
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO)
    return fig


def chart_cex_profile(cex_df: pd.DataFrame, spot: float, summary: dict,
                      symbol: str, focus_pct: float = 0.10) -> Optional[go.Figure]:
    if cex_df is None or cex_df.empty:
        return None
    df = _focus_range(cex_df, spot, focus_pct).copy()
    df["C_CEX_M"] = df["C_CEX"] / 1e6
    df["P_CEX_M"] = df["P_CEX"] / 1e6
    df["Net_CEX_M"] = df["Net_CEX"] / 1e6
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["Strike"], y=df["C_CEX_M"], name="Call CEX",
        marker=dict(color="rgba(34,197,94,0.72)", line=dict(width=0)),
        hovertemplate="Strike $%{x:.1f}<br>Call CEX: $%{y:+.2f}M/día<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=df["Strike"], y=df["P_CEX_M"], name="Put CEX",
        marker=dict(color="rgba(244,63,94,0.72)", line=dict(width=0)),
        hovertemplate="Strike $%{x:.1f}<br>Put CEX: $%{y:+.2f}M/día<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["Strike"], y=df["Net_CEX_M"], name="Net CEX",
        mode="lines+markers",
        line=dict(color="#fbbf24", width=2),
        marker=dict(size=5, color="#fbbf24", line=dict(width=1, color="#000")),
        hovertemplate="Strike $%{x:.1f}<br>Net CEX: $%{y:+.2f}M/día<extra></extra>",
    ))
    vline(fig, spot, text=f"  SPOT ${spot:.2f}")
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.12)")
    total_mn = summary.get("total_cex", 0) / 1e6
    regime = summary.get("regime", "NEUTRAL").replace("_", " ")
    r_color = GREEN if total_mn > 0 else (RED if total_mn < 0 else ORANGE)
    fig.update_layout(
        height=320, barmode="relative",
        title=dict(
            text=f"  CHARM EXPOSURE  ·  {symbol}  ·  {regime}  ·  "
                 f"Net: ${total_mn:+.1f}M por día",
            font=dict(size=11, color=r_color, family=FONT_MONO), x=0
        ),
        xaxis_title="Strike",
        yaxis_title="CEX ($M per 1 day of decay)",
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO)
    return fig


def chart_gex_by_expiry(exp_df: pd.DataFrame) -> Optional[go.Figure]:
    if exp_df is None or exp_df.empty:
        return None
    df = exp_df.copy()
    df["Abs"] = df["Net_GEX_M"].abs()
    df = df.nlargest(14, "Abs").sort_values("DTE")
    labels = [f"{str(r['Expiry'])[5:]}  ({r['DTE']}d)" for _, r in df.iterrows()]
    fig = go.Figure([
        go.Bar(x=labels, y=df["Call_GEX_M"], name="Calls",
               marker=dict(color="rgba(34,197,94,0.75)", line=dict(width=0)),
               hovertemplate="%{x}<br>Call GEX: $%{y:.1f}M<extra></extra>"),
        go.Bar(x=labels, y=df["Put_GEX_M"], name="Puts",
               marker=dict(color="rgba(244,63,94,0.75)", line=dict(width=0)),
               hovertemplate="%{x}<br>Put GEX: $%{y:.1f}M<extra></extra>"),
    ])
    fig.update_layout(height=280, barmode="relative",
                      xaxis_title="Expiración",
                      yaxis_title="GEX ($M)", **BASE)
    fig.update_xaxes(**AX_NOZERO, tickangle=-40)
    fig.update_yaxes(**AX_ZERO)
    return fig


def chart_dex_profile(dex_df: pd.DataFrame, spot: float, summary: dict,
                      symbol: str, focus_pct: float = 0.10) -> Optional[go.Figure]:
    if dex_df is None or dex_df.empty:
        return None
    # CRITICAL: sort by Strike before cumsum. `_focus_range` does NOT
    # guarantee strike order; the cumulative DEX trace was zigzagging
    # whenever the upstream df arrived unsorted, drawing visually
    # incorrect cumulative semantics (line jumped backward).
    df = _focus_range(dex_df, spot, focus_pct).sort_values("Strike").copy()
    df["C_DEX_M"] = df["C_DEX"] / 1e6
    df["P_DEX_M"] = df["P_DEX"] / 1e6
    df["Net_DEX_M"] = df["Net_DEX"] / 1e6
    fig = make_subplots(rows=2, cols=1, vertical_spacing=0.14,
                        row_heights=[0.62, 0.38],
                        subplot_titles=["DELTA EXPOSURE POR STRIKE",
                                        "NET DEX ACUMULADO"])
    fig.add_trace(go.Bar(
        x=df["Strike"], y=df["C_DEX_M"], name="Call DEX",
        marker=dict(color="rgba(34,197,94,0.72)", line=dict(width=0)),
        hovertemplate="Strike $%{x}<br>Call DEX: $%{y:+.1f}M<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=df["Strike"], y=df["P_DEX_M"], name="Put DEX",
        marker=dict(color="rgba(244,63,94,0.72)", line=dict(width=0)),
        hovertemplate="Strike $%{x}<br>Put DEX: $%{y:+.1f}M<extra></extra>",
    ), row=1, col=1)
    vline(fig, spot, row=1, col=1, text=f"  SPOT ${spot:.2f}")

    cum = df["Net_DEX"].cumsum() / 1e6
    fig.add_trace(go.Scatter(
        x=df["Strike"], y=cum, name="Cum Net DEX",
        line=dict(color=PURPLE, width=2),
        fill="tozeroy", fillcolor="rgba(168,85,247,0.07)",
        hovertemplate="Strike $%{x}<br>Cum DEX: $%{y:+.1f}M<extra></extra>",
    ), row=2, col=1)
    fig.add_hline(y=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.1)", row=2, col=1)
    vline(fig, spot, row=2, col=1)

    total = summary.get("total_dex", 0) / 1e6
    bias = summary.get("bias", "")
    clr = GREEN if total > 0 else RED
    fig.update_layout(
        height=520, barmode="relative",
        title=dict(text=f"  {symbol}  ·  DEX Total: ${total:+.0f}M  ·  {bias}",
                   font=dict(size=11, color=clr, family=FONT_MONO), x=0),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO, title_text="Strike")
    fig.update_yaxes(**AX_ZERO, title_text="DEX ($M)", row=1, col=1)
    fig.update_yaxes(**AX_ZERO, title_text="Cum DEX ($M)", row=2, col=1)
    for ann in fig.layout.annotations:
        ann.font.update(size=10, color="#606080", family=FONT_MONO)
    return fig
