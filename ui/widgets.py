"""
Tactical dashboard widgets.

  - flip_zone_widget  : real-time thermometer showing distance to Zero Γ
  - trade_setup_card  : AI-analyst-style card with bias / entry / stop /
                        target / expiration derived from all live signals

All functions return HTML strings ready to render with
`st.markdown(..., unsafe_allow_html=True)`.
"""
from __future__ import annotations

from typing import Optional


def _html(s: str) -> str:
    """Collapse an indented HTML block so Streamlit's markdown parser does
    NOT treat leading spaces as an indented code block.

    CommonMark (which Streamlit's markdown uses even with
    `unsafe_allow_html=True`) promotes any line starting with 4+ spaces into
    a `<pre><code>` block. Nested HTML with pretty indentation triggers this
    and the raw `<div>` text leaks out onto the page. Stripping left-whitespace
    per line + joining with newlines keeps the HTML valid while neutralising
    the markdown code-fence heuristic.
    """
    return "\n".join(line.lstrip() for line in s.splitlines() if line.strip())


def _humanize(n) -> str:
    """28,516,412 → '28.5M'. Purely presentational number compaction."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    a = abs(n)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{n / div:.1f}{suf}"
    return f"{n:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
#  MARKET HEADER  —  terminal-style top strip (Bloomberg / SpotGamma feel)
#  Pure presentation: receives already-computed values, renders nothing new.
# ─────────────────────────────────────────────────────────────────────────────
def market_header(
    symbol: str, spot: float, chg: float = 0.0, chg_p: float = 0.0,
    bid: Optional[float] = None, ask: Optional[float] = None,
    vol: Optional[float] = None, dte: Optional[int] = None,
    iv_atm: Optional[float] = None, p_c: Optional[float] = None,
    mp: Optional[float] = None, net_gex_bn: Optional[float] = None,
    em_lo: Optional[float] = None, em_hi: Optional[float] = None,
    updated: str = "", market_status: Optional[str] = None,
) -> str:
    """A single cohesive header panel: live dot + symbol + big price + change
    pill on the left, a hairline-separated stat rail on the right, and a slim
    1σ Expected-Move sub-bar underneath."""
    # Direction from chg when it's meaningful, else from chg_p — Schwab
    # sometimes ships netChange=0 with a nonzero percentChange (after hours),
    # which used to render the contradictory "▲ +0.00 · -1.11%" pill.
    _basis = chg if abs(chg or 0) >= 0.005 else (chg_p or 0)
    up = _basis >= 0
    chg_color = "#16C784" if up else "#EA3943"
    arrow = "▲" if up else "▼"
    if abs(chg or 0) < 0.005 and abs(chg_p or 0) >= 0.005:
        pill_txt = f"{arrow} {chg_p:+.2f}%"
    else:
        pill_txt = f"{arrow} {chg:+.2f} · {chg_p:+.2f}%"

    ms = (market_status or "").upper()
    if ms == "OPEN":
        dot_cls, dot_lbl, dot_col = "live", "LIVE", "#16C784"
    elif ms in ("PRE", "POST"):
        dot_cls, dot_lbl, dot_col = "idle", ms, "#F5A623"
    elif ms == "CLOSED":
        dot_cls, dot_lbl, dot_col = "off", "CLOSED", "#6b6b8a"
    else:
        dot_cls, dot_lbl, dot_col = "idle", "MKT", "#F5A623"

    def cell(label: str, value: str, vcolor: str = "#dcdcf0",
             sub: Optional[str] = None) -> str:
        sub_html = (f'<span style="font-size:0.58rem;color:{vcolor};'
                    f'opacity:0.6;margin-left:5px;">{sub}</span>') if sub else ""
        return (
            f'<div class="mh-cell" style="padding:0.1rem 1.15rem;'
            f'border-left:1px solid #1b1b2c;transition:background .15s;">'
            f'<div style="font-size:0.55rem;color:#5b5b80;letter-spacing:0.13em;'
            f'text-transform:uppercase;margin-bottom:4px;white-space:nowrap;">'
            f'{label}</div>'
            f'<div style="font-size:0.98rem;font-weight:700;color:{vcolor};'
            f'font-family:JetBrains Mono,monospace;font-variant-numeric:'
            f'tabular-nums;line-height:1;white-space:nowrap;">'
            f'{value}{sub_html}</div></div>'
        )

    ba = f"{bid:.2f} / {ask:.2f}" if (bid and ask) else "—"
    cells = ""
    cells += cell("BID / ASK", ba)
    cells += cell("VOLUMEN", _humanize(vol) if vol else "—")
    cells += cell("ATM IV", f"{iv_atm:.1f}%" if iv_atm else "—", "#22d3ee")
    cells += cell("P/C RATIO", f"{p_c:.2f}" if p_c else "—")
    cells += cell("MAX PAIN", f"${mp:,.0f}" if mp else "—", "#c4b5fd")
    if net_gex_bn is not None:
        ng_col = "#16C784" if net_gex_bn >= 0 else "#EA3943"
        ng_sub = "LONG Γ" if net_gex_bn >= 0 else "SHORT Γ"
        cells += cell("NET GEX", f"${net_gex_bn:+.2f}B", ng_col, ng_sub)
    else:
        cells += cell("NET GEX", "—")

    em_html = ""
    if em_lo and em_hi and spot:
        pct = (em_hi - spot) / spot * 100
        em_html = (
            f'<div style="display:flex;align-items:center;gap:0.85rem;'
            f'margin-top:0.75rem;padding-top:0.6rem;border-top:1px solid #14141f;'
            f'font-family:JetBrains Mono,monospace;">'
            f'<span style="font-size:0.56rem;color:#5b5b80;letter-spacing:0.12em;'
            f'text-transform:uppercase;white-space:nowrap;">1σ Expected Move</span>'
            f'<div style="flex:1;height:3px;border-radius:2px;min-width:40px;'
            f'background:linear-gradient(to right,rgba(168,85,247,0) 0%,'
            f'rgba(168,85,247,0.55) 50%,rgba(168,85,247,0) 100%);"></div>'
            f'<span style="font-size:0.82rem;color:#c4b5fd;font-weight:700;'
            f'white-space:nowrap;">${em_lo:.2f} — ${em_hi:.2f}</span>'
            f'<span style="font-size:0.62rem;color:#6b6b8a;">±{pct:.1f}%</span>'
            f'<span style="font-size:0.58rem;color:#3c3c58;white-space:nowrap;">'
            f'· upd {updated}</span></div>'
        )

    return _html(f"""
    <div style="position:relative;background:linear-gradient(135deg,#0b0b16 0%,#0e0e1c 55%,#0c0c18 100%);
         border:1px solid #1e1e32;border-radius:8px;padding:0.95rem 1.2rem 0.85rem;
         margin:0.2rem 0 0.9rem;box-shadow:0 1px 0 rgba(255,255,255,0.02) inset,0 6px 22px rgba(0,0,0,0.35);overflow:hidden;">
      <div style="position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(to right,#F5A623,rgba(245,166,35,0) 60%);"></div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:1.2rem;flex-wrap:wrap;">
        <div style="display:flex;align-items:center;gap:1.15rem;min-width:260px;">
          <div>
            <div style="font-size:0.6rem;color:{dot_col};letter-spacing:0.14em;font-family:JetBrains Mono,monospace;margin-bottom:3px;">
              <span class="mh-dot {dot_cls}"></span>{dot_lbl}
            </div>
            <div style="font-size:1.2rem;font-weight:800;color:#F5A623;font-family:JetBrains Mono,monospace;letter-spacing:0.08em;line-height:1;">{symbol}</div>
          </div>
          <div style="display:flex;align-items:baseline;gap:0.7rem;flex-wrap:wrap;">
            <span style="font-size:2.1rem;font-weight:800;color:#f5f5ff;font-family:JetBrains Mono,monospace;font-variant-numeric:tabular-nums;line-height:1;text-shadow:0 0 18px rgba(245,245,255,0.12);">${spot:,.2f}</span>
            <span style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:5px;background:{chg_color}1f;border:1px solid {chg_color}44;color:{chg_color};font-size:0.74rem;font-weight:700;font-family:JetBrains Mono,monospace;white-space:nowrap;">{pill_txt}</span>
          </div>
        </div>
        <div style="display:flex;align-items:center;flex-wrap:wrap;">{cells}</div>
      </div>
      {em_html}
    </div>
    """)


# ─────────────────────────────────────────────────────────────────────────────
#  GEX FLIP ZONE  —  thermometer widget
# ─────────────────────────────────────────────────────────────────────────────
def flip_zone_widget(spot: float, gex_sum: Optional[dict]) -> str:
    """Visual thermometer: spot distance to Zero Γ.

    Color ramp:
      🟢 > 1.0 %   — safe, régimen estable
      🟡 0.3–1.0 % — zona de atención
      🔴 < 0.3 %   — cruce inminente

    Also plots the spot within the [put_wall, call_wall] band so you see
    where in the structural range you actually are.
    """
    if not gex_sum or not spot:
        return _box_err("Sin datos GEX para flip zone.")
    gf = gex_sum.get("gamma_flip")
    cw = gex_sum.get("call_wall")
    pw = gex_sum.get("put_wall")
    regime = gex_sum.get("regime", "NEUTRAL")

    if not gf:
        return _box_err("Zero Γ no disponible.")

    dist_abs = gf - spot
    dist_pct = (dist_abs / spot) * 100 if spot else 0.0
    a = abs(dist_pct)

    # UX fix (live-audit finding): the REGIME is the primary message — the
    # old labels (SAFE / DANGER) only encoded distance-to-flip and read as
    # "all good" in green even inside a −$11B short-gamma book. Now the
    # headline and border colour reflect the regime; proximity to the flip
    # is the secondary line.
    if regime == "POSITIVE":
        color, status = "#16C784", "ESTABLE · dealer amortigua"
    elif regime == "NEGATIVE":
        color, status = "#EA3943", "INESTABLE · dealer amplifica"
    else:
        color, status = "#F5A623", "NEUTRAL · régimen indefinido"
    if a < 0.3:
        prox_col, prox_lbl = "#EA3943", "cruce de régimen INMINENTE"
    elif a < 1.0:
        prox_col, prox_lbl = "#F5A623", "flip cercano — atención"
    else:
        prox_col, prox_lbl = "#8a8aa8", "flip lejano"

    above = dist_abs > 0    # gf above spot → spot would need to rally to flip
    direction = "por ENCIMA del spot" if above else "por DEBAJO del spot"
    # Landing side determines the destination regime (SqueezeMetrics
    # convention: below gf = negative, above = positive).
    next_regime = "POSITIVE" if above else "NEGATIVE"
    cross_dir = "↑ subir" if above else "↓ caer"
    if next_regime == regime:
        # UX fix (live-audit finding): the old text could produce the absurd
        # "Régimen actual: NEGATIVE. Cruzar → cambia a NEGATIVE". When the
        # net-GEX sign and the flip side DISAGREE the book is in transition
        # (multiple crossings / mixed expiries) — say that honestly.
        cross_msg = (f'⚠ <b style="color:#F5A623">Señales mixtas</b>: net GEX '
                     f'{regime} con Zero Γ '
                     f'{"encima" if above else "debajo"} del spot — libro en '
                     f'transición; trata el régimen con cautela.')
    else:
        cross_msg = (f'Cruzar Zero Γ <b style="color:#a855f7">${gf:.0f}</b> '
                     f'({cross_dir} {a:.2f}%) cambiaría el régimen a '
                     f'<b>{next_regime}</b>.')

    # Thermometer: spot position inside [pw, cw] range as %
    bar_html = ""
    if cw and pw and cw > pw:
        pos = max(0.0, min(1.0, (spot - pw) / (cw - pw)))
        gf_pos = max(0.0, min(1.0, (gf - pw) / (cw - pw)))
        # Single-line spans so no line starts with 4+ spaces after the outer
        # dedent — prevents Streamlit's markdown from code-fencing the block.
        bar_html = (
            f'<div style="position:relative;height:14px;margin:8px 0 4px;'
            f'background:linear-gradient(to right,rgba(234,57,67,.25) 0%,'
            f'rgba(245,166,35,.15) 45%,rgba(245,166,35,.15) 55%,'
            f'rgba(22,199,132,.25) 100%);'
            f'border:1px solid #2a2a3a;border-radius:3px;">'
            f'<div title="Put Wall ${pw:.0f}" '
            f'style="position:absolute;left:0%;top:-3px;width:2px;height:20px;'
            f'background:#EA3943"></div>'
            f'<div title="Call Wall ${cw:.0f}" '
            f'style="position:absolute;left:100%;top:-3px;width:2px;height:20px;'
            f'background:#16C784"></div>'
            f'<div title="Zero Γ ${gf:.0f}" '
            f'style="position:absolute;left:{gf_pos*100:.1f}%;top:-5px;'
            f'width:2px;height:24px;background:#a855f7"></div>'
            f'<div title="Spot ${spot:.2f}" '
            f'style="position:absolute;left:{pos*100:.1f}%;top:-5px;'
            f'width:12px;height:24px;background:#fbbf24;border-radius:2px;'
            f'box-shadow:0 0 6px #fbbf24"></div>'
            f'</div>'
            f'<div style="display:flex;justify-content:space-between;'
            f'font-size:0.65rem;color:#606080;'
            f'font-family:JetBrains Mono,monospace;">'
            f'<span>PW ${pw:.0f}</span>'
            f'<span>Zero Γ ${gf:.0f}</span>'
            f'<span>CW ${cw:.0f}</span>'
            f'</div>'
        )

    return _html(f"""
    <div style="background:linear-gradient(135deg,rgba(20,20,36,0.85),rgba(14,14,26,0.85));
         border:1px solid {color}55;border-left:4px solid {color};
         padding:0.9rem 1rem;border-radius:6px;margin:0.4rem 0 1rem;
         font-family:JetBrains Mono,monospace;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;">
        <div>
          <div style="font-size:0.68rem;color:#7070a0;letter-spacing:0.1em;">
            GEX FLIP ZONE · régimen {regime}
          </div>
          <div style="font-size:1.15rem;font-weight:800;color:{color};margin-top:2px;">
            {status}
          </div>
          <div style="font-size:0.66rem;color:{prox_col};margin-top:3px;">
            {prox_lbl}
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.68rem;color:#7070a0;">Distancia a Zero Γ</div>
          <div style="font-size:1.4rem;font-weight:800;color:{prox_col};line-height:1.1;">
            {dist_pct:+.2f}%
          </div>
          <div style="font-size:0.7rem;color:#9090b0;">
            {dist_abs:+.2f} pts · {direction}
          </div>
        </div>
      </div>
      {bar_html}
      <div style="font-size:0.7rem;color:#9090b0;margin-top:6px;line-height:1.5;">
        Spot <b style="color:#fbbf24">${spot:.2f}</b> &nbsp;·&nbsp;
        Zero Γ <b style="color:#a855f7">${gf:.0f}</b> &nbsp;·&nbsp;
        {cross_msg}
      </div>
    </div>
    """)


# ─────────────────────────────────────────────────────────────────────────────
#  TRADE SETUP CARD  —  AI analyst
# ─────────────────────────────────────────────────────────────────────────────
def trade_setup_card(
    symbol: str,
    spot: float,
    gex_sum: Optional[dict],
    vex_sum: Optional[dict],
    cex_sum: Optional[dict],
    dex_sum: Optional[dict],
    hiro_snap: Optional[dict],
    hiro_z: Optional[float],
    atm_iv: Optional[float],
    iv_hv_ratio: Optional[float],
    em_lo: Optional[float],
    em_hi: Optional[float],
    dte: int = 0,
) -> str:
    """Compose a complete trade setup card from all live signals.

    Logic (multi-factor vote, each factor votes +1 / 0 / -1):
      · GEX regime         (LONG Γ → mean-revert bullish; SHORT Γ → bearish momentum)
      · HIRO               (positive / negative dealer flow)
      · Vanna              (long/short vanna — direction under vol expansion)
      · Delta bias         (call-heavy → bullish implied)
      · IV / HV ratio      (cheap IV favors long vol direction)

    The aggregated vote chooses bias. Entry / stop / target / expiry are
    anchored to structural GEX levels (walls, flip, HVL) and the expected
    move range — not free-floating.
    """
    if not gex_sum or not spot:
        return _card_err("Sin datos GEX suficientes para el setup.")

    regime = gex_sum.get("regime", "NEUTRAL")
    cw = gex_sum.get("call_wall")
    pw = gex_sum.get("put_wall")
    gf = gex_sum.get("gamma_flip")
    hvl = gex_sum.get("hvl")

    # ── Voting ──────────────────────────────────────────────────────────────
    votes: list[tuple[str, int, str]] = []

    if regime == "POSITIVE":
        votes.append(("Régimen Γ", +1, "LONG gamma — dealer absorbe, pinning"))
    elif regime == "NEGATIVE":
        votes.append(("Régimen Γ", -1, "SHORT gamma — dealer amplifica, momentum"))
    else:
        votes.append(("Régimen Γ", 0, "Neutral"))

    if hiro_snap:
        h = hiro_snap.get("hiro", 0)
        if h > 0:
            votes.append(("HIRO", +1, f"Dealer buy pressure +{h:,.0f}"))
        elif h < 0:
            votes.append(("HIRO", -1, f"Dealer sell pressure {h:,.0f}"))
        else:
            votes.append(("HIRO", 0, "Equilibrado"))
    if hiro_z is not None and abs(hiro_z) >= 2:
        votes.append(("HIRO z-score", +1 if hiro_z > 0 else -1,
                      f"Extremo {hiro_z:+.1f}σ"))

    if vex_sum:
        # Relative threshold so the Vanna vote works across symbol sizes.
        # The legacy absolute $100M threshold only fired on SPX/SPY-sized
        # books; mid-cap names never got a Vanna vote, sistemáticamente
        # sesgando el score-aggregate hacia GEX+DEX+HIRO. Now we compare
        # |total_vex| against half of (|call_vex|+|put_vex|) — fires when
        # one side dominates the other materially, independently of
        # symbol notional.
        vt = vex_sum.get("total_vex", 0) or 0
        cvex = abs(vex_sum.get("call_vex", 0) or 0)
        pvex = abs(vex_sum.get("put_vex", 0) or 0)
        gross = cvex + pvex
        if gross > 0:
            if vt > 0.20 * gross:
                votes.append(("Vanna", +1,
                              "Long vanna — vol expansion amplifica al alza"))
            elif vt < -0.20 * gross:
                votes.append(("Vanna", -1,
                              "Short vanna — vol expansion amplifica a la baja"))

    if dex_sum:
        bias = dex_sum.get("bias", "NEUTRAL")
        if bias == "CALL-HEAVY":
            votes.append(("Delta", +1, "Call-heavy — dealer long delta"))
        elif bias == "PUT-HEAVY":
            votes.append(("Delta", -1, "Put-heavy — dealer short delta"))

    if iv_hv_ratio is not None:
        if iv_hv_ratio < 0.8:
            votes.append(("IV/HV", 0,
                          f"IV barata ({iv_hv_ratio:.2f}x) — favor compra de vol"))
        elif iv_hv_ratio > 1.3:
            votes.append(("IV/HV", 0,
                          f"IV cara ({iv_hv_ratio:.2f}x) — favor venta de vol"))

    # ── Aggregate ───────────────────────────────────────────────────────────
    score = sum(v for _, v, _ in votes)
    if score >= 2:
        bias_word, bias_sub, bias_clr, arrow = "LONG", "bullish", "#16C784", "▲"
    elif score <= -2:
        bias_word, bias_sub, bias_clr, arrow = "SHORT", "bearish", "#EA3943", "▼"
    else:
        bias_word, bias_sub, bias_clr, arrow = "NEUTRAL", "range", "#F5A623", "◆"

    # ── Level-based targets (structural, not made up) ───────────────────────
    lv = _derive_levels(score, spot, cw, pw, gf, hvl, em_lo, em_hi, regime)
    expiry = _recommend_expiry(dte, regime, iv_hv_ratio)

    # ── Confluence (agreement of signals — NOT a win-probability) ───────────
    n = len([v for _, v, _ in votes if v != 0])
    conf = int(min(100, abs(score) / max(1, n) * 100)) if n else 0
    conf_clr = ("#16C784" if conf >= 67 else
                "#F5A623" if conf >= 34 else "#EA3943")

    # ── Votes (2-column compact grid) ───────────────────────────────────────
    vote_cells = ""
    for name, v, note in votes:
        sym = "▲" if v > 0 else ("▼" if v < 0 else "·")
        sym_clr = "#16C784" if v > 0 else ("#EA3943" if v < 0 else "#707090")
        vote_cells += (
            f'<div style="padding:2px 0;font-size:0.7rem;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;">'
            f'<span style="color:{sym_clr};font-weight:700;">{sym}</span> '
            f'<span style="color:#c0c0d8;">{name}</span> '
            f'<span style="color:#808098;">{note}</span></div>'
        )
    votes_html = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 22px;'
        f'margin:0.9rem 0 0.2rem;">{vote_cells}</div>'
    )

    # ── Price rail + metrics ────────────────────────────────────────────────
    def _money(v):
        return f"${v:,.2f}"

    rail_html = ""
    if lv["kind"] in ("long", "short") and lv.get("stop") and lv.get("target"):
        elo, ehi = lv["entry_lo"], lv["entry_hi"]
        stop, target = lv["stop"], lv["target"]
        emid = (elo + ehi) / 2.0
        if lv["kind"] == "long":
            risk, reward = emid - stop, target - emid
            left_lbl, left_clr, left_val = "STOP", "#EA3943", stop
            right_lbl, right_clr, right_val = "TARGET", "#16C784", target
            grad = ("linear-gradient(to right,rgba(234,57,67,.30) 0%,"
                    "rgba(245,166,35,.16) 45%,rgba(22,199,132,.30) 100%)")
        else:
            risk, reward = stop - emid, emid - target
            left_lbl, left_clr, left_val = "TARGET", "#16C784", target
            right_lbl, right_clr, right_val = "STOP", "#EA3943", stop
            grad = ("linear-gradient(to right,rgba(22,199,132,.30) 0%,"
                    "rgba(245,166,35,.16) 55%,rgba(234,57,67,.30) 100%)")
        rr = (reward / risk) if risk and risk > 0 else None
        risk_pct = risk / spot * 100 if spot else 0
        reward_pct = reward / spot * 100 if spot else 0
        rr_clr = ("#16C784" if (rr or 0) >= 2 else
                  "#F5A623" if (rr or 0) >= 1 else "#EA3943")

        pts = [stop, target, elo, ehi, spot]
        lo, hi = min(pts), max(pts)
        span = (hi - lo) or 1.0

        def pos(x):
            return max(0.0, min(100.0, (x - lo) / span * 100.0))
        eb_lo, eb_hi = sorted([pos(elo), pos(ehi)])
        rr_txt = f"{rr:.2f}<span style='font-size:0.6rem;color:{rr_clr};opacity:.7'>:1</span>" if rr else "—"

        rail_html = (
            f'<div style="margin:1rem 0 0.3rem;">'
            f'<div style="position:relative;height:8px;border-radius:4px;'
            f'background:{grad};border:1px solid #20202f;">'
            f'<div style="position:absolute;left:{eb_lo:.1f}%;width:{eb_hi - eb_lo:.1f}%;'
            f'top:0;bottom:0;background:rgba(168,85,247,.22);'
            f'border-left:1px solid #a855f7;border-right:1px solid #a855f7;"></div>'
            f'<div title="Stop" style="position:absolute;left:{pos(stop):.1f}%;top:-4px;'
            f'width:2px;height:16px;background:#EA3943;"></div>'
            f'<div title="Spot" style="position:absolute;left:{pos(spot):.1f}%;top:-5px;'
            f'width:11px;height:18px;border-radius:2px;background:#f5f5ff;'
            f'box-shadow:0 0 7px #f5f5ff;transform:translateX(-50%);"></div>'
            f'<div title="Target" style="position:absolute;left:{pos(target):.1f}%;top:-4px;'
            f'width:2px;height:16px;background:#16C784;transform:translateX(-2px);"></div>'
            f'</div>'
            f'<div style="display:flex;justify-content:space-between;font-size:0.56rem;'
            f'margin-top:7px;">'
            f'<span style="color:{left_clr};">{left_lbl} {left_val:,.2f}</span>'
            f'<span style="color:#a855f7;">ENTRY {elo:,.2f}–{ehi:,.2f}</span>'
            f'<span style="color:{right_clr};">{right_lbl} {right_val:,.2f}</span>'
            f'</div></div>'
        )
        metrics_html = (
            f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.5rem;'
            f'border-top:1px solid rgba(255,255,255,.05);padding-top:0.75rem;'
            f'margin-top:0.7rem;">'
            f'{_metric("RIESGO", f"−{_money(risk)}", "#EA3943", f"−{abs(risk_pct):.2f}%")}'
            f'{_metric("PREMIO", f"+{_money(reward)}", "#16C784", f"+{abs(reward_pct):.2f}%")}'
            f'{_metric("R : R", rr_txt, rr_clr)}'
            f'{_metric("EXPIRY", expiry, "#a855f7")}'
            f'</div>'
        )
    else:
        # Non-directional (iron condor / flat) — no R:R, show text levels.
        metrics_html = (
            f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.5rem;'
            f'border-top:1px solid rgba(255,255,255,.05);padding-top:0.75rem;'
            f'margin-top:0.9rem;">'
            f'{_metric("SETUP", lv.get("text_entry", "—"), "#e0e0f0")}'
            f'{_metric("STOP", lv.get("text_stop", "—"), "#EA3943")}'
            f'{_metric("TARGET", lv.get("text_target", "—"), "#16C784")}'
            f'{_metric("EXPIRY", expiry, "#a855f7")}'
            f'</div>'
        )

    return _html(f"""
    <div style="position:relative;background:linear-gradient(135deg,#0b0b16,#0e0e1c 60%,#0c0c18);
         border:1px solid #1e1e32;border-radius:9px;padding:1.05rem 1.25rem;
         margin:0.4rem 0 1rem;font-family:JetBrains Mono,monospace;
         box-shadow:0 6px 22px rgba(0,0,0,0.35);overflow:hidden;">
      <div style="position:absolute;top:0;left:0;right:0;height:2px;
           background:linear-gradient(to right,{bias_clr},rgba(0,0,0,0) 55%);"></div>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;
           gap:1rem;flex-wrap:wrap;">
        <div>
          <div style="font-size:0.58rem;color:#5b5b80;letter-spacing:0.16em;">
            TRADE SETUP&nbsp;·&nbsp;{symbol}
          </div>
          <div style="font-size:1.5rem;font-weight:800;color:{bias_clr};margin-top:4px;
               letter-spacing:0.02em;text-shadow:0 0 16px {bias_clr}33;">
            {arrow}&nbsp;{bias_word}&nbsp;<span style="color:#7a7a92;font-size:0.9rem;
            font-weight:600;">{bias_sub}</span>
          </div>
        </div>
        <div style="min-width:175px;">
          <div style="display:flex;justify-content:space-between;font-size:0.55rem;
               color:#5b5b80;letter-spacing:0.1em;margin-bottom:5px;">
            <span>CONFLUENCIA</span><span style="color:{conf_clr};font-weight:700;">{conf}%</span>
          </div>
          <div style="height:6px;border-radius:3px;background:#16162a;overflow:hidden;">
            <div style="width:{conf}%;height:100%;background:{conf_clr};
                 box-shadow:0 0 8px {conf_clr}88;"></div>
          </div>
          <div style="font-size:0.55rem;color:#4d4d70;margin-top:4px;text-align:right;">
            {n} señales · score {score:+d}
          </div>
        </div>
      </div>
      {votes_html}
      {rail_html}
      {metrics_html}
      <div style="font-size:0.58rem;color:#4d4d70;margin-top:0.7rem;
           line-height:1.4;font-style:italic;">
        Confluencia = acuerdo entre señales, NO probabilidad de ganar.
        Sugerencia algorítmica · no es asesoría · ajusta size a tu riesgo.
      </div>
    </div>
    """)


def key_levels_panel(spot: float, gex_sum: Optional[dict],
                     zones: Optional[list] = None, max_rows: int = 9) -> str:
    """Side panel for the Price & GEX Levels map — lists the key levels
    classified as resistance / support with a one-line explanation. Uses the
    same level classification as the chart (charts.levels_map)."""
    from charts.levels_map import collect_price_levels
    from quant.vt_levels import vt_dominance_label
    levels = collect_price_levels(spot, gex_sum, zones)
    if not levels:
        return _box_err("Sin niveles GEX para mapear.")
    majors = [lv for lv in levels if lv["major"]]
    clusters = sorted([lv for lv in levels if not lv["major"]],
                      key=lambda lv: abs(lv["price"] - spot))
    chosen = (majors + clusters)[:max_rows]
    chosen.sort(key=lambda lv: -lv["price"])

    rows = ""
    for lv in chosen:
        dist = (lv["price"] - spot) / spot * 100 if spot else 0.0
        rows += (
            f'<div style="padding:0.5rem 0;border-bottom:1px solid #16162a;">'
            f'<div style="display:flex;align-items:baseline;gap:9px;">'
            f'<span style="font-size:1.25rem;font-weight:800;color:{lv["color"]};">'
            f'{lv["price"]:.0f}</span>'
            f'<span style="font-size:0.58rem;letter-spacing:0.12em;color:{lv["color"]};">'
            f'{lv["tag"]}</span>'
            f'<span style="font-size:0.56rem;color:#4d4d70;margin-left:auto;">'
            f'{dist:+.2f}%</span></div>'
            f'<div style="font-size:0.65rem;color:#8585a8;margin-top:2px;">'
            f'{lv["desc"]}</div></div>'
        )
    # Volume-dominance chip: which side (calls/puts) moves more volume today.
    dom = vt_dominance_label(gex_sum)
    dom_html = ""
    if dom:
        dom_html = (
            f'<div style="margin-top:0.5rem;padding-top:0.45rem;'
            f'border-top:1px solid #16162a;font-size:0.62rem;'
            f'color:{dom["color"]};">▮ FLUJO DE SESIÓN · '
            f'<b>{dom["text"]}</b></div>')

    return _html(
        f'<div style="background:linear-gradient(135deg,#0b0b16,#0e0e1c);'
        f'border:1px solid #1e1e32;border-radius:9px;padding:0.6rem 0.95rem;'
        f'font-family:JetBrains Mono,monospace;">'
        f'<div style="font-size:0.56rem;color:#5b5b80;letter-spacing:0.16em;'
        f'text-transform:uppercase;margin-bottom:0.35rem;">Niveles clave</div>'
        f'{rows}{dom_html}</div>'
    )


def of_session_digest_panel(changes: dict) -> str:
    """'¿Qué cambió en la sesión?' — renders quant.orderflow_derived.
    session_changes(): GEX open→now, transiciones de régimen y saltos de
    muros, cada uno con su hora ET."""
    if not changes or not changes.get("n_ticks"):
        return _box_err("Sin historia de sesión todavía — el recorder "
                        "acumula un snapshot cada ~10 min de mercado.")

    def _et(ts_iso) -> str:
        try:
            import datetime as _dt
            from config import ET_TZ
            t = _dt.datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
            return t.astimezone(ET_TZ).strftime("%H:%M")
        except Exception:
            return "—"

    g0, g1 = changes.get("gex_open_mm"), changes.get("gex_now_mm")
    gd = changes.get("gex_delta_mm")
    gex_html = "—"
    if g0 is not None and g1 is not None:
        dcol = "#16C784" if (gd or 0) >= 0 else "#EA3943"
        gex_html = (f'${_humanize(g0 * 1e6)} → <b>${_humanize(g1 * 1e6)}</b> '
                    f'<span style="color:{dcol}">({gd:+,.0f}M)</span>')

    rch = changes.get("regime_changes") or []
    if rch:
        reg_html = " · ".join(
            f'<b style="color:{"#16C784" if c["to"] == "POSITIVE" else "#EA3943"}">'
            f'{_et(c["ts"])}</b> {c["from"][:3]}→{c["to"][:3]}' for c in rch)
    else:
        rnow = changes.get("regime_now") or "—"
        reg_html = f"sin cambios · {rnow} toda la sesión"

    wall_lines = ""
    wall_names = {"call_wall": ("Call Wall", "#16C784"),
                  "put_wall": ("Put Wall", "#EA3943"),
                  "hvl": ("HVL", "#a855f7")}
    for key, (name, clr) in wall_names.items():
        w = (changes.get("walls") or {}).get(key) or {}
        moves = w.get("moves") or []
        if moves:
            mtxt = " · ".join(f'{_et(m["ts"])} {m["from"]:.0f}→{m["to"]:.0f}'
                              for m in moves[-3:])
            extra = f" (+{len(moves) - 3} más)" if len(moves) > 3 else ""
            wall_lines += (f'<div style="font-size:0.7rem;color:#9595b8;'
                           f'margin-top:2px;"><b style="color:{clr}">{name}'
                           f'</b> se movió: {mtxt}{extra}</div>')
    if not wall_lines:
        wall_lines = ('<div style="font-size:0.7rem;color:#7a7a98;'
                      'margin-top:2px;">Muros estables toda la sesión ✓</div>')

    span = f'{_et(changes.get("first_ts"))} → {_et(changes.get("last_ts"))} ET'
    return _html(f"""
    <div style="background:linear-gradient(135deg,#0b0b16,#0e0e1c);
         border:1px solid #1e1e32;border-left:4px solid #F5A623;
         padding:0.85rem 1.05rem;border-radius:8px;margin:0.4rem 0 0.9rem;
         font-family:JetBrains Mono,monospace;">
      <div style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;">
        <div style="font-size:0.62rem;color:#F5A623;letter-spacing:0.14em;">
          ¿QUÉ CAMBIÓ EN LA SESIÓN?
        </div>
        <div style="font-size:0.6rem;color:#5b5b80;">{span} · {changes["n_ticks"]} snapshots</div>
      </div>
      <div style="font-size:0.78rem;color:#c8c8e0;margin-top:6px;">
        Net GEX: {gex_html}
      </div>
      <div style="font-size:0.7rem;color:#9595b8;margin-top:3px;">
        Régimen: {reg_html}
      </div>
      {wall_lines}
    </div>
    """)


# ─────────────────────────────────────────────────────────────────────────────
#  OVERVIEW COCKPIT  —  veredicto + mapa de precio a escala + acción AHORA
# ─────────────────────────────────────────────────────────────────────────────
def overview_cockpit(symbol: str, spot: float, chg_p: Optional[float],
                     gex_sum: Optional[dict], gex_0dte: Optional[dict] = None,
                     rnd_levels: Optional[dict] = None,
                     rnd_meta: Optional[dict] = None,
                     iv_hv: Optional[float] = None,
                     hiro_snap: Optional[dict] = None,
                     p_c: Optional[float] = None,
                     max_pain: Optional[float] = None) -> str:
    """Cockpit de decisión: lo que ves en 2 segundos. Régimen → la jugada,
    la acción de AHORA según dónde está el precio, un mapa de niveles A ESCALA,
    el plan en ambos extremos, contexto compacto y un aviso condicional."""
    if not gex_sum or not spot or spot <= 0:
        return _box_err("Sin datos GEX para el cockpit.")
    g = gex_sum
    regime = g.get("regime", "NEUTRAL")
    cw, pw = g.get("call_wall"), g.get("put_wall")
    gf, hvl = g.get("gamma_flip"), g.get("hvl")
    vt_c, vt_p = g.get("vt_c"), g.get("vt_p")
    net = g.get("total_gex")

    if regime == "POSITIVE":
        reg_lbl, reg_clr, mode = "GAMMA POSITIVA · RANGO", "#16C784", "range"
    elif regime == "NEGATIVE":
        reg_lbl, reg_clr, mode = "GAMMA NEGATIVA · TENDENCIA", "#EA3943", "trend"
    else:
        reg_lbl, reg_clr, mode = "RÉGIMEN NEUTRAL", "#F5A623", "neutral"

    # ── Alineación agregado vs 0DTE ──────────────────────────────────────────
    reg0 = (gex_0dte or {}).get("regime")
    aligned = bool(reg0 and reg0 == regime and regime != "NEUTRAL")
    diverge = bool(reg0 and reg0 != regime and regime != "NEUTRAL"
                   and reg0 != "NEUTRAL")
    if aligned:
        align_html = ('<span style="color:#16C784">✓ agregado &amp; 0DTE '
                      'alineados</span>')
    elif diverge:
        align_html = ('<span style="color:#fbbf24">⚠ agregado vs 0DTE '
                      'divergen</span>')
    else:
        align_html = '<span style="color:#6c6c90">0DTE n/d</span>'

    # ── Confluencia simple (alineación + confianza RND + IV/HV coherente) ────
    conf_rnd = (rnd_meta or {}).get("confidence")
    fac, tot = 0, 0
    if reg0:
        tot += 1; fac += 1 if aligned else 0
    if conf_rnd:
        tot += 1; fac += 1 if conf_rnd in ("high", "medium") else 0
    if iv_hv:
        tot += 1
        if mode == "range" and iv_hv > 1.0:
            fac += 1
        elif mode == "trend" and iv_hv < 1.0:
            fac += 1
    conf_pct = int(round(fac / tot * 100)) if tot else 0
    conf_clr = "#16C784" if conf_pct >= 67 else ("#fbbf24" if conf_pct >= 34
                                                 else "#EA3943")

    # ── Posición del precio dentro del rango estructural ─────────────────────
    pos = None
    if cw and pw and cw > pw:
        pos = max(0.0, min(1.0, (spot - pw) / (cw - pw)))

    def _near(a):
        return a and abs(spot - a) / spot < 0.0015

    # ── La ACCIÓN de AHORA (lo decisivo) ─────────────────────────────────────
    if gf and _near(gf):
        now_ico, now_clr = "⚠", "#fbbf24"
        now_big = "CERCA DEL FLIP — régimen indefinido"
        now_sub = "Reduce tamaño. Espera un cierre claro de un lado del Zero Γ."
    elif pos is not None and pos >= 0.80:
        if mode == "range":
            now_ico, now_clr = "▼", "#EA3943"
            now_big = f"EN EL TECHO (${cw:.0f}) — vende / fade"
            now_sub = (f"Stop arriba del Call Wall, objetivo el HVL "
                       f"${hvl:.0f}." if hvl else "Stop arriba del Call Wall.")
        else:
            now_ico, now_clr = "▲", "#16C784"
            now_big = f"ROMPIENDO EL TECHO (${cw:.0f}) — sigue al alza"
            now_sub = "Momentum: entra a favor, trailing stop. No fades."
    elif pos is not None and pos <= 0.20:
        if mode == "range":
            now_ico, now_clr = "▲", "#16C784"
            now_big = f"EN EL PISO (${pw:.0f}) — compra / fade"
            now_sub = (f"Stop debajo del Put Wall, objetivo el HVL "
                       f"${hvl:.0f}." if hvl else "Stop debajo del Put Wall.")
        else:
            now_ico, now_clr = "▼", "#EA3943"
            now_big = f"ROMPIENDO EL PISO (${pw:.0f}) — sigue a la baja"
            now_sub = "Momentum: entra a favor, trailing stop. No fades."
    else:
        if mode == "range":
            now_ico, now_clr = "⏸", "#fbbf24"
            now_big = "ESPERA — precio en zona media"
            now_sub = (f"No persigas el centro. Actúa en los extremos: "
                       f"vende ${cw:.0f} / compra ${pw:.0f}."
                       if (cw and pw) else "Actúa en los muros.")
        elif mode == "trend":
            now_ico, now_clr = "≈", "#EA3943"
            now_big = "TENDENCIA en curso — opera con momentum"
            now_sub = "El dealer amplifica. Sigue la dirección, no fades muros."
        else:
            now_ico, now_clr = "·", "#F5A623"
            now_big = "Sin sesgo claro"
            now_sub = "Espera a que el precio defina un lado del Gamma Flip."

    # ── Mapa de precio A ESCALA (SVG) ────────────────────────────────────────
    svg = _cockpit_price_map(spot, cw, pw, gf, hvl, vt_c, vt_p, mode)

    # ── Plan en ambos extremos ───────────────────────────────────────────────
    def _plan(level, side):
        if not level:
            return ('<div style="flex:1;background:#0e0e18;border:1px solid '
                    '#1e1e32;border-radius:9px;padding:8px 11px;color:#6c6c90;'
                    'font-size:0.72rem;">— sin muro</div>')
        tgt = hvl if hvl else spot
        if mode == "range":
            if side == "up":
                head, hc, bc = f"▼ SI LLEGA A ${level:.0f}", "#16C784", "#1e3a22"
                body = (f"SHORT/fade · stop ${level + spot*0.0008:.0f} · "
                        f"target ${tgt:.0f}")
            else:
                head, hc, bc = f"▲ SI LLEGA A ${level:.0f}", "#EA3943", "#3a1e22"
                body = (f"LONG/fade · stop ${level - spot*0.0008:.0f} · "
                        f"target ${tgt:.0f}")
        else:  # trend → breakout plays
            if side == "up":
                head, hc, bc = f"▲ SI ROMPE ${level:.0f}", "#16C784", "#1e3a22"
                body = f"LONG breakout · stop ${level:.0f} · deja correr"
            else:
                head, hc, bc = f"▼ SI ROMPE ${level:.0f}", "#EA3943", "#3a1e22"
                body = f"SHORT breakout · stop ${level:.0f} · deja correr"
        return (
            f'<div style="flex:1;background:#0e0e18;border:1px solid {bc};'
            f'border-radius:9px;padding:7px 10px;">'
            f'<div style="color:{hc};font-size:0.62rem;font-weight:700;">{head}</div>'
            f'<div style="color:#e8e8f4;font-size:0.66rem;margin-top:3px;">{body}'
            f'</div></div>')

    plan_html = (f'<div style="display:flex;gap:8px;margin-top:8px;">'
                 f'{_plan(cw, "up")}{_plan(pw, "down")}</div>')

    # ── Chips de contexto ────────────────────────────────────────────────────
    def _chip(label, val, vclr="#ececf6"):
        return (f'<span style="background:#0e0e18;border:1px solid #1e1e32;'
                f'border-radius:6px;padding:3px 8px;font-size:0.62rem;'
                f'color:#aeaecb;">{label} <b style="color:{vclr}">{val}</b></span>')
    chips = ""
    if net is not None:
        nclr = "#16C784" if net >= 0 else "#EA3943"
        chips += _chip("Net GEX", f"${net/1e9:+.2f}B", nclr)
    pct = (rnd_levels or {}).get("percentiles", {})
    p16, p84 = pct.get("p16"), pct.get("p84")
    if p16 and p84:
        chips += _chip("RND 1σ", f"{p16:,.0f}–{p84:,.0f}", "#22d3ee")
    if iv_hv:
        chips += _chip("IV/HV", f"{iv_hv:.2f}×", "#fbbf24")
    if hiro_snap and hiro_snap.get("hiro") is not None:
        h = hiro_snap.get("hiro", 0)
        chips += _chip("HIRO", ("▲ buy" if h >= 0 else "▼ sell"),
                       "#16C784" if h >= 0 else "#EA3943")
    if p_c is not None:
        chips += _chip("P/C", f"{p_c:.2f}")
    if max_pain:
        chips += _chip("Max Pain", f"{max_pain:.0f}")
    chips_html = (f'<div style="display:flex;flex-wrap:wrap;gap:5px;'
                  f'margin-top:8px;">{chips}</div>') if chips else ""

    # ── Aviso condicional ────────────────────────────────────────────────────
    warn = ""
    h = (hiro_snap or {}).get("hiro")
    if diverge:
        warn = ("Estructura y 0DTE divergen — para scalping pesa el 0DTE "
                f"({reg0}).")
    elif mode == "range" and pw and h is not None and h < 0:
        warn = (f"HIRO vendiendo — si pierde el Put Wall ${pw:.0f} con volumen, "
                f"el rango se rompe (posible giro a gamma negativa).")
    elif mode == "range" and cw and h is not None and h > 0:
        warn = (f"HIRO comprando — si supera el Call Wall ${cw:.0f} con volumen, "
                f"el rango se rompe al alza.")
    elif conf_rnd == "low":
        warn = "RND de baja confianza (0DTE) — los niveles RND son orientativos."
    warn_html = (
        f'<div style="background:#1a1407;border:1px solid #5a4410;'
        f'border-radius:7px;padding:6px 10px;font-size:0.64rem;color:#fbbf24;'
        f'margin-top:8px;">⚠ <b>Vigila:</b> {warn}</div>') if warn else ""

    chg_html = (f'<span style="color:{"#16C784" if (chg_p or 0) >= 0 else "#EA3943"};'
                f'font-size:0.66rem;">{(chg_p or 0):+.2f}%</span>'
                if chg_p is not None else "")

    return _html(f"""
    <div style="background:#0a0a12;border:1px solid #23233a;border-radius:12px;
         padding:0.8rem 0.95rem;margin:0.2rem 0 0.9rem;
         font-family:JetBrains Mono,monospace;font-size:0.7rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="color:#F5A623;font-weight:800;font-size:0.72rem;">❯ GEX</span>
          <span style="color:#f5f5ff;font-weight:800;font-size:0.9rem;">{symbol} ${spot:,.2f}</span>
          {chg_html}
        </div>
        <span style="background:{reg_clr}1a;border:1px solid {reg_clr};
              color:{reg_clr};border-radius:20px;padding:3px 10px;
              font-size:0.62rem;font-weight:700;">{reg_lbl}</span>
      </div>

      <div style="background:#11131c;border:1px solid #2a2a44;border-radius:10px;
           padding:0.6rem 0.8rem;margin-top:0.55rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:0.55rem;color:#5b5b80;letter-spacing:0.13em;">
            ACCIÓN AHORA</span>
          <span style="font-size:0.58rem;">{align_html} · conf
            <b style="color:{conf_clr}">{conf_pct}%</b></span>
        </div>
        <div style="color:#fff;font-weight:800;font-size:0.92rem;margin-top:4px;
             line-height:1.25;"><span style="color:{now_clr}">{now_ico}</span>
          {now_big}</div>
        <div style="color:#cfcfe6;font-size:0.7rem;margin-top:3px;">{now_sub}</div>
      </div>

      <div style="margin-top:0.7rem;">{svg}</div>
      {plan_html}
      {chips_html}
      {warn_html}
    </div>
    """)


def _cockpit_price_map(spot, cw, pw, gf, hvl, vt_c, vt_p, mode) -> str:
    """SVG horizontal del precio A ESCALA con muros, HVL, flip, VT y zonas de
    acción cerca de los muros. Posiciones proporcionales al precio real."""
    pts = [p for p in (cw, pw, gf, hvl, spot, vt_c, vt_p) if p]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    pad = max((hi - lo) * 0.07, spot * 0.0008)
    lo -= pad; hi += pad
    span = (hi - lo) or 1.0
    # viewBox ancho (1200) para que, al estirarse al ancho del Overview, el
    # texto renderice proporcional (~11-12px) y no gigante.
    X0, W = 28.0, 1144.0

    def X(p):
        return X0 + (p - lo) / span * W

    parts = ['<svg viewBox="0 0 1200 122" style="width:100%;display:block">']
    parts.append('<text x="12" y="12" fill="#5b5b80" '
                 'font-family="JetBrains Mono,monospace" font-size="10" '
                 'letter-spacing="1.2">MAPA DE PRECIO · A ESCALA</text>')
    # zonas de acción cerca de los muros (solo en rango)
    band = spot * 0.0035
    if mode == "range":
        if cw:
            x0 = X(cw - band)
            parts.append(f'<rect x="{x0:.1f}" y="46" width="{X(cw) - x0 + 14:.1f}"'
                         f' height="22" rx="4" fill="#16C784" opacity="0.10"/>')
            parts.append(f'<text x="{(x0 + X(cw)) / 2:.1f}" y="42" fill="#16C784"'
                         f' font-family="JetBrains Mono,monospace" font-size="9.5"'
                         f' text-anchor="middle">vende</text>')
        if pw:
            x1 = X(pw + band)
            parts.append(f'<rect x="{X(pw) - 14:.1f}" y="46" '
                         f'width="{x1 - X(pw) + 14:.1f}" height="22" rx="4" '
                         f'fill="#EA3943" opacity="0.10"/>')
            parts.append(f'<text x="{(X(pw) + x1) / 2:.1f}" y="42" fill="#EA3943"'
                         f' font-family="JetBrains Mono,monospace" font-size="9.5"'
                         f' text-anchor="middle">compra</text>')
    parts.append('<line x1="28" y1="57" x2="1172" y2="57" stroke="#23233a" '
                 'stroke-width="2"/>')

    def tick(p, clr, lbl, sub=None, major=True, dash=False):
        if not p:
            return
        x = X(p)
        h = 20 if major else 12
        da = ' stroke-dasharray="2 2"' if dash else ''
        wd = 3 if major else 1.5
        parts.append(f'<line x1="{x:.1f}" y1="{57 - h/2:.1f}" x2="{x:.1f}" '
                     f'y2="{57 + h/2:.1f}" stroke="{clr}" stroke-width="{wd}"{da}/>')
        fs = 11 if major else 9
        fw = ' font-weight="700"' if major else ''
        parts.append(f'<text x="{x:.1f}" y="80" fill="{clr}" '
                     f'font-family="JetBrains Mono,monospace" font-size="{fs}"{fw} '
                     f'text-anchor="middle">{p:.0f}</text>')
        if sub:
            parts.append(f'<text x="{x:.1f}" y="92" fill="#7a7a98" '
                         f'font-family="JetBrains Mono,monospace" font-size="8.5" '
                         f'text-anchor="middle">{sub}</text>')

    tick(gf, "#F5A623", "flip", "flip", major=True, dash=True)
    tick(vt_p, "#EA3943", "vtp", None, major=False, dash=True)
    tick(pw, "#EA3943", "pw", "PUT WALL", major=True)
    tick(hvl, "#a855f7", "hvl", "HVL imán", major=True, dash=True)
    tick(vt_c, "#fbbf24", "vtc", None, major=False, dash=True)
    tick(cw, "#16C784", "cw", "CALL WALL", major=True)

    # spot (encima de todo)
    xs = X(spot)
    parts.append(f'<line x1="{xs:.1f}" y1="32" x2="{xs:.1f}" y2="72" '
                 f'stroke="#22d3ee" stroke-width="2.5"/>')
    parts.append(f'<circle cx="{xs:.1f}" cy="57" r="5" fill="#22d3ee"/>')
    bx = max(2, min(1108, xs - 44))
    parts.append(f'<rect x="{bx:.1f}" y="14" width="88" height="18" rx="4" '
                 f'fill="#0a0a12" stroke="#22d3ee"/>')
    parts.append(f'<text x="{bx + 44:.1f}" y="27" fill="#22d3ee" '
                 f'font-family="JetBrains Mono,monospace" font-size="11" '
                 f'font-weight="700" text-anchor="middle">SPOT {spot:.0f}</text>')

    # nota de posición
    if cw and pw and cw > pw:
        ppos = (spot - pw) / (cw - pw) * 100
        side = "más cerca del piso" if ppos < 50 else "más cerca del techo"
        parts.append(f'<text x="600" y="112" fill="#7a7a98" '
                     f'font-family="JetBrains Mono,monospace" font-size="10" '
                     f'text-anchor="middle">posición: {ppos:.0f}% del rango · '
                     f'{side}</text>')
    parts.append('</svg>')
    return "".join(parts)


def panel_0dte_glass_metrics(zdte_sum: Optional[dict],
                             dex_sum: Optional[dict],
                             vex_sum: Optional[dict],
                             cex_sum: Optional[dict],
                             spot: float, minutes_to_close: float,
                             risk_color: str, risk_label: str) -> str:
    """Hero glassmorphism ('cristal water') para el 0DTE: cuenta-regresiva al
    cierre + 8 métricas (exposiciones y niveles) en tarjetas de cristal
    esmerilado sobre un fondo con orbes de color que el blur refracta.
    Estética Bloomberg + sofisticada."""
    g = zdte_sum or {}
    net_g = g.get("total_gex", 0) / 1e6
    net_d = (dex_sum or {}).get("total_dex", 0) / 1e6
    net_v = (vex_sum or {}).get("total_vex", 0) / 1e6
    net_c = (cex_sum or {}).get("total_cex", 0) / 1e6
    cw, pw = g.get("call_wall"), g.get("put_wall")
    gf, hvl = g.get("gamma_flip"), g.get("hvl")

    GREEN, RED, CYAN = "#16C784", "#EA3943", "#22d3ee"
    GOLD, PURPLE, INK = "#fbbf24", "#c4b5fd", "#f0f0fb"

    GLASS = ("background:rgba(255,255,255,0.045);"
             "backdrop-filter:blur(16px) saturate(150%);"
             "-webkit-backdrop-filter:blur(16px) saturate(150%);"
             "border:1px solid rgba(255,255,255,0.10);border-radius:13px;"
             "box-shadow:inset 0 1px 0 rgba(255,255,255,0.10),"
             "0 8px 30px rgba(0,0,0,0.32);")

    def _mm(v, unit=""):
        return (f"${v/1000:+,.1f}B{unit}" if abs(v) >= 1000
                else f"${v:+.1f}M{unit}")

    def tile(label, value, vclr, sub=""):
        sub_html = (f'<div style="font-size:0.56rem;color:#9a9ac0;margin-top:3px;'
                    f'white-space:nowrap;">{sub}</div>') if sub else ""
        return (
            f'<div style="{GLASS}padding:0.55rem 0.7rem;">'
            f'<div style="font-size:0.53rem;color:#8a8ab0;letter-spacing:0.13em;'
            f'text-transform:uppercase;white-space:nowrap;">{label}</div>'
            f'<div style="font-size:1.02rem;font-weight:800;color:{vclr};'
            f'margin-top:4px;font-variant-numeric:tabular-nums;line-height:1;'
            f'white-space:nowrap;">{value}</div>{sub_html}</div>')

    expos = (
        tile("Net GEX", _mm(net_g), GREEN if net_g >= 0 else RED,
             "LONG Γ · amortigua" if net_g >= 0 else "SHORT Γ · amplifica")
        + tile("Net DEX", _mm(net_d), GREEN if net_d >= 0 else RED,
               "call-heavy" if net_d > 0 else
               ("put-heavy" if net_d < 0 else "neutral"))
        + tile("Net VEX", _mm(net_v, "/vol"), CYAN, "vanna → 0 al cierre")
        + tile("Net CEX", _mm(net_c, "/día"), GOLD, "charm · flujo EOD"))

    gf_sub = (f"{(gf - spot)/spot*100:+.2f}% vs spot"
              if gf and spot and spot > 0 else "pivote de régimen")
    levels = (
        tile("Call Wall", f"${cw:.0f}" if cw else "—", GREEN, "techo de γ")
        + tile("Put Wall", f"${pw:.0f}" if pw else "—", RED, "piso de γ")
        + tile("Zero Γ", f"${gf:.0f}" if gf else "—", PURPLE, gf_sub)
        + tile("HVL · pin", f"${hvl:.0f}" if hvl else "—", CYAN, "imán de pinning"))

    mins = int(minutes_to_close)
    eod = (
        f'<div style="{GLASS}border-left:3px solid {risk_color};'
        f'padding:0.6rem 0.85rem;display:flex;justify-content:space-between;'
        f'align-items:center;gap:1rem;flex-wrap:wrap;">'
        f'<div><div style="font-size:0.53rem;color:#8a8ab0;letter-spacing:0.14em;">'
        f'TIME TO CLOSE</div><div style="font-size:1.5rem;font-weight:800;'
        f'color:{risk_color};line-height:1;">{mins}<span style="font-size:0.78rem;'
        f'color:#9a9ac0;font-weight:500;"> min</span></div></div>'
        f'<div style="text-align:center;"><div style="font-size:0.53rem;'
        f'color:#8a8ab0;letter-spacing:0.1em;">SPOT</div>'
        f'<div style="font-size:1.15rem;font-weight:800;color:{INK};">'
        f'${spot:,.2f}</div></div>'
        f'<div style="color:{risk_color};font-size:0.8rem;font-weight:700;'
        f'letter-spacing:0.06em;">{risk_label}</div></div>')

    orbs = (
        '<div style="position:absolute;top:-70px;left:-50px;width:300px;'
        'height:240px;background:radial-gradient(circle,rgba(245,166,35,0.20),'
        'transparent 68%);pointer-events:none;"></div>'
        '<div style="position:absolute;top:-50px;right:-40px;width:280px;'
        'height:220px;background:radial-gradient(circle,rgba(201,130,26,0.17),'
        'transparent 68%);pointer-events:none;"></div>'
        '<div style="position:absolute;bottom:-90px;left:34%;width:360px;'
        'height:260px;background:radial-gradient(circle,rgba(245,166,35,0.12),'
        'transparent 68%);pointer-events:none;"></div>')

    def _seclab(t):
        return (f'<div style="font-size:0.52rem;color:#6a6a90;'
                f'letter-spacing:0.18em;text-transform:uppercase;'
                f'margin:0.7rem 0 0.4rem;">{t}</div>')

    grid = ("display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));"
            "gap:9px;")
    return _html(f"""
    <div style="position:relative;overflow:hidden;border-radius:18px;
         padding:0.9rem;margin:0.3rem 0 0.9rem;
         background:linear-gradient(160deg,#0c0e1a 0%,#09090f 100%);
         border:1px solid rgba(255,255,255,0.07);
         font-family:JetBrains Mono,monospace;">
      {orbs}
      <div style="position:relative;z-index:1;">
        {eod}
        {_seclab('Exposiciones 0DTE · flujo de cobertura del dealer')}
        <div style="{grid}">{expos}</div>
        {_seclab('Niveles 0DTE · estructura de gamma de hoy')}
        <div style="{grid}">{levels}</div>
      </div>
    </div>
    """)


def regime_compare_panel(gex_agg: Optional[dict],
                         gex_0dte: Optional[dict]) -> str:
    """Compara el régimen de gamma AGREGADO (estructural, 0–60d) contra el
    0DTE (intradía) lado a lado, con una alerta cuando DIVERGEN — que es
    justo la señal valiosa para scalping ('estructura LONG pero 0DTE ya
    SHORT → pesa el 0DTE')."""
    def _read(gs):
        if not gs:
            return None
        return {"reg": gs.get("regime", "NEUTRAL"),
                "net": gs.get("total_gex"), "gf": gs.get("gamma_flip")}

    a, z = _read(gex_agg), _read(gex_0dte)

    def _lab(reg):
        if reg == "POSITIVE":
            return "LONG Γ", "#16C784", "dealer amortigua"
        if reg == "NEGATIVE":
            return "SHORT Γ", "#EA3943", "dealer amplifica"
        return "NEUTRAL", "#F5A623", "régimen indefinido"

    def _card(title, sub, data):
        if not data:
            body = ('<div style="font-size:0.95rem;color:#6b6b8a;'
                    'font-weight:700;">— no disponible</div>'
                    '<div style="font-size:0.6rem;color:#4a4a68;margin-top:4px;">'
                    'sin 0DTE para este símbolo</div>')
            bclr = "#1e1e32"
        else:
            lab, clr, desc = _lab(data["reg"])
            net = data["net"]
            net_txt = (f'${net / 1e9:+.2f}B' if net is not None else "—")
            gf_txt = (f'· Zero Γ ${data["gf"]:.0f}' if data["gf"] else "")
            body = (
                f'<div style="font-size:1.15rem;color:{clr};font-weight:800;'
                f'line-height:1;">{lab}</div>'
                f'<div style="font-size:0.62rem;color:{clr};margin-top:3px;">'
                f'{desc}</div>'
                f'<div style="font-size:0.66rem;color:#9595b8;margin-top:5px;">'
                f'Net GEX <b>{net_txt}</b> {gf_txt}</div>')
            bclr = f'{clr}55'
        return (
            f'<div style="flex:1 1 160px;background:#0b0b15;border:1px solid '
            f'{bclr};border-radius:7px;padding:0.6rem 0.75rem;">'
            f'<div style="font-size:0.55rem;color:#5b5b80;letter-spacing:0.12em;'
            f'text-transform:uppercase;margin-bottom:5px;">{title} '
            f'<span style="color:#3c3c58;">· {sub}</span></div>{body}</div>')

    # Divergence banner
    diverge = (a and z and a["reg"] != z["reg"]
               and a["reg"] != "NEUTRAL" and z["reg"] != "NEUTRAL")
    if diverge:
        banner = (
            f'<div style="background:rgba(245,166,35,0.12);border:1px solid '
            f'rgba(245,166,35,0.45);border-radius:6px;padding:0.4rem 0.7rem;'
            f'margin-bottom:0.55rem;font-size:0.66rem;color:#fbbf24;">'
            f'⚠ <b>DIVERGEN</b> — estructura {_lab(a["reg"])[0]} pero 0DTE '
            f'{_lab(z["reg"])[0]}. Para scalping intradía pesa el <b>0DTE</b> '
            f'(y más hacia el cierre).</div>')
    elif a and z and a["reg"] == z["reg"] and a["reg"] != "NEUTRAL":
        banner = (
            f'<div style="background:rgba(22,199,132,0.10);border:1px solid '
            f'rgba(22,199,132,0.35);border-radius:6px;padding:0.4rem 0.7rem;'
            f'margin-bottom:0.55rem;font-size:0.66rem;color:#16C784;">'
            f'✓ <b>ALINEADOS</b> — agregado y 0DTE ambos '
            f'{_lab(a["reg"])[0]}. Convicción más alta.</div>')
    else:
        banner = ""

    return _html(
        f'<div style="background:linear-gradient(135deg,#0b0b16,#0e0e1c);'
        f'border:1px solid #1e1e32;border-radius:9px;padding:0.7rem 0.95rem;'
        f'margin:0.2rem 0 0.4rem;font-family:JetBrains Mono,monospace;">'
        f'<div style="font-size:0.56rem;color:#5b5b80;letter-spacing:0.14em;'
        f'text-transform:uppercase;margin-bottom:0.5rem;">'
        f'◭ RÉGIMEN DE GAMMA · ESTRUCTURAL vs INTRADÍA</div>'
        f'{banner}'
        f'<div style="display:flex;gap:0.6rem;flex-wrap:wrap;">'
        f'{_card("Agregado", "0–60d", a)}'
        f'{_card("0DTE", "hoy", z)}</div></div>')


# ─────────────────────────────────────────────────────────────────────────────
#  Overview v3 — héroe de régimen (liquid glass) + gráfico mariposa GEX|RND
# ─────────────────────────────────────────────────────────────────────────────
_OV_GLASS = (
    "background:rgba(255,255,255,0.035);"
    "backdrop-filter:blur(14px) saturate(140%);"
    "-webkit-backdrop-filter:blur(14px) saturate(140%);"
    "border:1px solid rgba(255,255,255,0.09);border-radius:14px;"
    "box-shadow:inset 0 1px 0 rgba(255,255,255,0.08),"
    "0 8px 30px rgba(0,0,0,0.30);"
)


def _ov_regime(reg: Optional[str]):
    if reg == "POSITIVE":
        return ("GAMMA POSITIVA · LONG Γ", "#16C784",
                "El dealer amortigua el movimiento — fade extremos, "
                "el precio es atraído al pin.")
    if reg == "NEGATIVE":
        return ("GAMMA NEGATIVA · SHORT Γ", "#EA3943",
                "El dealer amplifica el movimiento — momentum manda, "
                "no fades los muros.")
    return ("GAMMA NEUTRAL", "#F5A623",
            "Régimen indefinido — espera confirmación de dirección.")


def overview_hero(symbol: str, spot: float, chg_p: Optional[float],
                  gex_scoped: Optional[dict], gex_agg: Optional[dict],
                  gex_0dte: Optional[dict], scope_label: str) -> str:
    """Héroe del Overview: precio grande + UN bloque de régimen legible en un
    vistazo. Cristal líquido (blur + orbes ámbar) sobre tokens de marca."""
    reg_title, reg_clr, reg_desc = _ov_regime((gex_scoped or {}).get("regime"))

    chg_html = ""
    if chg_p is not None:
        c_clr = "#16C784" if chg_p >= 0 else "#EA3943"
        arrow = "▲" if chg_p >= 0 else "▼"
        chg_html = (f'<span style="font-family:JetBrains Mono,monospace;'
                    f'font-size:0.95rem;color:{c_clr};">{arrow} '
                    f'{abs(chg_p):.2f}%</span>')

    a_reg = (gex_agg or {}).get("regime")
    z_reg = (gex_0dte or {}).get("regime") if gex_0dte else None
    if a_reg and z_reg and "NEUTRAL" not in (a_reg, z_reg):
        align = ('<div style="font-family:JetBrains Mono,monospace;'
                 'font-size:0.68rem;color:#16C784;margin-top:7px;">'
                 '✓ 0DTE y agregado alineados</div>'
                 if a_reg == z_reg else
                 '<div style="font-family:JetBrains Mono,monospace;'
                 'font-size:0.68rem;color:#F5A623;margin-top:7px;">'
                 '⚠ 0DTE y agregado divergen — para intradía pesa el 0DTE'
                 '</div>')
    else:
        align = ""

    net = (gex_scoped or {}).get("total_gex")
    net_html = (f'<span style="color:#9AA1A9;">Net GEX</span> '
                f'<b style="color:{reg_clr};">${net/1e9:+.2f}B</b>'
                if net is not None else "")

    orbs = (
        '<div style="position:absolute;top:-70px;right:-40px;width:300px;'
        'height:230px;background:radial-gradient(circle,'
        'rgba(245,166,35,0.16),transparent 68%);pointer-events:none;"></div>'
        '<div style="position:absolute;bottom:-80px;left:22%;width:340px;'
        'height:240px;background:radial-gradient(circle,'
        'rgba(201,130,26,0.11),transparent 68%);pointer-events:none;"></div>')

    return _html(
        f'<div style="{_OV_GLASS}position:relative;overflow:hidden;'
        f'padding:1.1rem 1.35rem;margin:0.3rem 0 0.55rem;">{orbs}'
        f'<div style="position:relative;z-index:1;display:flex;gap:1.8rem;'
        f'align-items:center;flex-wrap:wrap;">'
        f'<div style="min-width:200px;">'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:0.66rem;'
        f'color:#6B6B80;letter-spacing:0.16em;">{symbol} · {scope_label}</div>'
        f'<div style="display:flex;align-items:baseline;gap:10px;">'
        f'<span style="font-family:Space Grotesk,system-ui,sans-serif;'
        f'font-size:2.25rem;font-weight:700;color:#F4F5F6;line-height:1.08;">'
        f'{spot:,.2f}</span>{chg_html}</div>'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:0.7rem;'
        f'margin-top:3px;">{net_html}</div></div>'
        f'<div style="flex:1;min-width:280px;border-left:2px solid {reg_clr};'
        f'padding-left:18px;">'
        f'<div style="font-family:Space Grotesk,system-ui,sans-serif;'
        f'font-size:1.28rem;font-weight:700;color:{reg_clr};'
        f'line-height:1.15;">{reg_title}</div>'
        f'<div style="font-family:Inter,system-ui,sans-serif;'
        f'font-size:0.82rem;color:#9AA1A9;margin-top:4px;line-height:1.5;">'
        f'{reg_desc}</div>{align}</div></div></div>')


def overview_butterfly(gex_df, gex_sum: Optional[dict], rnd_df,
                       rnd_levels: Optional[dict], spot: float) -> str:
    """Gráfico 'mariposa': GEX por strike (ala izquierda) y densidad RND (ala
    derecha) compartiendo un eje de precio central. La línea de spot cruza
    ambas alas — gamma y probabilidad se leen a la misma altura de precio."""
    import numpy as np

    gs = gex_sum or {}
    if gex_df is None or gex_df.empty or not spot or spot <= 0:
        return ""

    # ── Ventana de strikes: ±1.5% del spot, ampliada para incluir muros
    #    cercanos (≤3%), máx 15 strikes alrededor del spot.
    df = gex_df.dropna(subset=["Strike", "Net_GEX"]).copy()
    lo, hi = spot * 0.985, spot * 1.015
    for w in (gs.get("call_wall"), gs.get("put_wall"), gs.get("hvl"),
              gs.get("gamma_flip")):
        if w and abs(w - spot) / spot <= 0.03:
            lo, hi = min(lo, w - 0.5), max(hi, w + 0.5)
    win = df[(df["Strike"] >= lo) & (df["Strike"] <= hi)]
    # .loc (etiquetas), NO .iloc: el índice de `win`/`df` conserva las
    # etiquetas del frame original (no contiguas tras filtrar) y sort_values()
    # devuelve esas etiquetas — usarlas como posiciones lanza IndexError.
    if len(win) < 5:
        win = df.loc[(df["Strike"] - spot).abs().sort_values().index[:11]]
    if len(win) > 15:
        win = win.loc[(win["Strike"] - spot).abs()
                      .sort_values().index[:15]]
    win = win.sort_values("Strike", ascending=False)
    strikes = win["Strike"].to_numpy(dtype=float)
    nets = win["Net_GEX"].to_numpy(dtype=float)
    if len(strikes) == 0 or np.max(np.abs(nets)) <= 0:
        return ""

    # ── Geometría (viewBox ancho 1200 → texto se renderiza ~proporcional)
    W, H = 1200.0, 470.0
    y0, y1 = 46.0, H - 44.0
    p_hi, p_lo = float(strikes.max()), float(strikes.min())
    span = max(p_hi - p_lo, 0.5)

    def _y(p):
        return y0 + (p_hi - p) / span * (y1 - y0)

    bar_right, bar_min_x = 540.0, 84.0
    spine_x, wing_x0, wing_x1 = 580.0, 622.0, 1140.0
    max_bar = bar_right - bar_min_x
    scale = max_bar / float(np.max(np.abs(nets)))
    n = len(strikes)
    bar_h = min(max(6.0, (y1 - y0) / max(n - 1, 1) * 0.52), 17.0)

    cw, pw = gs.get("call_wall"), gs.get("put_wall")
    gf, hvl = gs.get("gamma_flip"), gs.get("hvl")

    def _near(a, b, tol=0.26):
        return a is not None and b is not None and abs(a - b) <= tol

    svg = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" role="img" '
           f'aria-label="GEX por strike y densidad RND sobre el mismo eje '
           f'de precio; spot {spot:.2f}" style="display:block;">'
           '<defs><linearGradient id="ovRnd" x1="0" y1="0" x2="1" y2="0">'
           '<stop offset="0" stop-color="#F5A623" stop-opacity="0.02"/>'
           '<stop offset="1" stop-color="#F5A623" stop-opacity="0.24"/>'
           '</linearGradient></defs>']

    # ── Ala izquierda: barras Net GEX + spine + tags de muros
    mono = 'font-family="JetBrains Mono,monospace"'
    for k, v in zip(strikes, nets):
        y = _y(k)
        ln = abs(v) * scale
        clr = "#16C784" if v >= 0 else "#EA3943"
        svg.append(f'<rect x="{bar_right - ln:.1f}" y="{y - bar_h/2:.1f}" '
                   f'width="{ln:.1f}" height="{bar_h:.1f}" rx="2.5" '
                   f'fill="{clr}" fill-opacity="0.88"/>')
        # Spine: precio; muros en su color
        s_clr, s_w = "#6B6B80", "500"
        if _near(k, hvl):
            s_clr, s_w = "#F4F5F6", "700"
        if _near(k, gf):
            s_clr, s_w = "#F5A623", "700"
        if _near(k, cw):
            s_clr, s_w = "#16C784", "700"
        if _near(k, pw):
            s_clr, s_w = "#EA3943", "700"
        k_txt = f"{k:.0f}" if abs(k - round(k)) < 0.01 else f"{k:.1f}"
        svg.append(f'<text x="{spine_x:.0f}" y="{y + 5:.1f}" fill="{s_clr}" '
                   f'font-size="15.5" font-weight="{s_w}" {mono} '
                   f'text-anchor="middle">{k_txt}</text>')
        tag = None
        if _near(k, cw):
            tag = ("CW", "#16C784")
        elif _near(k, pw):
            tag = ("PW", "#EA3943")
        elif _near(k, gf):
            tag = ("ZΓ", "#F5A623")
        elif _near(k, hvl):
            tag = ("PIN", "#9AA1A9")
        if tag:
            svg.append(f'<text x="12" y="{y + 5:.1f}" fill="{tag[1]}" '
                       f'font-size="15" font-weight="700" {mono}>'
                       f'{tag[0]}</text>')

    # ── Ala derecha: densidad RND interpolada al mismo eje de precio
    has_rnd = rnd_df is not None and hasattr(rnd_df, "empty") \
        and not rnd_df.empty and "pdf" in getattr(rnd_df, "columns", [])
    if has_rnd:
        K = rnd_df["strike"].to_numpy(dtype=float)
        pdf = rnd_df["pdf"].to_numpy(dtype=float)
        ys = np.linspace(y0, y1, 72)
        prices = p_hi - (ys - y0) / (y1 - y0) * span
        dens = np.interp(prices, K, pdf, left=0.0, right=0.0)
        dmax = float(dens.max())
        if dmax > 0:
            xs = wing_x0 + dens / dmax * (wing_x1 - wing_x0 - 40.0)
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
            svg.append(f'<polygon points="{wing_x0:.0f},{y0:.0f} {pts} '
                       f'{wing_x0:.0f},{y1:.0f}" fill="url(#ovRnd)"/>')
            svg.append(f'<polyline points="{pts}" fill="none" '
                       f'stroke="#F5A623" stroke-width="2.2" '
                       f'stroke-linejoin="round"/>')
            lv = rnd_levels or {}
            mode = lv.get("mode")
            if mode and p_lo <= mode <= p_hi:
                my = _y(mode)
                mx = wing_x0 + float(np.interp(mode, K, pdf) / dmax) \
                    * (wing_x1 - wing_x0 - 40.0)
                svg.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="5" '
                           f'fill="#F5A623"/>')
                svg.append(f'<text x="{mx - 12:.1f}" y="{my - 12:.1f}" '
                           f'fill="#F4F5F6" font-size="15" {mono} '
                           f'text-anchor="end">moda {mode:.1f}</text>')
            pct = lv.get("percentiles") or {}
            for pkey, lab in (("p10", "P10"), ("p90", "P90")):
                pv = pct.get(pkey)
                if pv and p_lo <= pv <= p_hi:
                    py = _y(pv)
                    px = wing_x0 + float(np.interp(pv, K, pdf) / dmax) \
                        * (wing_x1 - wing_x0 - 40.0)
                    svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" '
                               f'r="3.4" fill="#9AA1A9"/>')
                    svg.append(f'<text x="{px + 12:.1f}" y="{py + 5:.1f}" '
                               f'fill="#9AA1A9" font-size="14.5" {mono}>'
                               f'{lab} {pv:.0f}</text>')
            # POP sobre el Put Wall (si la RND lo cubre)
            lp = (lv.get("level_probs") or {}).get("put_wall") or {}
            if lp.get("p_above") is not None:
                svg.append(f'<text x="{wing_x1:.0f}" y="{y1 - 6:.1f}" '
                           f'fill="#16C784" font-size="15" {mono} '
                           f'text-anchor="end">P(≥PW {lp.get("level"):.0f}) '
                           f'{lp["p_above"]*100:.0f}%</text>')
    else:
        svg.append(f'<text x="{(wing_x0 + wing_x1)/2:.0f}" '
                   f'y="{(y0 + y1)/2:.0f}" fill="#6B6B80" font-size="16" '
                   f'{mono} text-anchor="middle">RND no disponible para '
                   f'este vencimiento</text>')

    # ── Línea de spot cruzando ambas alas
    sy = _y(min(max(spot, p_lo), p_hi))
    svg.append(f'<line x1="{bar_min_x - 10:.0f}" y1="{sy:.1f}" '
               f'x2="{wing_x1:.0f}" y2="{sy:.1f}" stroke="#F5A623" '
               f'stroke-width="1.6" stroke-dasharray="7 5" '
               f'opacity="0.92"/>')
    svg.append(f'<text x="{wing_x1:.0f}" y="{sy - 9:.1f}" fill="#F5A623" '
               f'font-size="15.5" font-weight="700" {mono} '
               f'text-anchor="end">spot {spot:,.2f}</text>')
    svg.append('</svg>')

    header = (
        '<div style="display:flex;justify-content:space-between;'
        'margin-bottom:2px;font-family:JetBrains Mono,monospace;'
        'font-size:0.62rem;letter-spacing:0.18em;text-transform:uppercase;">'
        '<span style="color:#F5A623;">Modelo GEX '
        '<span style="color:#6B6B80;letter-spacing:0.04em;">· γ dealer por '
        'strike</span></span>'
        '<span style="color:#F5A623;">Modelo RND '
        '<span style="color:#6B6B80;letter-spacing:0.04em;">· prob. de '
        'cierre</span></span></div>')
    caption = (
        '<div style="text-align:center;font-family:JetBrains Mono,monospace;'
        'font-size:0.62rem;color:#6B6B80;margin-top:2px;">izq · Net GEX por '
        'strike (verde +γ · rojo −γ) &nbsp;·&nbsp; der · densidad RND de '
        'cierre &nbsp;·&nbsp; misma escala de precio · línea ámbar = spot'
        '</div>')
    orb = ('<div style="position:absolute;top:-60px;left:30%;width:360px;'
           'height:240px;background:radial-gradient(circle,'
           'rgba(245,166,35,0.07),transparent 68%);pointer-events:none;">'
           '</div>')
    return _html(
        f'<div style="{_OV_GLASS}position:relative;overflow:hidden;'
        f'padding:0.9rem 1.1rem 0.7rem;margin:0.15rem 0 0.5rem;">{orb}'
        f'<div style="position:relative;z-index:1;">{header}'
        f'{"".join(svg)}{caption}</div></div>')


