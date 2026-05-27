"""
Schwab data layer.

- Shared `requests.Session` with urllib3 retry/backoff (TCP reuse).
- Streamlit cache_data wrappers with short TTL so the dashboard doesn't spam.
- All functions return `(result, error_str)` so the UI can decide what to show.
"""
from __future__ import annotations

import datetime
from typing import Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from auth.schwab import refresh_access_token
from config import (
    CDMX_TZ,
    ET_TZ,
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
        # Respect Schwab's `Retry-After` header when present — it
        # overrides the computed backoff. Default in urllib3 ≥1.26 is
        # True but make it explicit so a downgrade doesn't silently
        # regress the rate-limit behavior.
        respect_retry_after_header=True,
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
_QUOTE_KEYS = (
    "last", "bid", "ask", "mark", "open", "high", "low", "close_prev",
    "volume", "net_change", "pct_change", "quote_time_ms", "trade_time_ms",
    "description",
)


def _empty_quote() -> dict:
    """All-None dict with the contract shape of `fetch_quote`. Returning
    a fully-populated dict on the error path (instead of `{}`) means
    callers can do `quote["last"]` / `quote.get("last")` uniformly
    without checking `err` first AND existence of the key. Several
    panels in `ui/` had been making both checks defensively; this
    contract is simpler and harder to misuse.
    """
    return {k: None for k in _QUOTE_KEYS}


@st.cache_data(ttl=8, show_spinner=False)
def fetch_quote(symbol: str) -> Tuple[dict, str]:
    try:
        r = _api_get("/marketdata/v1/quotes", params={"symbols": symbol})
    except Exception as exc:
        log.exception("fetch_quote network error")
        return _empty_quote(), str(exc)
    if r.status_code != 200:
        return _empty_quote(), f"HTTP {r.status_code}"
    try:
        data = r.json().get(symbol, {})
    except Exception as exc:
        return _empty_quote(), f"parse: {exc}"
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
#  Intraday — cached 5s, invalidated per minute via cache_bust arg.
#
#  Robustness fixes vs the legacy version:
#    (1) Use **explicit `startDate` + `endDate`** (epoch-ms) instead of
#        `period`+`periodType=day`. Schwab's `period=N` semantics return
#        "the last N COMPLETED trading sessions" — meaning during a live
#        session it stops at yesterday's 16:00 close and DOES NOT include
#        today's partial bars. Pinning `endDate` to *now* forces today's
#        in-progress session into the response.
#    (2) Group/filter by **Eastern Time** (the market's clock) — not Mexico
#        City — so "today" matches the current US trading session even when
#        the user is in a different timezone.
#    (3) Accept a `cache_bust` kwarg from the caller (a value that rotates
#        every N seconds, e.g. `int(time.time() // 30)`). Different value =
#        different cache key, guaranteeing a real refresh on each tick even
#        if Streamlit's TTL eviction is sluggish.
# ─────────────────────────────────────────────────────────────────────────────
# Note on cache config:
#   · NO ttl. The legacy `ttl=5` invalidated the cache every 5s, which
#     fought with the `cache_bust` arg the caller already rotates every
#     `intra_auto` seconds (typically 20). Two mechanisms racing made
#     fetches happen at the wrong cadence — sometimes every 5s (TTL
#     win), wasting Schwab API calls; sometimes the cached row was
#     stale because the bust hadn't ticked yet. Letting `cache_bust`
#     be the SOLE invalidation key is simpler and correct.
#   · max_entries=3 caps the cache at 3 distinct (symbol, freq, days,
#     include_extended, cache_bust) combinations. Without this, every
#     bust value adds an entry indefinitely (~180/hour) — the memory
#     creep that contributed to the Streamlit Cloud OOM suspension.
@st.cache_data(show_spinner=False, max_entries=3)
def fetch_intraday(symbol: str, freq_min: int = 1,
                   days: int = 1,
                   include_extended: bool = False,
                   cache_bust: int = 0) -> Tuple[pd.DataFrame, str]:
    """Fetch intraday OHLCV bars from Schwab.

    Parameters
    ----------
    symbol : str
        Ticker (already resolved if originally a futures root).
    freq_min : int
        Bar resolution in minutes (1, 5, 15, 30).
    days : int
        How many trading days of history to keep (filtered ET-day-wise).
    include_extended : bool
        If True, request pre-market + after-hours bars.
    cache_bust : int
        Rotating integer used purely to vary the cache key. Pass
        `int(time.time() // N)` to force a fresh fetch every N seconds.
    """
    _ = cache_bust  # noqa: F841 — only used to vary the cache key
    try:
        # Explicit window: from N+2 calendar days ago (covers weekends +
        # holidays) up to RIGHT NOW. endDate must include today or Schwab
        # truncates at the previous session's 16:00.
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        end_ms = int(now_utc.timestamp() * 1000)
        # +3 days padding handles weekends so days=1 still lands on the
        # previous session even after Friday → Monday.
        lookback_days = max(int(days), 1) + 3
        start_dt = now_utc - datetime.timedelta(days=lookback_days)
        start_ms = int(start_dt.timestamp() * 1000)

        r = _api_get("/marketdata/v1/pricehistory", params={
            "symbol": symbol,
            "periodType": "day",
            "frequencyType": "minute",
            "frequency": str(int(freq_min)),
            "startDate": str(start_ms),
            "endDate": str(end_ms),
            "needExtendedHoursData": "true" if include_extended else "false",
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
        # Group by ET trading day so the chart aligns with the US session.
        df["_d"] = df["date"].dt.tz_convert(ET_TZ).dt.date
        all_days = sorted(df["_d"].unique())
        keep = set(all_days[-max(1, int(days)):])
        df = df[df["_d"].isin(keep)].drop(columns=["_d"]).reset_index(drop=True)
        log.info(
            "intraday %s freq=%dm days_kept=%s last_bar=%s rows=%d",
            symbol, freq_min, sorted(keep),
            df["date"].iloc[-1].isoformat() if not df.empty else "—",
            len(df),
        )
        return df, ""
    except Exception as exc:
        log.exception("intraday error")
        return pd.DataFrame(), str(exc)
