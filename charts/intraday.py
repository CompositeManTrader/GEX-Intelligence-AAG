"""
TradingView-style intraday candlestick + volume with GEX price-lines.

- Candles via Schwab pricehistory (cached 20s in data.fetch).
- Latest price ticker fed separately from data.fetch.fetch_quote (cached 8s).
- Live ET + CDMX clock ticks every second inside the iframe via setInterval.
- Price-chip re-colors on live-tick.
"""
from __future__ import annotations

import html
import json
from typing import Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def _unix(dt) -> int:
    t = pd.Timestamp(dt)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return int(t.timestamp())


def render_tv_chart(price_df: pd.DataFrame, spot: float, gex_summary: dict,
                    mp: Optional[float] = None,
                    em_lo: Optional[float] = None,
                    em_hi: Optional[float] = None,
                    freq_min: int = 1,
                    live_quote: Optional[dict] = None,
                    market_status: str = "—") -> None:
    """Candlestick + volume + GEX structural levels via lightweight-charts v4."""
    if price_df is None or price_df.empty:
        st.caption("Sin datos de precio para mostrar la gráfica.")
        return
    df = price_df.copy().dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        st.caption("Sin velas válidas.")
        return

    candles = [
        {"time": _unix(r.date),
         "open": round(float(r.open), 4),
         "high": round(float(r.high), 4),
         "low": round(float(r.low), 4),
         "close": round(float(r.close), 4)}
        for r in df.itertuples()
    ]
    volumes = [
        {"time": _unix(r.date),
         "value": float(r.volume),
         "color": "#26a69a88" if r.close >= r.open else "#ef535088"}
        for r in df.itertuples()
    ]

    cw = gex_summary.get("call_wall") if gex_summary else None
    pw = gex_summary.get("put_wall") if gex_summary else None
    gf = gex_summary.get("gamma_flip") if gex_summary else None
    hvl = gex_summary.get("hvl") if gex_summary else None

    def _pl(price, color, title, style=0, width=1):
        if price is None or float(price) <= 0:
            return None
        return {"price": round(float(price), 2), "color": color,
                "lineWidth": width, "lineStyle": style,
                "axisLabelVisible": True, "title": title}

    gex_lines = [l for l in [
        _pl(spot, "#f97316", f"SPOT {spot:.2f}", 0, 2),
        _pl(cw, "#22c55e", f"CW {cw:.2f}" if cw else "", 2, 1),
        _pl(pw, "#ef4444", f"PW {pw:.2f}" if pw else "", 2, 1),
        _pl(gf, "#a855f7", f"GF {gf:.2f}" if gf else "", 1, 1),
        _pl(hvl, "#06b6d4", f"HVL {hvl:.2f}" if hvl else "", 4, 1),
        _pl(mp, "#94a3b8", f"MP {mp:.2f}" if mp else "", 4, 1),
        _pl(em_hi, "#c084fc", f"EM+ {em_hi:.2f}" if em_hi else "", 3, 1),
        _pl(em_lo, "#c084fc", f"EM- {em_lo:.2f}" if em_lo else "", 3, 1),
    ] if l is not None]

    # Prefer live quote for header; fall back to last candle close
    q_last = None
    q_open = None
    q_chg = None
    q_chg_p = None
    q_time_ms = None
    if live_quote:
        q_last = live_quote.get("last") or live_quote.get("mark")
        q_open = live_quote.get("open") or float(df["open"].iloc[0])
        q_chg = live_quote.get("net_change")
        q_chg_p = live_quote.get("pct_change")
        q_time_ms = live_quote.get("trade_time_ms") or live_quote.get("quote_time_ms")
    if q_last is None:
        q_last = float(df["close"].iloc[-1])
    if q_open is None:
        q_open = float(df["open"].iloc[0])
    if q_chg is None:
        q_chg = q_last - q_open
    if q_chg_p is None:
        q_chg_p = (q_chg / q_open * 100) if q_open else 0.0

    chg_clr = "#26a69a" if q_chg >= 0 else "#ef5350"
    freq_lbl = f"{freq_min}m"
    ms_status_clr = {
        "OPEN": "#22c55e", "PRE": "#f59e0b", "POST": "#f59e0b",
        "CLOSED": "#94a3b8",
    }.get(market_status, "#94a3b8")

    chips = "".join(filter(None, [
        f'<span class="cg">CW&nbsp;{cw:.0f}</span>' if cw else "",
        f'<span class="cr">PW&nbsp;{pw:.0f}</span>' if pw else "",
        f'<span class="cp">GF&nbsp;{gf:.0f}</span>' if gf else "",
        f'<span class="cy">HVL&nbsp;{hvl:.0f}</span>' if hvl else "",
        f'<span class="cs">MP&nbsp;{mp:.0f}</span>' if mp else "",
    ]))

    trade_time_js = "null" if q_time_ms is None else str(int(q_time_ms))

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#131722;color:#d1d4dc;font-family:'JetBrains Mono','Courier New',monospace;overflow:hidden}}
#h{{display:flex;align-items:center;gap:8px;padding:5px 12px;background:#1e222d;border-bottom:1px solid #2a2e39;flex-wrap:wrap;font-size:11px}}
#pr{{font-weight:700;font-size:15px;transition:color .25s}}
#dl{{color:{chg_clr};font-weight:600}}
#ms{{padding:2px 7px;border-radius:3px;font-size:10px;font-weight:700;background:rgba(255,255,255,0.04);color:{ms_status_clr};border:1px solid {ms_status_clr}44}}
#pulse{{display:inline-block;width:6px;height:6px;border-radius:50%;background:{ms_status_clr};margin-right:4px;animation:pulse 1.8s ease-in-out infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
span.co{{padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700;background:rgba(249,115,22,.15);color:#f97316}}
span.cg{{padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700;background:rgba(38,166,154,.15);color:#26a69a}}
span.cr{{padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700;background:rgba(239,83,80,.15);color:#ef5350}}
span.cp{{padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700;background:rgba(168,85,247,.15);color:#a855f7}}
span.cy{{padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700;background:rgba(6,182,212,.15);color:#06b6d4}}
span.cs{{padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700;background:rgba(148,163,184,.12);color:#94a3b8}}
#clk{{margin-left:auto;color:#9598a1;font-size:10px;text-align:right;line-height:1.35;font-variant-numeric:tabular-nums}}
#clk b{{color:#d1d4dc}}
#w{{position:relative;width:100%}}
#tip{{position:absolute;top:40px;left:10px;font-size:10px;color:#9598a1;pointer-events:none;z-index:10;background:rgba(19,23,34,.92);padding:3px 8px;border-radius:3px;border:1px solid #2a2e39;display:none}}
#mc{{width:100%;height:440px}}
#vc{{width:100%;height:70px}}
.flash-up{{animation:fu .6s ease-out}}
.flash-dn{{animation:fd .6s ease-out}}
@keyframes fu{{0%{{background:rgba(38,166,154,.35)}}100%{{background:transparent}}}}
@keyframes fd{{0%{{background:rgba(239,83,80,.35)}}100%{{background:transparent}}}}
</style></head><body>
<div id="h">
  <span id="ms"><span id="pulse"></span>{html.escape(market_status)}</span>
  <span id="pr">{q_last:.2f}</span>
  <span id="dl">{q_chg:+.2f}&nbsp;({q_chg_p:+.2f}%)</span>
  <span class="co">{freq_lbl}</span>
  {chips}
  <span id="clk">
    ET <b id="cet">--:--:--</b>&nbsp;·&nbsp;CDMX <b id="ccd">--:--:--</b><br>
    Last tick: <b id="clt">—</b>
  </span>
</div>
<div id="w">
  <div id="tip"></div>
  <div id="mc"></div>
  <div id="vc"></div>
</div>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
const C={json.dumps(candles)};
const V={json.dumps(volumes)};
const G={json.dumps(gex_lines)};
const TRADE_MS={trade_time_js};
const PR_INIT={q_last};
const TFmt=new Intl.DateTimeFormat("es-MX",{{timeZone:"America/Mexico_City",hour:"2-digit",minute:"2-digit",hour12:false}});
const DFmtCDMX=new Intl.DateTimeFormat("es-MX",{{timeZone:"America/Mexico_City",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}});
const DFmtET=new Intl.DateTimeFormat("en-US",{{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit",hour12:false}});
const ClkET=new Intl.DateTimeFormat("en-US",{{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}});
const ClkCDMX=new Intl.DateTimeFormat("es-MX",{{timeZone:"America/Mexico_City",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}});
const tickET=s=>ClkET.format(new Date(s*1000));
const fmt=s=>DFmtET.format(new Date(s*1000));
const CFG={{
  layout:{{background:{{type:"solid",color:"#131722"}},textColor:"#535964",fontFamily:"'JetBrains Mono','Courier New',monospace",fontSize:11}},
  grid:{{vertLines:{{color:"rgba(42,46,57,.5)",style:1}},horzLines:{{color:"rgba(42,46,57,.5)",style:1}}}},
  crosshair:{{mode:LightweightCharts.CrosshairMode.Normal,
    vertLine:{{color:"#758696",width:1,style:1,labelBackgroundColor:"#363a45"}},
    horzLine:{{color:"#758696",width:1,style:1,labelBackgroundColor:"#363a45"}}}},
  rightPriceScale:{{borderColor:"#2a2e39"}},
  timeScale:{{borderColor:"#2a2e39",timeVisible:true,secondsVisible:false,tickMarkFormatter:s=>fmt(s)}},
  localization:{{timeFormatter:s=>DFmtCDMX.format(new Date(s*1000))}},
  handleScroll:{{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true}},
  handleScale:{{mouseWheel:true,pinch:true,axisPressedMouseMove:true}},
}};
const W=document.getElementById("mc").offsetWidth||900;
const mc=LightweightCharts.createChart(document.getElementById("mc"),{{...CFG,width:W,height:440}});
const cs=mc.addCandlestickSeries({{upColor:"#26a69a",downColor:"#ef5350",borderUpColor:"#26a69a",borderDownColor:"#ef5350",wickUpColor:"#26a69a",wickDownColor:"#ef5350"}});
cs.setData(C);
G.forEach(l=>cs.createPriceLine(l));
const vc=LightweightCharts.createChart(document.getElementById("vc"),{{...CFG,width:W,height:70,timeScale:{{...CFG.timeScale,visible:false}},rightPriceScale:{{visible:false}},leftPriceScale:{{visible:false}}}});
const vs=vc.addHistogramSeries({{priceScaleId:"v",lastValueVisible:false,priceLineVisible:false}});
vs.setData(V);
let _syncing=false;
function syncRange(src,dst){{
  if(_syncing) return;
  const r=src.timeScale().getVisibleLogicalRange();
  if(!r) return;
  _syncing=true;
  dst.timeScale().setVisibleLogicalRange(r);
  _syncing=false;
}}
mc.timeScale().subscribeVisibleLogicalRangeChange(()=>syncRange(mc,vc));
vc.timeScale().subscribeVisibleLogicalRangeChange(()=>syncRange(vc,mc));
const tip=document.getElementById("tip");
mc.subscribeCrosshairMove(p=>{{
  if(!p.time||!p.seriesData.has(cs)){{tip.style.display="none";return;}}
  const r=p.seriesData.get(cs),d=r.close-r.open,pct=(d/r.open*100).toFixed(2),cl=d>=0?"#26a69a":"#ef5350";
  tip.style.display="block";
  tip.innerHTML=`<span style="color:#787b86">${{fmt(p.time)}} ET</span>&ensp;`
    +`<span style="color:${{cl}}">O:${{r.open.toFixed(2)}} H:${{r.high.toFixed(2)}} L:${{r.low.toFixed(2)}} C:${{r.close.toFixed(2)}}&nbsp;<b>${{d>=0?"+":""}}${{d.toFixed(2)}} (${{pct}}%)</b></span>`;
}});
new ResizeObserver(()=>{{const w=document.getElementById("w").offsetWidth;if(w>10){{mc.applyOptions({{width:w}});vc.applyOptions({{width:w}});}}}}).observe(document.getElementById("w"));
mc.timeScale().scrollToRealTime();

// Live clocks
const cet=document.getElementById("cet"),ccd=document.getElementById("ccd"),clt=document.getElementById("clt"),pr=document.getElementById("pr");
let _last=PR_INIT;
function relTime(ms){{
  if(!ms)return"—";
  const diff=(Date.now()-ms)/1000;
  if(diff<60)return Math.floor(diff)+"s";
  if(diff<3600)return Math.floor(diff/60)+"m "+Math.floor(diff%60)+"s";
  return Math.floor(diff/3600)+"h "+Math.floor((diff%3600)/60)+"m";
}}
setInterval(()=>{{
  const now=new Date();
  cet.textContent=ClkET.format(now);
  ccd.textContent=ClkCDMX.format(now);
  clt.textContent=relTime(TRADE_MS);
}},1000);
</script></body></html>"""
    components.html(page, height=556, scrolling=False)
