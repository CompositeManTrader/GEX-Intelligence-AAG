"""
Central configuration: constants, session keys, timezone helpers.
No side effects on import.
"""
from __future__ import annotations

import datetime
import logging
import re
from datetime import timezone
from typing import NamedTuple, Optional

import pytz

# ── Timezones ──────────────────────────────────────────────────────────────
CDMX_TZ = pytz.timezone("America/Mexico_City")
ET_TZ = pytz.timezone("America/New_York")
UTC = timezone.utc


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(UTC)


def safe_pct(numerator: Optional[float], denominator: Optional[float]
             ) -> Optional[float]:
    """Return `numerator / denominator * 100` guarded against zero/None.

    Returns None if either operand is None, NaN, or denominator ≤ 0.
    Used wherever we render a "X% vs spot"-style display — spot can be
    transiently 0 if the live-quote fetcher returned an empty body and
    the fallback chain decayed to `close=0`. The legacy code would then
    raise ZeroDivisionError and blank an entire panel.
    """
    if numerator is None or denominator is None:
        return None
    try:
        n = float(numerator)
        d = float(denominator)
    except (TypeError, ValueError):
        return None
    # NaN propagates as itself in float() — guard explicitly.
    if n != n or d != d or d <= 0:
        return None
    return n / d * 100.0


def market_status_et() -> tuple[str, datetime.datetime]:
    """Return ('OPEN'|'PRE'|'POST'|'CLOSED', now_et)."""
    now_et = datetime.datetime.now(ET_TZ)
    if now_et.weekday() >= 5:
        return "CLOSED", now_et
    t = now_et.time()
    if datetime.time(9, 30) <= t < datetime.time(16, 0):
        return "OPEN", now_et
    if datetime.time(4, 0) <= t < datetime.time(9, 30):
        return "PRE", now_et
    if datetime.time(16, 0) <= t < datetime.time(20, 0):
        return "POST", now_et
    return "CLOSED", now_et


# ── Logging ────────────────────────────────────────────────────────────────
def get_logger(name: str = "options_terminal") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


# ── Schwab API ─────────────────────────────────────────────────────────────
SCHWAB_AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
SCHWAB_BASE_URL = "https://api.schwabapi.com"

HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
# Backoff factor for `urllib3.Retry`. Total wait between attempts grows
# as `backoff_factor * (2 ** attempt)`. With factor=0.4 the waits are
# 0.4 + 0.8 + 1.6 = 2.8 s total — way under Schwab's typical
# Retry-After (which urllib3 already respects when present). On a real
# 429 burst that aggressive pattern hammers the API and prolongs the
# ban. 1.0 gives 1 + 2 + 4 = 7 s, a saner cadence; Retry-After header
# (when sent) still takes precedence over the computed backoff.
HTTP_BACKOFF = 1.0

TOKEN_REFRESH_MARGIN_S = 60

# ── Quant defaults ─────────────────────────────────────────────────────────
DEFAULT_RF_RATE = 0.045
DEFAULT_DIV_YIELD_INDEX = 0.013     # SPY proxy; used if no per-symbol override
MIN_IV_PCT = 1.0                    # IV% below this is treated as stale/zero
TRADING_DAYS = 252
CALENDAR_DAYS = 365
MARKET_CLOSE_ET = datetime.time(16, 0)

# Per-symbol dividend yields (extend as needed). Key: uppercase symbol.
DIVIDEND_YIELDS: dict[str, float] = {
    "SPY": 0.013,
    "SPX": 0.015,
    "QQQ": 0.006,
    "IWM": 0.013,
    "DIA": 0.017,
}


def dividend_yield_for(symbol: str) -> float:
    if not symbol:
        return 0.0
    return DIVIDEND_YIELDS.get(symbol.upper(), 0.0)


# ── Rate curve (tenor → annualized rate). Interpolated by DTE. ──────────
# Defaults approximate a flat-ish curve; override via st.secrets if needed.
RATE_CURVE_DEFAULT: dict[int, float] = {
    7:   0.0460,
    30:  0.0455,
    60:  0.0450,
    90:  0.0445,
    180: 0.0440,
    365: 0.0430,
}