def regime_flow_card(gex_agg: Optional[dict], gex_0dte: Optional[dict],
                     hiro_snap: Optional[dict]) -> str:
    """UNA tarjeta compacta: régimen estructural vs 0DTE (con alineación) +
    flujo HIRO + un takeaway accionable. Consolida lo que antes eran tres
    paneles sueltos (regime-compare, decision, HIRO) en el Overview."""
    def _lab(reg):
        if reg == "POSITIVE":
            return "LONG Γ", "#16C784", "dealer amortigua"
        if reg == "NEGATIVE":
            return "SHORT Γ", "#EA3943", "dealer amplifica"
        return "NEUTRAL", "#F5A623", "indefinido"

    a_reg = (gex_agg or {}).get("regime", "NEUTRAL")
    z_reg = (gex_0dte or {}).get("regime") if gex_0dte else None
    a_lab, a_clr, a_desc = _lab(a_reg)

    if z_reg and z_reg != "NEUTRAL" and a_reg != "NEUTRAL":
        align = ('<span style="color:#16C784;">✓ alineado</span>'
                 if z_reg == a_reg
                 else '<span style="color:#F5A623;">⚠ divergen</span>')
    else:
        align = ""
    if z_reg:
        z_lab, z_clr, _zd = _lab(z_reg)
        z_val = (f'<span style="color:{z_clr};font-weight:700;">{z_lab}</span>'
                 f'&nbsp;{align}')
    else:
        z_val = '<span style="color:#6b6b8a;">— sin 0DTE</span>'

    h = (hiro_snap or {}).get("hiro", 0) or 0
    if h > 0:
        hiro_val = '<span style="color:#16C784;font-weight:700;">▲ BUY pressure</span>'
    elif h < 0:
        hiro_val = '<span style="color:#EA3943;font-weight:700;">▼ SELL pressure</span>'
    else:
        hiro_val = '<span style="color:#9AA1A9;">equilibrado</span>'

    gov = z_reg or a_reg
    if gov == "NEGATIVE":
        take = "Dealer amplifica → opera con momentum, no fades los muros."
    elif gov == "POSITIVE":
        take = "Dealer amortigua → fade los extremos, mean-revert al pin (HVL)."
    else:
        take = "Régimen indefinido — espera confirmación de dirección."

    a_val = (f'<span style="color:{a_clr};font-weight:700;">{a_lab}</span>'
             f'&nbsp;<span style="color:{a_clr};font-size:0.6rem;opacity:.8;">'
             f'{a_desc}</span>')

    def _row(lbl, val, last=False):
        bb = "" if last else "border-bottom:1px solid #1c2026;"
        return (f'<div style="display:flex;justify-content:space-between;'
                f'align-items:center;padding:5px 0;{bb}font-size:0.72rem;">'
                f'<span style="color:#9AA1A9;">{lbl}</span>'
                f'<span style="font-family:JetBrains Mono,monospace;">{val}'
                f'</span></div>')

    glass = ("background:rgba(255,255,255,0.022);backdrop-filter:blur(9px) "
             "saturate(125%);-webkit-backdrop-filter:blur(9px) saturate(125%);"
             "border:1px solid rgba(255,255,255,0.07);border-radius:13px;"
             "padding:0.8rem 1rem;box-shadow:inset 0 1px 0 rgba(255,255,255,0.05);")
    return _html(
        f'<div style="{glass}">'
        f'<div style="font-size:0.58rem;color:#F5A623;letter-spacing:0.16em;'
        f'text-transform:uppercase;font-family:JetBrains Mono,monospace;'
        f'margin-bottom:0.5rem;">Régimen &amp; flujo</div>'
        f'{_row("Agregado · 0–60d", a_val)}'
        f'{_row("0DTE · hoy", z_val)}'
        f'{_row("HIRO · flujo", hiro_val, last=True)}'
        f'<div style="font-size:0.72rem;color:#c8c8d0;line-height:1.5;'
        f'margin-top:0.6rem;">{take}</div></div>')


