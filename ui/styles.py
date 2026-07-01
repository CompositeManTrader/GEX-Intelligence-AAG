"""Bloomberg-dark CSS block. Separated to keep app.py clean."""

CSS = """
<style>
/* Load the REAL brand fonts — without this import the whole app silently
 * falls back to the OS generic monospace (Courier-ish), which is why the
 * terminal aesthetic looked inconsistent across machines. */
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap');

html, body, [data-testid="stApp"], .main, .block-container {
    background-color: #0A0B0D !important;
    color: #c8c8d8 !important;
    font-family: 'Inter', system-ui, sans-serif !important;
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
    border-color: #F5A623 !important; color: #F5A623 !important;
    background: rgba(245,166,35,0.08) !important;
}
button[kind="primary"] {
    background: #F5A623 !important; border-color: #F5A623 !important;
    color: #000 !important; font-weight: 700 !important;
}
button[kind="primary"]:hover { background: #F5A623 !important; color: #000 !important; }
[data-testid="stLinkButton"] a {
    background: rgba(245,166,35,0.12) !important; border: 1px solid #F5A623 !important;
    color: #F5A623 !important; border-radius: 4px !important;
    padding: 8px 18px !important; font-size: 0.82rem !important;
    text-decoration: none !important; display: block !important; text-align: center !important;
}

[data-testid="stMetric"] {
    background: rgba(255,255,255,0.028) !important;
    backdrop-filter: blur(10px) saturate(130%) !important;
    -webkit-backdrop-filter: blur(10px) saturate(130%) !important;
    border: 1px solid rgba(255,255,255,0.075) !important;
    border-radius: 11px !important; padding: 10px 14px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06) !important;
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

/* ─── Tabs — terminal nav with a sliding orange underline ──────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border: none !important; border-radius: 0 !important;
    gap: 1px !important; padding: 0 0 1px !important;
    scrollbar-width: thin; scrollbar-color: #24243a transparent;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { height: 5px; }
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar-thumb {
    background: #24243a; border-radius: 3px;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar-thumb:hover { background: #34344e; }
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar-track { background: transparent; }
.stTabs [data-baseweb="tab"] {
    background: transparent !important; border-radius: 4px 4px 0 0 !important;
    padding: 7px 13px !important; margin: 0 !important;
    color: #57577a !important; font-size: 0.73rem !important;
    font-weight: 600 !important; font-family: 'JetBrains Mono', monospace !important;
    letter-spacing: 0.03em; white-space: nowrap;
    transition: color .15s, background .15s;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #b4b4d6 !important; background: rgba(245,166,35,0.05) !important;
}
.stTabs [aria-selected="true"] {
    background: rgba(245,166,35,0.06) !important; color: #F5A623 !important;
    text-shadow: 0 0 12px rgba(245,166,35,0.25);
}
/* baseweb's own underline track + sliding highlight → themed */
.stTabs [data-baseweb="tab-border"] { background-color: #18182a !important; }
.stTabs [data-baseweb="tab-highlight"] {
    background-color: #F5A623 !important; height: 2px !important;
    box-shadow: 0 0 8px rgba(245,166,35,0.5);
}

.stCaption p, [data-testid="stCaptionContainer"] p { color: #505070 !important; font-size: 0.72rem !important; }
p, .stMarkdown p { color: #a0a0c0 !important; }
h1, h2, h3 { color: #e0e0f0 !important;
    font-family: 'Space Grotesk', system-ui, sans-serif !important; font-weight: 700 !important; }

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
[data-testid="stExpander"] summary:hover { color: #F5A623 !important; }
[data-testid="stExpander"] summary svg { fill: #F5A623 !important; }

/* Brand mark — terminal prompt lockup ( ❯ GEX ▮ ) */
@keyframes brand-blink { 50% { opacity: 0; } }
.brand { display:flex; flex-direction:column; justify-content:center; padding-top:1px; }
.brand-line { display:flex; align-items:center; gap:8px; }
.brand-prompt { color:#F5A623; font-family:'JetBrains Mono',monospace;
    font-size:1.35rem; font-weight:800; line-height:1; }
.brand-word { color:#F4F5F6; font-family:'Space Grotesk',system-ui,sans-serif;
    font-size:1.32rem; font-weight:700; letter-spacing:0.04em; line-height:1; }
.brand-cursor { display:inline-block; width:10px; height:1.12rem; background:#F5A623;
    box-shadow:0 0 8px rgba(245,166,35,0.5);
    animation:brand-blink 1.1s steps(1) infinite; }
.brand-tag { font-family:'JetBrains Mono',monospace; font-size:0.52rem; color:#9AA1A9;
    letter-spacing:0.26em; margin-top:5px; white-space:nowrap; }

.bb-header {
    font-family: 'JetBrains Mono', monospace; font-size: 0.68rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.12em;
    color: #F5A623; border-left: 3px solid #F5A623;
    padding-left: 10px; margin: 1.4rem 0 0.8rem;
}
.bb-divider { border: none; border-top: 1px solid #1a1a2a; margin: 1.2rem 0; }

.conn-sub   { font-size: 0.82rem; color: #606080; text-align: center; margin: 0 0 1.6rem;
              font-family: 'Inter', sans-serif; }
.step-num   { display: inline-flex; align-items: center; justify-content: center;
              background: #F5A623; color: #000; border-radius: 50%;
              width: 22px; height: 22px; font-size: 0.7rem; font-weight: 800;
              margin-right: 8px; flex-shrink: 0; }
.step-label { font-size: 0.8rem; color: #9595b8; font-family: 'JetBrains Mono', monospace;
              letter-spacing: 0.04em; }

/* Bordered st.container(border=True) → terminal card (the old trick of
 * wrapping widgets in a raw <div class="step-card"> via markdown does NOT
 * work — Streamlit auto-closes the div, leaving an empty ghost box). */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: linear-gradient(135deg,#0b0b15,#0d0d18) !important;
    border: 1px solid #1e1e32 !important; border-radius: 9px !important;
    padding: 0.35rem 0.4rem !important;
}

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
.itm-c td { background: rgba(22,199,132,0.04) !important; }
.itm-p td { background: rgba(234,57,67,0.04) !important; }
.atm-row td { background: rgba(245,166,35,0.07) !important; border-top: 1px solid rgba(245,166,35,0.3) !important; border-bottom: 1px solid rgba(245,166,35,0.3) !important; }
.strike     { font-weight: 700; color: #d0d0e8; }
.atm-strike { color: #F5A623 !important; font-weight: 800; }
.pos { color: #16C784 !important; }
.neg { color: #EA3943 !important; }
.neu { color: #6060a0; }
.hi  { color: #e0e0f8 !important; font-weight: 600; }
.call-hdr { background: rgba(22,199,132,0.08) !important; color: #16C784 !important; font-weight: 700 !important; }
.put-hdr  { background: rgba(234,57,67,0.08) !important; color: #EA3943 !important; font-weight: 700 !important; }
.mid-hdr  { background: #0d0d1a !important; color: #F5A623 !important; font-weight: 800 !important; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 3px;
         font-size: 0.68rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
.badge-green  { background: rgba(22,199,132,0.15); color: #16C784; border: 1px solid rgba(22,199,132,0.3); }
.badge-red    { background: rgba(234,57,67,0.15); color: #EA3943; border: 1px solid rgba(234,57,67,0.3); }
.badge-orange { background: rgba(245,166,35,0.15); color: #F5A623; border: 1px solid rgba(245,166,35,0.3); }
.badge-gray   { background: rgba(100,100,150,0.15); color: #8080a0; border: 1px solid rgba(100,100,150,0.3); }

.stat-row { display:flex; gap:24px; align-items:baseline; margin-bottom:0.5rem; }
.stat-label { font-size:0.65rem; color:#505070; text-transform:uppercase; letter-spacing:0.08em; font-family:'JetBrains Mono',monospace; }
.stat-val   { font-size:1.1rem; font-weight:700; color:#e0e0f8; font-family:'JetBrains Mono',monospace; margin-top:2px; }

.kpi-panel { background:rgba(255,255,255,0.028); border:1px solid rgba(255,255,255,0.075);
             backdrop-filter:blur(11px) saturate(130%);
             -webkit-backdrop-filter:blur(11px) saturate(130%);
             border-radius:12px;
             box-shadow:inset 0 1px 0 rgba(255,255,255,0.06);
             padding:0.9rem 1.4rem; display:flex; gap:2rem; align-items:center;
             flex-wrap:wrap; margin-bottom:0.8rem; }
.kpi-item { min-width:110px; }
.kpi-lbl  { font-size:0.58rem; color:#505070; font-family:'JetBrains Mono',monospace;
            text-transform:uppercase; letter-spacing:0.1em; margin-bottom:2px; }
.kpi-val  { font-size:1.05rem; font-weight:800; font-family:'JetBrains Mono',monospace; color:#e0e0f0; }
.kpi-sub  { font-size:0.6rem; color:#505070; font-family:'JetBrains Mono',monospace; }

.decision-card {
    background: rgba(255,255,255,0.032) !important;
    backdrop-filter: blur(13px) saturate(135%);
    -webkit-backdrop-filter: blur(13px) saturate(135%);
    border: 1px solid rgba(255,255,255,0.085); border-radius: 13px;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.07),
                0 8px 26px rgba(0,0,0,0.28);
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
.decision-body code { background: #1a1a2a; color: #F5A623; padding: 1px 6px;
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
.mh-dot.live { background:#16C784; box-shadow:0 0 9px #16C784;
               animation:mh-pulse 1.8s ease-in-out infinite; }
.mh-dot.idle { background:#F5A623; box-shadow:0 0 7px rgba(245,166,35,0.6); }
.mh-dot.off  { background:#6b6b8a; }
.mh-cell:hover { background:rgba(255,255,255,0.018); }

/* Toggle accent → brand orange (best-effort across Streamlit versions) */
[data-testid="stToggle"] [role="switch"][aria-checked="true"],
[data-baseweb="checkbox"] [aria-checked="true"] > div:first-child {
    background-color: #F5A623 !important;
}

/* ─── Toolbar / command-bar polish ─────────────────────────────────────── */
[data-testid="stTextInput"] input {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.92rem !important; font-weight: 600 !important;
    letter-spacing: 0.05em; padding: 0.6rem 0.85rem !important;
    background: linear-gradient(135deg,#101019,#13131f) !important;
    transition: border-color .15s, box-shadow .15s;
}
[data-testid="stTextInput"] input::placeholder {
    color: #45456a !important; font-weight: 400 !important; letter-spacing: 0;
}
[data-testid="stTextInput"] input:focus {
    border-color: #F5A623 !important;
    box-shadow: 0 0 0 1px rgba(245,166,35,0.4),
                0 0 14px rgba(245,166,35,0.14) !important;
}
[data-baseweb="select"] > div {
    background: #101019 !important; border-color: #24243a !important;
    font-family: 'JetBrains Mono', monospace !important; font-size: 0.8rem !important;
    border-radius: 5px !important; transition: border-color .15s, box-shadow .15s;
}
[data-baseweb="select"]:focus-within > div {
    border-color: #F5A623 !important;
    box-shadow: 0 0 0 1px rgba(245,166,35,0.35) !important;
}
[data-testid="stButton"] button {
    padding: 0.5rem 0.55rem !important; font-size: 0.7rem !important;
    letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600 !important;
    background: linear-gradient(135deg,#101019,#13131f) !important;
}
/* Widget labels (toggles, sliders, selects) → finer mono */
[data-testid="stWidgetLabel"] p, [data-testid="stToggle"] label p {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.7rem !important; color: #8585a8 !important;
    letter-spacing: 0.04em;
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
 * keep the chart container fully visible at all times. Plus a glassmorphism
 * frame so every chart reads as a frosted card (Bloomberg + cristal). */
.stPlotlyChart, [data-testid="stPlotlyChart"] {
    transition: none !important;
    opacity: 1 !important;
    background: rgba(255,255,255,0.022) !important;
    backdrop-filter: blur(9px) saturate(125%) !important;
    -webkit-backdrop-filter: blur(9px) saturate(125%) !important;
    border: 1px solid rgba(255,255,255,0.065) !important;
    border-radius: 14px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 8px 30px rgba(0,0,0,0.28) !important;
    padding: 8px 10px 4px !important;
    margin: 4px 0 12px !important;
}

/* ── Sophisticated segmented controls (st.radio horizontal → glass pills) ── */
div[role="radiogroup"] { gap: 6px !important; flex-wrap: wrap !important; }
div[role="radiogroup"] > label {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 9px !important;
    padding: 4px 13px !important;
    margin: 0 !important;
    transition: background .18s ease, border-color .18s ease !important;
    cursor: pointer !important;
}
div[role="radiogroup"] > label:hover {
    background: rgba(245,166,35,0.10) !important;
    border-color: rgba(245,166,35,0.40) !important;
}
div[role="radiogroup"] > label:has(input:checked) {
    background: rgba(245,166,35,0.16) !important;
    border-color: #F5A623 !important;
}
/* hide the default radio dot for a clean segmented look */
div[role="radiogroup"] > label > div:first-child { display: none !important; }
div[role="radiogroup"] > label div { color: #c8c8e0 !important; font-size: 0.72rem !important; }

/* ── Sliders — refined orange thumb on a slim track ── */
[data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"] {
    background: #F5A623 !important;
    box-shadow: 0 0 0 4px rgba(245,166,35,0.18) !important;
}

/* ── Expanders → glass (upgrade the existing dark gradient) ── */
[data-testid="stExpander"] {
    background: rgba(255,255,255,0.022) !important;
    backdrop-filter: blur(10px) saturate(125%) !important;
    -webkit-backdrop-filter: blur(10px) saturate(125%) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 12px !important;
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
