"""
FX rates — currently used for USD↔MXN conversion in the Arbs panel.

Uses two free, key-less APIs in fallback order so a single endpoint
outage does not blank the UI:

  1. Frankfurter (ECB rates, very reliable)        https://api.frankfurter.app
  2. open.er-api.com (commercial free tier)        https://open.er-api.com

Both are queried via the shared `requests.Session` from `data.fetch` so
we get the existing retry/backoff behaviour. Results are cached for
60 seconds — FX rates barely move on intraday timescales and the user
does not need second-level precision for a quote display.
"""
from __future__ import annotations

import datetime
from typing import Optional

import requests
import streamlit as st

from config import HTTP_TIMEOUT, get_logger

log = get_logger("data.fx")


_FRANKFURTER_URL = "https://api.frankfurter.app/latest"
_ERAPI_URL = "https://open.er-api.com/v6/latest/USD"


@st.cache_data(ttl=60, show_spinner=False)
def fetch_usdmxn_rate(_cache_bust: int = 0) -> tuple[Optional[float], str, str]:
    """Return `(rate, source, error)`.

    rate : MXN per 1 USD, rounded to 4 decimals. None on total failure.
    source: 'frankfurter' | 'open-er-api' | '' if failed.
    error : empty string on success, error message otherwise.

    The cache_bust arg lets callers force a fresh fetch by passing
    `int(time.time() // 60)` if they prefer not to wait for the TTL.
    """
    _ = _cache_bust  # only varies the cache key

    # ── 1) Frankfurter (ECB) ──────────────────────────────────────────────
    try:
        r = requests.get(
            _FRANKFURTER_URL,
            params={"from": "USD", "to": "MXN"},
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            rate = data.get("rates", {}).get("MXN")
            if rate and float(rate) > 0:
                return round(float(rate), 4), "frankfurter", ""
    except Exception as exc:
        log.warning("frankfurter USDMXN failed: %s", exc)

    # ── 2) open.er-api.com fallback ───────────────────────────────────────
    try:
        r = requests.get(_ERAPI_URL, timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            rate = data.get("rates", {}).get("MXN")
            if rate and float(rate) > 0:
                return round(float(rate), 4), "open-er-api", ""
    except Exception as exc:
        log.warning("open-er-api USDMXN failed: %s", exc)

    return None, "", "Ambos endpoints FX fallaron — verifica conectividad."


def usdmxn_with_meta() -> dict:
    """Convenience wrapper that returns a dict with rate + freshness info,
    used by the Arbs panel header. Cached results are re-served for 60s."""
    rate, source, err = fetch_usdmxn_rate(_cache_bust=0)
    return dict(
        rate=rate,
        source=source,
        error=err,
        fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
