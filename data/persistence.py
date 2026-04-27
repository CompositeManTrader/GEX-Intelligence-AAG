"""
SQLite persistence for intraday HIRO + Orderflow snapshots and daily summaries.

Why this exists
---------------
Streamlit's `session_state` is per-tab/per-process — every browser refresh, page
navigation, or app restart wipes the rolling histories. For someone trading
futures off these levels, that's unacceptable: you want continuity across
restarts, replay of past sessions, and post-mortem comparisons.

What we store
-------------
1. `orderflow_ticks` — one row per orderflow snapshot tick (~30s cadence).
2. `hiro_ticks`      — one row per HIRO snapshot tick.
3. `daily_snapshots` — one row per (date, symbol) at session close, with all
                       key levels. The "what was it yesterday?" lookup table.

Design
------
- Single DB file at `~/.options_terminal/intraday.db` (override with env var
  OPTIONS_TERMINAL_DB).
- WAL mode → safe for the dashboard process to read while a worker writes.
- Connection cached via `st.cache_resource` so we reuse one handle.
- All writes are best-effort: if the DB is locked or the row already exists,
  we swallow the error and keep going. The UI must never crash on persistence.
- Reads return plain `list[dict]` (parity with the in-memory rolling history).
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

import streamlit as st

from config import get_logger

log = get_logger("data.persistence")


# ─────────────────────────────────────────────────────────────────────────────
#  DB path resolution + connection
# ─────────────────────────────────────────────────────────────────────────────
def _db_path() -> Path:
    env = os.environ.get("OPTIONS_TERMINAL_DB")
    if env:
        p = Path(env)
    else:
        p = Path.home() / ".options_terminal" / "intraday.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_SCHEMA = """
