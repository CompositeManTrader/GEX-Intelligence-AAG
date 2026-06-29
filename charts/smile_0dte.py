"""
0DTE volatility smile chart with gamma-walls overlay.

Single-panel curve: IV per strike for one expiry (typically 0DTE).
The X-axis is configurable so the trader can read the smile in the
mental model they prefer:

  · "strike"     — raw $ strike (default)
  · "moneyness"  — (K − S) / S × 100 in percent (signed)
  · "delta"      — |Δ| from the OTM-blended smile (0 ≈ wings, 0.5 ≈ ATM)

Overlays
--------
  · Spot vertical line (orange)
  · Walls (call_wall green, put_wall red, hvl/pin cyan, gamma_flip purple)
  · Rich-zone highlight: strikes whose IV > median + sigma·stdev
  · Optional IC strike markers when `ic_strikes` is provided

Inputs
------
`smile_df` is the output of `quant.ic_picker.build_smile_blend` — must
contain `Strike`, `Market_IV`, `C_IV`, `P_IV`, `Moneyness`, `Delta`.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from charts.theme import (
    AX_NOZERO, BASE, CYAN, FONT_MONO, GREEN, ORANGE, PURPLE, RED,
)
from quant.ic_picker import rich_zone_mask


def _x_values(smile_df: pd.DataFrame, x_axis: str, spot: float
              ) -> tuple[pd.Series, str]:
    """Return (x_series, x_axis_title) for the requested axis."""
    if x_axis == "moneyness":
        if "Moneyness" in smile_df.columns:
            return smile_df["Moneyness"], "Moneyness (%)"
        # fallback: compute
        return ((smile_df["Strike"] - spot) / spot * 100.0), "Moneyness (%)"
    if x_axis == "delta":
        if "Delta" in smile_df.columns:
            return smile_df["Delta"].abs(), "|Δ|"
    # default strike
    return smile_df["Strike"], "Strike"


def _wall_x(strike: float, x_axis: str, spot: float,
            smile_df: pd.DataFrame) -> Optional[float]:
    """Map a wall STRIKE to the chosen x-axis space."""
    if strike is None:
        return None
    if x_axis == "moneyness":
        return (float(strike) - spot) / spot * 100.0
    if x_axis == "delta":
        # Pull delta from the nearest strike row in the smile.
        # `idxmin()` returns the index label; with the reset_index in
        # `chart_smile_0dte` this aligns to position, but using `argmin`
        # (positional) makes the call invariant to caller index state.
        if smile_df.empty or "Delta" not in smile_df.columns:
            return None
        diffs = (pd.to_numeric(smile_df["Strike"], errors="coerce")
                 - float(strike)).abs().to_numpy()
        if not np.isfinite(diffs).any():
            return None
        pos = int(np.nanargmin(diffs))
        v = pd.to_numeric(smile_df["Delta"].iloc[pos], errors="coerce")
        return float(abs(v)) if pd.notna(v) else None
    return float(strike)


def chart_smile_0dte(
    smile_df: pd.DataFrame, spot: float,
    walls: Optional[dict] = None,
    x_axis: str = "strike",
    rich_sigma: float = 1.0,
    ic_strikes: Optional[dict] = None,
    symbol: str = "",
    expiry: str = "0DTE",
) -> Optional[go.Figure]:
    """Render the 0DTE volatility smile with walls overlay.

    Parameters
    ----------
    smile_df : DataFrame from `build_smile_blend` (must have Market_IV).
    spot, walls : current spot and the GEX summary (call_wall, put_wall,
                  hvl, gamma_flip). `walls` may be None.
    x_axis : "strike" | "moneyness" | "delta"
    rich_sigma : highlight strikes where IV > median + sigma·stdev.
    ic_strikes : dict {short_put, long_put, short_call, long_call}
                 — optional, overlays vertical markers for each leg.
    """
    if smile_df is None or smile_df.empty:
        return None
    if "Market_IV" not in smile_df.columns:
        return None
    df = smile_df.sort_values("Strike").reset_index(drop=True)

    x_series, x_title = _x_values(df, x_axis, spot)
    y_market = pd.to_numeric(df["Market_IV"], errors="coerce")

    fig = go.Figure()

    # ── Underlying call / put curves (faint, for context)
    if "C_IV" in df.columns and df["C_IV"].notna().any():
        fig.add_trace(go.Scatter(
            x=x_series, y=df["C_IV"], name="Call IV",
            mode="lines", line=dict(color=GREEN, width=1.0, dash="dot"),
            hovertemplate="K %{customdata:.0f}<br>Call IV: %{y:.1f}%<extra></extra>",
            customdata=df["Strike"],
        ))
    if "P_IV" in df.columns and df["P_IV"].notna().any():
        fig.add_trace(go.Scatter(
            x=x_series, y=df["P_IV"], name="Put IV",
            mode="lines", line=dict(color=RED, width=1.0, dash="dot"),
            hovertemplate="K %{customdata:.0f}<br>Put IV: %{y:.1f}%<extra></extra>",
            customdata=df["Strike"],
        ))

    # ── OTM-blended Market_IV — the headline smile curve
    fig.add_trace(go.Scatter(
        x=x_series, y=y_market, name="Market IV (OTM blend)",
        mode="lines+markers",
        line=dict(color=ORANGE, width=2.4),
        marker=dict(size=5, color=ORANGE,
                    line=dict(color="#0b0b14", width=1)),
        hovertemplate=(
            "K %{customdata[0]:.0f}<br>"
            "IV %{y:.1f}%<br>"
            "Δ %{customdata[1]:+.3f}<extra></extra>"
        ),
        customdata=np.stack(
            [df["Strike"].to_numpy(),
             (df["Delta"].to_numpy() if "Delta" in df.columns
              else np.zeros(len(df)))],
            axis=-1,
        ),
    ))

    # ── Rich-zone highlight (markers on top of the curve)
    mask = rich_zone_mask(df, sigma=rich_sigma)
    if mask.any():
        fig.add_trace(go.Scatter(
            x=x_series[mask], y=y_market[mask],
            mode="markers",
            marker=dict(size=11, color="rgba(234,57,67,0.0)",
                        line=dict(color=RED, width=2)),
            name=f"Rich zone (>mediana + {rich_sigma:.1f}σ)",
            hovertemplate=(
                "RICH<br>K %{customdata:.0f}<br>"
                "IV %{y:.1f}%<extra></extra>"
            ),
            customdata=df.loc[mask, "Strike"].to_numpy(),
        ))

    # ── Spot vertical line
    # In `delta` mode, spot maps to |Δ| ≈ 0.5 by definition (ATM call/put
    # delta) regardless of which strike is the spot — so the vline always
    # sits at the middle of the x-axis and conveys nothing. Skip drawing
    # the spot line in delta mode; the smile minimum already marks ATM.
    if x_axis != "delta":
        spot_x = _wall_x(spot, x_axis, spot, df)
        if spot_x is not None:
            fig.add_vline(
                x=spot_x, line_dash="solid", line_color=ORANGE, line_width=2,
                annotation_text=f"  SPOT ${spot:,.2f}",
                annotation_font=dict(size=10, color=ORANGE, family=FONT_MONO),
                annotation_position="top",
            )

    # ── Walls overlay
    walls = walls or {}
    wall_specs = [
        ("call_wall", GREEN, "CW", "dashdot"),
        ("put_wall", RED, "PW", "dashdot"),
        ("hvl", CYAN, "HVL", "dot"),
        ("gamma_flip", PURPLE, "Zero Γ", "dash"),
    ]
    for key, color, label, dash in wall_specs:
        v = walls.get(key)
        if v is None:
            continue
        wx = _wall_x(v, x_axis, spot, df)
        if wx is None:
            continue
        fig.add_vline(
            x=wx, line_dash=dash, line_color=color, line_width=1.2,
            annotation_text=f"  {label} ${v:,.0f}",
            annotation_font=dict(size=9, color=color, family=FONT_MONO),
            annotation_position="bottom",
        )

    # ── IC strike markers (when provided)
    if ic_strikes:
        legs = [
            ("short_put", RED, "SP", "solid"),
            ("long_put", RED, "LP", "dot"),
            ("short_call", GREEN, "SC", "solid"),
            ("long_call", GREEN, "LC", "dot"),
        ]
        for key, color, label, dash in legs:
            v = ic_strikes.get(key)
            if v is None:
                continue
            wx = _wall_x(v, x_axis, spot, df)
            if wx is None:
                continue
            fig.add_vline(
                x=wx, line_dash=dash, line_color=color, line_width=1.0,
                annotation_text=f"  {label}",
                annotation_position="top right",
                annotation_font=dict(size=9, color=color, family=FONT_MONO),
                opacity=0.7,
            )

    # ── Layout
    title = f"  0DTE SMILE  ·  {symbol}  ·  {expiry}"
    fig.update_layout(
        height=380,
        title=dict(
            text=title,
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        margin=dict(l=70, r=30, t=50, b=40),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1,
            font=dict(size=9, color="#9090b0"),
            bgcolor="rgba(0,0,0,0)",
        ),
        **{k: v for k, v in BASE.items()
           if k not in ("margin", "legend")},
    )
    fig.update_xaxes(**AX_NOZERO, title_text=x_title)
    fig.update_yaxes(**AX_NOZERO, title_text="IV (%)")
    return fig
