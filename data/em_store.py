"""
Storage backend for the EM accuracy tracker.

Dual backend, chosen at runtime:
  · If DATABASE_URL is set (Neon / any Postgres) → Postgres via psycopg2.
  · Otherwise → local SQLite at ~/.options_terminal/em_tracker.db.

This lets the headless GitHub-Actions runner write to Neon (persistent,
private, survives between runs), while a local dashboard with no
DATABASE_URL still works against a local file. Same API either way.

The DATABASE_URL can come from:
  · os.environ["DATABASE_URL"]            (GitHub Actions / shell)
  · st.secrets["DATABASE_URL"]            (Streamlit Cloud / local secrets)
"""
from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path
from typing import Optional


_COLUMNS = [
    "symbol", "date", "snapshot_ts", "spot_open", "dte",
    "rnd_method", "rnd_p05", "rnd_p10", "rnd_p25", "rnd_p50",
    "rnd_p75", "rnd_p90", "rnd_p95", "rnd_p16", "rnd_p84",
    "rnd_mode", "rnd_std",
    "close_actual", "move_actual",
    "inside_p10_p90", "inside_p05_p95", "inside_1sigma", "settled",
]

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS em_accuracy (
    symbol         TEXT NOT NULL,
    date           TEXT NOT NULL,
    snapshot_ts    TEXT,
    spot_open      DOUBLE PRECISION,
    dte            INTEGER,
    rnd_method     TEXT,
    rnd_p05        DOUBLE PRECISION,
    rnd_p10        DOUBLE PRECISION,
    rnd_p25        DOUBLE PRECISION,
    rnd_p50        DOUBLE PRECISION,
    rnd_p75        DOUBLE PRECISION,
    rnd_p90        DOUBLE PRECISION,
    rnd_p95        DOUBLE PRECISION,
    rnd_p16        DOUBLE PRECISION,
    rnd_p84        DOUBLE PRECISION,
    rnd_mode       DOUBLE PRECISION,
    rnd_std        DOUBLE PRECISION,
    close_actual   DOUBLE PRECISION,
    move_actual    DOUBLE PRECISION,
    inside_p10_p90 INTEGER,
    inside_p05_p95 INTEGER,
    inside_1sigma  INTEGER,
    settled        INTEGER DEFAULT 0,
    PRIMARY KEY (symbol, date)
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


# ─────────────────────────────────────────────────────────────────────────────
#  Connection
# ─────────────────────────────────────────────────────────────────────────────
def _sqlite_path() -> Path:
    env = os.environ.get("EM_TRACKER_DB")
    p = Path(env) if env else Path.home() / ".options_terminal" / "em_tracker.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect():
    """Return (conn, flavor) where flavor is 'pg' or 'sqlite'. The caller
    must close the connection."""
    url = _database_url()
    if url:
        import psycopg2
        conn = psycopg2.connect(url)
        return conn, "pg"
    conn = sqlite3.connect(str(_sqlite_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn, "sqlite"


def _ph(flavor: str) -> str:
    """Parameter placeholder for the flavor."""
    return "%s" if flavor == "pg" else "?"


def init_db() -> None:
    """Create the table if it doesn't exist. Idempotent."""
    conn, flavor = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_PG_SCHEMA if flavor == "pg" else _SQLITE_SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Write / read
# ─────────────────────────────────────────────────────────────────────────────
def record_prediction(record: dict) -> bool:
    """Insert a prediction if none exists yet for (symbol, date).
    Returns True if a row was inserted, False if one already existed
    (we keep the FIRST prediction of the day — the open-anchored one).
    """
    if not record or not record.get("symbol") or not record.get("date"):
        return False
    init_db()
    conn, flavor = _connect()
    ph = _ph(flavor)
    try:
        cur = conn.cursor()
        cols = ", ".join(_COLUMNS)
        vals = ", ".join([ph] * len(_COLUMNS))
        if flavor == "pg":
            sql = (f"INSERT INTO em_accuracy ({cols}) VALUES ({vals}) "
                   f"ON CONFLICT (symbol, date) DO NOTHING")
        else:
            sql = (f"INSERT OR IGNORE INTO em_accuracy ({cols}) "
                   f"VALUES ({vals})")
        params = [record.get(c) for c in _COLUMNS]
        cur.execute(sql, params)
        inserted = cur.rowcount > 0
        conn.commit()
        return bool(inserted)
    finally:
        conn.close()


def settle(symbol: str, date_iso: str, fields: dict) -> bool:
    """Update settlement fields for (symbol, date). Returns True if a row
    was updated."""
    if not fields:
        return False
    init_db()
    conn, flavor = _connect()
    ph = _ph(flavor)
    try:
        cur = conn.cursor()
        set_clause = ", ".join(f"{k} = {ph}" for k in fields)
        sql = (f"UPDATE em_accuracy SET {set_clause} "
               f"WHERE symbol = {ph} AND date = {ph}")
        params = list(fields.values()) + [symbol, date_iso]
        cur.execute(sql, params)
        updated = cur.rowcount > 0
        conn.commit()
        return bool(updated)
    finally:
        conn.close()


def load_pending(symbol: str) -> list[dict]:
    """Return unsettled prediction rows for `symbol` (settled = 0)."""
    return _query(
        "SELECT * FROM em_accuracy WHERE symbol = {ph} AND "
        "(settled = 0 OR settled IS NULL) ORDER BY date ASC",
        (symbol,),
    )


def load_history(symbol: str, limit: int = 250) -> list[dict]:
    """Return all rows for `symbol`, most recent first."""
    return _query(
        "SELECT * FROM em_accuracy WHERE symbol = {ph} "
        "ORDER BY date DESC LIMIT {ph}",
        (symbol, limit),
    )


def get_today(symbol: str, date_iso: str) -> Optional[dict]:
    rows = _query(
        "SELECT * FROM em_accuracy WHERE symbol = {ph} AND date = {ph}",
        (symbol, date_iso),
    )
    return rows[0] if rows else None


def _query(sql_tmpl: str, params: tuple) -> list[dict]:
    init_db()
    conn, flavor = _connect()
    ph = _ph(flavor)
    sql = sql_tmpl.replace("{ph}", ph)
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
    """Diagnostics: which backend is active."""
    return {
        "backend": "postgres" if _is_postgres() else "sqlite",
        "location": ("Neon/Postgres" if _is_postgres()
                     else str(_sqlite_path())),
    }
