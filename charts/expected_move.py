"""
Expected-move band chart for the 0DTE tab.

Renders a horizontal "ruler" centered on spot with sigma bands at
0.5σ / 1σ / 1.5σ / 2σ as semi-transparent rectangles. If an iron
condor suggestion is provided, the short strikes overlay as solid
vertical lines and the wings as dashed lines — at a glance the
trader sees where the IC sits relative to the implied range.
"""
from __future__ import annotations

from typing import Optional

import plotly.graph_objects as go

from charts.theme import (
    AX_NOZERO, AX_ZERO, BASE, FONT_MONO, GREEN, ORANGE, RED,
)


# Per-band colour ramp: smaller sigma = denser fill, larger = lighter.
_BAND_STYLE = {
    0.5: ("rgba(34,197,94,0.18)",  "#22c55e"),  # innermost — green-ish
    1.0: ("rgba(245,158,11,0.16)", "#f59e0b"),  # 1σ — amber
    1.5: ("rgba(168,85,247,0.13)", "#a855f7"),  # 1.5σ — purple
    2.0: ("rgba(244,63,94,0.10)",  "#f43f5e"),  # 2σ — outer — red
}


def chart_em_bands(analysis, symbol: str = "",
                   ic_suggestion=None) -> Optional[go.Figure]:
    """Render the expected-move bands as horizontal price bands.

    Parameters
    ----------
    analysis : EMAnalysis
        Output of `quant.expected_move.compute_em_bands`.
    symbol : str
        Title hint.
    ic_suggestion : IronCondorSuggestion or None
        If provided, overlays the IC strikes (short solid, long dashed).
    """
    if analysis is None or not analysis.bands:
        return None

    spot = analysis.spot
    bands = sorted(analysis.bands, key=lambda b: b.sigma, reverse=True)

    fig = go.Figure()

    # X axis goes 0..1 (proportion of session) so we can place legend
    # markers nicely. The price is on Y.
    # Draw the widest band first (so smaller bands stack on top).
    for b in bands:
        fill, stroke = _BAND_STYLE.get(b.sigma, ("rgba(120,120,180,0.12)",
                                                "#7070a0"))
        # Band rectangle as a closed polygon — easier to label than hrect
        # and supports independent annotation positioning.
        fig.add_shape(
            type="rect",
            x0=0, x1=1, xref="paper",
            y0=b.low, y1=b.high,
            fillcolor=fill, line=dict(color=stroke, width=0.8, dash="dot"),
            layer="below",
        )
        # Side labels — high & low of this band, with sigma multiple
        fig.add_annotation(
            x=1.0, xref="paper",
            y=b.high, yref="y",
            text=(f"  +{b.sigma:.1f}σ  ${b.high:,.2f}  "
                  f"P-touch {b.p_touch_high*100:.0f}%"),
            showarrow=False, xanchor="left",
            font=dict(size=9, color=stroke, family=FONT_MONO),
        )
        fig.add_annotation(
            x=1.0, xref="paper",
            y=b.low, yref="y",
            text=(f"  −{b.sigma:.1f}σ  ${b.low:,.2f}  "
                  f"P-touch {b.p_touch_low*100:.0f}%"),
            showarrow=False, xanchor="left",
            font=dict(size=9, color=stroke, family=FONT_MONO),
        )
        # P-inside label on the left margin
        fig.add_annotation(
            x=0.0, xref="paper",
            y=0.5 * (b.low + b.high),
            text=(f"  P-inside {b.p_inside*100:.0f}%"),
            showarrow=False, xanchor="left",
            font=dict(size=9, color=stroke, family=FONT_MONO),
        )

    # ── Spot line — bright, on top
    fig.add_shape(
        type="line",
        x0=0, x1=1, xref="paper",
        y0=spot, y1=spot,
        line=dict(color=ORANGE, width=2.5),
    )
    fig.add_annotation(
        x=0.5, xref="paper", y=spot,
        text=f"  SPOT ${spot:,.2f}  ·  1σ = ${analysis.sigma_move_dollars:.2f}",
        showarrow=False, yshift=10,
        font=dict(size=11, color=ORANGE, family=FONT_MONO),
        bgcolor="rgba(14,14,26,0.85)", borderpad=3,
    )

    # ── Iron condor overlay
    if ic_suggestion is not None:
        # Short strikes solid green/red, long strikes dashed
        for strike, color, label in [
            (ic_suggestion.short_call, GREEN, "SHORT CALL"),
            (ic_suggestion.long_call, GREEN, "LONG CALL"),
            (ic_suggestion.short_put, RED, "SHORT PUT"),
            (ic_suggestion.long_put, RED, "LONG PUT"),
        ]:
            is_long = "LONG" in label
            fig.add_shape(
                type="line",
                x0=0.05, x1=0.95, xref="paper",
                y0=strike, y1=strike,
                line=dict(
                    color=color, width=1.6,
                    dash="dot" if is_long else "solid",
                ),
                layer="above",
            )
            fig.add_annotation(
                x=0.05, xref="paper", y=strike,
                text=f"  {label} ${strike:,.0f}",
                showarrow=False, xanchor="left",
                font=dict(size=9, color=color, family=FONT_MONO),
                bgcolor="rgba(14,14,26,0.75)", borderpad=2,
            )

    # X axis is purely cosmetic — hide ticks
    fig.update_xaxes(visible=False, range=[0, 1])
    fig.update_yaxes(**AX_NOZERO, title_text="Price")

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
            f"IC POP {ic_suggestion.prob_of_profit*100:.0f}%"
        )
    fig.update_layout(
        height=380,
        title=dict(
            text="  " + "  ·  ".join(title_bits),
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
        margin=dict(l=80, r=180, t=50, b=20),
        **{k: v for k, v in BASE.items() if k not in ("margin",)},
    )
    return fig