# ── Futures contracts ──────────────────────────────────────────────────────
# Map a futures root → underlying chain to fetch from Schwab + contract specs.
# We default to the ETF proxy (proven working with this codebase). Toggle to
# the cash index (SPX/NDX/RUT/DJX) only if your Schwab account has index quotes.
class FutureSpec(NamedTuple):
    root: str          # "ES"
    name: str          # "E-mini S&P 500"
    underlying: str    # cash index ("SPX")
    etf_proxy: str     # ETF used as chain proxy ("SPY")
    point_value: float # $ P&L per 1 index point
    tick_size: float   # min increment in index points
    tick_value: float  # $ per tick (= point_value * tick_size)
    etf_ratio: float   # (future / etf) ratio in points — used to convert
                       # ETF strikes to "future points" approximations.
                       # Set to 1.0 if proxy = index (SPX/NDX/RUT/DJX).


FUTURES_SPECS: dict[str, FutureSpec] = {
    # Equity index futures
    "ES":  FutureSpec("ES",  "E-mini S&P 500",       "SPX", "SPY", 50.0, 0.25, 12.50, 10.0),
    "MES": FutureSpec("MES", "Micro E-mini S&P 500", "SPX", "SPY",  5.0, 0.25,  1.25, 10.0),
    "NQ":  FutureSpec("NQ",  "E-mini Nasdaq-100",    "NDX", "QQQ", 20.0, 0.25,  5.00, 41.0),
    "MNQ": FutureSpec("MNQ", "Micro E-mini Nasdaq",  "NDX", "QQQ",  2.0, 0.25,  0.50, 41.0),
    "RTY": FutureSpec("RTY", "E-mini Russell 2000",  "RUT", "IWM", 50.0, 0.10,  5.00, 10.0),
    "M2K": FutureSpec("M2K", "Micro E-mini R2K",     "RUT", "IWM",  5.0, 0.10,  0.50, 10.0),
    "YM":  FutureSpec("YM",  "E-mini Dow",           "DJX", "DIA",  5.0, 1.00,  5.00, 100.0),
    "MYM": FutureSpec("MYM", "Micro E-mini Dow",     "DJX", "DIA",  0.50, 1.00, 0.50, 100.0),
    # Commodity / metals — no options chain needed but specs useful for sizing
    "CL":  FutureSpec("CL",  "Crude Oil",            "USO", "USO", 1000.0, 0.01, 10.00, 1.0),
    "GC":  FutureSpec("GC",  "Gold",                 "GLD", "GLD",  100.0, 0.10, 10.00, 1.0),
}

# If True, prefer cash index chain (SPX/NDX/RUT/DJX) over ETF proxy.
# Set to False if your Schwab API plan doesn't return index chains.
FUTURES_PREFER_INDEX = False


def is_future(symbol: str) -> bool:
    return bool(symbol) and symbol.upper() in FUTURES_SPECS


def future_spec(symbol: str) -> Optional[FutureSpec]:
    if not symbol:
        return None
    return FUTURES_SPECS.get(symbol.upper())


def resolve_chain_symbol(symbol: str,
                         prefer_index: Optional[bool] = None
                         ) -> tuple[str, Optional[FutureSpec]]:
    """Given a user-typed ticker, return (chain_symbol_to_fetch, FutureSpec|None).

    If symbol is a futures root, we substitute the underlying for the API call
    so users can type ES/NQ/RTY directly.
    """
    if not symbol:
        return "", None
    s = symbol.upper()
    spec = FUTURES_SPECS.get(s)
    if spec is None:
        return s, None
    use_index = FUTURES_PREFER_INDEX if prefer_index is None else prefer_index
    chain = spec.underlying if use_index else spec.etf_proxy
    return chain, spec


