"""
Storage backend for CONTINUOUS orderflow snapshots.

This is the persistence layer that makes the Orderflow tab useful: a
headless GitHub-Actions runner snapshots the chain every ~10 minutes
during RTH and writes here, so the dashboard sees the FULL session
history whenever it is opened — independent of the app being open and
immune to Streamlit Cloud's ephemeral filesystem (which wipes the local
SQLite on every redeploy and was the root cause of the "empty orderflow"
problem).

Dual backend, chosen at runtime (same pattern as data/em_store.py):
  · DATABASE_URL set (Neon / any Postgres) → psycopg2.
  · Otherwise → local SQLite at ~/.options_terminal/of_history.db.

Tables
------
of_ticks    one row per (symbol, ts): session-level summary — spot, net
            GEX/DEX/VEX/CEX, walls, flip, HVL, regime, plus the 0DTE
            bucket's net GEX and walls.
of_strikes  per-strike rows for the 0DTE expiry near the spot: net GEX,
            OI and cumulative day volume per side. Volume deltas between
            snapshots are the intraday flow proxy (OI only updates
            overnight — that is an OCC constraint, not a bug).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

TICK_COLUMNS = [
    "symbol", "ts", "spot",
    "net_gex_mm", "call_gex_mm", "put_gex_mm",
    "call_wall", "put_wall", "gamma_flip", "hvl", "regime",
    "net_dex_mm", "net_vex_mm", "net_cex_mm",
    "gex_0dte_mm", "call_wall_0dte", "put_wall_0dte", "hvl_0dte",
]

STRIKE_COLUMNS = [
    "symbol", "ts", "strike",
    "net_gex_mm", "call_oi", "put_oi", "call_vol", "put_vol",
]

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS of_ticks (
    symbol         TEXT NOT NULL,
    ts             TEXT NOT NULL,
    spot           DOUBLE PRECISION,
    net_gex_mm     DOUBLE PRECISION,
    call_gex_mm    DOUBLE PRECISION,
    put_gex_mm     DOUBLE PRECISION,
    call_wall      DOUBLE PRECISION,
    put_wall       DOUBLE PRECISION,
    gamma_flip     DOUBLE PRECISION,
    hvl            DOUBLE PRECISION,
    regime         TEXT,
    net_dex_mm     DOUBLE PRECISION,
    net_vex_mm     DOUBLE PRECISION,
    net_cex_mm     DOUBLE PRECISION,
    gex_0dte_mm    DOUBLE PRECISION,
    call_wall_0dte DOUBLE PRECISION,
    put_wall_0dte  DOUBLE PRECISION,
    hvl_0dte       DOUBLE PRECISION,
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS of_strikes (
    symbol      TEXT NOT NULL,
    ts          TEXT NOT NULL,
    strike      DOUBLE PRECISION NOT NULL,
    net_gex_mm  DOUBLE PRECISION,
    call_oi     DOUBLE PRECISION,
    put_oi      DOUBLE PRECISION,
    call_vol    DOUBLE PRECISION,
    put_vol     DOUBLE PRECISION,
    PRIMARY KEY (symbol, ts, strike)
);
"""

_SQLITE_SCHEMA = _PG_SCHEMA.replace("DOUBLE PRECISION", "REAL")


def _database_url() -> Optional[str]:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


def _is_postgres() -> bool:
    return bool(_database_url())


def _sqlite_path() -> Path:
    env = os.environ.get("OF_STORE_DB")
    p = Path(env) if env else Path.home() / ".options_terminal" / "of_history.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect():
    url = _database_url()
    if url:
        import psycopg2
        return psycopg2.connect(url), "pg"
    conn = sqlite3.connect(str(_sqlite_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn, "sqlite"


def _ph(flavor: str) -> str:
    return "%s" if flavor == "pg" else "?"


def init_db() -> None:
    """Create the tables if missing. Idempotent."""
    conn, flavor = _connect()
    try:
        cur = conn.cursor()
        schema = _PG_SCHEMA if flavor == "pg" else _SQLITE_SCHEMA
        for stmt in schema.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Write
# ─────────────────────────────────────────────────────────────────────────────
def record_tick(tick: dict, strikes: Optional[list[dict]] = None) -> bool:
    """Insert one orderflow snapshot (+ its per-strike rows).

    Duplicate (symbol, ts) inserts are ignored, so a double-fired cron is
    harmless. Returns True if the tick row was inserted.
    """
    if not tick or not tick.get("symbol") or not tick.get("ts"):
        return False
    init_db()
    conn, flavor = _connect()
    ph = _ph(flavor)
    try:
        cur = conn.cursor()
        cols = ", ".join(TICK_COLUMNS)
        vals = ", ".join([ph] * len(TICK_COLUMNS))
        if flavor == "pg":
            sql = (f"INSERT INTO of_ticks ({cols}) VALUES ({vals}) "
                   f"ON CONFLICT (symbol, ts) DO NOTHING")
        else:
            sql = f"INSERT OR IGNORE INTO of_ticks ({cols}) VALUES ({vals})"
        cur.execute(sql, [tick.get(c) for c in TICK_COLUMNS])
        inserted = cur.rowcount > 0

        if strikes:
            scols = ", ".join(STRIKE_COLUMNS)
            svals = ", ".join([ph] * len(STRIKE_COLUMNS))
            if flavor == "pg":
                ssql = (f"INSERT INTO of_strikes ({scols}) VALUES ({svals}) "
                        f"ON CONFLICT (symbol, ts, strike) DO NOTHING")
            else:
                ssql = (f"INSERT OR IGNORE INTO of_strikes ({scols}) "
                        f"VALUES ({svals})")
            rows = [[s.get(c) for c in STRIKE_COLUMNS] for s in strikes
                    if s.get("strike") is not None]
            if rows:
                cur.executemany(ssql, rows)
        conn.commit()
        return bool(inserted)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Read
# ─────────────────────────────────────────────────────────────────────────────
def load_ticks(symbol: str, hours: float = 9.0,
               limit: int = 500) -> list[dict]:
    """Session tick history for `symbol`, oldest→newest, last `hours`."""
    import datetime
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=hours)).isoformat()
    rows = _query(
        "SELECT * FROM of_ticks WHERE symbol = {ph} AND ts >= {ph} "
        "ORDER BY ts ASC LIMIT {ph}",
        (symbol, cutoff, limit),
    )
    return rows


def load_strikes(symbol: str, hours: float = 9.0,
                 limit: int = 20000) -> list[dict]:
    """Per-strike snapshot history, oldest→newest, last `hours`."""
    import datetime
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=hours)).isoformat()
    return _query(
        "SELECT * FROM of_strikes WHERE symbol = {ph} AND ts >= {ph} "
        "ORDER BY ts ASC, strike ASC LIMIT {ph}",
        (symbol, cutoff, limit),
    )


def _query(sql_tmpl: str, params: tuple) -> list[dict]:
    init_db()
    conn, flavor = _connect()
    sql = sql_tmpl.replace("{ph}", _ph(flavor))
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        if flavor == "pg":
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        return [dict(r) for r in rows]
    finally:
        conn.close()


def backend_info() -> dict:
    return {
        "backend": "postgres" if _is_postgres() else "sqlite",
        "location": ("Neon/Postgres" if _is_postgres()
                     else str(_sqlite_path())),
    }
