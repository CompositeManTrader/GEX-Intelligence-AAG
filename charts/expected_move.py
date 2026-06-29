"""
Expected-move band chart for the 0DTE tab.

Renders horizontal price bands at 0.5σ / 1σ / 1.5σ / 2σ around spot.
If an iron condor suggestion is provided, the short strikes overlay as
solid horizontal lines and the wings as dashed lines — the trader sees
at a glance where the IC sits relative to the implied range.

Implementation notes
--------------------
Earlier versions used `add_shape(type='rect', xref='paper', yref='y')`
which produced an empty plot because Plotly does NOT auto-range the
y-axis based on shapes — only on traces. The chart appeared empty with
y∈[-1, 4] regardless of the actual band prices.

Fix: render the bands as filled scatter traces (which DO contribute to
the y-axis auto-range), and set an explicit `range=[low_pad, high_pad]`
as a belt-and-suspenders guarantee.
"""
from __future__ import annotations

from typing import Optional

import plotly.graph_objects as go

from charts.theme import (
    AX_NOZERO, BASE, FONT_MONO, GREEN, ORANGE, RED,
)


# Per-band colour ramp: smaller sigma = denser fill, larger = lighter.
_BAND_STYLE = {
    0.5: ("rgba(22,199,132,0.22)",  "#16C784"),
    1.0: ("rgba(245,166,35,0.20)", "#F5A623"),
    1.5: ("rgba(168,85,247,0.16)", "#a855f7"),
    2.0: ("rgba(234,57,67,0.12)",  "#EA3943"),
}


