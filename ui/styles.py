"""Bloomberg-dark CSS block. Separated to keep app.py clean."""

CSS = """
<style>
html, body, [data-testid="stApp"], .main, .block-container {
    background-color: #080810 !important;
    color: #c8c8d8 !important;
}
.block-container { padding: 2rem 1.6rem 2rem !important; max-width: 100% !important; }

input, textarea, select,
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] div[data-baseweb="select"] {
    background: #12121e !important; color: #e0e0f0 !important;
    border-color: #2a2a3e !important; border-radius: 4px !important;
}
[data-testid="stTextInput"] label,
[data-testid="stSelectbox"] label { color: #6868a0 !important; font-size: 0.72rem !important; }

[data-testid="stButton"] button {
    background: transparent !important; border: 1px solid #2a2a3e !important;
    color: #c0c0d8 !important; border-radius: 4px !important;
    font-size: 0.78rem !important; font-family: 'JetBrains Mono', monospace !important;
    transition: all 0.15s;
}
[data-testid="stButton"] button:hover {
    border-color: #f97316 !important; color: #f97316 !important;
    background: rgba(249,115,22,0.08) !important;
}
button[kind="primary"] {
    background: #f97316 !important; border-color: #f97316 !important;
    color: #000 !important; font-weight: 700 !important;
}
button[kind="primary"]:hover { background: #fb923c !important; color: #000 !important; }
[data-testid="stLinkButton"] a {
    background: rgba(249,115,22,0.12) !important; border: 1px solid #f97316 !important;
    color: #f97316 !important; border-radius: 4px !important;
    padding: 8px 18px !important; font-size: 0.82rem !important;
    text-decoration: none !important; display: block !important; text-align: center !important;
}

[data-testid="stMetric"] {
    background: #0e0e1a !important; border: 1px solid #1e1e30 !important;
    border-radius: 4px !important; padding: 10px 14px !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.62rem !important; text-transform: uppercase; letter-spacing: 0.1em;
    font-weight: 600 !important; color: #606080 !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.25rem !important; font-weight: 700 !important;
    color: #e8e8f8 !important;
    font-family: 'JetBrains Mono', 'Courier New', monospace !important;
}
[data-testid="stMetricDelta"] { font-size: 0.72rem !important; font-family: 'JetBrains Mono', monospace !important; }

.stTabs [data-baseweb="tab-list"] {
    background: #0e0e1a !important; border-radius: 4px !important;
    gap: 2px !important; padding: 2px !important;
    border: 1px solid #1e1e30 !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 3px !important; padding: 5px 18px !important;
    color: #606080 !important; font-size: 0.78rem !important;
    font-weight: 500 !important; font-family: 'JetBrains Mono', monospace !important;
}
.stTabs [aria-selected="true"] { background: #1e1e30 !important; color: #f97316 !important; }

.stCaption p, [data-testid="stCaptionContainer"] p { color: #505070 !important; font-size: 0.72rem !important; }
p, .stMarkdown p { color: #a0a0c0 !important; }
h1, h2, h3 { color: #e0e0f0 !important; }

[data-testid="stSidebar"] { background: #0a0a14 !important; border-right: 1px solid #1a1a2a !important; }
[data-testid="stSidebarContent"] * { color: #a0a0c0 !important; }
[data-testid="stSlider"] div { color: #a0a0c0 !important; }

[data-testid="stExpander"] {
    background: linear-gradient(135deg,#0b0b15,#0d0d18) !important;
    border: 1px solid #181828 !important; border-radius: 7px !important;
    margin-bottom: 0.35rem !important;
}
[data-testid="stExpander"] summary {
    color: #7777a0 !important; font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.68rem !important; letter-spacing: 0.09em !important;
    text-transform: uppercase; padding: 0.45rem 0.85rem !important;
}
[data-testid="stExpander"] summary:hover { color: #f97316 !important; }
[data-testid="stExpander"] summary svg { fill: #f97316 !important; }

/* Brand mark (top-left logo lockup) */
.brand { display:flex; align-items:center; gap:11px; padding-top:1px; }
.brand-glyph {
    width:33px; height:33px; border-radius:9px; flex-shrink:0;
    background:linear-gradient(135deg,#f97316 0%,#9a3412 100%);
    display:flex; align-items:center; justify-content:center;
    color:#0a0a12; font-weight:800; font-size:1.1rem;
    font-family:'JetBrains Mono',monospace;
    box-shadow:0 0 15px rgba(249,115,22,0.35),0 2px 6px rgba(0,0,0,0.45);
}
.brand-name { font-family:'JetBrains Mono',monospace; font-weight:800;
    font-size:0.88rem; color:#f5f5ff; letter-spacing:0.05em; line-height:1;
    white-space:nowrap; }
.brand-name span { color:#f97316; margin-left:5px; font-weight:600; }
.brand-tag { font-size:0.5rem; color:#5b5b80; letter-spacing:0.24em;
    margin-top:4px; font-family:'JetBrains Mono',monospace; white-space:nowrap; }

.bb-header {
    font-family: 'JetBrains Mono', monospace; font-size: 0.68rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.12em;
    color: #f97316; border-left: 3px solid #f97316;
    padding-left: 10px; margin: 1.4rem 0 0.8rem;
}
.bb-divider { border: none; border-top: 1px solid #1a1a2a; margin: 1.2rem 0; }

.conn-logo  { font-size: 2.5rem; display: block; text-align: center; margin-bottom: 0.5rem; }
.conn-title { font-size: 1.5rem; font-weight: 800; color: #f97316; text-align: center;
              font-family: 'JetBrains Mono', monospace; margin: 0 0 0.2rem; letter-spacing: 0.05em; }
.conn-sub   { font-size: 0.82rem; color: #606080; text-align: center; margin: 0 0 2rem; }
.step-card  { background: #0e0e1a; border: 1px solid #1e1e30; border-radius: 6px;
              padding: 1.1rem 1.3rem; margin-bottom: 0.9rem; }
.step-num   { display: inline-flex; align-items: center; justify-content: center;
              background: #f97316; color: #000; border-radius: 50%;
              width: 22px; height: 22px; font-size: 0.7rem; font-weight: 800;
              margin-right: 8px; flex-shrink: 0; }
.step-label { font-size: 0.82rem; color: #9090b0; }

.chain-wrap { overflow-x: auto; border: 1px solid #1a1a2a; border-radius: 4px; }
.chain {
    width: 100%; border-collapse: collapse;
    font-size: 0.75rem; font-family: 'JetBrains Mono', 'Courier New', monospace;
}
.chain thead th {
    background: #0d0d1a; color: #505070; font-size: 0.62rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.08em;
    padding: 7px 10px; text-align: right; white-space: nowrap;
    border-bottom: 1px solid #1a1a2a;
}
.chain thead th.lft { text-align: left; }
.chain thead th.ctr { text-align: center; }
.chain tbody td {
    padding: 4px 10px; text-align: right; color: #9090b0;
    border-bottom: 1px solid #111120; white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.chain tbody td.lft { text-align: left; }
.chain tbody td.ctr { text-align: center; }
.chain tbody tr:last-child td { border-bottom: none; }
.chain tbody tr:hover td { background: #111120 !important; }
.itm-c td { background: rgba(34,197,94,0.04) !important; }
.itm-p td { background: rgba(244,63,94,0.04) !important; }
.atm-row td { background: rgba(249,115,22,0.07) !important; border-top: 1px solid rgba(249,115,22,0.3) !important; border-bottom: 1px solid rgba(249,115,22,0.3) !important; }
.strike     { font-weight: 700; color: #d0d0e8; }
.atm-strike { color: #f97316 !important; font-weight: 800; }
.pos { color: #22c55e !important; }
.neg { color: #f43f5e !important; }
.neu { color: #6060a0; }
.hi  { color: #e0e0f8 !important; font-weight: 600; }
.call-hdr { background: rgba(34,197,94,0.08) !important; color: #22c55e !important; font-weight: 700 !important; }
.put-hdr  { background: rgba(244,63,94,0.08) !important; color: #f43f5e !important; font-weight: 700 !important; }
.mid-hdr  { background: #0d0d1a !important; color: #f97316 !important; font-weight: 800 !important; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 3px;
         font-size: 0.68rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
.badge-green  { background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); }
.badge-red    { background: rgba(244,63,94,0.15); color: #f43f5e; border: 1px solid rgba(244,63,94,0.3); }
.badge-orange { background: rgba(249,115,22,0.15); color: #f97316; border: 1px solid rgba(249,115,22,0.3); }
.badge-gray   { background: rgba(100,100,150,0.15); color: #8080a0; border: 1px solid rgba(100,100,150,0.3); }

.stat-row { display:flex; gap:24px; align-items:baseline; margin-bottom:0.5rem; }
.stat-label { font-size:0.65rem; color:#505070; text-transform:uppercase; letter-spacing:0.08em; font-family:'JetBrains Mono',monospace; }
.stat-val   { font-size:1.1rem; font-weight:700; color:#e0e0f8; font-family:'JetBrains Mono',monospace; margin-top:2px; }

.kpi-panel { background:#0e0e1a; border:1px solid #1e1e30; border-radius:6px;
             padding:0.9rem 1.4rem; display:flex; gap:2rem; align-items:center;
             flex-wrap:wrap; margin-bottom:0.8rem; }
.kpi-item { min-width:110px; }
.kpi-lbl  { font-size:0.58rem; color:#505070; font-family:'JetBrains Mono',monospace;
            text-transform:uppercase; letter-spacing:0.1em; margin-bottom:2px; }
.kpi-val  { font-size:1.05rem; font-weight:800; font-family:'JetBrains Mono',monospace; color:#e0e0f0; }
.kpi-sub  { font-size:0.6rem; color:#505070; font-family:'JetBrains Mono',monospace; }

.decision-card {
    background: linear-gradient(135deg, #0e0e1a 0%, #12121e 100%);
    border: 1px solid #2a2a3e; border-radius: 6px;
    padding: 1rem 1.3rem; margin: 0.8rem 0;
}
.decision-title {
    font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
    font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase;
    margin-bottom: 0.6rem;
}
.decision-body {
    font-size: 0.82rem; color: #c0c0d8; line-height: 1.6;
    font-family: 'Inter', -apple-system, sans-serif;
}
.decision-body b { color: #e8e8f8; }
.decision-body code { background: #1a1a2a; color: #f97316; padding: 1px 6px;
                      border-radius: 3px; font-family: 'JetBrains Mono', monospace;
                      font-size: 0.78rem; }

.footer { text-align:center; font-size:0.65rem; color:#2a2a3a; margin-top:2rem;
          font-family:'JetBrains Mono',monospace; }

/* ─── Market header (terminal top strip) ───────────────────────────────── */
@keyframes mh-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.4; transform: scale(0.78); }
}
.mh-dot { display:inline-block; width:8px; height:8px; border-radius:50%;
          margin-right:7px; vertical-align:middle; }
.mh-dot.live { background:#22c55e; box-shadow:0 0 9px #22c55e;
               animation:mh-pulse 1.8s ease-in-out infinite; }
.mh-dot.idle { background:#f59e0b; box-shadow:0 0 7px rgba(245,158,11,0.6); }
.mh-dot.off  { background:#6b6b8a; }
.mh-cell:hover { background:rgba(255,255,255,0.018); }

/* Toggle accent → brand orange (best-effort across Streamlit versions) */
[data-testid="stToggle"] [role="switch"][aria-checked="true"],
[data-baseweb="checkbox"] [aria-checked="true"] > div:first-child {
    background-color: #f97316 !important;
}

/* ─── Anti-flicker on auto-refresh ───────────────────────────────────────
 * When st_autorefresh fires every 30s, Streamlit shows a "RUNNING…" pill
 * and re-paints status overlays. That visible flash is what you perceive
 * as the chart blinking. We hide it.
 *
 * Plotly's <iframe> components with stable keys do an in-place data diff
 * (no remount), so the chart itself updates smoothly underneath. */

[data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stHeader"] { background: transparent !important; }
.stDeployButton { display: none !important; }

/* Suppress the brief opacity flicker while Streamlit re-renders the DOM:
 * keep the chart container fully visible at all times. */
.stPlotlyChart, [data-testid="stPlotlyChart"] {
    transition: none !important;
    opacity: 1 !important;
}

/* When the script reruns, Streamlit briefly ghosts already-rendered
 * components. The selector below keeps them at full opacity throughout. */
[data-stale="true"] { opacity: 1 !important; }

/* Smooth spinner fade so any remaining loading indicator is less jarring */
[data-testid="stSpinner"] {
    transition: opacity 0.2s ease-in-out;
}
</style>
"""