# ── Cash-index symbols → Schwab marketdata format ──────────────────────────
# Schwab (post-TDA) needs cash indices with a "$" prefix and ".X" suffix on
# the options-chain / quote endpoints (e.g. SPX → "$SPX.X"). Plain "SPX"
# returns HTTP 400 "Invalid Parameter/Value". Equities & ETFs pass through
# unchanged. We keep the clean root ("SPX") everywhere internally (dividends,
# persistence keys, display) and ONLY translate the outbound API symbol.
INDEX_API_SYMBOLS: dict[str, str] = {
    "SPX": "$SPX.X",
    "NDX": "$NDX.X",
    "RUT": "$RUT.X",
    "VIX": "$VIX.X",
    "DJX": "$DJI",
}


def to_api_symbol(symbol: str) -> str:
    """Map a cash-index root (SPX/NDX/RUT/VIX) to its Schwab marketdata
    symbol ($SPX.X …). Everything else is returned unchanged."""
    if not symbol:
        return symbol
    return INDEX_API_SYMBOLS.get(symbol.upper(), symbol)


def api_symbol_candidates(symbol: str) -> list[str]:
    """Ordered list of Schwab API symbols to try for a given root.

    For cash indices we return BOTH the ".X" and the bare "$"-prefixed
    forms (Schwab's accepted format has varied by endpoint and across the
    TDA→Schwab migration), so a caller can try the primary and fall back to
    the alternative instead of hard-failing on a format guess. For everything
    else it's just the symbol itself.
    """
    if not symbol:
        return [symbol]
    s = symbol.upper()
    primary = INDEX_API_SYMBOLS.get(s)
    if primary is None:
        return [s]
    if primary.endswith(".X"):
        return [primary, primary[:-2]]        # ["$SPX.X", "$SPX"]
    return [primary, primary + ".X"]           # ["$DJI", "$DJI.X"]


def points_distance(future_root: str, etf_strike: float, etf_spot: float
                    ) -> Optional[float]:
    """Convert an ETF strike distance to *future points* using the ratio.
    ES_pts ≈ (etf_strike − etf_spot) × etf_ratio. Useful for DOM-ready levels.
    Returns None if symbol isn't a known future."""
    spec = future_spec(future_root)
    if spec is None:
        return None
    return float(etf_strike - etf_spot) * spec.etf_ratio


def dollars_per_point(future_root: str) -> Optional[float]:
    spec = future_spec(future_root)
    return spec.point_value if spec else None


# ── Session-state keys (no more magic strings) ─────────────────────────────
class SS:
    TOKENS = "tokens"
    CONNECTED = "connected"
    APP_KEY = "app_key"
    APP_SECRET = "app_secret"
    CALLBACK_URL = "callback_url"
    OAUTH_PENDING = "oauth_pending"
    OAUTH_CODE = "oauth_code"
    CHAIN_DATA = "chain_data"
    LAST_SYM = "last_sym"
    LAST_STRIKES = "last_strikes"
    SYMBOL = "symbol"
    LAST_REFRESH = "last_refresh"
    ALL_EXPS = "all_exps"
    SEL_EXP = "sel_exp"
    REFRESH_COUNT = "_last_refresh_count"
    AUTO_REFRESH = "auto_refresh_toggle"
    HIRO_HISTORY = "hiro_history"
    ORDERFLOW_HISTORY = "orderflow_history"
    FUTURE_ROOT = "future_root"           # e.g. "ES" if user typed ES
    PREFER_INDEX = "prefer_index_chain"   # toggle ETF proxy ↔ cash index
    TRADING_MODE = "trading_mode"         # single-screen mode toggle
    REPLAY_DATE = "replay_date"           # historical replay selected day
    REPLAY_CURSOR = "replay_cursor"       # time cursor when replaying


# ── Symbol validation (XSS + API hygiene) ──────────────────────────────────
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def sanitize_symbol(raw: str) -> str:
    """Return uppercase stripped symbol if it matches equity ticker pattern,
    else empty string. Prevents HTML injection and bad API calls."""
    if not raw:
        return ""
    s = raw.strip().upper()
    return s if _SYMBOL_RE.match(s) else ""