CREATE TABLE IF NOT EXISTS orderflow_ticks (
    ts          TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    spot        REAL,
    net_gex_mm  REAL,
    call_gex_mm REAL,
    put_gex_mm  REAL,
    call_wall   REAL,
    put_wall    REAL,
    gamma_flip  REAL,
    net_dex_mm  REAL,
    call_dex_mm REAL,
    put_dex_mm  REAL,
    net_vex_mm  REAL,
    call_vex_mm REAL,
    put_vex_mm  REAL,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS hiro_ticks (
    ts         TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    spot       REAL,
    call_flow  REAL,
    put_flow   REAL,
    hiro       REAL,
    ratio      REAL,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    date       TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    spot_close REAL,
    total_gex  REAL,
    call_gex   REAL,
    put_gex    REAL,
    call_wall  REAL,
    put_wall   REAL,
    gamma_flip REAL,
    hvl        REAL,
    max_pain   REAL,
    iv_atm     REAL,
    regime     TEXT,
    extra_json TEXT,
    PRIMARY KEY (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_of_symbol_ts  ON orderflow_ticks(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_hiro_symbol_ts ON hiro_ticks(symbol, ts);
"""


@st.cache_resource(show_spinner=False)
def _conn() -> sqlite3.Connection:
    path = _db_path()
    c = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.executescript(_SCHEMA)
    c.commit()
    log.info("persistence DB ready at %s", path)
    return c


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────
def _today_iso() -> str:
    return datetime.datetime.utcnow().date().isoformat()


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Orderflow ticks
# ─────────────────────────────────────────────────────────────────────────────
ORDERFLOW_FIELDS = [
    "spot", "net_gex_mm", "call_gex_mm", "put_gex_mm",
    "call_wall", "put_wall", "gamma_flip",
    "net_dex_mm", "call_dex_mm", "put_dex_mm",
    "net_vex_mm", "call_vex_mm", "put_vex_mm",
]


def persist_orderflow_tick(symbol: str, tick: dict) -> None:
    """INSERT OR IGNORE — dedup by (symbol, ts). Best-effort."""
    if not symbol or not tick:
        return
    ts = tick.get("timestamp")
    if not ts:
        return
    cols = ["ts", "symbol"] + ORDERFLOW_FIELDS
    vals = [ts, symbol] + [_safe_float(tick.get(f)) for f in ORDERFLOW_FIELDS]
    placeholders = ",".join("?" * len(cols))
    try:
        c = _conn()
        c.execute(
            f"INSERT OR IGNORE INTO orderflow_ticks ({','.join(cols)}) "
            f"VALUES ({placeholders})",
            vals,
        )
        c.commit()
    except Exception:
        log.exception("persist_orderflow_tick failed")


def load_orderflow_history(symbol: str, date: Optional[str] = None,
                           limit: int = 5000) -> list[dict]:
    """Return rows for the given symbol/date as plain dicts.
    If `date` is None, return today's rows."""
    if not symbol:
        return []
    d = date or _today_iso()
    try:
        c = _conn()
        cur = c.execute(
            "SELECT * FROM orderflow_ticks "
            "WHERE symbol=? AND substr(ts,1,10)=? "
            "ORDER BY ts ASC LIMIT ?",
            (symbol, d, limit),
        )
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["timestamp"] = row.pop("ts", None)
            rows.append(row)
        return rows
    except Exception:
        log.exception("load_orderflow_history failed")
        return []


def load_recent_orderflow(symbol: str, hours: int = 8,
                          limit: int = 1000) -> list[dict]:
    """Last N hours of orderflow ticks for a symbol — used to seed the
    in-memory history when the dashboard starts up mid-session."""
    if not symbol:
        return []
    cutoff = (datetime.datetime.utcnow()
              - datetime.timedelta(hours=hours)).isoformat()
    try:
        c = _conn()
        cur = c.execute(
            "SELECT * FROM orderflow_ticks WHERE symbol=? AND ts>=? "
            "ORDER BY ts ASC LIMIT ?",
            (symbol, cutoff, limit),
        )
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["timestamp"] = row.pop("ts", None)
            rows.append(row)
        return rows
    except Exception:
        log.exception("load_recent_orderflow failed")
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  HIRO ticks
# ─────────────────────────────────────────────────────────────────────────────
HIRO_FIELDS = ["spot", "call_flow", "put_flow", "hiro", "ratio"]


def persist_hiro_tick(symbol: str, tick: dict) -> None:
    if not symbol or not tick:
        return
    ts = tick.get("timestamp")
    if not ts:
        return
    cols = ["ts", "symbol"] + HIRO_FIELDS
    vals = [ts, symbol] + [_safe_float(tick.get(f)) for f in HIRO_FIELDS]
    placeholders = ",".join("?" * len(cols))
    try:
        c = _conn()
        c.execute(
            f"INSERT OR IGNORE INTO hiro_ticks ({','.join(cols)}) "
            f"VALUES ({placeholders})",
            vals,
        )
        c.commit()
    except Exception:
        log.exception("persist_hiro_tick failed")


def load_hiro_history(symbol: str, date: Optional[str] = None,
                      limit: int = 5000) -> list[dict]:
    if not symbol:
        return []
    d = date or _today_iso()
    try:
        c = _conn()
        cur = c.execute(
            "SELECT * FROM hiro_ticks WHERE symbol=? AND substr(ts,1,10)=? "
            "ORDER BY ts ASC LIMIT ?",
            (symbol, d, limit),
        )
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["timestamp"] = row.pop("ts", None)
            rows.append(row)
        return rows
    except Exception:
        log.exception("load_hiro_history failed")
        return []


def load_recent_hiro(symbol: str, hours: int = 8,
                     limit: int = 1000) -> list[dict]:
    if not symbol:
        return []
    cutoff = (datetime.datetime.utcnow()
              - datetime.timedelta(hours=hours)).isoformat()
    try:
        c = _conn()
        cur = c.execute(
            "SELECT * FROM hiro_ticks WHERE symbol=? AND ts>=? "
            "ORDER BY ts ASC LIMIT ?",
            (symbol, cutoff, limit),
        )
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["timestamp"] = row.pop("ts", None)
            rows.append(row)
        return rows
    except Exception:
        log.exception("load_recent_hiro failed")
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  Daily snapshots
# ─────────────────────────────────────────────────────────────────────────────
def persist_daily_snapshot(symbol: str, spot: float,
                           gex_sum: dict, max_pain_v: Optional[float],
                           iv_atm: Optional[float],
                           extra: Optional[dict] = None) -> None:
    """Upsert a single (symbol, date=today) summary row. Idempotent."""
    if not symbol:
        return
    date = _today_iso()
    s = gex_sum or {}
    row = {
        "date": date,
        "symbol": symbol,
        "spot_close": _safe_float(spot),
        "total_gex": _safe_float(s.get("total_gex")),
        "call_gex": _safe_float(s.get("call_gex")),
        "put_gex": _safe_float(s.get("put_gex")),
        "call_wall": _safe_float(s.get("call_wall")),
        "put_wall": _safe_float(s.get("put_wall")),
        "gamma_flip": _safe_float(s.get("gamma_flip")),
        "hvl": _safe_float(s.get("hvl")),
        "max_pain": _safe_float(max_pain_v),
        "iv_atm": _safe_float(iv_atm),
        "regime": str(s.get("regime")) if s.get("regime") else None,
        "extra_json": json.dumps(extra) if extra else None,
    }
    try:
        c = _conn()
        cols = list(row.keys())
        placeholders = ",".join("?" * len(cols))
        updates = ",".join(f"{k}=excluded.{k}" for k in cols
                           if k not in ("symbol", "date"))
        c.execute(
            f"INSERT INTO daily_snapshots ({','.join(cols)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(symbol, date) DO UPDATE SET {updates}",
            list(row.values()),
        )
        c.commit()
    except Exception:
        log.exception("persist_daily_snapshot failed")


def load_daily_snapshots(symbol: str, days: int = 30) -> list[dict]:
    if not symbol:
        return []
    cutoff = (datetime.datetime.utcnow().date()
              - datetime.timedelta(days=days)).isoformat()
    try:
        c = _conn()
        cur = c.execute(
            "SELECT * FROM daily_snapshots WHERE symbol=? AND date>=? "
            "ORDER BY date DESC",
            (symbol, cutoff),
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        log.exception("load_daily_snapshots failed")
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  Replay support
# ─────────────────────────────────────────────────────────────────────────────
def available_replay_dates(symbol: str, lookback_days: int = 60) -> list[str]:
    """Distinct YYYY-MM-DD dates that have at least one orderflow tick stored
    for `symbol`, most recent first. Used to populate the replay date picker."""
    if not symbol:
        return []
    cutoff = (datetime.datetime.utcnow().date()
              - datetime.timedelta(days=lookback_days)).isoformat()
    try:
        c = _conn()
        cur = c.execute(
            "SELECT DISTINCT substr(ts,1,10) AS d FROM orderflow_ticks "
            "WHERE symbol=? AND substr(ts,1,10)>=? ORDER BY d DESC",
            (symbol, cutoff),
        )
        return [r["d"] for r in cur.fetchall() if r["d"]]
    except Exception:
        log.exception("available_replay_dates failed")
        return []


def db_stats() -> dict:
    """Quick summary for a 'storage' panel: total rows + unique symbols/days."""
    try:
        c = _conn()
        of = c.execute("SELECT COUNT(*) AS n FROM orderflow_ticks").fetchone()
        hi = c.execute("SELECT COUNT(*) AS n FROM hiro_ticks").fetchone()
        ds = c.execute("SELECT COUNT(*) AS n FROM daily_snapshots").fetchone()
        syms = c.execute(
            "SELECT COUNT(DISTINCT symbol) AS n FROM orderflow_ticks"
        ).fetchone()
        size_mb = _db_path().stat().st_size / (1024 * 1024) \
            if _db_path().exists() else 0.0
        return dict(
            orderflow_rows=int(of["n"] if of else 0),
            hiro_rows=int(hi["n"] if hi else 0),
            daily_rows=int(ds["n"] if ds else 0),
            symbols=int(syms["n"] if syms else 0),
            size_mb=round(size_mb, 2),
            path=str(_db_path()),
        )
    except Exception:
        log.exception("db_stats failed")
        return {}


def purge_old_ticks(keep_days: int = 30) -> int:
    """Delete tick data older than `keep_days`. Daily snapshots are kept."""
    cutoff = (datetime.datetime.utcnow()
              - datetime.timedelta(days=keep_days)).isoformat()
    try:
        c = _conn()
        n1 = c.execute("DELETE FROM orderflow_ticks WHERE ts<?",
                       (cutoff,)).rowcount
        n2 = c.execute("DELETE FROM hiro_ticks WHERE ts<?",
                       (cutoff,)).rowcount
        c.commit()
        return int(n1 + n2)
    except Exception:
        log.exception("purge_old_ticks failed")
        return 0
