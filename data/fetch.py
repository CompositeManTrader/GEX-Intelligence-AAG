"""
Schwab data layer.

- Shared `requests.Session` with urllib3 retry/backoff (TCP reuse).
- Streamlit cache_data wrappers with short TTL so the dashboard doesn't spam.
- All functions return `(result, error_str)` so the UI can decide what to show.
"""
from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from auth.schwab import refresh_access_token
from config import (
    CDMX_TZ,
    HTTP_BACKOFF,
    HTTP_RETRIES,
    HTTP_TIMEOUT,
    SCHWAB_BASE_URL,
    SS,
    get_logger,
)

log = get_logger("data.fetch")


# ─────────────────────────────────────────────────────────────────────────────
def _build_session() -> requests.Session:
    retry = Retry(
        total=HTTP_RETRIES,
        connect=HTTP_RETRIES,
        read=HTTP_RETRIES,
        backoff_factor=HTTP_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    s = requests.Session()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


@st.cache_resource
def _session() -> requests.Session:
    return _build_session()


def _api_get(path: str, params: Optional[dict] = None) -> requests.Response:
    refresh_access_token()
    tok = st.session_state.get(SS.TOKENS, {})
    if not tok:
        st.error("Sin tokens. Reconéctate.")
        st.stop()
    url = f"{SCHWAB_BASE_URL}{path}"
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    return _session().get(
        url,
        headers={"Authorization": f"Bearer {tok['access_token']}"},
        params=clean,
        timeout=HTTP_TIMEOUT,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Options chain — cached 30s
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def fetch_chain(symbol: str, strike_count: int,
                from_date: str, to_date: str) -> Tuple[Optional[dict], str]:
    try:
        r = _api_get("/marketdata/v1/chains", params={
            "symbol": symbol, "contractType": "ALL",
            "strikeCount": strike_count, "includeUnderlyingQuote": "true",
            "fromDate": from_date, "toDate": to_date,
        })
    except Exception as exc:
        log.exception("fetch_chain network error")
        return None, str(exc)
    if r.status_code != 200:
        log.error("fetch_chain %s status=%s body=%s", symbol, r.status_code, r.text[:200])
        return None, f"HTTP {r.status_code}: {r.text[:300]}"
    return r.json(), ""


# ─────────────────────────────────────────────────────────────────────────────
#  Daily price history — cached 1h
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_price_history(symbol: str, period: int = 1,
                        period_type: str = "year"
                        ) -> Tuple[pd.DataFrame, str]:
    try:
        r = _api_get("/marketdata/v1/pricehistory", params={
            "symbol": symbol, "periodType": period_type, "period": period,
            "frequencyType": "daily", "frequency": 1,
            "needExtendedHoursData": "false",
        })
        if r.status_code != 200:
            log.error("price_history %s status=%s", symbol, r.status_code)
            return pd.DataFrame(), f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        if data.get("empty", False):
            return pd.DataFrame(), f"Símbolo '{symbol}' no encontrado."
        candles = data.get("candles", [])
        if not candles:
            return pd.DataFrame(), "Sin velas en respuesta."
        df = pd.DataFrame(candles)
        df["date"] = pd.to_datetime(df["datetime"], unit="ms")
        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        return df.sort_values("date").reset_index(drop=True), ""
    except Exception as exc:
        log.exception("price_history error")
        return pd.DataFrame(), str(exc)


# ─────────────────────────────────────────────────────────────────────────────
#  Live quote — cached 8s (for real-time spot ticker in UI/chart)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=8, show_spinner=False)
def fetch_quote(symbol: str) -> Tuple[dict, str]:
    try:
        r = _api_get("/marketdata/v1/quotes", params={"symbols": symbol})
    except Exception as exc:
        log.exception("fetch_quote network error")
        return {}, str(exc)
    if r.status_code != 200:
        return {}, f"HTTP {r.status_code}"
    try:
        data = r.json().get(symbol, {})
    except Exception as exc:
        return {}, f"parse: {exc}"
    quote = data.get("quote", {}) or {}
    ref = data.get("reference", {}) or {}
    return {
        "last": quote.get("lastPrice") or quote.get("mark"),
        "bid":  quote.get("bidPrice"),
        "ask":  quote.get("askPrice"),
        "mark": quote.get("mark"),
        "open": quote.get("openPrice"),
        "high": quote.get("highPrice"),
        "low":  quote.get("lowPrice"),
        "close_prev": quote.get("closePrice"),
        "volume": quote.get("totalVolume"),
        "net_change": quote.get("netChange"),
        "pct_change": quote.get("netPercentChange"),
        "quote_time_ms": quote.get("quoteTime"),
        "trade_time_ms": quote.get("tradeTime"),
        "description": ref.get("description"),
    }, ""


# ─────────────────────────────────────────────────────────────────────────────
#  Intraday — cached 8s (agresivo: el auto-refresh de la tab es de 10-20s,
#  así que con ttl=8 garantizamos que cada tick de refresh re-pega a Schwab).
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=8, show_spinner=False)
def fetch_intraday(symbol: str, freq_min: int = 1,
                   days: int = 1) -> Tuple[pd.DataFrame, str]:
    try:
        r = _api_get("/marketdata/v1/pricehistory", params={
            "symbol": symbol,
            "periodType": "day",
            "period": str(min(max(int(days), 1), 10)),
            "frequencyType": "minute",
            "frequency": str(int(freq_min)),
            "needExtendedHoursData": "false",
        })
        if r.status_code != 200:
            try:
                err_detail = r.json()
            except Exception:
                err_detail = r.text[:300]
            log.error("intraday %s status=%s", symbol, r.status_code)
            return pd.DataFrame(), f"HTTP {r.status_code}: {err_detail}"
        data = r.json()
        if data.get("empty", False):
            return pd.DataFrame(), f"Sin datos intraday para '{symbol}'."
        candles = data.get("candles", [])
        if not candles:
            return pd.DataFrame(), "La API devolvió 0 velas. Mercado cerrado o sin datos."
        df = pd.DataFrame(candles)
        df["date"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        df = df.sort_values("date").reset_index(drop=True)
        df["_d"] = df["date"].dt.tz_convert(CDMX_TZ).dt.date
        all_days = sorted(df["_d"].unique())
        keep = set(all_days[-max(1, days):])
        df = df[df["_d"].isin(keep)].drop(columns=["_d"]).reset_index(drop=True)
        return df, ""
    except Exception as exc:
        log.exception("intraday error")
        return pd.DataFrame(), str(exc)
