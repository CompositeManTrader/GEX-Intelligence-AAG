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
    next_regime = "NEGATIVE" if regime == "POSITIVE" else "POSITIVE"

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
        vt = vex_sum.get("total_vex", 0)
        if vt > 1e8:
            votes.append(("Vanna", +1, "Long vanna — vol expansion amplifica al alza"))
        elif vt < -1e8:
            votes.append(("Vanna", -1, "Short vanna — vol expansion amplifica a la baja"))

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
    """Choose an expiry preset based on the regime and IV richness."""
    # SHORT gamma + IV cara → short-dated debit (momentum, fast decay risk OK)
    # SHORT gamma + IV barata → longer-dated debit
    # LONG gamma + IV cara → short-dated credit spreads
    # LONG gamma + IV barata → calendars or stay out
    if iv_hv_ratio is None:
        iv_hv_ratio = 1.0
    if regime == "NEGATIVE":
        if iv_hv_ratio > 1.3:
            return "0-2 DTE (debit)"
        return "7-14 DTE (debit)"
    if regime == "POSITIVE":
        if iv_hv_ratio > 1.3:
            return "1-7 DTE (credit)"
        return "30-45 DTE (calendars)"
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
