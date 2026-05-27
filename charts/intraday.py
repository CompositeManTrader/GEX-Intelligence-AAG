"""
Intraday candlestick chart — Plotly native.

Rewrite of the previous lightweight-charts iframe implementation. Uses native
Plotly so it integrates cleanly with Streamlit's rerun cycle (no stale
JS-side state, no time-offset bugs, no iframe clock drift).

Features:
  - OHLC candles on the primary panel, volume histogram below.
  - All structural GEX levels as horizontal lines with right-side labels:
      SPOT · CW · PW · GF · HVL · MP · EM±
  - Anchored VWAP (from session open) as a dashed line with band highlight.
  - Hover: OHLC + change + % + volume.
  - X-axis in Eastern Time (market time) with market hours highlighting.
  - Session-profile helper: volume composition by 30-min buckets.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.theme import (
    AX_NOZERO, BASE, CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _anchored_vwap(df: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP: cum(price × vol) / cum(vol) from first bar.

    Forward-fills over zero-volume bars so the line is continuous even when
    the opening or intermediate candles have null volume (common in extended
    hours or low-liquidity names).
    """
    if df.empty or "volume" not in df.columns:
        return pd.Series(dtype=float)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].astype(float).fillna(0)
    pv = (typical * vol).cumsum()
    cv = vol.cumsum()
    vwap = pv / cv.where(cv > 0)
    # Forward-fill to paper over gaps, then back-fill the very first NaN
    # (happens when the opening candle has zero volume).
    return vwap.ffill().bfill()


def _as_et(dt_series: pd.Series) -> pd.Series:
    """Convert a UTC-aware or naive datetime series to US/Eastern.

    Defensive against:
      · Mixed-type input (string + Timestamp + numpy.datetime64) — coerce
        all via `pd.to_datetime(errors="coerce")`.
      · Already tz-aware in non-UTC zone — convert directly.
      · All-NaT input (e.g., a chain that came through with bad dates) —
        return the series unchanged so downstream `df.sort_values` and
        `df["date_et"].dt.date.max()` don't raise.
    """
    s = pd.to_datetime(dt_series, errors="coerce")
    if s.isna().all():
        return s  # nothing to convert; downstream handles empty/NaT
    if s.dt.tz is None:
        # Naive → assume UTC (Schwab pricehistory returns epoch ms which
        # we already pass through `utc=True`, but cached/pickled paths
        # have been observed to drop tz on some pandas versions).
        s = s.dt.tz_localize("UTC")
    return s.dt.tz_convert("America/New_York")


