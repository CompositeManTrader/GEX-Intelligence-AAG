"""
Options-chain HTML table builder. Uses list.append + "".join — ~5× faster than
the original `h += "…"` pattern on 200+ strikes.
"""
from __future__ import annotations

import pandas as pd


_CHAIN_COLS = ["Bid", "Ask", "Mark", "Volume", "OI",
               "IV%", "Delta", "Gamma", "Theta", "Vega"]


def _fmt(v, col: str = "") -> str:
    if pd.isna(v):
        return '<span class="neu">—</span>'
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if col == "IV%":
        color = "pos" if f < 30 else ("neg" if f > 60 else "hi")
        return f'<span class="{color}">{f:.1f}%</span>'
    if col in ("Volume", "OI"):
        s = f"{int(f):,}"
        return f'<span class="hi">{s}</span>' if f > 0 else f'<span class="neu">{s}</span>'
    if col == "Delta":
        # Color by |Δ| (moneyness intensity), not signed Δ. Puts have
        # negative deltas in [-1, 0] — coloring −0.5 (ATM put) red as if
        # it were a far-OTM short was misleading. Use intensity scale:
        # ITM (|Δ|>0.7) = strong, near-ATM (0.3<|Δ|≤0.7) = mid, far-OTM
        # (|Δ|≤0.3) = neutral. Sign is preserved in the rendered number.
        a = abs(f)
        cls = "pos" if a > 0.7 else ("hi" if a > 0.3 else "neu")
        return f'<span class="{cls}">{f:+.3f}</span>'
    if col in ("Gamma", "Vega"):
        return (f'<span class="hi">{f:.4f}</span>' if f > 0
                else f'<span class="neu">{f:.4f}</span>')
    if col == "Theta":
        return f'<span class="neg">{f:.3f}</span>'
    if col in ("Bid", "Ask", "Mark"):
        return (f'<span class="hi">{f:.2f}</span>' if f > 0
                else '<span class="neu">—</span>')
    return f"{f:.2f}"


def _pct_label(s: float, spot: float) -> str:
    """Strike % distance from spot — guarded against zero/None spot so a
    transient parse miss from `data/fetch.fetch_quote` cannot crash the
    whole chain render with ZeroDivisionError."""
    if not spot or spot <= 0:
        return "—"
    return f"{(s / spot - 1) * 100:+.1f}%"


def build_table(c_df: pd.DataFrame, p_df: pd.DataFrame,
                spot: float, mode: str) -> str:
    c_df = c_df.sort_values("Strike") if not c_df.empty else c_df
    p_df = p_df.sort_values("Strike") if not p_df.empty else p_df
    strikes = sorted(set(
        (c_df["Strike"].tolist() if not c_df.empty else []) +
        (p_df["Strike"].tolist() if not p_df.empty else [])
    ))
    if not strikes:
        return "<p style='color:#404060;padding:1rem'>Sin datos para esta selección.</p>"
    atm_s = min(strikes, key=lambda s: abs(s - spot))
    c_idx = c_df.set_index("Strike").to_dict("index") if not c_df.empty else {}
    p_idx = p_df.set_index("Strike").to_dict("index") if not p_df.empty else {}
    c_cols = [c for c in _CHAIN_COLS if not c_df.empty and c in c_df.columns]
    p_cols = [c for c in _CHAIN_COLS if not p_df.empty and c in p_df.columns]

    def hdr(cols: list[str], side: str) -> str:
        cls = ("call-hdr" if side == "call" else
               ("put-hdr" if side == "put" else "mid-hdr"))
        return "".join(f'<th class="{cls} ctr">{c}</th>' for c in cols)

    def cells(row: dict, cols: list[str]) -> str:
        return "".join(f"<td>{_fmt(row.get(c, float('nan')), c)}</td>" for c in cols)

    parts: list[str] = ['<div class="chain-wrap"><table class="chain">']

    if mode == "calls":
        parts.append("<thead><tr><th class='lft'>STRIKE</th>")
        parts.append(hdr(c_cols, "call"))
        parts.append("</tr></thead><tbody>")
        for s in strikes:
            r = c_idx.get(s, {})
            itm = r.get("ITM", False)
            rc = "atm-row" if s == atm_s else ("itm-c" if itm else "")
            sc = "atm-strike" if s == atm_s else "strike"
            pct = (f'<span style="font-size:0.6rem;color:#404060;margin-left:4px">'
                   f'{_pct_label(s, spot)}</span>')
            parts.append(f'<tr class="{rc}"><td class="lft">'
                         f'<span class="{sc}">${s:.1f}</span>{pct}</td>')
            parts.append(cells(r, c_cols))
            parts.append("</tr>")

    elif mode == "puts":
        parts.append("<thead><tr><th class='lft'>STRIKE</th>")
        parts.append(hdr(p_cols, "put"))
        parts.append("</tr></thead><tbody>")
        for s in strikes:
            r = p_idx.get(s, {})
            itm = r.get("ITM", False)
            rc = "atm-row" if s == atm_s else ("itm-p" if itm else "")
            sc = "atm-strike" if s == atm_s else "strike"
            pct = (f'<span style="font-size:0.6rem;color:#404060;margin-left:4px">'
                   f'{_pct_label(s, spot)}</span>')
            parts.append(f'<tr class="{rc}"><td class="lft">'
                         f'<span class="{sc}">${s:.1f}</span>{pct}</td>')
            parts.append(cells(r, p_cols))
            parts.append("</tr>")

    else:
        parts.append(
            "<thead><tr>"
            f'<th colspan="{len(c_cols)}" class="call-hdr ctr" '
            f'style="border-right:1px solid #22c55e33;">▲ CALLS</th>'
            '<th class="mid-hdr ctr" '
            'style="border-left:1px solid #22c55e33;border-right:1px solid #f43f5e33;">'
            'STRIKE</th>'
            f'<th colspan="{len(p_cols)}" class="put-hdr ctr" '
            f'style="border-left:1px solid #f43f5e33;">▼ PUTS</th>'
            "</tr><tr>"
        )
        parts.append(hdr(c_cols, "call"))
        parts.append('<th class="mid-hdr ctr" '
                     'style="border-left:1px solid #22c55e33;'
                     'border-right:1px solid #f43f5e33;">$</th>')
        parts.append(hdr(p_cols, "put"))
        parts.append("</tr></thead><tbody>")
        for s in strikes:
            cr, pr = c_idx.get(s, {}), p_idx.get(s, {})
            c_itm, p_itm = cr.get("ITM", False), pr.get("ITM", False)
            is_atm = s == atm_s
            parts.append("<tr>")
            for col in c_cols:
                bg = "background:rgba(34,197,94,0.04);" if c_itm and not is_atm else ""
                parts.append(f'<td style="{bg}">{_fmt(cr.get(col, float("nan")), col)}</td>')
            mid = ("background:rgba(249,115,22,0.1);color:#f97316;font-weight:800;"
                   if is_atm else
                   "background:#0d0d1a;color:#9090b0;font-weight:600;")
            pct = _pct_label(s, spot)
            parts.append(f'<td class="ctr" style="{mid}'
                         f'border-left:1px solid #22c55e22;'
                         f'border-right:1px solid #f43f5e22;">'
                         f'${s:.1f} <span style="font-size:0.6rem;opacity:0.5">{pct}</span></td>')
            for col in p_cols:
                bg = "background:rgba(244,63,94,0.04);" if p_itm and not is_atm else ""
                parts.append(f'<td style="{bg}">{_fmt(pr.get(col, float("nan")), col)}</td>')
            parts.append("</tr>")

    parts.append("</tbody></table></div>")
    return "".join(parts)