def _metric(label: str, value: str, color: str = "#e0e0f0",
            sub: Optional[str] = None) -> str:
    """Compact metric cell used by the trade-setup-card footer grid."""
    sub_html = (f'<span style="font-size:0.62rem;color:{color};opacity:.65;'
                f'margin-left:5px;">{sub}</span>') if sub else ""
    return (
        f'<div><div style="font-size:0.55rem;color:#5b5b80;letter-spacing:0.1em;">'
        f'{label}</div><div style="font-size:0.92rem;color:{color};font-weight:700;'
        f'margin-top:2px;">{value}{sub_html}</div></div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Internals
# ─────────────────────────────────────────────────────────────────────────────
def _derive_levels(
    score: int, spot: float,
    cw: Optional[float], pw: Optional[float],
    gf: Optional[float], hvl: Optional[float],
    em_lo: Optional[float], em_hi: Optional[float],
    regime: str,
) -> dict:
    """Derive entry / stop / target from structural GEX levels.

    Returns a dict (NUMERIC for directional setups, so the card can compute
    R:R, distances and draw the price rail):
      kind        : "long" | "short" | "condor" | "flat"
      entry_lo/hi : float | None    (entry zone bounds)
      stop, target: float | None
      text_*      : str  | None     (non-directional fallback labels)

    Philosophy (unchanged):
      - LONG:  enter on pullback to HVL/flip (support), stop below put wall,
               target call wall / EM+.
      - SHORT: enter on rally to HVL/call wall, stop above call wall,
               target put wall / EM-.
      - NEUTRAL: iron condor between walls (POSITIVE Γ) or stay flat.
    """
    if score >= 2:
        entry_lo = max([x for x in [hvl, gf, pw] if x and x < spot] or [spot * 0.995])
        entry_hi = spot
        stop = (pw * 0.997) if pw else spot * 0.985
        target = cw or em_hi or (spot * 1.02)
        return {"kind": "long", "entry_lo": entry_lo, "entry_hi": entry_hi,
                "stop": stop, "target": target}
    if score <= -2:
        entry_lo = spot
        entry_hi = min([x for x in [hvl, gf, cw] if x and x > spot] or [spot * 1.005])
        stop = (cw * 1.003) if cw else spot * 1.015
        target = pw or em_lo or (spot * 0.98)
        return {"kind": "short", "entry_lo": entry_lo, "entry_hi": entry_hi,
                "stop": stop, "target": target}
    if regime == "POSITIVE" and cw and pw:
        return {"kind": "condor", "entry_lo": pw, "entry_hi": cw,
                "stop": None, "target": None,
                "text_entry": f"Sell {pw:.0f}P / {cw:.0f}C",
                "text_stop": "ruptura de muro", "text_target": "decay → expiry"}
    return {"kind": "flat", "entry_lo": None, "entry_hi": None,
            "stop": None, "target": None,
            "text_entry": "Stay flat / esperar", "text_stop": "—", "text_target": "—"}


def _recommend_expiry(dte: int, regime: str,
                      iv_hv_ratio: Optional[float]) -> str:
    """Choose an expiry preset based on the regime, IV richness, and
    the trader's currently-selected DTE on the dashboard.

    The `dte` parameter is now used as an explicit lower bound: if the
    user is already on a near-dated chain (≤ 7 DTE) the recommendation
    won't suggest "30-45 DTE (calendars)" — that would be unactionable
    without changing the selected expiry. Previously `dte` was unused.
    """
    if iv_hv_ratio is None:
        iv_hv_ratio = 1.0
    # Saturate the trader's anchor at a reasonable cap so a 0DTE
    # selection doesn't completely lock out longer recommendations.
    anchor_dte = max(0, int(dte))
    if regime == "NEGATIVE":
        if iv_hv_ratio > 1.3:
            return "0-2 DTE (debit)"
        # If trader is already on 0DTE, "7-14" is awkward; keep close.
        return "0-2 DTE (debit)" if anchor_dte == 0 else "7-14 DTE (debit)"
    if regime == "POSITIVE":
        if iv_hv_ratio > 1.3:
            return "1-7 DTE (credit)"
        # Avoid recommending 30-45d calendars when the trader is on
        # weekly chains; the suggestion would require switching tab.
        return ("1-7 DTE (credit)" if anchor_dte <= 7
                else "30-45 DTE (calendars)")
    return "7-21 DTE"


def _box_err(msg: str) -> str:
    return (
        '<div style="background:rgba(20,20,36,0.55);border-left:3px solid #8b8ba7;'
        'padding:0.5rem 0.8rem;margin:0.3rem 0 1rem;border-radius:4px;'
        'font-family:JetBrains Mono,monospace;font-size:0.72rem;'
        f'color:#8b8ba7;">{msg}</div>'
    )


def _card_err(msg: str) -> str:
    return _box_err(f"🤖 Trade Setup Card — {msg}")


# ─────────────────────────────────────────────────────────────────────────────
#  TRADING MODE  —  single-screen futures-ready view
# ─────────────────────────────────────────────────────────────────────────────
def trading_hero(display_root: str, chain_symbol: str,
                 spot: float, fut_spec, regime: Optional[str],
                 net_gex_bn: Optional[float], hiro_z: Optional[float]) -> str:
    """Hero header: enormous price, futures-equivalent, régimen pill."""
    fut_px = (spot * fut_spec.etf_ratio) if fut_spec else None
    fut_label = (
        f'<div style="font-size:1.2rem;color:#06b6d4;'
        f'letter-spacing:0.05em;margin-top:-0.4rem">'
        f'≈ {fut_px:,.2f} {display_root}'
        f'</div>'
    ) if fut_spec and fut_px else ""

    regime_color = {
        "POSITIVE": "#16C784",
        "NEGATIVE": "#EA3943",
        "NEUTRAL": "#F5A623",
    }.get(regime or "NEUTRAL", "#9ca3af")

    gex_str = (f"${net_gex_bn:+.2f}B" if net_gex_bn is not None else "—")
    hiro_str = (f"{hiro_z:+.2f}σ" if hiro_z is not None else "—")
    hiro_color = (
        "#16C784" if (hiro_z or 0) > 0.5
        else "#EA3943" if (hiro_z or 0) < -0.5
        else "#9ca3af"
    )

    return _html(f"""
<div style="background:linear-gradient(135deg,#0a0d14 0%,#10131c 100%);
            border:1px solid #1e2230;border-radius:8px;padding:1.4rem 1.6rem;
            margin:0.6rem 0 1.2rem;font-family:JetBrains Mono,monospace;">
  <div style="display:flex;justify-content:space-between;align-items:flex-end;
              gap:2rem;flex-wrap:wrap;">
    <div>
      <div style="font-size:0.65rem;color:#6b7280;letter-spacing:0.18em;
                  text-transform:uppercase;margin-bottom:0.2rem">
        {chain_symbol}{' &middot; ' + display_root if fut_spec else ''}
      </div>
      <div style="font-size:3.2rem;font-weight:700;color:#e5e7eb;
                  line-height:1;letter-spacing:-0.02em">
        ${spot:,.2f}
      </div>
      {fut_label}
    </div>
    <div style="display:flex;gap:1.2rem;font-size:0.78rem;align-items:center;">
      <div style="text-align:right">
        <div style="color:#6b7280;font-size:0.62rem;letter-spacing:0.14em;
                    text-transform:uppercase">Régimen</div>
        <div style="color:{regime_color};font-size:1.1rem;font-weight:700">
          {regime or '—'} Γ
        </div>
      </div>
      <div style="text-align:right">
        <div style="color:#6b7280;font-size:0.62rem;letter-spacing:0.14em;
                    text-transform:uppercase">Net GEX</div>
        <div style="color:{regime_color};font-size:1.1rem;font-weight:700">
          {gex_str}
        </div>
      </div>
      <div style="text-align:right">
        <div style="color:#6b7280;font-size:0.62rem;letter-spacing:0.14em;
                    text-transform:uppercase">HIRO z</div>
        <div style="color:{hiro_color};font-size:1.1rem;font-weight:700">
          {hiro_str}
        </div>
      </div>
    </div>
  </div>
</div>
""")


def levels_strip(spot: float, fut_spec,
                 cw: Optional[float], pw: Optional[float],
                 gf: Optional[float], hvl: Optional[float],
                 mp: Optional[float]) -> str:
    """Wide strip with all key levels in $ (cash) and futures points distance.
    Designed for at-a-glance reading next to a DOM."""
    if fut_spec is None:
        ratio = 1.0
        ppt = 1.0
        pt_label = "$"
    else:
        ratio = fut_spec.etf_ratio
        ppt = fut_spec.point_value
        pt_label = f"{fut_spec.root}pts"

    def _row(name: str, level: Optional[float], color: str, role: str) -> str:
        if level is None:
            val_str = "—"
            dist_str = ""
            dollars = ""
        else:
            val_str = f"${level:,.2f}"
            pts = (level - spot) * ratio
            dist_str = f"{pts:+.1f} {pt_label}"
            dollars = (f"<span style='color:#6b7280;font-size:0.60rem'>"
                       f"  ${pts*ppt:+,.0f}/c</span>")
        return _html(f"""
<div style="display:flex;justify-content:space-between;align-items:center;
            padding:0.55rem 0.9rem;border-left:3px solid {color};
            background:rgba(15,17,24,0.7);margin-bottom:0.25rem;
            border-radius:0 4px 4px 0">
  <div style="display:flex;flex-direction:column;gap:0.05rem">
    <div style="color:#6b7280;font-size:0.58rem;letter-spacing:0.14em;
                text-transform:uppercase">{role}</div>
    <div style="color:{color};font-size:0.95rem;font-weight:700">{name}</div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.05rem">
    <div style="color:#e5e7eb;font-size:0.95rem;font-weight:700;
                font-family:JetBrains Mono,monospace">{val_str}</div>
    <div style="color:{color};font-size:0.72rem;font-weight:600">
      {dist_str}{dollars}
    </div>
  </div>
</div>
""")

    body = ""
    body += _row("CALL WALL",  cw,  "#16C784", "Resistencia · cap arriba")
    body += _row("HVL",        hvl, "#06b6d4", "Atractor · imán intradía")
    body += _row("ZERO Γ",     gf,  "#a855f7", "Régimen · cruce = volatilidad")
    body += _row("MAX PAIN",   mp,  "#F5A623", "Pin · cierre objetivo")
    body += _row("PUT WALL",   pw,  "#EA3943", "Soporte · cap abajo")
    return body


def position_sizer(account_size: float, risk_pct: float,
                   stop_pts: float, fut_spec) -> str:
    """Tiny calculator: dado tamaño de cuenta, %riesgo y stop en puntos,
    recomienda contratos. Solo aplica si el símbolo es un futuro."""
    if fut_spec is None:
        return _box_err(
            "Position Sizer disponible solo para futuros (ES/NQ/RTY/YM/MES/MNQ/M2K/MYM)."
        )
    risk_dollars = account_size * (risk_pct / 100.0)
    risk_per_contract = stop_pts * fut_spec.point_value
    if risk_per_contract <= 0:
        contracts = 0
    else:
        contracts = int(risk_dollars / risk_per_contract)
    return _html(f"""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;
            border-radius:6px;padding:0.9rem 1rem;
            font-family:JetBrains Mono,monospace;">
  <div style="color:#6b7280;font-size:0.62rem;letter-spacing:0.16em;
              text-transform:uppercase;margin-bottom:0.5rem">
    📐 Position Sizer · {fut_spec.root}
  </div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1rem">
    <div>
      <div style="color:#6b7280;font-size:0.58rem">Cuenta</div>
      <div style="color:#e5e7eb;font-size:1rem;font-weight:700">
        ${account_size:,.0f}
      </div>
    </div>
    <div>
      <div style="color:#6b7280;font-size:0.58rem">Riesgo / trade</div>
      <div style="color:#F5A623;font-size:1rem;font-weight:700">
        ${risk_dollars:,.0f} <span style="font-size:0.7rem">({risk_pct:.1f}%)</span>
      </div>
    </div>
    <div>
      <div style="color:#6b7280;font-size:0.58rem">Stop</div>
      <div style="color:#EA3943;font-size:1rem;font-weight:700">
        {stop_pts:.1f} pts
        <span style="color:#6b7280;font-size:0.65rem">
          (${risk_per_contract:,.0f}/c)
        </span>
      </div>
    </div>
    <div>
      <div style="color:#6b7280;font-size:0.58rem">Contratos</div>
      <div style="color:#16C784;font-size:1.6rem;font-weight:800;line-height:1">
        {contracts}
      </div>
    </div>
  </div>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
#  GAMMA ZONES PANEL  —  P1 / P2 / P3 ranked clusters
# ─────────────────────────────────────────────────────────────────────────────
def panel_zones_html(zones: list, spot: Optional[float] = None) -> str:
    """Render a ranked-table of GammaZone objects (or their dicts) with
    width, score, side and current spot location relative to each zone.

    The table answers four questions at a glance:
      · Where are the strongest gamma clusters?
      · How wide is each cluster (pad for stops)?
      · Which side (call / put / mixed)?
      · Is the spot inside one of them right now?
    """
    if not zones:
        return _box_err("Sin zonas detectables todavía.")

    rows: list[str] = []
    for z in zones:
        zd = z if isinstance(z, dict) else z.to_dict()
        rank = int(zd.get("rank") or 0)
        label = zd.get("label") or f"P{rank}"
        peak = float(zd.get("peak_strike") or 0)
        low = float(zd.get("low_strike") or 0)
        high = float(zd.get("high_strike") or 0)
        width = float(zd.get("width") or 0)
        score = float(zd.get("integrated_gex_mm") or 0)
        side = zd.get("side") or "mixed"
        dist_pct = float(zd.get("distance_pct") or 0)

        # Side badge styling
        if side == "call_dominant":
            side_color = "#16C784"
            side_label = "CALL ▲"
        elif side == "put_dominant":
            side_color = "#EA3943"
            side_label = "PUT ▼"
        else:
            side_color = "#F5A623"
            side_label = "MIXED ◇"

        # Is spot inside this zone right now?
        in_zone = (spot is not None and low <= float(spot) <= high)
        in_marker = (
            '<span style="color:#fbbf24;font-weight:700">  ●  spot dentro</span>'
            if in_zone else ''
        )

        # Width descriptor
        width_str = (f"{width:.0f}" if width >= 1 else f"{width:.2f}")
        range_str = (
            f"${peak:,.0f}" if width < 0.01
            else f"${low:,.0f} – ${high:,.0f}"
        )

        rows.append(
            f'<tr>'
            f'<td style="padding:5px 10px;color:{side_color};'
            f'font-weight:800;font-family:JetBrains Mono,monospace;'
            f'font-size:0.86rem">{label}</td>'
            f'<td style="padding:5px 10px;color:#e0e0f0;'
            f'font-family:JetBrains Mono,monospace">{range_str}</td>'
            f'<td style="padding:5px 10px;color:#9090b0;text-align:right;'
            f'font-family:JetBrains Mono,monospace">{width_str} pts</td>'
            f'<td style="padding:5px 10px;color:#e0e0f0;text-align:right;'
            f'font-family:JetBrains Mono,monospace;font-weight:700">'
            f'${_humanize(score * 1e6)}</td>'
            f'<td style="padding:5px 10px;color:{side_color};text-align:center;'
            f'font-family:JetBrains Mono,monospace;font-size:0.74rem;'
            f'font-weight:700">{side_label}</td>'
            f'<td style="padding:5px 10px;color:#7070a0;text-align:right;'
            f'font-family:JetBrains Mono,monospace;font-size:0.78rem">'
            f'{dist_pct:+.2f}%{in_marker}</td>'
            f'</tr>'
        )

    # Spot-context line below the table
    spot_msg = ""
    if spot is not None:
        # Find the zone (if any) containing the spot
        in_zone = None
        for z in zones:
            zd = z if isinstance(z, dict) else z.to_dict()
            lo = float(zd.get("low_strike") or 0)
            hi = float(zd.get("high_strike") or 0)
            if lo <= float(spot) <= hi:
                in_zone = zd
                break
        if in_zone is not None:
            lbl = in_zone.get("label", "P?")
            sd = in_zone.get("side", "mixed")
            verb = ("posible PINNING (long-γ)" if sd == "call_dominant"
                    else "posible REJECTION (put-dominant)" if sd == "put_dominant"
                    else "zona mixta — sin sesgo claro")
            spot_msg = (
                f'<div style="margin-top:0.5rem;padding:0.45rem 0.7rem;'
                f'background:rgba(251,191,36,0.10);border-left:3px solid #fbbf24;'
                f'border-radius:0 4px 4px 0;font-family:JetBrains Mono,monospace;'
                f'font-size:0.78rem;color:#e0e0f0">'
                f'Spot <b>${float(spot):,.2f}</b> está dentro de <b>{lbl}</b> · '
                f'{verb}</div>'
            )
        else:
            # Find the nearest zone
            best = None
            best_d = float("inf")
            for z in zones:
                zd = z if isinstance(z, dict) else z.to_dict()
                peak = float(zd.get("peak_strike") or 0)
                d = abs(peak - float(spot))
                if d < best_d:
                    best_d = d
                    best = zd
            if best is not None:
                lbl = best.get("label", "P?")
                spot_msg = (
                    f'<div style="margin-top:0.5rem;padding:0.45rem 0.7rem;'
                    f'background:rgba(255,255,255,0.04);border-left:3px solid #7070a0;'
                    f'border-radius:0 4px 4px 0;font-family:JetBrains Mono,monospace;'
                    f'font-size:0.78rem;color:#9090b0">'
                    f'Spot <b>${float(spot):,.2f}</b> entre zonas · más cerca '
                    f'de <b>{lbl}</b> ({best_d:.2f} pts)</div>'
                )

    return (
        '<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;'
        'border-radius:6px;padding:0.7rem 0.9rem;margin:0.5rem 0;'
        'font-family:JetBrains Mono,monospace">'
        '<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.14em;'
        'margin-bottom:0.5rem;text-transform:uppercase">'
        '⛰  GAMMA ZONES  ·  ranked clusters by integrated |GEX|</div>'
        '<table style="width:100%;border-collapse:collapse;font-size:0.78rem">'
        '<thead><tr>'
        '<th style="text-align:left;padding:3px 10px;color:#606080;'
        'font-weight:500;font-size:0.66rem;letter-spacing:0.10em">RANK</th>'
        '<th style="text-align:left;padding:3px 10px;color:#606080;'
        'font-weight:500;font-size:0.66rem;letter-spacing:0.10em">RANGO</th>'
        '<th style="text-align:right;padding:3px 10px;color:#606080;'
        'font-weight:500;font-size:0.66rem;letter-spacing:0.10em">ANCHO</th>'
        '<th style="text-align:right;padding:3px 10px;color:#606080;'
        'font-weight:500;font-size:0.66rem;letter-spacing:0.10em">SCORE</th>'
        '<th style="text-align:center;padding:3px 10px;color:#606080;'
        'font-weight:500;font-size:0.66rem;letter-spacing:0.10em">SIDE</th>'
        '<th style="text-align:right;padding:3px 10px;color:#606080;'
        'font-weight:500;font-size:0.66rem;letter-spacing:0.10em">VS SPOT</th>'
        '</tr></thead><tbody>'
        + "".join(rows) +
        '</tbody></table>'
        + spot_msg +
        '</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
#  EXPECTED MOVE BANDS  —  multi-sigma table
# ─────────────────────────────────────────────────────────────────────────────
def panel_em_table_html(analysis) -> str:
    """Render the multi-σ band table as a standalone card.

    Caller is expected to lay this side-by-side with `panel_em_ic_html`
    via `st.columns` — flexbox inside a single markdown chunk has been
    flaky in Streamlit's CommonMark renderer.
    """
    if analysis is None:
        return _box_err(
            "Expected Move analyzer no disponible — IV ATM no resolvió.")

    rows: list[str] = []
    for b in analysis.bands:
        b_dict = b if isinstance(b, dict) else b.to_dict()
        sigma = float(b_dict.get("sigma") or 0)
        low = float(b_dict.get("low") or 0)
        high = float(b_dict.get("high") or 0)
        width = float(b_dict.get("width") or 0)
        p_in = float(b_dict.get("p_inside") or 0)
        p_tlo = float(b_dict.get("p_touch_low") or 0)
        p_thi = float(b_dict.get("p_touch_high") or 0)
        if sigma <= 0.5:
            color = "#16C784"
        elif sigma <= 1.0:
            color = "#F5A623"
        elif sigma <= 1.5:
            color = "#a855f7"
        else:
            color = "#EA3943"
        rows.append(
            f'<tr>'
            f'<td style="padding:4px 8px;color:{color};font-weight:700">{sigma:.1f}σ</td>'
            f'<td style="padding:4px 8px;text-align:right;color:#e0e0f0">${low:,.2f}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:#e0e0f0">${high:,.2f}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:#9090b0">${width:,.2f}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:{color};font-weight:700">{p_in*100:.0f}%</td>'
            f'<td style="padding:4px 8px;text-align:right;color:#7070a0;font-size:0.72rem">{p_tlo*100:.0f}/{p_thi*100:.0f}</td>'
            f'</tr>'
        )

    skew_tag = "skew-adjusted" if analysis.skew_adjusted else "symmetric"
    body = _html(f"""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-radius:6px;padding:0.6rem 0.85rem;font-family:JetBrains Mono,monospace">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.12em;margin-bottom:0.45rem;text-transform:uppercase">📏 EXPECTED MOVE  ·  spot ${analysis.spot:,.2f}  ·  T={analysis.minutes_to_close:.0f}min  ·  IV {analysis.iv_blend:.1f}%  ·  {skew_tag}</div>
<table style="width:100%;border-collapse:collapse;font-size:0.78rem">
<thead><tr>
<th style="text-align:left;padding:3px 8px;color:#606080;font-weight:500;font-size:0.64rem;letter-spacing:0.08em">σ</th>
<th style="text-align:right;padding:3px 8px;color:#606080;font-weight:500;font-size:0.64rem;letter-spacing:0.08em">LOW</th>
<th style="text-align:right;padding:3px 8px;color:#606080;font-weight:500;font-size:0.64rem;letter-spacing:0.08em">HIGH</th>
<th style="text-align:right;padding:3px 8px;color:#606080;font-weight:500;font-size:0.64rem;letter-spacing:0.08em">WIDTH</th>
<th style="text-align:right;padding:3px 8px;color:#606080;font-weight:500;font-size:0.64rem;letter-spacing:0.08em">P-IN</th>
<th style="text-align:right;padding:3px 8px;color:#606080;font-weight:500;font-size:0.64rem;letter-spacing:0.08em">PoT L/H %</th>
</tr></thead><tbody>
__ROWS__
</tbody></table>
<div style="color:#606080;font-size:0.65rem;margin-top:0.4rem;line-height:1.4">P-inside = prob. spot ∈ banda al cierre · PoT = prob. de touch al low/high antes del cierre</div>
</div>
""")
    return body.replace("__ROWS__", "".join(rows))


# ─────────────────────────────────────────────────────────────────────────────
#  IRON CONDOR SUGGESTION
# ─────────────────────────────────────────────────────────────────────────────
def panel_em_ic_html(ic_suggestion) -> str:
    """Render the iron-condor suggestion as a standalone card.
    Caller renders side-by-side with `panel_em_table_html` via columns.
    """
    if ic_suggestion is None:
        return _html("""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-radius:6px;padding:0.6rem 0.85rem;font-family:JetBrains Mono,monospace">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase">🦅 IRON CONDOR 0DTE</div>
<div style="color:#7070a0;font-size:0.78rem;padding:0.6rem 0">Sugerencia no disponible — IV ATM o T insuficientes.</div>
</div>
""")

    ic = (ic_suggestion if isinstance(ic_suggestion, dict)
          else ic_suggestion.to_dict())
    # Defensive: any missing leg means the suggestion is incomplete (e.g.
    # wing math failed at an edge case). Render the "no data" card
    # instead of crashing with KeyError mid-panel.
    required = ("short_put", "long_put", "short_call", "long_call")
    if any(ic.get(k) is None for k in required):
        return _html("""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-radius:6px;padding:0.6rem 0.85rem;font-family:JetBrains Mono,monospace">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase">🦅 IRON CONDOR 0DTE</div>
<div style="color:#7070a0;font-size:0.78rem;padding:0.6rem 0">Sugerencia incompleta — falta algún strike (wing math fuera de rango).</div>
</div>
""")
    pop = float(ic.get("prob_of_profit", 0) or 0) * 100
    pop_color = ("#16C784" if pop >= 70 else
                 "#F5A623" if pop >= 50 else "#EA3943")
    target_pop = int(float(ic.get("target_pop", 0.7) or 0.7) * 100)
    short_put = float(ic["short_put"])
    long_put = float(ic["long_put"])
    short_call = float(ic["short_call"])
    long_call = float(ic["long_call"])
    wing = float(ic["wing_width"])
    pot_sp = float(ic["p_touch_short_put"]) * 100
    pot_sc = float(ic["p_touch_short_call"]) * 100

    return _html(f"""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-radius:6px;padding:0.6rem 0.85rem;font-family:JetBrains Mono,monospace">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.12em;text-transform:uppercase">🦅 IRON CONDOR 0DTE (target POP {target_pop}%)</div>
<div style="color:{pop_color};font-size:1.05rem;font-weight:700">POP {pop:.0f}%</div>
</div>
<table style="width:100%;border-collapse:collapse;font-size:0.78rem;margin-top:0.2rem">
<tr>
<td style="padding:5px 8px;border-left:3px solid #EA3943;background:rgba(234,57,67,0.07);width:50%;vertical-align:top">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.08em">PUT WING</div>
<div style="color:#EA3943;font-weight:700">Sell ${short_put:,.0f}P</div>
<div style="color:#9090b0;font-size:0.70rem">Buy ${long_put:,.0f}P (wing ${wing:.0f})</div>
<div style="color:#7070a0;font-size:0.66rem;margin-top:0.2rem">PoT short {pot_sp:.0f}%</div>
</td>
<td style="padding:5px 8px;border-left:3px solid #16C784;background:rgba(22,199,132,0.07);width:50%;vertical-align:top">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.08em">CALL WING</div>
<div style="color:#16C784;font-weight:700">Sell ${short_call:,.0f}C</div>
<div style="color:#9090b0;font-size:0.70rem">Buy ${long_call:,.0f}C (wing ${wing:.0f})</div>
<div style="color:#7070a0;font-size:0.66rem;margin-top:0.2rem">PoT short {pot_sc:.0f}%</div>
</td>
</tr>
</table>
<div style="color:#606080;font-size:0.65rem;margin-top:0.45rem;line-height:1.4">Max loss = wing ({wing:.0f}pts) − credit. PoT = prob. de touch al short antes del cierre.</div>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
#  GEX gate badge (PASS/FAIL for 0DTE IC setup)
# ─────────────────────────────────────────────────────────────────────────────
def panel_gex_gate_html(gate: dict) -> str:
    """Render a small badge summarising the GEX-regime gate verdict.
    Pass `gate` = output of `quant.ic_picker.gex_gate_check`.
    """
    if not gate:
        return _box_err("GEX gate no disponible.")
    passed = bool(gate.get("pass"))
    bar_color = "#16C784" if passed else "#EA3943"
    label = "PASS" if passed else "FAIL"

    def _chk(ok: bool, txt: str) -> str:
        symbol = "✓" if ok else "✗"
        clr = "#16C784" if ok else "#EA3943"
        return (f'<span style="color:{clr};font-weight:700;'
                f'margin-right:0.45rem">{symbol}</span>'
                f'<span style="color:#c0c0d8">{txt}</span>')

    net_bn = gate.get("net_gex_usd")
    net_bn = (float(net_bn) / 1e9) if net_bn is not None else None
    gf = gate.get("gamma_flip")
    cushion = gate.get("cushion_pct")
    regime = gate.get("regime") or "—"

    checks = [
        _chk(gate.get("regime_ok"), f"Régimen <b>{regime}</b>"),
        _chk(gate.get("net_gex_ok"),
             f"Net GEX <b>{net_bn:+.2f}B</b>" if net_bn is not None
             else "Net GEX no disp."),
        _chk(gate.get("above_flip_ok"),
             f"spot > Zero Γ <b>${gf:,.0f}</b>" if gf is not None
             else "Zero Γ no disp."),
        _chk(gate.get("cushion_ok"),
             f"colchón <b>{cushion:.2f}%</b>" if cushion is not None
             else "colchón no disp."),
    ]
    verdict = gate.get("verdict") or ""
    return _html(f"""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-left:4px solid {bar_color};border-radius:0 4px 4px 0;padding:0.55rem 0.85rem;margin:0.45rem 0;font-family:JetBrains Mono,monospace">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.4rem">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.14em;text-transform:uppercase">🚦 GEX GATE  ·  Iron Condor 0DTE</div>
<div style="color:{bar_color};font-size:1.05rem;font-weight:800;letter-spacing:0.06em">{label}</div>
</div>
<div style="font-size:0.78rem;line-height:1.6">{' &nbsp;·&nbsp; '.join(checks)}</div>
<div style="color:#7070a0;font-size:0.70rem;margin-top:0.35rem">{verdict}</div>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
#  Iron Condor strike-suggestion summary (one-liner)
# ─────────────────────────────────────────────────────────────────────────────
def panel_ic_strike_suggest_html(suggestion: dict,
                                 walls: Optional[dict] = None) -> str:
    """Render the strike suggestion produced by
    `quant.ic_picker.suggest_strikes_from_walls`. Lightweight banner —
    the rich detail lives in the wing-width comparison table."""
    if not suggestion:
        return _box_err("Sin sugerencia de strikes disponible.")
    sp = suggestion.get("short_put")
    sc = suggestion.get("short_call")
    centre = suggestion.get("centre")
    source = suggestion.get("source", "—")
    notes = suggestion.get("notes") or []
    pw = (walls or {}).get("put_wall")
    cw = (walls or {}).get("call_wall")
    notes_html = ""
    if notes:
        notes_html = (
            '<div style="color:#7070a0;font-size:0.68rem;margin-top:0.35rem;'
            'line-height:1.5">'
            + "<br>".join(f"· {n}" for n in notes)
            + '</div>'
        )
    return _html(f"""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-radius:6px;padding:0.55rem 0.85rem;margin:0.45rem 0;font-family:JetBrains Mono,monospace">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.14em;text-transform:uppercase;margin-bottom:0.35rem">🎯 STRIKES SUGERIDOS  ·  fuente {source}</div>
<div style="display:flex;gap:1rem;font-size:0.82rem">
<div style="flex:1 1 0;border-left:3px solid #EA3943;padding-left:0.6rem">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.10em">SHORT PUT</div>
<div style="color:#EA3943;font-weight:700;font-size:1.0rem">{(f"${sp:,.0f}" if sp else "—")}</div>
<div style="color:#7070a0;font-size:0.66rem">PW {(f"${pw:,.0f}" if pw else "—")}</div>
</div>
<div style="flex:1 1 0;border-left:3px solid #fbbf24;padding-left:0.6rem">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.10em">CENTRO</div>
<div style="color:#fbbf24;font-weight:700;font-size:1.0rem">{(f"${centre:,.0f}" if centre else "—")}</div>
<div style="color:#7070a0;font-size:0.66rem">HVL / spot</div>
</div>
<div style="flex:1 1 0;border-left:3px solid #16C784;padding-left:0.6rem">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.10em">SHORT CALL</div>
<div style="color:#16C784;font-weight:700;font-size:1.0rem">{(f"${sc:,.0f}" if sc else "—")}</div>
<div style="color:#7070a0;font-size:0.66rem">CW {(f"${cw:,.0f}" if cw else "—")}</div>
</div>
</div>
{notes_html}
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
#  Back-compat wrapper (legacy callers expecting one function).
# ─────────────────────────────────────────────────────────────────────────────
def panel_em_bands_html(analysis, ic_suggestion=None) -> str:
    """Deprecated combined version — kept so existing callers don't break.
    New code should use `panel_em_table_html` + `panel_em_ic_html` with
    `st.columns` for layout control.
    """
    return panel_em_table_html(analysis) + "\n" + panel_em_ic_html(ic_suggestion)


# ─────────────────────────────────────────────────────────────────────────────
#  EXPECTED-RANGE summary panel (RND stats + level probabilities)
# ─────────────────────────────────────────────────────────────────────────────
def panel_rnd_stats_html(stats: dict, spot: float) -> str:
    """Render the risk-neutral-density summary: implied mean/std, skew,
    excess kurtosis (vs Gaussian baseline of 0), and per-level
    probabilities. `stats` is the output of
    `quant.expected_range.rnd_stats`."""
    if not stats:
        return _box_err("Risk-neutral density no disponible (faltan IV por strike).")

    mean = stats.get("mean")
    std = stats.get("std")
    std_pct = stats.get("std_pct")
    skew = stats.get("skew", 0.0)
    kurt = stats.get("excess_kurtosis", 0.0)

    # Interpretation chips
    skew_txt = ("sesgo bajista (cola izq. gorda)" if skew < -0.15
                else "sesgo alcista (cola der. gorda)" if skew > 0.15
                else "≈ simétrico")
    skew_clr = ("#EA3943" if skew < -0.15 else
                "#16C784" if skew > 0.15 else "#9090b0")
    kurt_txt = ("colas GORDAS (riesgo de cola alto)" if kurt > 0.5
                else "colas finas" if kurt < -0.5 else "≈ normal")
    kurt_clr = "#F5A623" if abs(kurt) > 0.5 else "#9090b0"

    rows = ""
    for name, info in (stats.get("level_probs") or {}).items():
        lvl = info.get("level")
        pb = info.get("p_below", 0) * 100
        pa = info.get("p_above", 0) * 100
        label = {
            "call_wall": "Call Wall", "put_wall": "Put Wall",
            "hvl": "HVL", "gamma_flip": "Zero Γ",
        }.get(name, name)
        rows += (
            f'<tr>'
            f'<td style="padding:3px 10px;color:#c0c0d8">{label} '
            f'<span style="color:#7070a0">${lvl:,.0f}</span></td>'
            f'<td style="padding:3px 10px;text-align:right;color:#EA3943">'
            f'P&lt; {pb:.0f}%</td>'
            f'<td style="padding:3px 10px;text-align:right;color:#16C784">'
            f'P&gt; {pa:.0f}%</td>'
            f'</tr>'
        )

    levels_table = (
        '<table style="width:100%;border-collapse:collapse;font-size:0.76rem;'
        'margin-top:0.4rem">'
        '<thead><tr>'
        '<th style="text-align:left;padding:2px 10px;color:#606080;'
        'font-size:0.62rem;letter-spacing:0.10em">NIVEL</th>'
        '<th style="text-align:right;padding:2px 10px;color:#606080;'
        'font-size:0.62rem;letter-spacing:0.10em">P(CIERRE DEBAJO)</th>'
        '<th style="text-align:right;padding:2px 10px;color:#606080;'
        'font-size:0.62rem;letter-spacing:0.10em">P(CIERRE ARRIBA)</th>'
        '</tr></thead><tbody>' + rows + '</tbody></table>'
    ) if rows else ""

    return _html(f"""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-radius:6px;padding:0.7rem 0.9rem;margin:0.5rem 0;font-family:JetBrains Mono,monospace">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.14em;text-transform:uppercase;margin-bottom:0.5rem">🎲 RISK-NEUTRAL DENSITY · estadística implícita</div>
<div style="display:flex;gap:1.2rem;flex-wrap:wrap;font-size:0.82rem">
<div><div style="color:#6b7280;font-size:0.6rem">MEDIA IMPLÍCITA</div><div style="color:#e0e0f0;font-weight:700">${mean:,.2f}</div></div>
<div><div style="color:#6b7280;font-size:0.6rem">σ IMPLÍCITA</div><div style="color:#e0e0f0;font-weight:700">${std:,.2f} ({std_pct:.2f}%)</div></div>
<div><div style="color:#6b7280;font-size:0.6rem">SKEW</div><div style="color:{skew_clr};font-weight:700">{skew:+.2f}</div><div style="color:{skew_clr};font-size:0.62rem">{skew_txt}</div></div>
<div><div style="color:#6b7280;font-size:0.6rem">EXCESS KURTOSIS</div><div style="color:{kurt_clr};font-weight:700">{kurt:+.2f}</div><div style="color:{kurt_clr};font-size:0.62rem">{kurt_txt}</div></div>
</div>
{levels_table}
<div style="color:#606080;font-size:0.64rem;margin-top:0.45rem;line-height:1.4">Extraído del chain vía Breeden-Litzenberger (∂²C/∂K²). Skew &lt;0 = mercado teme caídas; kurtosis &gt;0 = colas más gordas que la normal → el modelo Gaussiano subestima movimientos extremos.</div>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
#  RND EXACT LEVELS panel (SVI model — central Expected Range model)
# ─────────────────────────────────────────────────────────────────────────────
def _rnd_sparkline_svg(rnd, levels: dict, spot: float,
                       width: int = 360, height: int = 70) -> str:
    """Inline SVG of the implied density: filled curve + P25–P75 shaded
    'likely zone' + spot marker. Used by the compact Overview panel."""
    import numpy as _np
    try:
        k = rnd["strike"].to_numpy(float)
        p = rnd["pdf"].to_numpy(float)
    except Exception:
        return ""
    if k.size < 3:
        return ""
    pct = (levels or {}).get("percentiles", {})
    lo = pct.get("p5") or float(k.min())
    hi = pct.get("p95") or float(k.max())
    span = max(hi - lo, 1e-9)
    lo, hi = lo - span * 0.10, hi + span * 0.10
    mask = (k >= lo) & (k <= hi)
    if mask.sum() < 3:
        mask = _np.ones_like(k, dtype=bool)
    ks, ps = k[mask], p[mask]
    if ks.size > 80:                       # downsample for a compact path
        idx = _np.linspace(0, ks.size - 1, 80).astype(int)
        ks, ps = ks[idx], ps[idx]
    kmin, kmax = float(ks.min()), float(ks.max())
    pmax = float(ps.max()) or 1.0
    pad = 7.0
    sx = (lambda v: (v - kmin) / (kmax - kmin) * width if kmax > kmin else 0.0)
    sy = (lambda v: height - pad - (v / pmax) * (height - 2 * pad))
    line_pts = " ".join(f"{sx(a):.1f},{sy(b):.1f}" for a, b in zip(ks, ps))
    fill_pts = (f"{sx(kmin):.1f},{height - pad:.1f} " + line_pts +
                f" {sx(kmax):.1f},{height - pad:.1f}")
    iqr = ""
    p25, p75 = pct.get("p25"), pct.get("p75")
    if p25 and p75:
        x0, x1 = sx(max(p25, kmin)), sx(min(p75, kmax))
        iqr = (f'<rect x="{x0:.1f}" y="{pad:.1f}" width="{max(x1 - x0, 1):.1f}" '
               f'height="{height - 2 * pad:.1f}" fill="rgba(22,199,132,0.14)"/>')
    spot_ln = ""
    if kmin <= spot <= kmax:
        xs = sx(spot)
        spot_ln = (f'<line x1="{xs:.1f}" y1="{pad - 3:.1f}" x2="{xs:.1f}" '
                   f'y2="{height - pad:.1f}" stroke="#F5A623" stroke-width="1.6"/>')
    return (
        f'<svg width="100%" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block">'
        f'{iqr}<polygon points="{fill_pts}" fill="rgba(6,182,212,0.16)"/>'
        f'<polyline points="{line_pts}" fill="none" stroke="#22d3ee" '
        f'stroke-width="1.8"/>{spot_ln}</svg>'
    )


def rnd_mini_panel(rnd, levels: dict, meta: Optional[dict], spot: float) -> str:
    """Compact Overview card surfacing the crown-jewel RND model: a mini
    implied-distribution sparkline + the 1σ-equivalent band, skew and a
    confidence dot. Returns '' when there is no usable density (kept silent
    on Overview rather than showing an error box)."""
    if rnd is None or getattr(rnd, "empty", True) or not levels:
        return ""
    pct = levels.get("percentiles", {})
    p16, p84 = levels.get("p16"), levels.get("p84")
    std_pct = levels.get("std_pct")
    skew = levels.get("skew", 0.0) or 0.0
    method = ((meta or {}).get("method") or "—").upper()
    conf = (meta or {}).get("confidence", "—")
    svg = _rnd_sparkline_svg(rnd, levels, spot)
    if not svg:
        return ""

    band = (f"${p16:,.1f} – ${p84:,.1f}" if (p16 and p84) else "—")
    band_pct = f"±{std_pct:.2f}%" if std_pct else ""
    sk_clr = ("#EA3943" if skew < -0.15 else
              "#16C784" if skew > 0.15 else "#9090b0")
    sk_txt = ("sesgo bajista ▼" if skew < -0.15
              else "sesgo alcista ▲" if skew > 0.15 else "≈ simétrico")
    conf_map = {"high": ("#16C784", "alta"), "medium": ("#F5A623", "media"),
                "low": ("#EA3943", "baja")}
    c_clr, c_txt = conf_map.get(conf, ("#9090b0", "—"))

    return _html(f"""
    <div style="background:linear-gradient(135deg,#0b0b16,#0e0e1c);
         border:1px solid #1e1e32;border-radius:8px;padding:0.7rem 0.95rem;
         margin:0.2rem 0 0.9rem;font-family:JetBrains Mono,monospace;">
      <div style="display:flex;align-items:center;justify-content:space-between;
           margin-bottom:0.5rem;">
        <span style="font-size:0.6rem;color:#22d3ee;letter-spacing:0.14em;">
          ◈ DISTRIBUCIÓN IMPLÍCITA · RISK-NEUTRAL DENSITY</span>
        <span style="font-size:0.56rem;color:#5b5b80;">
          modelo {method} · <span style="color:{c_clr}">●</span>
          confianza {c_txt}</span>
      </div>
      <div style="display:flex;gap:1.1rem;align-items:center;flex-wrap:wrap;">
        <div style="flex:1 1 320px;min-width:240px;">{svg}
          <div style="display:flex;justify-content:space-between;
               font-size:0.54rem;color:#5b5b80;margin-top:2px;">
            <span>P5</span>
            <span style="color:#16C784;">zona probable 50% (P25–P75)</span>
            <span>P95</span></div>
        </div>
        <div style="display:flex;gap:1.3rem;flex-wrap:wrap;">
          <div><div style="font-size:0.56rem;color:#6b7280;">RANGO 1σ (P16–P84)</div>
            <div style="font-size:0.92rem;font-weight:700;color:#e8e8f4;">{band}
              <span style="font-size:0.6rem;color:#7070a0;">{band_pct}</span></div></div>
          <div><div style="font-size:0.56rem;color:#6b7280;">SESGO</div>
            <div style="font-size:0.92rem;font-weight:700;color:{sk_clr};">
              {skew:+.2f} <span style="font-size:0.58rem;">{sk_txt}</span></div></div>
        </div>
      </div>
      <div style="font-size:0.56rem;color:#4a4a68;margin-top:0.45rem;">
        Lo que el mercado de opciones cotiza para el cierre · detalle completo en
        <b style="color:#7070a0;">📐 Expected Range</b></div>
    </div>
    """)


def panel_rnd_levels_html(levels_data: dict, spot: float,
                          meta: Optional[dict] = None) -> str:
    """Render the exact level table from the SVI risk-neutral density:
    percentiles (P5…P95), mode, 1σ-equivalent band, plus per-wall
    probabilities and a fit-quality footer. `levels_data` is the output
    of `quant.rnd.rnd_levels`; `meta` is the dict from `quant.rnd.build_rnd`.
    """
    if not levels_data:
        return _box_err("Risk-neutral density no disponible "
                        "(faltan IV por strike o el ajuste falló).")

    pct = levels_data.get("percentiles", {})
    mode = levels_data.get("mode")
    mean = levels_data.get("mean")
    std = levels_data.get("std")
    std_pct = levels_data.get("std_pct")
    skew = levels_data.get("skew", 0.0)
    kurt = levels_data.get("excess_kurtosis", 0.0)
    p16 = levels_data.get("p16")
    p84 = levels_data.get("p84")

    skew_clr = ("#EA3943" if skew < -0.15 else
                "#16C784" if skew > 0.15 else "#9090b0")
    skew_txt = ("sesgo bajista" if skew < -0.15
                else "sesgo alcista" if skew > 0.15 else "≈ simétrico")
    kurt_clr = "#F5A623" if abs(kurt) > 0.5 else "#9090b0"
    kurt_txt = ("colas GORDAS" if kurt > 0.5
                else "colas finas" if kurt < -0.5 else "≈ normal")

    # Percentile ladder as a horizontal strip
    pcells = ""
    pct_order = [("p5", "#EA3943"), ("p10", "#F5A623"), ("p25", "#16C784"),
                 ("p50", "#e0e0f0"), ("p75", "#16C784"), ("p90", "#F5A623"),
                 ("p95", "#EA3943")]
    for key, clr in pct_order:
        v = pct.get(key)
        if v is None:
            continue
        lbl = key.upper().replace("P", "P")
        pcells += (
            f'<div style="flex:1 1 0;text-align:center;padding:0.35rem 0.2rem;'
            f'border-bottom:2px solid {clr}">'
            f'<div style="color:#7070a0;font-size:0.58rem">{lbl}</div>'
            f'<div style="color:{clr};font-weight:700;font-size:0.84rem;'
            f'font-family:JetBrains Mono,monospace">${v:,.1f}</div></div>'
        )

    # Per-wall probability rows
    rows = ""
    for name, info in (levels_data.get("level_probs") or {}).items():
        if name == "spot":
            continue
        label = {"call_wall": "Call Wall", "put_wall": "Put Wall",
                 "hvl": "HVL", "gamma_flip": "Zero Γ"}.get(name, name)
        lvl = info.get("level")
        pb = info.get("p_below", 0) * 100
        pa = info.get("p_above", 0) * 100
        pt = info.get("p_touch", 0) * 100
        rows += (
            f'<tr>'
            f'<td style="padding:3px 10px;color:#c0c0d8">{label} '
            f'<span style="color:#7070a0">${lvl:,.0f}</span></td>'
            f'<td style="padding:3px 10px;text-align:right;color:#EA3943">{pb:.0f}%</td>'
            f'<td style="padding:3px 10px;text-align:right;color:#16C784">{pa:.0f}%</td>'
            f'<td style="padding:3px 10px;text-align:right;color:#fbbf24">{pt:.0f}%</td>'
            f'</tr>'
        )
    levels_table = (
        '<table style="width:100%;border-collapse:collapse;font-size:0.76rem;'
        'margin-top:0.5rem"><thead><tr>'
        '<th style="text-align:left;padding:2px 10px;color:#606080;font-size:0.6rem">NIVEL</th>'
        '<th style="text-align:right;padding:2px 10px;color:#606080;font-size:0.6rem">P&lt; CIERRE</th>'
        '<th style="text-align:right;padding:2px 10px;color:#606080;font-size:0.6rem">P&gt; CIERRE</th>'
        '<th style="text-align:right;padding:2px 10px;color:#606080;font-size:0.6rem">P TOUCH</th>'
        '</tr></thead><tbody>' + rows + '</tbody></table>'
    ) if rows else ""

    # Fit-quality footer + prominent confidence badge
    foot = ""
    conf_badge = ""
    if meta:
        method = (meta.get("method") or "—").upper()
        rmse = meta.get("rmse")
        arb = meta.get("arb_free")
        fwd = meta.get("forward")
        arb_txt = ("✓ arbitrage-free" if arb is True
                   else "⚠ no verificado" if arb is None else "✗ con arbitraje")
        arb_clr = "#16C784" if arb is True else "#F5A623"
        rmse_txt = f"RMSE {rmse:.1e}" if rmse is not None else ""
        # Diagnostics: surface WHY a non-SVI method was used (the SVI fit was
        # rejected or unavailable), plus n_strikes / min_g, so the fallback
        # can be diagnosed from the live data without a debugger.
        n_strk = meta.get("n_strikes")
        min_g = meta.get("min_g")
        reject = meta.get("svi_reject")
        calib = meta.get("calibration")
        diag = f" · strikes={n_strk}" if n_strk else ""
        if min_g is not None:
            diag += f" · min_g={min_g:+.4f}"
        if calib == "penalized-arbfree":
            diag += (' · <span style="color:#16C784">calib penalizada '
                     'arb-free</span>')
        elif reject and (meta.get("method") != "svi"):
            diag += (f' · <span style="color:#F5A623">SVI rechazado: '
                     f'{reject}</span>')
        # Honesty flags: negative density mass (corrupt fallback) and how much
        # of the tails is pure extrapolation beyond the observed strikes.
        neg = meta.get("neg_mass_pct")
        extrap = meta.get("extrap_frac")
        if neg is not None and neg > 1.0:
            diag += (f' · <span style="color:#EA3943">masa neg {neg:.1f}% '
                     f'(densidad poco fiable)</span>')
        if extrap is not None and extrap > 25.0:
            diag += (f' · <span style="color:#F5A623">colas extrapoladas '
                     f'{extrap:.0f}%</span>')
        # Prominent confidence badge — the honest bottom line for the trader.
        conf = meta.get("confidence")
        reasons = " · ".join(meta.get("confidence_reasons") or [])
        if conf == "low":
            conf_badge = (
                '<div style="background:rgba(234,57,67,0.12);border:1px solid '
                'rgba(234,57,67,0.4);border-radius:5px;padding:0.4rem 0.65rem;'
                'margin-bottom:0.55rem;font-size:0.66rem;color:#EA3943;'
                'font-family:JetBrains Mono,monospace;">⚠ BAJA CONFIANZA — '
                f'{reasons}. Trata estos niveles como orientativos, no exactos.'
                '</div>')
        elif conf == "medium":
            conf_badge = (
                '<div style="background:rgba(245,166,35,0.10);border:1px solid '
                'rgba(245,166,35,0.35);border-radius:5px;padding:0.35rem 0.65rem;'
                'margin-bottom:0.55rem;font-size:0.64rem;color:#fbbf24;'
                f'font-family:JetBrains Mono,monospace;">◐ Confianza media — '
                f'{reasons}.</div>')
        foot = (
            f'<div style="color:#606080;font-size:0.64rem;margin-top:0.5rem;'
            f'line-height:1.4">Modelo: <b>{method}</b> · forward '
            f'${fwd:,.2f} · {rmse_txt} · '
            f'<span style="color:{arb_clr}">{arb_txt}</span>{diag}. '
            f'Niveles por inversión exacta de la CDF (no interpolación).</div>'
        )

    def _stat(label, value, vclr="#e8e8f4", note=""):
        note_html = (f'<span style="font-size:0.56rem;color:#7070a0;'
                     f'margin-left:3px;">{note}</span>') if note else ""
        return (
            f'<div style="flex:1 1 120px;background:#0b0b15;border:1px solid '
            f'#1a1a2c;border-radius:6px;padding:0.4rem 0.55rem;">'
            f'<div style="color:#6b7280;font-size:0.55rem;letter-spacing:0.06em;'
            f'text-transform:uppercase;margin-bottom:2px;">{label}</div>'
            f'<div style="color:{vclr};font-weight:700;font-size:0.92rem;'
            f'font-variant-numeric:tabular-nums;">{value}{note_html}</div></div>'
        )

    stat_cards = (
        _stat("Mode (+probable)", f"${mode:,.2f}", "#06b6d4") +
        _stat("Mediana P50", f"${pct.get('p50', 0):,.2f}") +
        _stat("Rango 1σ (P16–P84)", f"${p16:,.0f}–{p84:,.0f}") +
        _stat("σ implícita", f"${std:,.2f}", note=f"{std_pct:.2f}%") +
        _stat("Skew", f"{skew:+.2f}", skew_clr, note=skew_txt) +
        _stat("Kurtosis", f"{kurt:+.2f}", kurt_clr, note=kurt_txt)
    )

    return _html(f"""
<div style="background:linear-gradient(135deg,#0c0c18,#101020);border:1px solid #1e2230;border-radius:9px;padding:0.85rem 1rem;margin:0.5rem 0;font-family:JetBrains Mono,monospace;box-shadow:0 6px 22px rgba(0,0,0,0.32)">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.6rem">
<span style="color:#22d3ee;font-size:0.64rem;letter-spacing:0.14em;text-transform:uppercase">◈ NIVELES EXACTOS · RISK-NEUTRAL DENSITY</span>
<span style="color:#4a4a68;font-size:0.56rem">inversión exacta de la CDF</span>
</div>
{conf_badge}
<div style="display:flex;gap:0.45rem;flex-wrap:wrap;margin-bottom:0.55rem">{stat_cards}</div>
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.1em;margin:0.4rem 0 0.25rem">ESCALERA DE PERCENTILES · probabilidad de cierre</div>
<div style="display:flex;gap:0.15rem">{pcells}</div>
{levels_table}
{foot}
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
#  EM ACCURACY TRACKER panel
# ─────────────────────────────────────────────────────────────────────────────
def panel_em_accuracy_html(stats: dict, backend: str = "—") -> str:
    """Render the EM accuracy / calibration summary. `stats` is the output
    of `quant.em_tracker.accuracy_stats`. Shows hit-rates vs the expected
    68/80/90% targets and the calibration verdict."""
    from quant.em_tracker import verdict_text
    if not stats:
        return _box_err("Tracker sin datos todavía.")

    n_clean = stats.get("n_clean", 0)
    n_settled = stats.get("n_settled", 0)
    ready = stats.get("ready", False)
    vlabel, vclr = verdict_text(stats)

    def _row(label, observed, expected):
        if observed is None:
            obs_txt, clr = "—", "#9090b0"
        else:
            obs = observed * 100
            # green if within ±6pts of target, amber otherwise
            clr = "#16C784" if abs(obs - expected) <= 6 else "#F5A623"
            obs_txt = f"{obs:.0f}%"
        return (
            f'<tr><td style="padding:3px 10px;color:#c0c0d8">{label}</td>'
            f'<td style="padding:3px 10px;text-align:right;color:{clr};'
            f'font-weight:700">{obs_txt}</td>'
            f'<td style="padding:3px 10px;text-align:right;color:#7070a0">'
            f'{expected:.0f}%</td></tr>'
        )

    ratio = stats.get("avg_move_ratio")
    ratio_txt = ""
    if ratio is not None:
        rclr = ("#EA3943" if ratio > 1.1 else
                "#16C784" if ratio < 0.9 else "#9090b0")
        rmsg = ("realizado &gt; implícito → IV barata" if ratio > 1.1
                else "realizado &lt; implícito → IV cara" if ratio < 0.9
                else "realizado ≈ implícito")
        ratio_txt = (
            f'<div style="margin-top:0.4rem;font-size:0.78rem">'
            f'Move ratio medio: <b style="color:{rclr}">{ratio:.2f}×</b> '
            f'<span style="color:#7070a0">({rmsg})</span></div>'
        )

    return _html(f"""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-left:4px solid {vclr};border-radius:0 4px 4px 0;padding:0.7rem 0.9rem;margin:0.5rem 0;font-family:JetBrains Mono,monospace">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.4rem">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.14em;text-transform:uppercase">📊 EM ACCURACY · calibración del modelo</div>
<div style="color:#7070a0;font-size:0.66rem">{n_clean} limpias · {n_settled} liquidadas · {backend}</div>
</div>
<div style="color:{vclr};font-size:0.92rem;font-weight:700;margin-bottom:0.5rem">{vlabel}</div>
<table style="width:100%;border-collapse:collapse;font-size:0.78rem">
<thead><tr>
<th style="text-align:left;padding:2px 10px;color:#606080;font-size:0.6rem">BANDA</th>
<th style="text-align:right;padding:2px 10px;color:#606080;font-size:0.6rem">OBSERVADO</th>
<th style="text-align:right;padding:2px 10px;color:#606080;font-size:0.6rem">ESPERADO</th>
</tr></thead><tbody>
{_row("Cierre dentro P10–P90", stats.get("hit_p10_p90"), 80)}
{_row("Cierre dentro P05–P95", stats.get("hit_p05_p95"), 90)}
{_row("Cierre dentro 1σ (P16–P84)", stats.get("hit_1sigma"), 68)}
</tbody></table>
{ratio_txt}
<div style="color:#606080;font-size:0.64rem;margin-top:0.45rem;line-height:1.4">Si OBSERVADO &gt; ESPERADO consistentemente → el modelo sobre-estima la vol (IV cara, favor vender). Si &lt; → sub-estima (colas gordas, compra/amplía). Se registra automático cada sesión vía el job headless.</div>
</div>
""")
