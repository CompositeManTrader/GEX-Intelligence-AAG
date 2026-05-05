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
) -> Optional[go.Figure]:
    """Return a Plotly candlestick + volume + GEX-levels figure."""
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

    # ── VWAP line (anchored to session open) ───────────────────────────────
    if not vwap.empty and vwap.notna().any():
        fig.add_trace(go.Scatter(
            x=df["date_et"], y=vwap, mode="lines", name="VWAP",
            line=dict(color="#a78bfa", width=1.2, dash="dash"),
            hovertemplate="VWAP %{y:.2f}<extra></extra>",
            showlegend=False,
        ), row=1, col=1)

    # ── Volume bars ─────────────────────────────────────────────────────────
    vol_colors = [
        "rgba(38,166,154,0.55)" if c >= o else "rgba(239,83,80,0.55)"
        for o, c in zip(df["open"], df["close"])
    ]
    fig.add_trace(go.Bar(
        x=df["date_et"], y=df["volume"], marker_color=vol_colors,
        marker_line_width=0, name="Volume", showlegend=False,
        hovertemplate="Vol %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    # ── Horizontal GEX levels on candles panel ──────────────────────────────
    def _hline(y: Optional[float], color: str, label: str, dash: str = "dot"):
        if y is None or float(y) <= 0:
            return
        fig.add_hline(
            y=float(y), line_dash=dash, line_color=color, line_width=1.1,
            annotation_text=f" {label} {float(y):.2f}",
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

    # ── Annotate last candle with live price tag ────────────────────────────
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

    # ── Layout ──────────────────────────────────────────────────────────────
    chg_sign = "+" if q_chg >= 0 else ""
    title = (
        f"  {symbol}  ·  ${q_last:.2f}  "
        f"<span style='color:{last_clr}'>{chg_sign}{q_chg:.2f} "
        f"({q_chg_p:+.2f}%)</span>  ·  "
        f"H ${hi_day:.2f}  L ${lo_day:.2f}  ·  {freq_min}m"
    )

    fig.update_layout(
        height=560, showlegend=False,
        title=dict(
            text=title, font=dict(size=12, color="#c0c0d8", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO, rangeslider=dict(visible=False), row=1, col=1)
    fig.update_xaxes(**AX_NOZERO, row=2, col=1)
    fig.update_yaxes(**AX_NOZERO, title_text="Precio", row=1, col=1)
    fig.update_yaxes(**AX_NOZERO, title_text="Vol", row=2, col=1)
    # Disable plotly's range selector buttons for a cleaner look
    fig.update_layout(xaxis_rangeslider_visible=False)
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
    # Focus on the most recent session only
    last_day = df["date_et"].dt.date.max()
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
    # Color: green if close ≥ open in that bucket, else red
    grouped["color"] = np.where(
        grouped["close"] >= grouped["open"],
        "rgba(34,197,94,0.78)", "rgba(244,63,94,0.78)",
    )
    # Mark market-hour buckets bold
    grouped["is_mkt"] = grouped["bucket"].dt.time.between(
        pd.Timestamp("09:30").time(), pd.Timestamp("15:30").time()
    )

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
