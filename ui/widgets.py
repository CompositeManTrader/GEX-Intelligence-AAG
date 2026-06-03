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
    up = (chg or 0) >= 0
    chg_color = "#22c55e" if up else "#f43f5e"
    arrow = "▲" if up else "▼"

    ms = (market_status or "").upper()
    if ms == "OPEN":
        dot_cls, dot_lbl, dot_col = "live", "LIVE", "#22c55e"
    elif ms in ("PRE", "POST"):
        dot_cls, dot_lbl, dot_col = "idle", ms, "#f59e0b"
    elif ms == "CLOSED":
        dot_cls, dot_lbl, dot_col = "off", "CLOSED", "#6b6b8a"
    else:
        dot_cls, dot_lbl, dot_col = "idle", "MKT", "#f59e0b"

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
        ng_col = "#22c55e" if net_gex_bn >= 0 else "#f43f5e"
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
      <div style="position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(to right,#f97316,rgba(249,115,22,0) 60%);"></div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:1.2rem;flex-wrap:wrap;">
        <div style="display:flex;align-items:center;gap:1.15rem;min-width:260px;">
          <div>
            <div style="font-size:0.6rem;color:{dot_col};letter-spacing:0.14em;font-family:JetBrains Mono,monospace;margin-bottom:3px;">
              <span class="mh-dot {dot_cls}"></span>{dot_lbl}
            </div>
            <div style="font-size:1.2rem;font-weight:800;color:#f97316;font-family:JetBrains Mono,monospace;letter-spacing:0.08em;line-height:1;">{symbol}</div>
          </div>
          <div style="display:flex;align-items:baseline;gap:0.7rem;flex-wrap:wrap;">
            <span style="font-size:2.1rem;font-weight:800;color:#f5f5ff;font-family:JetBrains Mono,monospace;font-variant-numeric:tabular-nums;line-height:1;text-shadow:0 0 18px rgba(245,245,255,0.12);">${spot:,.2f}</span>
            <span style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:5px;background:{chg_color}1f;border:1px solid {chg_color}44;color:{chg_color};font-size:0.74rem;font-weight:700;font-family:JetBrains Mono,monospace;white-space:nowrap;">{arrow} {chg:+.2f} · {chg_p:+.2f}%</span>
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
    if a < 0.3:
        color = "#f43f5e"; status = "CROSS IMMINENT"; emoji = "🔴"
    elif a < 1.0:
        color = "#f59e0b"; status = "DANGER ZONE"; emoji = "🟡"
    else:
        color = "#22c55e"; status = "SAFE"; emoji = "🟢"

    above = dist_abs > 0    # gf above spot → spot would need to rally to flip
    direction = "por ENCIMA del spot" if above else "por DEBAJO del spot"
    # Crossing direction matters: if Zero Γ is ABOVE spot, a rally up across
    # it pushes Net GEX into POSITIVE territory; a fall below an above-spot
    # gf is impossible (can't fall through a level above you). Net GEX is
    # negative below gf and positive above gf (SqueezeMetrics convention),
    # so the destination regime is determined by which side of gf you land.
    # The legacy 2-state toggle assumed binary regime and mis-labelled the
    # transition target whenever the current regime was NEUTRAL.
    next_regime = "POSITIVE" if above else "NEGATIVE"

    # Thermometer: spot position inside [pw, cw] range as %
    bar_html = ""
    if cw and pw and cw > pw:
        pos = max(0.0, min(1.0, (spot - pw) / (cw - pw)))
        gf_pos = max(0.0, min(1.0, (gf - pw) / (cw - pw)))
        # Single-line spans so no line starts with 4+ spaces after the outer
        # dedent — prevents Streamlit's markdown from code-fencing the block.
        bar_html = (
            f'<div style="position:relative;height:14px;margin:8px 0 4px;'
            f'background:linear-gradient(to right,rgba(244,63,94,.25) 0%,'
            f'rgba(245,158,11,.15) 45%,rgba(245,158,11,.15) 55%,'
            f'rgba(34,197,94,.25) 100%);'
            f'border:1px solid #2a2a3a;border-radius:3px;">'
            f'<div title="Put Wall ${pw:.0f}" '
            f'style="position:absolute;left:0%;top:-3px;width:2px;height:20px;'
            f'background:#f43f5e"></div>'
            f'<div title="Call Wall ${cw:.0f}" '
            f'style="position:absolute;left:100%;top:-3px;width:2px;height:20px;'
            f'background:#22c55e"></div>'
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
            {emoji} GEX FLIP ZONE
          </div>
          <div style="font-size:1.15rem;font-weight:800;color:{color};margin-top:2px;">
            {status}
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.68rem;color:#7070a0;">Distancia a Zero Γ</div>
          <div style="font-size:1.4rem;font-weight:800;color:{color};line-height:1.1;">
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
        Régimen actual: <b style="color:{color}">{regime}</b>.
        Cruzar Zero Γ → régimen cambia a <b>{next_regime}</b>.
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
        bias, bias_clr = "LONG (bullish)", "#22c55e"; bias_emoji = "📈"
    elif score <= -2:
        bias, bias_clr = "SHORT (bearish)", "#f43f5e"; bias_emoji = "📉"
    else:
        bias, bias_clr = "NEUTRAL / RANGE", "#f59e0b"; bias_emoji = "↔️"

    # ── Level-based targets (structural, not made up) ───────────────────────
    entry_zone, stop, target = _derive_levels(
        score, spot, cw, pw, gf, hvl, em_lo, em_hi, regime,
    )

    # ── Expiration recommendation ───────────────────────────────────────────
    expiry = _recommend_expiry(dte, regime, iv_hv_ratio)

    # ── Confidence ──────────────────────────────────────────────────────────
    n = len([v for _, v, _ in votes if v != 0])
    conf = int(min(100, abs(score) / max(1, n) * 100)) if n else 0
    conf_clr = ("#22c55e" if conf >= 67 else
                "#f59e0b" if conf >= 34 else "#f43f5e")

    # ── Render votes table ──────────────────────────────────────────────────
    rows_html = ""
    for name, v, note in votes:
        sym = "▲" if v > 0 else ("▼" if v < 0 else "·")
        sym_clr = "#22c55e" if v > 0 else ("#f43f5e" if v < 0 else "#707090")
        rows_html += (
            f'<tr><td style="padding:3px 10px 3px 0;color:{sym_clr};'
            f'font-weight:700;width:18px;">{sym}</td>'
            f'<td style="padding:3px 10px 3px 0;color:#c0c0d8;width:120px;">{name}</td>'
            f'<td style="padding:3px 0;color:#9090b0;">{note}</td></tr>'
        )

    return _html(f"""
    <div style="background:linear-gradient(135deg,rgba(30,30,50,0.6),rgba(14,14,26,0.8));
         border:1px solid #2a2a3a;border-left:4px solid {bias_clr};
         padding:1rem 1.2rem;border-radius:6px;margin:0.6rem 0 1rem;
         font-family:JetBrains Mono,monospace;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;
           gap:1rem;flex-wrap:wrap;margin-bottom:0.8rem;">
        <div>
          <div style="font-size:0.68rem;color:#7070a0;letter-spacing:0.14em;">
            🤖 TRADE SETUP CARD  ·  {symbol}
          </div>
          <div style="font-size:1.35rem;font-weight:800;color:{bias_clr};
               margin-top:3px;letter-spacing:0.02em;">
            {bias_emoji}&nbsp;{bias}
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.68rem;color:#7070a0;">Confianza</div>
          <div style="font-size:1.35rem;font-weight:800;color:{conf_clr};">
            {conf}%
          </div>
          <div style="font-size:0.65rem;color:#606080;">
            {n} señales
          </div>
        </div>
      </div>

      <table style="width:100%;border-collapse:collapse;font-size:0.72rem;
             line-height:1.5;margin-bottom:0.8rem;">
        {rows_html}
      </table>

      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.6rem;
           border-top:1px solid rgba(255,255,255,0.05);padding-top:0.7rem;">
        <div>
          <div style="font-size:0.62rem;color:#7070a0;letter-spacing:0.1em;">ENTRY</div>
          <div style="font-size:0.9rem;color:#e0e0f0;font-weight:700;">{entry_zone}</div>
        </div>
        <div>
          <div style="font-size:0.62rem;color:#7070a0;letter-spacing:0.1em;">STOP</div>
          <div style="font-size:0.9rem;color:#f43f5e;font-weight:700;">{stop}</div>
        </div>
        <div>
          <div style="font-size:0.62rem;color:#7070a0;letter-spacing:0.1em;">TARGET</div>
          <div style="font-size:0.9rem;color:#22c55e;font-weight:700;">{target}</div>
        </div>
        <div>
          <div style="font-size:0.62rem;color:#7070a0;letter-spacing:0.1em;">EXPIRY</div>
          <div style="font-size:0.9rem;color:#a855f7;font-weight:700;">{expiry}</div>
        </div>
      </div>

      <div style="font-size:0.62rem;color:#505070;margin-top:0.7rem;
           line-height:1.4;font-style:italic;">
        ⚠ Sugerencia algorítmica basada en confluencia de señales. No constituye asesoría.
        Ajusta size según tu tolerancia al riesgo.
      </div>
    </div>
    """)


# ─────────────────────────────────────────────────────────────────────────────
#  Internals
# ─────────────────────────────────────────────────────────────────────────────
def _derive_levels(
    score: int, spot: float,
    cw: Optional[float], pw: Optional[float],
    gf: Optional[float], hvl: Optional[float],
    em_lo: Optional[float], em_hi: Optional[float],
    regime: str,
) -> tuple[str, str, str]:
    """Derive entry / stop / target from structural GEX levels.

    Philosophy:
      - LONG:  enter on pullback to HVL or gamma flip (support), stop below
               put wall (structural break), target call wall / EM+.
      - SHORT: enter on rally to HVL or call wall, stop above call wall,
               target put wall / EM-.
      - NEUTRAL: iron condor style — sell premium between walls.
    """
    def f(v: Optional[float]) -> str:
        return f"${v:.2f}" if v else "—"

    if score >= 2:
        # LONG: buy pullbacks to support
        entry_lo = max([x for x in [hvl, gf, pw] if x and x < spot] or [spot * 0.995])
        entry_hi = spot
        entry = f"${entry_lo:.2f} – ${entry_hi:.2f}"
        stop = f(pw * 0.997 if pw else spot * 0.985)
        target = f(cw or em_hi or (spot * 1.02))
        return entry, stop, target
    if score <= -2:
        # SHORT: sell rallies to resistance
        entry_lo = spot
        entry_hi = min([x for x in [hvl, gf, cw] if x and x > spot] or [spot * 1.005])
        entry = f"${entry_lo:.2f} – ${entry_hi:.2f}"
        stop = f(cw * 1.003 if cw else spot * 1.015)
        target = f(pw or em_lo or (spot * 0.98))
        return entry, stop, target
    # NEUTRAL: iron condor between walls, or stay flat in short gamma
    if regime == "POSITIVE" and cw and pw:
        entry = f"Sell {pw:.0f}P / {cw:.0f}C"
        stop = "break of wall"
        target = f"decay hasta expiry"
        return entry, stop, target
    return "Stay flat / wait", "—", "—"


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
        "POSITIVE": "#22c55e",
        "NEGATIVE": "#f43f5e",
        "NEUTRAL": "#f59e0b",
    }.get(regime or "NEUTRAL", "#9ca3af")

    gex_str = (f"${net_gex_bn:+.2f}B" if net_gex_bn is not None else "—")
    hiro_str = (f"{hiro_z:+.2f}σ" if hiro_z is not None else "—")
    hiro_color = (
        "#22c55e" if (hiro_z or 0) > 0.5
        else "#f43f5e" if (hiro_z or 0) < -0.5
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
    body += _row("CALL WALL",  cw,  "#22c55e", "Resistencia · cap arriba")
    body += _row("HVL",        hvl, "#06b6d4", "Atractor · imán intradía")
    body += _row("ZERO Γ",     gf,  "#a855f7", "Régimen · cruce = volatilidad")
    body += _row("MAX PAIN",   mp,  "#f59e0b", "Pin · cierre objetivo")
    body += _row("PUT WALL",   pw,  "#f43f5e", "Soporte · cap abajo")
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
      <div style="color:#f59e0b;font-size:1rem;font-weight:700">
        ${risk_dollars:,.0f} <span style="font-size:0.7rem">({risk_pct:.1f}%)</span>
      </div>
    </div>
    <div>
      <div style="color:#6b7280;font-size:0.58rem">Stop</div>
      <div style="color:#f43f5e;font-size:1rem;font-weight:700">
        {stop_pts:.1f} pts
        <span style="color:#6b7280;font-size:0.65rem">
          (${risk_per_contract:,.0f}/c)
        </span>
      </div>
    </div>
    <div>
      <div style="color:#6b7280;font-size:0.58rem">Contratos</div>
      <div style="color:#22c55e;font-size:1.6rem;font-weight:800;line-height:1">
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
            side_color = "#22c55e"
            side_label = "CALL ▲"
        elif side == "put_dominant":
            side_color = "#f43f5e"
            side_label = "PUT ▼"
        else:
            side_color = "#f59e0b"
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
            f'${score:+,.0f}M</td>'
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
            color = "#22c55e"
        elif sigma <= 1.0:
            color = "#f59e0b"
        elif sigma <= 1.5:
            color = "#a855f7"
        else:
            color = "#f43f5e"
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
    pop_color = ("#22c55e" if pop >= 70 else
                 "#f59e0b" if pop >= 50 else "#f43f5e")
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
<td style="padding:5px 8px;border-left:3px solid #f43f5e;background:rgba(244,63,94,0.07);width:50%;vertical-align:top">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.08em">PUT WING</div>
<div style="color:#f43f5e;font-weight:700">Sell ${short_put:,.0f}P</div>
<div style="color:#9090b0;font-size:0.70rem">Buy ${long_put:,.0f}P (wing ${wing:.0f})</div>
<div style="color:#7070a0;font-size:0.66rem;margin-top:0.2rem">PoT short {pot_sp:.0f}%</div>
</td>
<td style="padding:5px 8px;border-left:3px solid #22c55e;background:rgba(34,197,94,0.07);width:50%;vertical-align:top">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.08em">CALL WING</div>
<div style="color:#22c55e;font-weight:700">Sell ${short_call:,.0f}C</div>
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
    bar_color = "#22c55e" if passed else "#f43f5e"
    label = "PASS" if passed else "FAIL"

    def _chk(ok: bool, txt: str) -> str:
        symbol = "✓" if ok else "✗"
        clr = "#22c55e" if ok else "#f43f5e"
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
<div style="flex:1 1 0;border-left:3px solid #f43f5e;padding-left:0.6rem">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.10em">SHORT PUT</div>
<div style="color:#f43f5e;font-weight:700;font-size:1.0rem">{(f"${sp:,.0f}" if sp else "—")}</div>
<div style="color:#7070a0;font-size:0.66rem">PW {(f"${pw:,.0f}" if pw else "—")}</div>
</div>
<div style="flex:1 1 0;border-left:3px solid #fbbf24;padding-left:0.6rem">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.10em">CENTRO</div>
<div style="color:#fbbf24;font-weight:700;font-size:1.0rem">{(f"${centre:,.0f}" if centre else "—")}</div>
<div style="color:#7070a0;font-size:0.66rem">HVL / spot</div>
</div>
<div style="flex:1 1 0;border-left:3px solid #22c55e;padding-left:0.6rem">
<div style="color:#7070a0;font-size:0.58rem;letter-spacing:0.10em">SHORT CALL</div>
<div style="color:#22c55e;font-weight:700;font-size:1.0rem">{(f"${sc:,.0f}" if sc else "—")}</div>
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
    skew_clr = ("#f43f5e" if skew < -0.15 else
                "#22c55e" if skew > 0.15 else "#9090b0")
    kurt_txt = ("colas GORDAS (riesgo de cola alto)" if kurt > 0.5
                else "colas finas" if kurt < -0.5 else "≈ normal")
    kurt_clr = "#f59e0b" if abs(kurt) > 0.5 else "#9090b0"

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
            f'<td style="padding:3px 10px;text-align:right;color:#f43f5e">'
            f'P&lt; {pb:.0f}%</td>'
            f'<td style="padding:3px 10px;text-align:right;color:#22c55e">'
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

    skew_clr = ("#f43f5e" if skew < -0.15 else
                "#22c55e" if skew > 0.15 else "#9090b0")
    skew_txt = ("sesgo bajista" if skew < -0.15
                else "sesgo alcista" if skew > 0.15 else "≈ simétrico")
    kurt_clr = "#f59e0b" if abs(kurt) > 0.5 else "#9090b0"
    kurt_txt = ("colas GORDAS" if kurt > 0.5
                else "colas finas" if kurt < -0.5 else "≈ normal")

    # Percentile ladder as a horizontal strip
    pcells = ""
    pct_order = [("p5", "#f43f5e"), ("p10", "#f59e0b"), ("p25", "#22c55e"),
                 ("p50", "#e0e0f0"), ("p75", "#22c55e"), ("p90", "#f59e0b"),
                 ("p95", "#f43f5e")]
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
            f'<td style="padding:3px 10px;text-align:right;color:#f43f5e">{pb:.0f}%</td>'
            f'<td style="padding:3px 10px;text-align:right;color:#22c55e">{pa:.0f}%</td>'
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

    # Fit-quality footer
    foot = ""
    if meta:
        method = (meta.get("method") or "—").upper()
        rmse = meta.get("rmse")
        arb = meta.get("arb_free")
        fwd = meta.get("forward")
        arb_txt = ("✓ arbitrage-free" if arb is True
                   else "⚠ no verificado" if arb is None else "✗ con arbitraje")
        arb_clr = "#22c55e" if arb is True else "#f59e0b"
        rmse_txt = f"RMSE {rmse:.1e}" if rmse is not None else ""
        foot = (
            f'<div style="color:#606080;font-size:0.64rem;margin-top:0.5rem;'
            f'line-height:1.4">Modelo: <b>{method}</b> · forward '
            f'${fwd:,.2f} · {rmse_txt} · '
            f'<span style="color:{arb_clr}">{arb_txt}</span>. '
            f'Niveles por inversión exacta de la CDF (no interpolación).</div>'
        )

    return _html(f"""
<div style="background:rgba(15,17,24,0.85);border:1px solid #1e2230;border-radius:6px;padding:0.7rem 0.9rem;margin:0.5rem 0;font-family:JetBrains Mono,monospace">
<div style="color:#9090b0;font-size:0.66rem;letter-spacing:0.14em;text-transform:uppercase;margin-bottom:0.5rem">🎯 NIVELES EXACTOS · risk-neutral density (SVI)</div>
<div style="display:flex;gap:1.2rem;flex-wrap:wrap;font-size:0.82rem;margin-bottom:0.4rem">
<div><div style="color:#6b7280;font-size:0.6rem">MODE (+probable)</div><div style="color:#06b6d4;font-weight:700">${mode:,.2f}</div></div>
<div><div style="color:#6b7280;font-size:0.6rem">MEDIANA P50</div><div style="color:#e0e0f0;font-weight:700">${pct.get('p50',0):,.2f}</div></div>
<div><div style="color:#6b7280;font-size:0.6rem">1σ-equiv (P16–P84)</div><div style="color:#e0e0f0;font-weight:700">${p16:,.1f} – ${p84:,.1f}</div></div>
<div><div style="color:#6b7280;font-size:0.6rem">σ IMPLÍCITA</div><div style="color:#e0e0f0;font-weight:700">${std:,.2f} ({std_pct:.2f}%)</div></div>
<div><div style="color:#6b7280;font-size:0.6rem">SKEW</div><div style="color:{skew_clr};font-weight:700">{skew:+.2f} <span style="font-size:0.6rem">{skew_txt}</span></div></div>
<div><div style="color:#6b7280;font-size:0.6rem">KURTOSIS</div><div style="color:{kurt_clr};font-weight:700">{kurt:+.2f} <span style="font-size:0.6rem">{kurt_txt}</span></div></div>
</div>
<div style="color:#7070a0;font-size:0.6rem;letter-spacing:0.1em;margin:0.3rem 0 0.1rem">ESCALERA DE PERCENTILES (probabilidad de cierre)</div>
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
            clr = "#22c55e" if abs(obs - expected) <= 6 else "#f59e0b"
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
        rclr = ("#f43f5e" if ratio > 1.1 else
                "#22c55e" if ratio < 0.9 else "#9090b0")
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
