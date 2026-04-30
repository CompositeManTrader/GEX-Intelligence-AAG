"""
Orderflow PRO — richer visualisations of the dealer-exposure tick stream.

Replaces the static three-snapshot stack with:
  · stacked-area Net GEX composition (call vs put), spot overlay,
    walls drawn as continuous trajectories (not "latest" horizontal lines)
  · velocity panel — ∂GEX/∂t in $M/min, anomaly-coloured
  · DEX & VEX with per-DTE-bucket lines (0DTE / week / month)
  · z-score badges on every panel title
  · per-strike GEX heatmap over time
  · cumulative dealer hedge flow estimate
  · what-changed top-movers table
  · wall-stability widget (current value, age, stdev)

All functions are pure: take a history list (and optional auxiliary
inputs) and return a Plotly figure or HTML string. No I/O.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.theme import (
    AX_NOZERO, AX_ZERO, BASE, CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED,
)
from quant.orderflow_derived import (
    cumulative_hedge_flow, velocity, wall_stability, what_changed,
    zscore_intraday,
)


_AX_SECONDARY = {k: v for k, v in AX_NOZERO.items() if k != "showgrid"}


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _prepare(history: list) -> Optional[pd.DataFrame]:
    if not history:
        return None
    df = pd.DataFrame(history)
    if "timestamp" not in df.columns:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    if df.empty:
        return None
    try:
        df["timestamp"] = df["timestamp"].dt.tz_convert("America/New_York")
    except Exception:
        pass
    return df.reset_index(drop=True)


def _z_badge(z: Optional[float]) -> str:
    if z is None:
        return ""
    sym = "▲" if z > 0 else ("▼" if z < 0 else "·")
    flag = "  ⚠" if abs(z) >= 2.0 else ""
    return f"   ·   z {sym}{abs(z):.1f}σ{flag}"


# ─────────────────────────────────────────────────────────────────────────────
#  Main 4-row chart — composition + velocity + DEX + VEX with buckets
# ─────────────────────────────────────────────────────────────────────────────
def chart_orderflow_pro_stack(history: list,
                              symbol: str = "") -> Optional[go.Figure]:
    df = _prepare(history)
    if df is None:
        return None

    # Compute derived metrics from the raw (UTC) history once. Pass the
    # original list — derived helpers handle their own ET conversion.
    z_gex = zscore_intraday(history, "net_gex_mm")
    z_dex = zscore_intraday(history, "net_dex_mm")
    z_vex = zscore_intraday(history, "net_vex_mm")

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.32, 0.18, 0.25, 0.25],
        specs=[
            [{"secondary_y": True}],
            [{"secondary_y": False}],
            [{"secondary_y": True}],
            [{"secondary_y": True}],
        ],
        subplot_titles=[
            f"Net GEX  ·  composition + walls trajectory{_z_badge(z_gex)}",
            "∂GEX/∂t  ·  velocity ($M / min)",
            f"DEX  ·  by DTE bucket{_z_badge(z_dex)}",
            f"Convexity (VEX)  ·  by DTE bucket{_z_badge(z_vex)}",
        ],
    )

    # ── Row 1: Net GEX stacked area + walls trajectory + spot ─────────────
    if "call_gex_mm" in df.columns and df["call_gex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["call_gex_mm"],
            name="Call GEX (stacked +)", mode="lines",
            line=dict(color=GREEN, width=0.8),
            fill="tozeroy", fillcolor="rgba(34,197,94,0.18)",
            hovertemplate="%{x|%H:%M:%S}<br>Call GEX: $%{y:+.1f}M<extra></extra>",
        ), row=1, col=1, secondary_y=False)
    if "put_gex_mm" in df.columns and df["put_gex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["put_gex_mm"],
            name="Put GEX (stacked −)", mode="lines",
            line=dict(color=RED, width=0.8),
            fill="tozeroy", fillcolor="rgba(244,63,94,0.18)",
            hovertemplate="%{x|%H:%M:%S}<br>Put GEX: $%{y:+.1f}M<extra></extra>",
        ), row=1, col=1, secondary_y=False)
    if "net_gex_mm" in df.columns and df["net_gex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_gex_mm"],
            name="Net GEX", mode="lines",
            line=dict(color="#e0e0f0", width=2.0),
            hovertemplate="%{x|%H:%M:%S}<br>Net GEX: $%{y:+.1f}M<extra></extra>",
        ), row=1, col=1, secondary_y=False)
    # Walls trajectory — continuous lines on the spot axis (not static refs)
    for key, color, label in (
        ("call_wall", GREEN, "CW"),
        ("put_wall",  RED,   "PW"),
        ("gamma_flip", PURPLE, "Zero Γ"),
    ):
        if key in df.columns and df[key].notna().any():
            fig.add_trace(go.Scatter(
                x=df["timestamp"], y=df[key], name=label, mode="lines",
                line=dict(color=color, width=1.0, dash="dash"),
                opacity=0.55, showlegend=True,
                hovertemplate=f"%{{x|%H:%M:%S}}<br>{label}: $%{{y:.0f}}<extra></extra>",
            ), row=1, col=1, secondary_y=True)
    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], name="Spot", mode="lines",
            line=dict(color=ORANGE, width=1.5),
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), row=1, col=1, secondary_y=True)

    # ── Row 2: GEX velocity ───────────────────────────────────────────────
    vel_df = velocity(history, "net_gex_mm", window_min=5)
    if vel_df is not None and not vel_df.empty:
        try:
            vel_df["timestamp"] = vel_df["timestamp"].dt.tz_convert("America/New_York")
        except Exception:
            pass
        v = vel_df["net_gex_mm_velocity_per_min"]
        # Adaptive threshold: 1σ of velocity itself; >2σ flags an anomaly.
        v_clean = v.dropna()
        sigma = float(v_clean.std(ddof=1)) if len(v_clean) > 2 else 0.0
        bar_colors = []
        for x in v:
            if not np.isfinite(x):
                bar_colors.append("rgba(0,0,0,0)")
            elif sigma > 0 and abs(x) >= 2 * sigma:
                bar_colors.append(RED if x < 0 else GREEN)
            elif sigma > 0 and abs(x) >= sigma:
                bar_colors.append("rgba(244,63,94,0.55)" if x < 0
                                  else "rgba(34,197,94,0.55)")
            else:
                bar_colors.append("rgba(168,85,247,0.5)")
        fig.add_trace(go.Bar(
            x=vel_df["timestamp"], y=v, marker_color=bar_colors,
            marker_line_width=0, name="∂GEX/∂t",
            hovertemplate="%{x|%H:%M:%S}<br>%{y:+.1f} $M/min<extra></extra>",
        ), row=2, col=1)
        fig.add_hline(y=0, line_dash="dot",
                      line_color="rgba(255,255,255,0.15)", row=2, col=1)

    # ── Row 3: DEX with DTE buckets ───────────────────────────────────────
    bucket_specs = [
        ("0dte", "0DTE",  CYAN),
        ("week", "Week",  ORANGE),
        ("month", "Month", PURPLE),
    ]
    for name, label, color in bucket_specs:
        col = f"dex_net_{name}_mm"
        if col in df.columns and df[col].notna().any():
            fig.add_trace(go.Scatter(
                x=df["timestamp"], y=df[col], name=f"DEX {label}",
                mode="lines", line=dict(color=color, width=1.4),
                hovertemplate=f"%{{x|%H:%M:%S}}<br>DEX {label}: $%{{y:+.1f}}M<extra></extra>",
            ), row=3, col=1, secondary_y=False)
    if "net_dex_mm" in df.columns and df["net_dex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_dex_mm"], name="DEX Total",
            mode="lines", line=dict(color="#e0e0f0", width=1.8),
            hovertemplate="%{x|%H:%M:%S}<br>DEX: $%{y:+.1f}M<extra></extra>",
        ), row=3, col=1, secondary_y=False)
    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines", showlegend=False,
            line=dict(color=ORANGE, width=1.0, dash="dot"),
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), row=3, col=1, secondary_y=True)

    # ── Row 4: VEX with DTE buckets ───────────────────────────────────────
    for name, label, color in bucket_specs:
        col = f"vex_net_{name}_mm"
        if col in df.columns and df[col].notna().any():
            fig.add_trace(go.Scatter(
                x=df["timestamp"], y=df[col], name=f"VEX {label}",
                mode="lines", line=dict(color=color, width=1.4, dash="dot"),
                hovertemplate=f"%{{x|%H:%M:%S}}<br>VEX {label}: $%{{y:+.1f}}M<extra></extra>",
                showlegend=False,
            ), row=4, col=1, secondary_y=False)
    if "net_vex_mm" in df.columns and df["net_vex_mm"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["net_vex_mm"], name="VEX Total",
            mode="lines", line=dict(color=CYAN, width=1.8),
            hovertemplate="%{x|%H:%M:%S}<br>VEX: $%{y:+.1f}M<extra></extra>",
        ), row=4, col=1, secondary_y=False)
    if "spot" in df.columns and df["spot"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["spot"], mode="lines", showlegend=False,
            line=dict(color=ORANGE, width=1.0, dash="dot"),
            hovertemplate="%{x|%H:%M:%S}<br>Spot: $%{y:.2f}<extra></extra>",
        ), row=4, col=1, secondary_y=True)

    # Zero refs
    for r in (1, 3, 4):
        fig.add_hline(y=0, line_dash="dot",
                      line_color="rgba(255,255,255,0.10)", row=r, col=1,
                      secondary_y=False)

    fig.update_layout(
        height=940,
        title=dict(
            text=f"  ORDERFLOW PRO  ·  {symbol}  ·  {len(df)} ticks",
            font=dict(size=12, color="#c0c0d8", family=FONT_MONO), x=0,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.04,
                    xanchor="right", x=1,
                    font=dict(size=9, color="#9090b0"),
                    bgcolor="rgba(0,0,0,0)"),
        **{k: v for k, v in BASE.items() if k != "legend"},
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO, title_text="GEX $M",   row=1, col=1, secondary_y=False)
    fig.update_yaxes(**_AX_SECONDARY, title_text="$",  row=1, col=1, secondary_y=True, showgrid=False)
    fig.update_yaxes(**AX_ZERO, title_text="$M / min", row=2, col=1)
    fig.update_yaxes(**AX_ZERO, title_text="DEX $M",   row=3, col=1, secondary_y=False)
    fig.update_yaxes(**_AX_SECONDARY, title_text="Spot $", row=3, col=1, secondary_y=True, showgrid=False)
    fig.update_yaxes(**AX_ZERO, title_text="VEX $M",   row=4, col=1, secondary_y=False)
    fig.update_yaxes(**_AX_SECONDARY, title_text="Spot $", row=4, col=1, secondary_y=True, showgrid=False)
    for ann in fig.layout.annotations:
        ann.font.update(size=10, color="#606080", family=FONT_MONO)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  Cumulative dealer hedge flow
# ─────────────────────────────────────────────────────────────────────────────
def chart_cum_hedge_flow(history: list,
                         symbol: str = "") -> Optional[go.Figure]:
    df = cumulative_hedge_flow(history)
    if df is None or df.empty:
        return None
    try:
        df["timestamp"] = df["timestamp"].dt.tz_convert("America/New_York")
    except Exception:
        pass
    fig = go.Figure()
    pos = df["cum_mm"].clip(lower=0)
    neg = df["cum_mm"].clip(upper=0)
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=pos, name="Long-γ counter-trend (positive)",
        line=dict(color=GREEN, width=1.4),
        fill="tozeroy", fillcolor="rgba(34,197,94,0.16)",
        hovertemplate="%{x|%H:%M:%S}<br>Cum: $%{y:+.0f}M<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=neg, name="Short-γ pro-trend (negative)",
        line=dict(color=RED, width=1.4),
        fill="tozeroy", fillcolor="rgba(244,63,94,0.16)",
        hovertemplate="%{x|%H:%M:%S}<br>Cum: $%{y:+.0f}M<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.20)")
    fig.update_layout(
        height=260,
        title=dict(
            text=f"  CUM DEALER HEDGE FLOW  ·  {symbol}  ·  Σ GEX × ΔSpot%",
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_ZERO, title_text="Cum hedge ($M·% units)")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  Per-strike GEX heatmap over time
# ─────────────────────────────────────────────────────────────────────────────
def chart_strike_heatmap(strike_history: list, symbol: str = "",
                         metric: str = "gex_mm",
                         spot_history: Optional[list] = None,
                         bucket: str = "month") -> Optional[go.Figure]:
    """Heatmap (strike × time) of per-strike `metric` over the session.

    `strike_history` is the long-format list from
    `data.persistence.load_strike_history`, i.e. dicts with
    {ts, strike, gex_mm, dex_mm, vex_mm}. `spot_history` (optional) is
    the orderflow tick history used to overlay the spot trajectory.
    """
    if not strike_history:
        return None
    df = pd.DataFrame(strike_history)
    if "ts" not in df.columns or "strike" not in df.columns:
        return None
    if metric not in df.columns:
        return None
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    df = df.dropna(subset=["ts", "strike", metric])
    if df.empty:
        return None
    try:
        df["ts"] = df["ts"].dt.tz_convert("America/New_York")
    except Exception:
        pass

    # Pivot to strike × time
    pv = df.pivot_table(index="strike", columns="ts", values=metric,
                        aggfunc="mean").sort_index()
    z = pv.to_numpy()
    if z.size == 0:
        return None
    # Symmetric colorscale around 0 — so positive / negative GEX read clearly
    vmax = float(np.nanpercentile(np.abs(z), 95)) if np.isfinite(z).any() else 1.0
    vmax = max(vmax, 1e-6)
    fig = go.Figure(data=go.Heatmap(
        z=z, x=pv.columns, y=pv.index,
        zmin=-vmax, zmax=vmax,
        colorscale=[
            [0.0, "rgba(244,63,94,0.95)"],
            [0.5, "rgba(20,20,36,0.0)"],
            [1.0, "rgba(34,197,94,0.95)"],
        ],
        colorbar=dict(title=f"{metric} ($M)", thickness=10),
        hovertemplate="%{x|%H:%M:%S}<br>K $%{y:.0f}<br>%{z:+.2f} $M<extra></extra>",
    ))
    # Spot overlay
    if spot_history:
        sdf = _prepare(spot_history)
        if sdf is not None and "spot" in sdf.columns:
            fig.add_trace(go.Scatter(
                x=sdf["timestamp"], y=sdf["spot"], mode="lines",
                line=dict(color=ORANGE, width=2),
                name="Spot",
                hovertemplate="%{x|%H:%M:%S}<br>Spot $%{y:.2f}<extra></extra>",
            ))
    fig.update_layout(
        height=420,
        title=dict(
            text=f"  STRIKE HEATMAP  ·  {symbol}  ·  bucket={bucket}",
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_NOZERO, title_text="Strike")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  HTML widgets — what changed + wall stability
# ─────────────────────────────────────────────────────────────────────────────
def panel_what_changed_html(rows_now: list[dict], rows_prev: list[dict],
                            metric: str = "Net_GEX",
                            top_n: int = 6) -> str:
    """Small HTML table of the top strike movers between two snapshots."""
    df_now = pd.DataFrame(rows_now or [])
    df_prev = pd.DataFrame(rows_prev or [])
    movers = what_changed(df_now, df_prev, metric=metric, top_n=top_n)
    if movers.empty:
        return ('<div style="color:#606080;font-size:0.72rem;'
                'font-family:JetBrains Mono,monospace;padding:0.4rem">'
                'Sin datos suficientes para detectar movers todavía.</div>')
    rows = []
    for _, r in movers.iterrows():
        d = float(r["delta"])
        clr = "#22c55e" if d > 0 else ("#f43f5e" if d < 0 else "#9090b0")
        sign = "▲" if d > 0 else ("▼" if d < 0 else "·")
        rows.append(
            f'<tr>'
            f'<td style="padding:3px 10px;color:#c0c0d8;'
            f'font-family:JetBrains Mono,monospace">${float(r["Strike"]):.0f}</td>'
            f'<td style="padding:3px 10px;color:#7070a0;text-align:right">'
            f'{float(r["prev"]):+.1f}</td>'
            f'<td style="padding:3px 10px;color:#e0e0f0;text-align:right">'
            f'{float(r["now"]):+.1f}</td>'
            f'<td style="padding:3px 10px;color:{clr};text-align:right;'
            f'font-weight:700">{sign} {abs(d):.1f}</td>'
            f'</tr>'
        )
    return (
        '<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;'
        'border-radius:6px;padding:0.6rem 0.8rem;margin:0.4rem 0;'
        'font-family:JetBrains Mono,monospace">'
        '<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.12em;'
        'margin-bottom:0.4rem">▤ TOP MOVERS  ·  '
        f'{metric}  ·  Δ entre snapshots</div>'
        '<table style="width:100%;border-collapse:collapse;font-size:0.74rem">'
        '<thead><tr>'
        '<th style="text-align:left;padding:2px 10px;color:#606080;'
        'font-weight:500">STRIKE</th>'
        '<th style="text-align:right;padding:2px 10px;color:#606080;'
        'font-weight:500">PREV $M</th>'
        '<th style="text-align:right;padding:2px 10px;color:#606080;'
        'font-weight:500">NOW $M</th>'
        '<th style="text-align:right;padding:2px 10px;color:#606080;'
        'font-weight:500">Δ</th>'
        '</tr></thead><tbody>'
        + "".join(rows) +
        '</tbody></table></div>'
    )


def panel_wall_stability_html(history: list) -> str:
    """Three-cell strip showing the current value, age and stdev of each wall.
    A wall that has held within ±1 strike for 60+ minutes is a *real* wall;
    one minted in the last 5 minutes is noise."""
    cw = wall_stability(history, "call_wall")
    pw = wall_stability(history, "put_wall")
    gf = wall_stability(history, "gamma_flip")

    def _cell(label: str, color: str, w: dict) -> str:
        if not w:
            v = age = sd = "—"
        else:
            v = f"${w['current']:.0f}"
            age = f"{w['age_min']:.0f} min"
            sd = f"σ {w['stddev']:.1f}"
        return (
            f'<div style="flex:1 1 0;background:rgba(15,17,24,0.7);'
            f'border-left:3px solid {color};padding:0.5rem 0.7rem;'
            f'border-radius:0 4px 4px 0">'
            f'<div style="color:#6b7280;font-size:0.58rem;letter-spacing:0.12em">'
            f'{label}</div>'
            f'<div style="color:{color};font-size:1.05rem;font-weight:700;'
            f'font-family:JetBrains Mono,monospace">{v}</div>'
            f'<div style="color:#7070a0;font-size:0.66rem;'
            f'font-family:JetBrains Mono,monospace">{age}  ·  {sd}</div>'
            f'</div>'
        )

    return (
        '<div style="display:flex;gap:0.4rem;margin:0.3rem 0;">'
        + _cell("CW STABILITY",   "#22c55e", cw)
        + _cell("PW STABILITY",   "#f43f5e", pw)
        + _cell("Zero Γ STABILITY", "#a855f7", gf)
        + '</div>'
    )


def panel_cross_session_html(rows: list[dict],
                             metric_key: str = "net_gex_mm",
                             metric_label: str = "Net GEX") -> str:
    """Horizontal strip with `metric` at this minute on the previous N
    sessions. Pass the output of
    `data.persistence.load_intraday_at_time_of_day`.
    """
    if not rows:
        return ('<div style="color:#606080;font-size:0.72rem;'
                'font-family:JetBrains Mono,monospace;padding:0.4rem">'
                'Sin historia comparable de sesiones previas todavía.</div>')
    cells = []
    vals = [r.get(metric_key) for r in rows if r.get(metric_key) is not None]
    median = float(np.median(vals)) if vals else 0.0
    for r in rows:
        d = r.get("session_date", "?")
        v = r.get(metric_key)
        if v is None:
            txt, clr = "—", "#7070a0"
        else:
            v = float(v)
            txt = f"${v:+.0f}M"
            clr = "#22c55e" if v > 0 else ("#f43f5e" if v < 0 else "#9090b0")
        cells.append(
            f'<div style="flex:1 1 0;text-align:center;'
            f'background:rgba(15,17,24,0.7);border:1px solid #1e2230;'
            f'border-radius:4px;padding:0.4rem 0.3rem;font-family:'
            f'JetBrains Mono,monospace">'
            f'<div style="color:#7070a0;font-size:0.6rem">{d[5:]}</div>'
            f'<div style="color:{clr};font-size:0.85rem;font-weight:700">'
            f'{txt}</div></div>'
        )
    return (
        '<div style="margin:0.3rem 0">'
        '<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.12em;'
        'margin-bottom:0.3rem;font-family:JetBrains Mono,monospace">'
        f'▤ {metric_label.upper()} A ESTA HORA  ·  últimas {len(rows)} sesiones'
        f'  ·  mediana ${median:+.0f}M</div>'
        '<div style="display:flex;gap:0.3rem">'
        + "".join(cells) +
        '</div></div>'
    )