def chart_em_bands(analysis, symbol: str = "",
                   ic_suggestion=None) -> Optional[go.Figure]:
    if analysis is None or not analysis.bands:
        return None

    spot = analysis.spot
    # Bands sorted small→large σ so smaller bands render last (on top).
    bands_small_first = sorted(analysis.bands, key=lambda b: b.sigma)
    bands_large_first = sorted(analysis.bands, key=lambda b: b.sigma, reverse=True)

    # ── Y-axis range — explicit, with 25% padding beyond the widest band.
    widest = bands_large_first[0]
    y_pad = max(0.5, 0.25 * (widest.high - widest.low))
    y_min = widest.low - y_pad
    y_max = widest.high + y_pad
    if ic_suggestion is not None:
        ic = (ic_suggestion if isinstance(ic_suggestion, dict)
              else ic_suggestion.to_dict())
        y_min = min(y_min, float(ic.get("long_put", y_min)) - 0.2 * y_pad)
        y_max = max(y_max, float(ic.get("long_call", y_max)) + 0.2 * y_pad)

    fig = go.Figure()

    # X axis is a synthetic "session" axis 0..1. The chart is essentially
    # a vertical ruler, but we use a real x range so traces auto-range too.
    X_LO, X_HI = 0.0, 1.0

    # ── Bands as filled scatter traces (widest first so they sit behind) ─
    for b in bands_large_first:
        fill, stroke = _BAND_STYLE.get(b.sigma, ("rgba(120,120,180,0.12)",
                                                "#7070a0"))
        fig.add_trace(go.Scatter(
            x=[X_LO, X_HI, X_HI, X_LO, X_LO],
            y=[b.low, b.low, b.high, b.high, b.low],
            fill="toself", fillcolor=fill,
            line=dict(color=stroke, width=0.7, dash="dot"),
            mode="lines",
            name=f"{b.sigma:.1f}σ band",
            hovertemplate=(
                f"<b>{b.sigma:.1f}σ band</b><br>"
                f"Low ${b.low:,.2f} · High ${b.high:,.2f}<br>"
                f"Width ${b.width:,.2f} ({b.width_pct:.2f}%)<br>"
                f"P-inside {b.p_inside*100:.1f}%<br>"
                f"PoT low {b.p_touch_low*100:.0f}% · "
                f"PoT high {b.p_touch_high*100:.0f}%"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

    # ── Per-band side labels (annotations anchored at right edge) ──────
    for b in bands_small_first:
        _, stroke = _BAND_STYLE.get(b.sigma, ("rgba(120,120,180,0.12)",
                                              "#7070a0"))
        fig.add_annotation(
            x=X_HI, y=b.high,
            text=(f"  +{b.sigma:.1f}σ  ${b.high:,.2f} "
                  f"· PoT {b.p_touch_high*100:.0f}%"),
            showarrow=False, xanchor="left",
            font=dict(size=10, color=stroke, family=FONT_MONO),
        )
        fig.add_annotation(
            x=X_HI, y=b.low,
            text=(f"  −{b.sigma:.1f}σ  ${b.low:,.2f} "
                  f"· PoT {b.p_touch_low*100:.0f}%"),
            showarrow=False, xanchor="left",
            font=dict(size=10, color=stroke, family=FONT_MONO),
        )

    # ── Spot line — bright orange, on top
    fig.add_trace(go.Scatter(
        x=[X_LO, X_HI], y=[spot, spot],
        mode="lines",
        line=dict(color=ORANGE, width=2.5),
        name="Spot", hoverinfo="skip", showlegend=False,
    ))
    fig.add_annotation(
        x=0.5, y=spot,
        text=(f"SPOT ${spot:,.2f}  ·  1σ = "
              f"${analysis.sigma_move_dollars:.2f}"),
        showarrow=False, yshift=12,
        font=dict(size=11, color=ORANGE, family=FONT_MONO),
        bgcolor="rgba(14,14,26,0.85)", borderpad=4,
    )

    # ── Iron condor overlay
    if ic_suggestion is not None:
        ic = (ic_suggestion if isinstance(ic_suggestion, dict)
              else ic_suggestion.to_dict())
        legs = [
            (float(ic["short_call"]), GREEN, "SHORT CALL", "solid"),
            (float(ic["long_call"]), GREEN, "LONG CALL", "dot"),
            (float(ic["short_put"]), RED, "SHORT PUT", "solid"),
            (float(ic["long_put"]), RED, "LONG PUT", "dot"),
        ]
        for strike, color, label, dash in legs:
            fig.add_trace(go.Scatter(
                x=[0.05, 0.6], y=[strike, strike],
                mode="lines",
                line=dict(color=color, width=1.6, dash=dash),
                name=label, hoverinfo="skip", showlegend=False,
            ))
            fig.add_annotation(
                x=0.05, y=strike,
                text=f"  {label} ${strike:,.0f}",
                showarrow=False, xanchor="left",
                font=dict(size=9, color=color, family=FONT_MONO),
                bgcolor="rgba(14,14,26,0.75)", borderpad=2,
            )

    # ── P-inside callouts on the LEFT side (paper-x = 0) for each band
    for b in bands_small_first:
        _, stroke = _BAND_STYLE.get(b.sigma, ("rgba(120,120,180,0.12)",
                                              "#7070a0"))
        fig.add_annotation(
            x=X_LO, y=0.5 * (b.low + b.high),
            text=f"P-in {b.p_inside*100:.0f}%  ",
            showarrow=False, xanchor="right",
            font=dict(size=9, color=stroke, family=FONT_MONO),
        )

    # ── Axes
    fig.update_xaxes(
        visible=False, range=[X_LO - 0.18, X_HI + 0.34],
        showgrid=False, zeroline=False,
    )
    fig.update_yaxes(
        **AX_NOZERO,
        title_text="Price", range=[y_min, y_max],
    )

    # ── Title
    minutes = analysis.minutes_to_close
    skew_tag = "skew-adj" if analysis.skew_adjusted else "symmetric"
    title_bits = [
        f"EM BANDS · {symbol}" if symbol else "EM BANDS",
        f"IV {analysis.iv_blend:.1f}%",
        skew_tag,
        f"T = {minutes:.0f} min",
    ]
    if ic_suggestion is not None:
        title_bits.append(
            f"IC POP {float(ic_suggestion.prob_of_profit)*100:.0f}%"
            if not isinstance(ic_suggestion, dict)
            else f"IC POP {float(ic_suggestion['prob_of_profit'])*100:.0f}%"
        )

    fig.update_layout(
        height=420,
        title=dict(
            text="  " + "  ·  ".join(title_bits),
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        margin=dict(l=90, r=200, t=50, b=20),
        **{k: v for k, v in BASE.items() if k != "margin"},
    )
    return fig
