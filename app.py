"""
OPTIONS TERMINAL  —  Professional Gamma Exposure Dashboard
Charles Schwab API · Real-time GEX / VEX / CEX / DEX · Dealer Flow Analytics

Slim entry point. Real code lives in:
  auth/          — Schwab OAuth
  config.py      — constants, timezone, session keys
  data/          — HTTP fetch + Schwab chain parsing
  quant/         — Black-Scholes, exposures, levels, vol analytics
  charts/        — Plotly profiles + lightweight-charts intraday
  ui/            — CSS, decision panel, chain table, render modules
  tests/         — pytest suite
"""
from __future__ import annotations

import warnings

import streamlit as st

from ui.render import run

warnings.filterwarnings("ignore")


st.set_page_config(
    page_title="Options Terminal",
    page_icon="▤",
    layout="wide",
    initial_sidebar_state="collapsed",
)


run()
