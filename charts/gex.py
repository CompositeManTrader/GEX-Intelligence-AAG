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
                      ) -> Optional[go.Figure]:
    """
    view ∈ {"all", "net", "call", "put"} — controls which series are rendered.
    focus_pct: None → all strikes; float → ±pct window around spot.
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

    fig = go.Figure()
    if show_call:
        fig.add_trace(go.Bar(
            y=df["Strike"], x=df["C_GEX_M"], orientation="h", name="Call GEX",
            marker=dict(color="rgba(34,197,94,0.78)", line=dict(width=0)),
            hovertemplate="<b>Strike $%{y:.1f}</b><br>Call GEX: $%{x:.1f}M<extra></extra>",
        ))
    if show_put:
        fig.add_trace(go.Bar(
            y=df["Strike"], x=df["P_GEX_M"], orientation="h", name="Put GEX",
            marker=dict(color="rgba(244,63,94,0.78)", line=dict(width=0)),
            hovertemplate="<b>Strike $%{y:.1f}</b><br>Put GEX: $%{x:.1f}M<extra></extra>",
        ))
    if show_net:
        if net_as_bars:
            # Color each bar by sign for readability
            net_colors = [
                "rgba(34,197,94,0.78)" if v >= 0 else "rgba(244,63,94,0.78)"
                for v in df["Net_GEX_M"]
            ]
            fig.add_trace(go.Bar(
                y=df["Strike"], x=df["Net_GEX_M"], orientation="h", name="Net GEX",
                marker=dict(color=net_colors, line=dict(width=0)),
                hovertemplate="<b>Strike $%{y:.1f}</b><br>Net GEX: $%{x:+.1f}M<extra></extra>",
            ))
        else:
            fig.add_trace(go.Scatter(
                y=df["Strike"], x=df["Net_GEX_M"], mode="markers", name="Net GEX",
                marker=dict(symbol="diamond", size=5, color="#fbbf24",
                            line=dict(width=1, color="#000")),
                hovertemplate="<b>Strike $%{y:.1f}</b><br>Net GEX: $%{x:+.1f}M<extra></extra>",
            ))

    cw = summary.get("call_wall")
    pw = summary.get("put_wall")
    gf = summary.get("gamma_flip")
    hvl = summary.get("hvl")

    fig.add_hline(y=spot, line_dash="solid", line_color=ORANGE, line_width=2,
                  annotation_text=f"  SPOT ${spot:.2f}",
                  annotation_font_size=11, annotation_font_color=ORANGE,
                  annotation_position="top right")
    if cw is not None:
        fig.add_hline(y=cw, line_dash="dashdot", line_color=GREEN, line_width=1.2,
                      annotation_text=f"  CALL WALL ${cw:.0f}",
                      annotation_font_size=10, annotation_font_color=GREEN,
                      annotation_position="top right")
    if pw is not None:
        fig.add_hline(y=pw, line_dash="dashdot", line_color=RED, line_width=1.2,
                      annotation_text=f"  PUT WALL ${pw:.0f}",
                      annotation_font_size=10, annotation_font_color=RED,
                      annotation_position="bottom right")
    if gf is not None and (not cw or abs(gf - cw) > 0.5) and (not pw or abs(gf - pw) > 0.5):
        fig.add_hline(y=gf, line_dash="dot", line_color=PURPLE, line_width=1.4,
                      annotation_text=f"  ZERO Γ ${gf:.0f}",
                      annotation_font_size=10, annotation_font_color=PURPLE,
                      annotation_position="top right")
    if hvl is not None and (not cw or abs(hvl - cw) > 0.5) and (not pw or abs(hvl - pw) > 0.5):
        fig.add_hline(y=hvl, line_dash="dashdot", line_color=CYAN, line_width=1,
                      annotation_text=f"  HVL ${hvl:.0f}",
                      annotation_font_size=9, annotation_font_color=CYAN,
                      annotation_position="bottom right")
    fig.add_vline(x=0, line_dash="solid",
                  line_color="rgba(255,255,255,0.12)", line_width=1)

    regime = summary.get("regime", "NEUTRAL")
    total_bn = summary.get("total_gex", 0) / 1e9
    r_color = GREEN if regime == "POSITIVE" else (RED if regime == "NEGATIVE" else ORANGE)

    fig.update_layout(
        height=640, barmode="overlay",
        title=dict(
            text=f"  {symbol}  ·  {regime} Γ  ·  Net: ${total_bn:+.3f}B  ·  "
                 f"DTE ≤ {summary.get('max_dte', 60)}d  ·  "
                 f"{summary.get('n_strikes', 0)} strikes",
            font=dict(size=12, color=r_color, family=FONT_MONO), x=0
        ),
        xaxis_title="Gamma Exposure ($M per 1% move)",
        yaxis_title="Strike",
        **BASE,
    )
    fig.update_xaxes(**AX_ZERO)
    fig.update_yaxes(**AX_NOZERO, tickformat="$,.0f")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  GexBot-style GEX chart  —  horizontal bars + intraday price overlay
#  (dual X axis: GEX ($M) on top, wall-clock time on bottom, shared Y=strike)
# ─────────────────────────────────────────────────────────────────────────────
def chart_gex_gexbot_style(
    gex_df: pd.DataFrame,
    spot: float,
    summary: dict,
    symbol: str,
    intraday_df: Optional[pd.DataFrame] = None,
    focus_pct: Optional[float] = 0.03,
    view: str = "all",
) -> Optional[go.Figure]:
    """Replica del layout de gexbot.com.

    Muestra la distribución de Gamma Exposure por strike como barras
    horizontales (calls a la derecha en verde, puts a la izquierda en rojo),
    y superpone la curva del spot intradía usando un eje-X secundario
    (tiempo) que comparte el eje-Y (strike) con las barras.

    Parámetros
    ----------
    gex_df : DataFrame con columnas Strike, C_GEX, P_GEX, Net_GEX.
    spot : precio actual del subyacente.
    summary : dict con 'regime', 'call_wall', 'put_wall', 'gamma_flip',
              'total_gex', 'max_dte', 'n_strikes'.
    intraday_df : DataFrame de velas intradía (fetch_intraday). Opcional;
                  si se omite, solo se muestran las barras y los walls.
    focus_pct : filtro ±% alrededor del spot. `None` → todos los strikes.
    view : "all" | "net" | "call" | "put" — qué series renderizar.
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
    # When Net is the ONLY series shown, render it as sign-colored bars so
    # it has visual weight (dots alone look empty on an otherwise blank panel).
    net_as_bars = v == "net"

    fig = go.Figure()

    # ── GEX bars (xaxis=x, top) ─────────────────────────────────────────
    if show_call:
        fig.add_trace(go.Bar(
            y=df["Strike"], x=df["C_GEX_M"], orientation="h",
            name="Call GEX",
            marker=dict(color="rgba(34,197,94,0.85)", line=dict(width=0)),
            hovertemplate="Strike $%{y:.1f}<br>Call GEX: $%{x:.1f}M<extra></extra>",
            xaxis="x",
        ))
    if show_put:
        fig.add_trace(go.Bar(
            y=df["Strike"], x=df["P_GEX_M"], orientation="h",
            name="Put GEX",
            marker=dict(color="rgba(244,63,94,0.85)", line=dict(width=0)),
            hovertemplate="Strike $%{y:.1f}<br>Put GEX: $%{x:.1f}M<extra></extra>",
            xaxis="x",
        ))
    if show_net:
        if net_as_bars:
            net_colors = [
                "rgba(34,197,94,0.85)" if v >= 0 else "rgba(244,63,94,0.85)"
                for v in df["Net_GEX_M"]
            ]
            fig.add_trace(go.Bar(
                y=df["Strike"], x=df["Net_GEX_M"], orientation="h",
                name="Net GEX",
                marker=dict(color=net_colors, line=dict(width=0)),
                hovertemplate="Strike $%{y:.1f}<br>Net GEX: $%{x:+.1f}M<extra></extra>",
                xaxis="x",
            ))
        else:
            # Dots on top of Call+Put bars — gexbot-style overlay indicator.
            fig.add_trace(go.Scatter(
                y=df["Strike"], x=df["Net_GEX_M"], mode="markers",
                name="Net GEX",
                marker=dict(symbol="circle", size=6, color="#60a5fa",
                            line=dict(width=1, color="#1e40af")),
                hovertemplate="Strike $%{y:.1f}<br>Net GEX: $%{x:+.1f}M<extra></extra>",
                xaxis="x",
            ))

    # ── Intraday price curve (xaxis=x2, bottom) ─────────────────────────
    price_added = False
    if (intraday_df is not None and not intraday_df.empty
            and "close" in intraday_df.columns and "date" in intraday_df.columns):
        idf = intraday_df.copy()
        s = pd.to_datetime(idf["date"], errors="coerce")
        if s.dt.tz is None:
            s = s.dt.tz_localize("UTC")
        idf["date_et"] = s.dt.tz_convert("America/New_York")
        # Limit to the most recent session (gexbot shows today only)
        last_day = idf["date_et"].dt.date.max()
        idf = idf[idf["date_et"].dt.date == last_day]
        if not idf.empty:
            fig.add_trace(go.Scatter(
                x=idf["date_et"], y=idf["close"], mode="lines",
                name="Spot intraday",
                line=dict(color="#06b6d4", width=1.6),
                hovertemplate="%{x|%H:%M:%S} ET<br>$%{y:.2f}<extra></extra>",
                xaxis="x2",
            ))
            price_added = True

    # ── Zero-GEX vertical line (on primary xaxis) ───────────────────────
    fig.add_vline(x=0, line_dash="solid",
                  line_color="rgba(255,255,255,0.28)", line_width=1)

    # ── Wall lines + left-anchored colored labels (gexbot style) ────────
    cw = summary.get("call_wall")
    pw = summary.get("put_wall")
    gf = summary.get("gamma_flip")

    def _wall(y: Optional[float], color: str, dash: str = "dash",
              text_color: str = "#0b0b14") -> None:
        if y is None:
            return
        fig.add_hline(y=float(y), line_dash=dash,
                      line_color=color, line_width=1.3)
        fig.add_annotation(
            xref="paper", x=0.0, y=float(y), yref="y",
            text=f"  {float(y):.2f}  ",
            showarrow=False, xanchor="right", yanchor="middle",
            font=dict(size=10, color=text_color, family=FONT_MONO),
            bgcolor=color, bordercolor=color, borderpad=3,
        )

    # Order matters: draw spot LAST so its label renders on top
    _wall(cw, GREEN, dash="dash")
    _wall(pw, RED, dash="dash")
    if (gf is not None
            and (not cw or abs(gf - cw) > 0.5)
            and (not pw or abs(gf - pw) > 0.5)):
        _wall(gf, PURPLE, dash="dot", text_color="#ffffff")
    _wall(spot, "#e8e8f0", dash="solid")

    # ── Layout ──────────────────────────────────────────────────────────
    regime = summary.get("regime", "NEUTRAL")
    total_bn = summary.get("total_gex", 0) / 1e9
    r_color = GREEN if regime == "POSITIVE" else (RED if regime == "NEGATIVE" else ORANGE)
    n_strikes = summary.get("n_strikes", 0)
    max_dte = summary.get("max_dte", 60)

    xaxis2_cfg = dict(
        overlaying="x",
        side="bottom",
        showgrid=False,
        linecolor="#1a1a2a", showline=True,
        tickfont=dict(size=9, family=FONT_MONO, color="#06b6d4"),
        zeroline=False,
        anchor="y",
    )
    if not price_added:
        # Hide the unused secondary x-axis entirely
        xaxis2_cfg["visible"] = False

    fig.update_layout(
        height=680,
        barmode="overlay",
        title=dict(
            text=(f"  {symbol}  ·  {regime} Γ  ·  Net: ${total_bn:+.3f}B  ·  "
                  f"Spot ${spot:.2f}  ·  {n_strikes} strikes  ·  DTE ≤ {max_dte}d"),
            font=dict(size=11, color=r_color, family=FONT_MONO), x=0,
        ),
        xaxis=dict(
            title="Gamma Exposure ($M per 1% move)",
            side="top",
            zeroline=True,
            zerolinecolor="rgba(255,255,255,0.28)", zerolinewidth=1,
            showgrid=True, gridcolor="rgba(255,255,255,0.04)",
            linecolor="#1a1a2a", showline=True,
            tickfont=dict(size=10, family=FONT_MONO, color="#606080"),
            title_font=dict(size=10, color="#606080"),
        ),
        xaxis2=xaxis2_cfg,
        yaxis=dict(
            title="Strike",
            side="left",
            showgrid=True, gridcolor="rgba(255,255,255,0.04)",
            linecolor="#1a1a2a", showline=True,
            tickfont=dict(size=10, family=FONT_MONO, color="#a0a0c0"),
            title_font=dict(size=10, color="#606080"),
        ),
        plot_bgcolor=BG_PLOT,
        paper_bgcolor=BG_DARK,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.06,
                    xanchor="right", x=1,
                    font=dict(size=10, color="#9090b0"),
                    bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=85, r=30, t=72, b=40),
        hoverlabel=dict(bgcolor="#1a1a2a", font_family=FONT_MONO,
                        bordercolor="#3a3a4a", font_color="#e0e0f0"),
        font=dict(size=11, family=FONT_MONO, color="#7070a0"),
    )
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
    df = _focus_range(dex_df, spot, focus_pct).copy()
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
