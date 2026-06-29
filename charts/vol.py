"""Greeks surface, IV skew, term structure, OI/volume, vol cone, IV/HV history, returns distribution."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.theme import (
    AX_NOZERO, AX_ZERO, BASE, BLUE, FONT_MONO, GREEN, ORANGE, PURPLE, RED, vline,
)


def chart_greeks(c: pd.DataFrame, p: pd.DataFrame, spot: float) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=["DELTA", "GAMMA", "THETA  (decay / día)", "IV SMILE"],
        vertical_spacing=0.22, horizontal_spacing=0.10,
    )
    for g, r, cc in [("Delta", 1, 1), ("Gamma", 1, 2),
                     ("Theta", 2, 1), ("IV%", 2, 2)]:
        for df, lbl, clr in [(c, "Calls", GREEN), (p, "Puts", RED)]:
            if df is None or df.empty or g not in df.columns:
                continue
            d = df.sort_values("Strike")
            fig.add_trace(go.Scatter(
                x=d["Strike"], y=d[g], name=lbl,
                line=dict(color=clr, width=2), mode="lines+markers",
                marker=dict(size=4, color=clr),
                showlegend=(r == 1 and cc == 1), legendgroup=lbl,
                hovertemplate=f"Strike: %{{x}}<br>{g}: %{{y:.4f}}<extra>{lbl}</extra>",
            ), row=r, col=cc)
        vline(fig, spot, row=r, col=cc, label=False)
    fig.update_layout(height=500, **BASE)
    fig.update_xaxes(**AX_NOZERO, title_text="Strike")
    fig.update_yaxes(**AX_ZERO, row=1, col=1)
    fig.update_yaxes(**AX_NOZERO, row=1, col=2)
    fig.update_yaxes(**AX_ZERO, row=2, col=1)
    fig.update_yaxes(**AX_NOZERO, title_text="IV (%)", row=2, col=2)
    for ann in fig.layout.annotations:
        ann.font.update(size=10, color="#606080", family=FONT_MONO)
    return fig


def chart_iv_skew(skew_df: pd.DataFrame, spot: float) -> Optional[go.Figure]:
    """Legacy multi-expiry skew: nearest-DTE-per-strike (kept for back-compat)."""
    if skew_df is None or skew_df.empty:
        return None
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=["IV POR STRIKE  (Calls vs Puts)",
                        "SKEW  (Put IV − Call IV)"],
        horizontal_spacing=0.10,
    )
    fig.add_trace(go.Scatter(
        x=skew_df["Strike"], y=skew_df["C_IV"], name="Call IV",
        line=dict(color=GREEN, width=2), mode="lines",
        hovertemplate="Strike %{x}<br>Call IV: %{y:.1f}%<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=skew_df["Strike"], y=skew_df["P_IV"], name="Put IV",
        line=dict(color=RED, width=2), mode="lines",
        hovertemplate="Strike %{x}<br>Put IV: %{y:.1f}%<extra></extra>",
    ), row=1, col=1)
    vline(fig, spot, row=1, col=1, label=False)
    # NaN guard: `NaN > 0` is False so NaN-skew bars used to be coloured
    # GREEN silently. Same pattern as the smile chart's skew column.
    clrs = [RED if (pd.notna(v) and v > 0) else GREEN
            for v in skew_df["Skew"]]
    fig.add_trace(go.Bar(
        x=skew_df["Strike"], y=skew_df["Skew"],
        marker_color=clrs, marker_line_width=0,
        name="Skew", showlegend=False,
        hovertemplate="Strike %{x}<br>Skew: %{y:.1f}%<extra></extra>",
    ), row=1, col=2)
    fig.add_hline(y=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.08)", row=1, col=2)
    vline(fig, spot, row=1, col=2, label=False)
    fig.update_layout(height=320, **BASE)
    fig.update_xaxes(**AX_NOZERO, title_text="Strike")
    fig.update_yaxes(**AX_NOZERO, title_text="IV (%)", row=1, col=1)
    fig.update_yaxes(**AX_ZERO, title_text="Put IV − Call IV (%)", row=1, col=2)
    for ann in fig.layout.annotations:
        ann.font.update(size=10, color="#606080", family=FONT_MONO)
    return fig


def chart_iv_smile(smile_df: pd.DataFrame, spot: float, expiry: str,
                   dte: int, metrics: Optional[dict] = None) -> Optional[go.Figure]:
    """Volatility smile for a SINGLE expiry: Call IV, Put IV, Market smile,
    with ATM marker and RR25 / BF25 annotations."""
    if smile_df is None or smile_df.empty:
        return None
    sm = smile_df.sort_values("Strike")
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=["VOLATILITY SMILE  (Calls · Puts · Market OTM)",
                        "SKEW  (Put IV − Call IV)"],
        horizontal_spacing=0.10,
    )
    # Market smile (OTM blend) — primary curve like gexbot
    fig.add_trace(go.Scatter(
        x=sm["Strike"], y=sm["Market_IV"], name="Market (OTM)",
        line=dict(color=ORANGE, width=3),
        mode="lines",
        hovertemplate="K %{x}<br>IV OTM: %{y:.1f}%<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=sm["Strike"], y=sm["C_IV"], name="Call IV",
        line=dict(color=GREEN, width=1.4, dash="dot"),
        mode="lines",
        hovertemplate="K %{x}<br>Call IV: %{y:.1f}%<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=sm["Strike"], y=sm["P_IV"], name="Put IV",
        line=dict(color=RED, width=1.4, dash="dot"),
        mode="lines",
        hovertemplate="K %{x}<br>Put IV: %{y:.1f}%<extra></extra>",
    ), row=1, col=1)
    # ATM marker
    if metrics and metrics.get("atm_iv"):
        fig.add_trace(go.Scatter(
            x=[spot], y=[metrics["atm_iv"]], mode="markers",
            name="ATM", marker=dict(size=11, color=PURPLE, symbol="diamond",
                                    line=dict(width=1.5, color="#0b0b14")),
            hovertemplate=f"ATM IV: {metrics['atm_iv']:.2f}%<extra></extra>",
            showlegend=False,
        ), row=1, col=1)
    vline(fig, spot, row=1, col=1, label=False)
    # Skew col: Put_IV - Call_IV. Compute the skew once and use the SAME
    # array for both y-values and the per-bar color list — otherwise a NaN
    # IV on either side desyncs the dropna'd colors from the un-dropna'd
    # bars and Plotly recycles colors silently, mis-coloring strikes.
    skew_y = (sm["P_IV"] - sm["C_IV"])
    clrs = [RED if (pd.notna(v) and v > 0) else GREEN for v in skew_y]
    fig.add_trace(go.Bar(
        x=sm["Strike"], y=skew_y,
        marker_color=clrs, marker_line_width=0,
        name="Skew", showlegend=False,
        hovertemplate="K %{x}<br>P−C IV: %{y:.1f}%<extra></extra>",
    ), row=1, col=2)
    fig.add_hline(y=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.08)", row=1, col=2)
    vline(fig, spot, row=1, col=2, label=False)

    title_bits = [f"{expiry[:10]}", f"{dte}d"]
    if metrics:
        if metrics.get("atm_iv") is not None:
            title_bits.append(f"ATM {metrics['atm_iv']:.1f}%")
        if metrics.get("rr25") is not None:
            rr = metrics["rr25"]
            title_bits.append(f"RR25 {rr:+.1f}")
        if metrics.get("bf25") is not None:
            title_bits.append(f"BF25 {metrics['bf25']:+.1f}")
    fig.update_layout(
        height=340, **BASE,
        title=dict(
            text="  " + "  ·  ".join(title_bits),
            font=dict(size=11, color="#9090b0", family=FONT_MONO), x=0,
        ),
    )
    fig.update_xaxes(**AX_NOZERO, title_text="Strike")
    fig.update_yaxes(**AX_NOZERO, title_text="IV (%)", row=1, col=1)
    fig.update_yaxes(**AX_ZERO, title_text="Put IV − Call IV (%)", row=1, col=2)
    for ann in fig.layout.annotations:
        ann.font.update(size=10, color="#606080", family=FONT_MONO)
    return fig


def chart_term_structure(ts_df: pd.DataFrame) -> Optional[go.Figure]:
    """Term-structure curve with contango/backwardation coloring.

    - Color ramp on markers: green if IV rises with DTE (contango, vol-expansion
      priced into back months), red if IV falls with DTE (backwardation / event).
    - Front-month dashed baseline.
    - Size of markers proportional to DTE delta from prior tenor (emphasis).
    - Annotation only on key tenors (first, last, kinks).
    """
    if ts_df is None or ts_df.empty:
        return None
    ts = ts_df.sort_values("DTE").reset_index(drop=True)
    front_iv = float(ts["ATM_IV"].iloc[0])
    # Per-point regime color: diff vs front month
    diffs = ts["ATM_IV"] - front_iv
    # NaN-safe: NaN comparisons return False, sending NaN-diffs to the
    # ORANGE bucket silently. Mark NaN as neutral grey instead so they
    # don't masquerade as "neutral term".
    colors = [
        GREEN if (pd.notna(d) and d > 0.3) else
        RED if (pd.notna(d) and d < -0.3) else
        "rgba(120,120,150,0.50)" if not pd.notna(d) else
        ORANGE
        for d in diffs
    ]
    # Slope hint
    back_iv = float(ts["ATM_IV"].iloc[-1])
    net = back_iv - front_iv
    if net > 0.5:
        regime, regime_clr = "CONTANGO", GREEN
    elif net < -0.5:
        regime, regime_clr = "BACKWARDATION", RED
    else:
        regime, regime_clr = "FLAT", ORANGE

    fig = go.Figure()
    # Filled baseline band
    fig.add_hline(y=front_iv, line_dash="dot", line_color="rgba(245,166,35,0.5)",
                  line_width=1,
                  annotation_text=f"  Front {front_iv:.1f}%",
                  annotation_font_color=ORANGE, annotation_font_size=9)
    fig.add_trace(go.Scatter(
        x=ts["DTE"], y=ts["ATM_IV"],
        mode="lines+markers",
        line=dict(color=ORANGE, width=2.2, shape="spline", smoothing=0.5),
        marker=dict(size=10, color=colors,
                    line=dict(width=1.5, color="#0b0b14")),
        fill="tonexty",
        fillcolor="rgba(245,166,35,0.05)",
        hovertemplate="DTE %{x}d · IV %{y:.2f}%  ·  %{customdata}<extra></extra>",
        customdata=[str(e)[:10] for e in ts["Expiry"]],
        name="ATM IV",
        showlegend=False,
    ))
    # Label only first, last, and any tenor near 30/60 if present.
    # `idxmin()` returns the index *label*; combined with `iloc[j]` it
    # was fragile (only works because we did reset_index above). Use
    # `argmin()` (numpy semantics, returns positional index) for an
    # invariant that doesn't rely on the reset.
    n = len(ts)
    mark_idx = {0, n - 1}
    for target in (30, 60, 90):
        if n > 2:
            j = int((ts["DTE"] - target).abs().to_numpy().argmin())
            if abs(ts["DTE"].iloc[j] - target) <= 5:
                mark_idx.add(j)
    for i in mark_idx:
        row = ts.iloc[i]
        fig.add_annotation(
            x=row["DTE"], y=row["ATM_IV"],
            text=f"{str(row['Expiry'])[5:10]}<br>{row['ATM_IV']:.1f}%",
            showarrow=False, yshift=18,
            font=dict(size=9, color="#9090b0", family=FONT_MONO),
            bgcolor="rgba(14,14,26,0.7)", borderpad=2,
        )
    fig.update_layout(
        height=300,
        xaxis_title="DTE (días)", yaxis_title="ATM IV (%)",
        title=dict(
            text=f"  TERM STRUCTURE  ·  {regime}  ·  front {front_iv:.1f}%  →  {back_iv:.1f}%  ({net:+.1f} pts)",
            font=dict(size=11, color=regime_clr, family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_NOZERO)
    return fig


def chart_oi_volume(c: pd.DataFrame, p: pd.DataFrame, spot: float,
                    em_low: Optional[float] = None,
                    em_high: Optional[float] = None) -> go.Figure:
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=["OPEN INTEREST POR STRIKE", "VOLUMEN POR STRIKE"],
        horizontal_spacing=0.10,
    )
    for metric, col in [("OI", 1), ("Volume", 2)]:
        for df, lbl, clr in [(c, "Calls", "rgba(34,197,94,0.65)"),
                             (p, "Puts", "rgba(244,63,94,0.65)")]:
            if df is None or df.empty or metric not in df.columns:
                continue
            d = df.sort_values("Strike")
            fig.add_trace(go.Bar(
                x=d["Strike"], y=d[metric], name=lbl,
                marker_color=clr, marker_line_width=0,
                showlegend=(col == 1), legendgroup=lbl,
                hovertemplate=f"Strike %{{x}}<br>{metric}: %{{y:,}}<extra>{lbl}</extra>",
            ), row=1, col=col)
        vline(fig, spot, row=1, col=col, label=False)
        if em_low and em_high:
            for em_val, em_lbl in [(em_low, "EM−"), (em_high, "EM+")]:
                fig.add_vline(
                    x=em_val, line_dash="dashdot",
                    line_color="rgba(168,85,247,0.4)", line_width=1,
                    annotation_text=f"  {em_lbl} ${em_val:.0f}",
                    annotation_font_size=8, annotation_font_color="#a855f7",
                    row=1, col=col,
                )
    fig.update_layout(height=300, barmode="overlay", **BASE)
    fig.update_xaxes(**AX_NOZERO, title_text="Strike")
    fig.update_yaxes(**AX_NOZERO)
    for ann in fig.layout.annotations:
        ann.font.update(size=10, color="#606080", family=FONT_MONO)
    return fig


def chart_vol_cone(analytics: dict, atm_iv: Optional[float],
                   symbol: str) -> Optional[go.Figure]:
    cone = (analytics or {}).get("cone", {})
    if not cone:
        return None
    windows = list(cone.keys())
    p10 = [cone[w]["p10"] for w in windows]
    p25 = [cone[w]["p25"] for w in windows]
    p50 = [cone[w]["p50"] for w in windows]
    p75 = [cone[w]["p75"] for w in windows]
    p90 = [cone[w]["p90"] for w in windows]
    curr = [cone[w]["current"] for w in windows]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=windows + windows[::-1], y=p90 + p10[::-1],
        fill="toself", fillcolor="rgba(59,130,246,0.06)",
        line=dict(color="rgba(0,0,0,0)"),
        showlegend=True, name="P10–P90", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=windows + windows[::-1], y=p75 + p25[::-1],
        fill="toself", fillcolor="rgba(59,130,246,0.14)",
        line=dict(color="rgba(0,0,0,0)"),
        showlegend=True, name="P25–P75", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=windows, y=p50, name="Mediana HV",
        line=dict(color=BLUE, width=1.5, dash="dot"),
        hovertemplate="%{x}: Mediana %{y:.1f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=windows, y=curr, name="HV Actual",
        line=dict(color=ORANGE, width=2.5),
        mode="lines+markers", marker=dict(size=6),
        hovertemplate="%{x}: HV Actual %{y:.1f}%<extra></extra>",
    ))
    if atm_iv:
        fig.add_hline(
            y=atm_iv, line_dash="dash", line_color=GREEN, line_width=1.5,
            annotation_text=f"  ATM IV {atm_iv:.1f}%",
            annotation_font_color=GREEN, annotation_font_size=10,
        )
    fig.update_layout(
        height=320,
        xaxis_title="Ventana lookback",
        yaxis_title="Volatilidad (%)",
        title=dict(
            text=f"  VOLATILITY CONE · {symbol}",
            font=dict(size=11, color="#606080", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_NOZERO)
    return fig


def chart_iv_hv_history(analytics: dict, atm_iv: Optional[float]
                        ) -> Optional[go.Figure]:
    hv30_s = (analytics or {}).get("hv30_series")
    dates = (analytics or {}).get("dates")
    if hv30_s is None or dates is None or len(hv30_s) < 10:
        return None
    hv30_s = hv30_s.dropna()
    # After dropna, `hv30_s.index` are LABELS of surviving rows, not
    # positions. `.iloc[labels]` only works coincidentally when the
    # source index is a default RangeIndex. Use `.loc` (label-based)
    # so we don't silently fall back to an integer 0..N x-axis when
    # the caller passes a non-default index.
    try:
        hv_dates = dates.loc[hv30_s.index].reset_index(drop=True)
    except Exception:
        # Try positional fallback before giving up and using integers.
        try:
            hv_dates = dates.iloc[hv30_s.index].reset_index(drop=True)
        except Exception:
            hv_dates = pd.Series(range(len(hv30_s)))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hv_dates, y=hv30_s.values, name="HV30",
        line=dict(color=ORANGE, width=2), fill="tozeroy",
        fillcolor="rgba(245,166,35,0.06)",
        hovertemplate="%{x|%Y-%m-%d}<br>HV30: %{y:.1f}%<extra></extra>",
    ))
    if atm_iv:
        fig.add_hline(
            y=atm_iv, line_dash="dash", line_color=GREEN, line_width=1.5,
            annotation_text=f"  ATM IV {atm_iv:.1f}%",
            annotation_font_color=GREEN, annotation_font_size=10,
        )
    last_date = hv_dates.iloc[-1] if hasattr(hv_dates, "iloc") else hv_dates[-1]
    last_hv = float(hv30_s.iloc[-1])
    fig.add_trace(go.Scatter(
        x=[last_date], y=[last_hv], mode="markers",
        marker=dict(size=9, color=ORANGE,
                    line=dict(width=2, color="#0b0b14")),
        name="HV30 actual", showlegend=True,
        hovertemplate=f"HV30 actual: {last_hv:.1f}%<extra></extra>",
    ))
    fig.update_layout(height=260, xaxis_title="Fecha",
                      yaxis_title="Volatilidad (%)", **BASE)
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_NOZERO)
    return fig


def chart_returns_dist(analytics: dict, symbol: str) -> Optional[go.Figure]:
    log_rets = (analytics or {}).get("log_returns")
    if log_rets is None or len(log_rets) < 20:
        return None
    rets_pct = (log_rets * 100).dropna()
    mu, sig = float(rets_pct.mean()), float(rets_pct.std())
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=rets_pct, name="Retornos", nbinsx=60,
        marker_color="rgba(59,130,246,0.55)", marker_line=dict(width=0),
        histnorm="probability density",
        hovertemplate="Retorno: %{x:.2f}%<br>Densidad: %{y:.4f}<extra></extra>",
    ))
    # Normal-fit overlay needs sig>0. Constant-return series (e.g. weekend
    # gap-only OHLC) give sig=0 → divide-by-zero → inf trace → blown y-range.
    if sig > 0:
        x_norm = np.linspace(rets_pct.min(), rets_pct.max(), 200)
        y_norm = (1.0 / (sig * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_norm - mu) / sig) ** 2)
        fig.add_trace(go.Scatter(
            x=x_norm, y=y_norm, name="Normal",
            line=dict(color=ORANGE, width=2, dash="dot"), hoverinfo="skip",
        ))
    for n, clr, lbl in [(1, "rgba(34,197,94,0.5)", "±1σ"),
                        (2, "rgba(244,63,94,0.4)", "±2σ")]:
        for sign in (-1, 1):
            fig.add_vline(
                x=mu + sign * n * sig, line_dash="dot",
                line_color=clr, line_width=1,
                annotation_text=f" {lbl}" if sign > 0 else "",
                annotation_font_size=9, annotation_font_color=clr,
            )
    fig.add_vline(x=0, line_dash="dot",
                  line_color="rgba(255,255,255,0.1)", line_width=1)
    skew = (analytics or {}).get("skewness", 0)
    kurt = (analytics or {}).get("kurtosis", 0)
    fig.update_layout(
        height=260,
        xaxis_title="Retorno diario (%)",
        yaxis_title="Densidad",
        title=dict(
            text=(f"  DISTRIBUCIÓN DE RETORNOS · {symbol} · "
                  f"μ={mu:.2f}% σ={sig:.2f}% Skew={skew:.2f} Kurt={kurt:.2f}"),
            font=dict(size=11, color="#606080", family=FONT_MONO), x=0,
        ),
        **BASE,
    )
    fig.update_xaxes(**AX_NOZERO)
    fig.update_yaxes(**AX_NOZERO)
    return fig
