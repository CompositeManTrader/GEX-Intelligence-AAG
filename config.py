"""
Central configuration: constants, session keys, timezone helpers.
No side effects on import.
"""
from __future__ import annotations

import datetime
import logging
import re
from datetime import timezone

import pytz

# ── Timezones ──────────────────────────────────────────────────────────────
CDMX_TZ = pytz.timezone("America/Mexico_City")
ET_TZ = pytz.timezone("America/New_York")
UTC = timezone.utc


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(UTC)


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
HTTP_BACKOFF = 0.4

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


# ── Symbol validation (XSS + API hygiene) ──────────────────────────────────
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def sanitize_symbol(raw: str) -> str:
    """Return uppercase stripped symbol if it matches equity ticker pattern,
    else empty string. Prevents HTML injection and bad API calls."""
    if not raw:
        return ""
    s = raw.strip().upper()
    return s if _SYMBOL_RE.match(s) else ""