# ─────────────────────────────────────────────────────────────────────────────
#  Main chart
# ─────────────────────────────────────────────────────────────────────────────
def render_intraday_chart(
    price_df: pd.DataFrame,
    spot: float,
    gex_summary: Optional[dict],
    mp: Optional[float] = None,
    em_lo: Optional[float] = None,
    em_hi: Optional[float] = None,
    freq_min: int = 1,
    symbol: str = "",
    zones: Optional[list] = None,
    prev_close: Optional[float] = None,
    days: int = 1,
) -> Optional[go.Figure]:
    """Trading-grade intraday candlestick with full GEX overlay.

    Parameters
    ----------
    zones : optional list of `quant.zones.GammaZone` (or dicts) to
            overlay as horizontal bands behind the candles.
    prev_close : optional previous-session close, plotted as a thin
            reference line so the trader sees today's drift vs yesterday.
    days : number of trading days currently being shown. Drives x-axis
            rangebreaks (collapse weekends + overnight) for multi-day mode.

    Visualisation features (vs the legacy basic version):
      · Range-selector buttons (5m / 15m / 1H / Hoy / Todo)
      · Crosshair cursor (x + y spikes) — pro-grade hover
      · Y-axis autoranges to visible X window (zoom-friendly)
      · Pre-market / after-hours background shading
      · VWAP ±1σ bands around the anchored VWAP
      · Day high / low markers with horizontal extension
      · Walls annotated with `(±X%)` distance from spot
      · Rangebreaks hide weekends and overnight gaps in multi-day mode
      · Clean Plotly modebar (only useful tools)
    """
    if price_df is None or price_df.empty:
        return None
    df = price_df.copy().dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return None

    df["date_et"] = _as_et(df["date"])
    df = df.sort_values("date_et").reset_index(drop=True)
    vwap = _anchored_vwap(df)

    # Derived values
    q_last = float(df["close"].iloc[-1])
    q_open = float(df["open"].iloc[0])
    q_chg = q_last - q_open
    q_chg_p = (q_chg / q_open * 100) if q_open else 0.0
    hi_day = float(df["high"].max())
    lo_day = float(df["low"].min())
    hi_idx = int(df["high"].idxmax())
    lo_idx = int(df["low"].idxmin())
    hi_ts = df["date_et"].iloc[hi_idx]
    lo_ts = df["date_et"].iloc[lo_idx]

    # GEX levels
    cw = gex_summary.get("call_wall") if gex_summary else None
    pw = gex_summary.get("put_wall") if gex_summary else None
    gf = gex_summary.get("gamma_flip") if gex_summary else None
    hvl = gex_summary.get("hvl") if gex_summary else None

    # Two-row subplot (candles + volume)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02,
        row_heights=[0.78, 0.22],
    )

    # ── Pre/after-market background shading ─────────────────────────────────
    # Apply only when the chart actually contains bars in those windows
    # (i.e., user enabled "Extended hours"). Use shape `add_vrect` per
    # zone with x bounds from the actual data, not hardcoded times.
    if not df.empty:
        # Group by ET trading date and shade pre/post within each day
        df_et_dates = df["date_et"].dt.date
        for et_day in sorted(df_et_dates.unique()):
            day_mask = df_et_dates == et_day
            day_df = df.loc[day_mask]
            if day_df.empty:
                continue
            day_min = day_df["date_et"].min()
            day_max = day_df["date_et"].max()
            # 09:30 and 16:00 ET on this day, as tz-aware Timestamps
            try:
                rth_open = day_min.replace(hour=9, minute=30,
                                           second=0, microsecond=0)
                rth_close = day_min.replace(hour=16, minute=0,
                                            second=0, microsecond=0)
            except Exception:
                continue
            # Pre-market shading
            if day_min < rth_open:
                fig.add_vrect(
                    x0=day_min, x1=rth_open,
                    fillcolor="rgba(245,158,11,0.04)",
                    line=dict(width=0), layer="below",
                    row=1, col=1,
                )
            # After-hours shading
            if day_max > rth_close:
                fig.add_vrect(
                    x0=rth_close, x1=day_max,
                    fillcolor="rgba(120,120,150,0.05)",
                    line=dict(width=0), layer="below",
                    row=1, col=1,
                )

    # ── Gamma-zone bands (BEFORE candles so they sit "below") ──────────────
    if zones:
        for z in zones:
            zd = z if isinstance(z, dict) else z.to_dict()
            rank = int(zd.get("rank") or 0)
            side = zd.get("side") or "mixed"
            label = zd.get("label") or f"P{rank}"
            low = float(zd.get("low_strike") or 0)
            high = float(zd.get("high_strike") or 0)
            score_mm = float(zd.get("integrated_gex_mm") or 0)
            if low <= 0 or high <= 0:
                continue
            if abs(high - low) < 0.01:
                pad = max(0.25, abs(high) * 0.001)
                low_p, high_p = low - pad, high + pad
            else:
                low_p, high_p = low, high
            alpha = max(0.04, 0.16 - 0.05 * (rank - 1))
            if side == "call_dominant":
                fill, stroke_clr = f"rgba(34,197,94,{alpha})", "#22c55e"
            elif side == "put_dominant":
                fill, stroke_clr = f"rgba(244,63,94,{alpha})", "#f43f5e"
            else:
                fill, stroke_clr = f"rgba(245,158,11,{alpha})", "#f59e0b"
            fig.add_hrect(
                y0=low_p, y1=high_p,
                fillcolor=fill, opacity=1.0,
                line=dict(width=0), layer="below",
                annotation_text=f" {label} · ${score_mm:+.0f}M",
                annotation_position="top left",
                annotation_font=dict(size=9, color=stroke_clr,
                                     family=FONT_MONO),
                row=1, col=1,
            )

    # ── Candles ─────────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df["date_et"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        increasing=dict(line=dict(color="#26a69a", width=1),
                        fillcolor="#26a69a"),
        decreasing=dict(line=dict(color="#ef5350", width=1),
                        fillcolor="#ef5350"),
        name="OHLC", showlegend=False,
        hovertext=[
            f"O {o:.2f}  H {h:.2f}  L {l:.2f}  C {c:.2f}<br>Δ {c - o:+.2f} ({((c - o) / o * 100) if o else 0:+.2f}%)"
            for o, h, l, c in zip(df["open"], df["high"], df["low"], df["close"])
        ],
        hoverinfo="x+text",
    ), row=1, col=1)

    # ── VWAP + ±1σ bands ────────────────────────────────────────────────────
    if not vwap.empty and vwap.notna().any():
        # Compute rolling stdev of (typical price − VWAP) over the session.
        # Bands ±1σ visualise the "fair-zone" — price excursions outside
        # are mean-reversion candidates in POSITIVE Γ regime.
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        diff = (typical - vwap).astype(float)
        # Expanding-window stdev (no look-ahead) then clip to a stable
        # minimum so the band has visual presence at session open.
        sd = diff.expanding(min_periods=3).std(ddof=1).fillna(0.0)
        sd = sd.clip(lower=0.0)
        upper = vwap + sd
        lower = vwap - sd
        # Band fill — upper trace fills down to the lower trace
        fig.add_trace(go.Scatter(
            x=df["date_et"], y=upper, mode="lines",
            line=dict(color="rgba(167,139,250,0)", width=0),
            hoverinfo="skip", showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df["date_et"], y=lower, mode="lines",
            line=dict(color="rgba(167,139,250,0)", width=0),
            fill="tonexty", fillcolor="rgba(167,139,250,0.08)",
            hoverinfo="skip", showlegend=False,
        ), row=1, col=1)
        # VWAP line on top
        fig.add_trace(go.Scatter(
            x=df["date_et"], y=vwap, mode="lines", name="VWAP",
            line=dict(color="#a78bfa", width=1.2, dash="dash"),
            hovertemplate="VWAP %{y:.2f}<extra></extra>",
            showlegend=False,
        ), row=1, col=1)

    # ── Day high / low markers ──────────────────────────────────────────────
    # Plot as small triangles + annotation so the trader sees the time-of-day
    # of the session extremes — useful for "is the high being retested?"
    fig.add_trace(go.Scatter(
        x=[hi_ts], y=[hi_day], mode="markers+text",
        marker=dict(symbol="triangle-down", size=10, color="#22c55e",
                    line=dict(color="#0b0b14", width=1)),
        text=[f"H ${hi_day:.2f}"],
        textposition="top center",
        textfont=dict(size=9, color="#22c55e", family=FONT_MONO),
        hoverinfo="skip", showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=[lo_ts], y=[lo_day], mode="markers+text",
        marker=dict(symbol="triangle-up", size=10, color="#f43f5e",
                    line=dict(color="#0b0b14", width=1)),
        text=[f"L ${lo_day:.2f}"],
        textposition="bottom center",
        textfont=dict(size=9, color="#f43f5e", family=FONT_MONO),
        hoverinfo="skip", showlegend=False,
    ), row=1, col=1)

    # ── Volume bars with intensity grading ──────────────────────────────────
    # Color by direction (green up, red down) AND alpha proportional to
    # the bar's volume relative to the session max. Hot bars pop visually.
    vmax = float(df["volume"].max()) if df["volume"].max() > 0 else 1.0
    vol_colors = []
    for o, c, v in zip(df["open"], df["close"], df["volume"]):
        base = (38, 166, 154) if c >= o else (239, 83, 80)
        intensity = 0.35 + 0.55 * min(1.0, float(v) / vmax)
        vol_colors.append(f"rgba({base[0]},{base[1]},{base[2]},{intensity:.2f})")
    fig.add_trace(go.Bar(
        x=df["date_et"], y=df["volume"], marker_color=vol_colors,
        marker_line_width=0, name="Volume", showlegend=False,
        hovertemplate="Vol %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    # ── Horizontal GEX levels — with distance % from spot ──────────────────
    def _hline(y: Optional[float], color: str, label: str,
               dash: str = "dot"):
        if y is None or float(y) <= 0:
            return
        y_f = float(y)
        # Annotate with distance % from spot when spot is valid
        if spot and spot > 0 and label != "SPOT":
            dist_pct = (y_f - spot) / spot * 100
            ann = f" {label} {y_f:.2f}  ({dist_pct:+.2f}%)"
        else:
            ann = f" {label} {y_f:.2f}"
        fig.add_hline(
            y=y_f, line_dash=dash, line_color=color, line_width=1.1,
            annotation_text=ann,
            annotation_font=dict(size=9, color=color, family=FONT_MONO),
            annotation_position="right",
            row=1, col=1,
        )

    _hline(spot, ORANGE, "SPOT", dash="solid")
    _hline(cw, GREEN, "CW")
    _hline(pw, RED, "PW")
    _hline(gf, PURPLE, "GF", dash="dash")
    _hline(hvl, CYAN, "HVL", dash="dashdot")
    _hline(mp, "#94a3b8", "MP", dash="longdash")
    _hline(em_hi, "#c084fc", "EM+", dash="dot")
    _hline(em_lo, "#c084fc", "EM-", dash="dot")
    # Previous-session close — neutral grey, important reference.
    _hline(prev_close, "#9ca3af", "PrevClose", dash="dot")

    # ── Last candle live-price tag ──────────────────────────────────────────
    last_ts = df["date_et"].iloc[-1]
    last_clr = GREEN if q_chg >= 0 else RED
    fig.add_annotation(
        x=last_ts, y=q_last,
        text=f"  {q_last:.2f}  ({q_chg_p:+.2f}%)",
        showarrow=False, xanchor="left",
        font=dict(size=10, family=FONT_MONO, color="#fff"),
        bgcolor=last_clr, bordercolor=last_clr,
        borderpad=3, row=1, col=1,
    )

    # ── Layout + title ──────────────────────────────────────────────────────
    chg_sign = "+" if q_chg >= 0 else ""
    title_bits = [
        f"  {symbol}",
        f"${q_last:.2f}",
        f"<span style='color:{last_clr}'>{chg_sign}{q_chg:.2f} "
        f"({q_chg_p:+.2f}%)</span>",
        f"H ${hi_day:.2f}",
        f"L ${lo_day:.2f}",
        f"{freq_min}m",
    ]
    if prev_close and prev_close > 0:
        vs_prev = (q_last - prev_close) / prev_close * 100
        title_bits.insert(3, f"<span style='color:#9ca3af'>"
                              f"vs prev {vs_prev:+.2f}%</span>")
    title = "  ·  ".join(title_bits)

    fig.update_layout(
        height=620, showlegend=False,
        title=dict(
            text=title, font=dict(size=12, color="#c0c0d8", family=FONT_MONO),
            x=0,
        ),
        dragmode="zoom",  # default drag is zoom-rectangle (not pan)
        hovermode="x unified",  # one tooltip shared across rows
        # Restrict the modebar to relevant trading tools
        modebar=dict(
            remove=["lasso2d", "select2d", "autoScale2d"],
            bgcolor="rgba(0,0,0,0)",
            color="#9090b0",
            activecolor="#a78bfa",
        ),
        **BASE,
    )

    # ── X-axis: range selector + spikes + rangebreaks ──────────────────────
    rangeselector = dict(
        bgcolor="rgba(20,20,36,0.85)",
        activecolor="rgba(167,139,250,0.85)",
        bordercolor="#2a2a3a",
        borderwidth=1,
        font=dict(size=10, color="#c0c0d8", family=FONT_MONO),
        x=0.0, y=1.06, xanchor="left",
        buttons=[
            dict(count=15, label="15m", step="minute", stepmode="backward"),
            dict(count=1,  label="1H",  step="hour",   stepmode="backward"),
            dict(count=4,  label="4H",  step="hour",   stepmode="backward"),
            dict(step="day", count=1, label="Hoy",     stepmode="todate"),
            dict(step="all", label="Todo"),
        ],
    )

    # Range-breaks: when showing multiple days, collapse weekends and
    # overnight gaps so candles aren't visually crushed by empty time.
    # Skip rangebreaks on single-day view since there's nothing to hide.
    rangebreaks = []
    if days > 1:
        rangebreaks = [
            dict(bounds=["sat", "mon"]),       # hide weekends
            dict(bounds=[20, 4], pattern="hour"),  # hide overnight
        ]

    fig.update_xaxes(
        **AX_NOZERO,
        rangeslider=dict(visible=False),
        rangeselector=rangeselector,
        rangebreaks=rangebreaks,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikedash="dot",
        spikethickness=1,
        spikecolor="rgba(255,255,255,0.30)",
        row=1, col=1,
    )
    # Bottom (volume) x-axis: same rangebreaks but no selector
    fig.update_xaxes(
        **AX_NOZERO,
        rangebreaks=rangebreaks,
        row=2, col=1,
    )

    # ── Y-axis: spikes + autorange to visible X window ─────────────────────
    fig.update_yaxes(
        **AX_NOZERO, title_text="Precio",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikedash="dot",
        spikethickness=1,
        spikecolor="rgba(255,255,255,0.30)",
        autorange=True,
        fixedrange=False,
        row=1, col=1,
    )
    fig.update_yaxes(
        **AX_NOZERO, title_text="Vol",
        fixedrange=False, row=2, col=1,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  Session Profile — volume by hour bucket (horizontal bar)
# ─────────────────────────────────────────────────────────────────────────────
def chart_session_profile(price_df: pd.DataFrame,
                          symbol: str = "") -> Optional[go.Figure]:
    """Horizontal bar chart: cumulative volume per 30-min bucket of the
    latest session in ET. Shows where the volume concentrated during the day,
    which often delimits the intraday range."""
    if price_df is None or price_df.empty or "volume" not in price_df.columns:
        return None
    df = price_df.copy().dropna(subset=["open", "high", "low", "close", "volume"])
    if df.empty:
        return None
    df["date_et"] = _as_et(df["date"])
    # If `_as_et` returned an all-NaT series (its own fallback path on
    # malformed timestamps), `.dt.date.max()` returns NaT and the next
    # equality filter masks every row away → blank chart. Guard explicitly.
    if df["date_et"].isna().all():
        return None
    # Focus on the most recent session only
    last_day = df["date_et"].dt.date.max()
    if pd.isna(last_day):
        return None
    df = df[df["date_et"].dt.date == last_day]
    if df.empty:
        return None

    # 30-minute buckets, labeled by start time in ET
    df["bucket"] = df["date_et"].dt.floor("30min")
    grouped = df.groupby("bucket", as_index=False).agg(
        volume=("volume", "sum"),
        open=("open", "first"),
        close=("close", "last"),
    )
    grouped["label"] = grouped["bucket"].dt.strftime("%H:%M")
    # Color: green if close ≥ open in that bucket, else red.
    # Mask NaN (close or open missing) explicitly — `NaN >= NaN` is False
    # so legacy code colored those buckets red even though they're empty.
    nan_mask = grouped["close"].isna() | grouped["open"].isna()
    grouped["color"] = np.where(
        grouped["close"] >= grouped["open"],
        "rgba(34,197,94,0.78)", "rgba(244,63,94,0.78)",
    )
    grouped.loc[nan_mask, "color"] = "rgba(120,120,150,0.30)"

    total_vol = grouped["volume"].sum() or 1
    grouped["pct"] = grouped["volume"] / total_vol * 100

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=grouped["label"], x=grouped["volume"], orientation="h",
        marker=dict(color=grouped["color"], line=dict(width=0)),
        hovertemplate=(
            "%{y} ET<br>Vol %{x:,.0f}"
            "<br>%{customdata:.1f}% del día<extra></extra>"
        ),
        customdata=grouped["pct"],
        showlegend=False,
    ))
    # Highlight the busiest bucket
    if not grouped.empty:
        top_idx = int(grouped["volume"].idxmax())
        top_lbl = grouped.loc[top_idx, "label"]
        top_pct = grouped.loc[top_idx, "pct"]
        fig.add_annotation(
            x=grouped.loc[top_idx, "volume"],
            y=top_lbl,
            text=f" PEAK · {top_pct:.0f}%",
            showarrow=False, xanchor="left",
            font=dict(size=10, color="#fbbf24", family=FONT_MONO),
        )

    fig.update_layout(
        height=max(260, 22 * len(grouped) + 80),
        title=dict(
            text=f"  SESSION PROFILE  ·  {symbol}  ·  "
                 f"{last_day.strftime('%Y-%m-%d')}",
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        xaxis_title="Volume",
        yaxis_title="ET bucket (30m)",
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(autorange="reversed",
                     showgrid=False,
                     tickfont=dict(size=10, color="#9090b0", family=FONT_MONO))
    return fig
