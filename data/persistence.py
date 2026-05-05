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
from datetime import timezone
from pathlib import Path
from typing import Optional

import streamlit as st

from config import ET_TZ, get_logger

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

CREATE TABLE IF NOT EXISTS orderflow_strikes (
    ts        TEXT NOT NULL,
    symbol    TEXT NOT NULL,
    bucket    TEXT NOT NULL,
    strike    REAL NOT NULL,
    gex_mm    REAL,
    dex_mm    REAL,
    vex_mm    REAL,
    oi        INTEGER,
    PRIMARY KEY (symbol, ts, bucket, strike)
);

CREATE TABLE IF NOT EXISTS orderflow_zones (
    ts                 TEXT NOT NULL,
    symbol             TEXT NOT NULL,
    rank               INTEGER NOT NULL,
    label              TEXT,
    peak_strike        REAL,
    low_strike         REAL,
    high_strike        REAL,
    width              REAL,
    peak_gex_mm        REAL,
    integrated_gex_mm  REAL,
    side               TEXT,
    distance_pct       REAL,
    is_above_spot      INTEGER,
    PRIMARY KEY (symbol, ts, rank)
);

CREATE INDEX IF NOT EXISTS idx_of_symbol_ts    ON orderflow_ticks(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_hiro_symbol_ts  ON hiro_ticks(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_ofs_sym_ts      ON orderflow_strikes(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_ofs_sym_strike  ON orderflow_strikes(symbol, strike, ts);
CREATE INDEX IF NOT EXISTS idx_ofz_sym_ts      ON orderflow_zones(symbol, ts);
"""

# Per-DTE-bucket fields persisted on the wide aggregate table. Schema is
# evolved via additive ALTER TABLE so existing DBs are upgraded silently.
_BUCKET_TICK_COLUMNS: tuple[str, ...] = (
    "gex_net_0dte_mm",  "gex_call_0dte_mm",  "gex_put_0dte_mm",
    "gex_net_week_mm",  "gex_call_week_mm",  "gex_put_week_mm",
    "gex_net_month_mm", "gex_call_month_mm", "gex_put_month_mm",
    "dex_net_0dte_mm", "dex_net_week_mm", "dex_net_month_mm",
    "vex_net_0dte_mm", "vex_net_week_mm", "vex_net_month_mm",
    "net_cex_mm", "hvl", "regime",
)


def _migrate_orderflow_ticks(c: sqlite3.Connection) -> None:
    """Additive ALTER TABLE for older DBs that pre-date the bucket columns.
    SQLite returns OperationalError on duplicate column; we ignore.
    """
    cur = c.execute("PRAGMA table_info(orderflow_ticks)")
    existing = {row["name"] for row in cur.fetchall()}
    for col in _BUCKET_TICK_COLUMNS:
        if col in existing:
            continue
        sql_type = "TEXT" if col == "regime" else "REAL"
        try:
            c.execute(f"ALTER TABLE orderflow_ticks ADD COLUMN {col} {sql_type}")
        except sqlite3.OperationalError:
            pass
    c.commit()


@st.cache_resource(show_spinner=False)
def _conn() -> sqlite3.Connection:
    path = _db_path()
    c = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.executescript(_SCHEMA)
    _migrate_orderflow_ticks(c)
    c.commit()
    log.info("persistence DB ready at %s", path)
    return c


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────
def _today_iso() -> str:
    """Today as YYYY-MM-DD in *Eastern Time* — the market clock.

    Using UTC date here would have classified late-session ET ticks
    (15:00–16:00 ET in winter is 20:00–21:00 UTC, fine; but 16:00 ET in
    summer becomes 20:00 UTC, still same day) — except it gets worse for
    after-hours data: a tick at 18:30 ET = 23:30 UTC stays "today", but
    20:30 ET = 00:30 next-UTC-day would be filed under tomorrow.
    Trading-session correlation requires the market's clock.
    """
    return datetime.datetime.now(ET_TZ).date().isoformat()


def _et_cutoff_iso(days: int) -> str:
    """Return an ET-anchored cutoff timestamp for `days` ago, in ISO format."""
    return (datetime.datetime.now(ET_TZ) - datetime.timedelta(days=days)).isoformat()


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
    # Bucket fields (tier-1 of the orderflow rework). Float fields here
    # are coerced via _safe_float; the lone string field 'regime' is
    # appended below in persist_orderflow_tick so the value is preserved.
    "gex_net_0dte_mm",  "gex_call_0dte_mm",  "gex_put_0dte_mm",
    "gex_net_week_mm",  "gex_call_week_mm",  "gex_put_week_mm",
    "gex_net_month_mm", "gex_call_month_mm", "gex_put_month_mm",
    "dex_net_0dte_mm", "dex_net_week_mm", "dex_net_month_mm",
    "vex_net_0dte_mm", "vex_net_week_mm", "vex_net_month_mm",
    "net_cex_mm", "hvl",
]


def persist_orderflow_tick(symbol: str, tick: dict) -> None:
    """INSERT OR IGNORE — dedup by (symbol, ts). Best-effort.

    Floats are sanitized via `_safe_float`; the `regime` text label is
    appended verbatim. Callers should gate writes via
    `quant.orderflow.should_persist_tick` so we don't write 30s of
    identical rows during quiet markets.
    """
    if not symbol or not tick:
        return
    ts = tick.get("timestamp")
    if not ts:
        return
    cols = ["ts", "symbol"] + ORDERFLOW_FIELDS + ["regime"]
    vals = ([ts, symbol]
            + [_safe_float(tick.get(f)) for f in ORDERFLOW_FIELDS]
            + [str(tick["regime"]) if tick.get("regime") else None])
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
    cutoff = (datetime.datetime.now(timezone.utc)
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
    cutoff = (datetime.datetime.now(timezone.utc)
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
    cutoff = (datetime.datetime.now(ET_TZ).date()
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
    cutoff = (datetime.datetime.now(ET_TZ).date()
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
    cutoff = (datetime.datetime.now(timezone.utc)
              - datetime.timedelta(days=keep_days)).isoformat()
    try:
        c = _conn()
        n1 = c.execute("DELETE FROM orderflow_ticks WHERE ts<?",
                       (cutoff,)).rowcount
        n2 = c.execute("DELETE FROM hiro_ticks WHERE ts<?",
                       (cutoff,)).rowcount
        n3 = c.execute("DELETE FROM orderflow_strikes WHERE ts<?",
                       (cutoff,)).rowcount
        n4 = c.execute("DELETE FROM orderflow_zones WHERE ts<?",
                       (cutoff,)).rowcount
        c.commit()
        return int(n1 + n2 + n3 + n4)
    except Exception:
        log.exception("purge_old_ticks failed")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
#  Gamma zones (P1/P2/P3 …) — persisted per tick for replay + cross-session
# ─────────────────────────────────────────────────────────────────────────────
def persist_zones_tick(symbol: str, ts: str, zones: list[dict]) -> None:
    """Persist a top-N gamma-zones snapshot. Zones are dicts produced by
    :func:`quant.zones.GammaZone.to_dict`. Best-effort, silent on errors.
    """
    if not symbol or not ts or not zones:
        return
    try:
        rows = [
            (
                ts, symbol,
                int(z.get("rank") or 0),
                str(z.get("label") or ""),
                _safe_float(z.get("peak_strike")),
                _safe_float(z.get("low_strike")),
                _safe_float(z.get("high_strike")),
                _safe_float(z.get("width")),
                _safe_float(z.get("peak_gex_mm")),
                _safe_float(z.get("integrated_gex_mm")),
                str(z.get("side") or ""),
                _safe_float(z.get("distance_pct")),
                1 if z.get("is_above_spot") else 0,
            )
            for z in zones
        ]
        c = _conn()
        c.executemany(
            "INSERT OR IGNORE INTO orderflow_zones "
            "(ts, symbol, rank, label, peak_strike, low_strike, high_strike, "
            " width, peak_gex_mm, integrated_gex_mm, side, distance_pct, "
            " is_above_spot) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        c.commit()
    except Exception:
        log.exception("persist_zones_tick failed")


def load_zones_history(symbol: str, date: Optional[str] = None,
                       limit: int = 5000) -> list[dict]:
    """Return zones rows for `symbol` on the given ET date, sorted by
    (ts ASC, rank ASC). Useful for replay and for the "zones drift"
    visualisation (how the P1 strike migrated through the day).
    """
    if not symbol:
        return []
    d = date or _today_iso()
    try:
        c = _conn()
        cur = c.execute(
            "SELECT * FROM orderflow_zones "
            "WHERE symbol=? AND substr(ts,1,10)=? "
            "ORDER BY ts ASC, rank ASC LIMIT ?",
            (symbol, d, limit),
        )
        out = []
        for r in cur.fetchall():
            row = dict(r)
            row["timestamp"] = row.pop("ts", None)
            row["is_above_spot"] = bool(row.get("is_above_spot"))
            out.append(row)
        return out
    except Exception:
        log.exception("load_zones_history failed")
        return []


def latest_zones(symbol: str) -> list[dict]:
    """Return the most recently persisted zones for `symbol` as a list
    of dicts, sorted by rank ASC. Empty if none."""
    if not symbol:
        return []
    try:
        c = _conn()
        cur = c.execute(
            "SELECT MAX(ts) AS t FROM orderflow_zones WHERE symbol=?",
            (symbol,),
        )
        row = cur.fetchone()
        last_ts = row["t"] if row else None
        if not last_ts:
            return []
        cur = c.execute(
            "SELECT * FROM orderflow_zones WHERE symbol=? AND ts=? "
            "ORDER BY rank ASC",
            (symbol, last_ts),
        )
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["timestamp"] = d.pop("ts", None)
            d["is_above_spot"] = bool(d.get("is_above_spot"))
            out.append(d)
        return out
    except Exception:
        log.exception("latest_zones failed")
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  Per-strike orderflow snapshots
# ─────────────────────────────────────────────────────────────────────────────
def persist_strike_tick(symbol: str, ts: str, bucket: str,
                        gex_df, dex_df=None, vex_df=None) -> None:
    """Persist a per-strike snapshot for one (symbol, ts, bucket).

    Each row is the SCALED $M contribution at a single strike, for one
    DTE bucket. Storing strike-level data unlocks the GEX heatmap and
    the "what changed in last N minutes" panel — neither is reconstructible
    from the flat aggregate tick alone.

    Inputs are the per-strike profile DataFrames returned by
    `compute_gex_profile` / `compute_dex_profile` / `compute_vex_profile`
    for the bucket. Best-effort: silently swallows errors.
    """
    if not symbol or not ts or not bucket:
        return
    try:
        import pandas as pd
        if gex_df is None or len(gex_df) == 0:
            return
        # Build a strike-indexed view with optional per-strike GEX/DEX/VEX in $M
        df = gex_df.set_index("Strike")[["Net_GEX"]].rename(columns={"Net_GEX": "gex"})
        df["gex_mm"] = df["gex"] / 1e6
        if dex_df is not None and len(dex_df) > 0 and "Net_DEX" in dex_df.columns:
            df = df.join(
                (dex_df.set_index("Strike")["Net_DEX"] / 1e6).rename("dex_mm"),
                how="outer",
            )
        else:
            df["dex_mm"] = None
        if vex_df is not None and len(vex_df) > 0 and "Net_VEX" in vex_df.columns:
            df = df.join(
                (vex_df.set_index("Strike")["Net_VEX"] / 1e6).rename("vex_mm"),
                how="outer",
            )
        else:
            df["vex_mm"] = None

        rows = [
            (ts, symbol, bucket, float(k),
             _safe_float(r.get("gex_mm")),
             _safe_float(r.get("dex_mm")),
             _safe_float(r.get("vex_mm")),
             None)
            for k, r in df.iterrows()
        ]
        if not rows:
            return
        c = _conn()
        c.executemany(
            "INSERT OR IGNORE INTO orderflow_strikes "
            "(ts, symbol, bucket, strike, gex_mm, dex_mm, vex_mm, oi) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        c.commit()
    except Exception:
        log.exception("persist_strike_tick failed")


def load_strike_history(symbol: str, bucket: str = "month",
                        date: Optional[str] = None,
                        limit: int = 50000) -> list[dict]:
    """Load per-strike snapshots for a symbol+bucket on a given date
    (default: today ET). Returns long-format rows
    `{ts, strike, gex_mm, dex_mm, vex_mm}`, sorted by ts ASC, strike ASC.
    """
    if not symbol or not bucket:
        return []
    d = date or _today_iso()
    try:
        c = _conn()
        cur = c.execute(
            "SELECT ts, strike, gex_mm, dex_mm, vex_mm FROM orderflow_strikes "
            "WHERE symbol=? AND bucket=? AND substr(ts,1,10)=? "
            "ORDER BY ts ASC, strike ASC LIMIT ?",
            (symbol, bucket, d, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        log.exception("load_strike_history failed")
        return []


def latest_two_strike_snapshots(symbol: str, bucket: str = "month"
                                ) -> tuple[list[dict], list[dict]]:
    """Return (newest_snapshot, prior_snapshot) as two strike-keyed row
    lists for the given symbol+bucket. Used by the "what changed" panel:
    feed both into `quant.orderflow_derived.what_changed`. Empty lists
    if not enough history.
    """
    if not symbol or not bucket:
        return [], []
    try:
        c = _conn()
        cur = c.execute(
            "SELECT DISTINCT ts FROM orderflow_strikes "
            "WHERE symbol=? AND bucket=? ORDER BY ts DESC LIMIT 2",
            (symbol, bucket),
        )
        ts_pair = [r["ts"] for r in cur.fetchall()]
        if len(ts_pair) < 2:
            return [], []
        new_ts, old_ts = ts_pair[0], ts_pair[1]

        def _rows(ts: str) -> list[dict]:
            cur2 = c.execute(
                "SELECT strike AS Strike, gex_mm AS Net_GEX, "
                "dex_mm AS Net_DEX, vex_mm AS Net_VEX "
                "FROM orderflow_strikes "
                "WHERE symbol=? AND bucket=? AND ts=?",
                (symbol, bucket, ts),
            )
            return [dict(r) for r in cur2.fetchall()]

        return _rows(new_ts), _rows(old_ts)
    except Exception:
        log.exception("latest_two_strike_snapshots failed")
        return [], []


# ─────────────────────────────────────────────────────────────────────────────
#  Cross-session compare — "today at 10:30 vs same time over last N days"
# ─────────────────────────────────────────────────────────────────────────────
def load_intraday_at_time_of_day(symbol: str,
                                 hh: int, mm: int,
                                 days: int = 10,
                                 fields: Optional[list[str]] = None
                                 ) -> list[dict]:
    """For each of the last `days` ET trading dates, return the orderflow
    tick row whose ts is *closest* to HH:MM ET on that date. Useful as a
    "what was net GEX yesterday at this same minute?" anchor.

    Returns rows ordered date ASC.
    """
    if not symbol:
        return []
    fields = fields or ["spot", "net_gex_mm", "net_dex_mm", "net_vex_mm",
                        "call_wall", "put_wall", "gamma_flip"]
    try:
        import pandas as pd
        # Build the candidate dates list locally (ET).
        today_et = datetime.datetime.now(ET_TZ).date()
        dates = [(today_et - datetime.timedelta(days=k)).isoformat()
                 for k in range(1, days + 1)]
        c = _conn()
        rows: list[dict] = []
        target_min = hh * 60 + mm
        col_list = ", ".join(fields)
        for d in dates:
            # Pick the row whose ts (UTC ISO) corresponds to the smallest
            # absolute minutes-of-day-difference vs target. We approximate
            # by extracting hour+minute from the substring HH:MM in `ts`
            # and converting UTC→ET via a fixed offset based on date —
            # since DST varies, a precise filter is awkward in pure SQL.
            # Cheapest: scan that day's rows and pick min(|HH:MM diff|) in
            # Python after converting to ET.
            cur = c.execute(
                f"SELECT ts, {col_list} FROM orderflow_ticks "
                "WHERE symbol=? AND substr(ts,1,10)=? "
                "ORDER BY ts ASC",
                (symbol, d),
            )
            best: Optional[dict] = None
            best_diff = 10 ** 9
            for r in cur.fetchall():
                try:
                    ts = pd.Timestamp(r["ts"])
                    if ts.tzinfo is None:
                        ts = ts.tz_localize("UTC")
                    et = ts.tz_convert(ET_TZ)
                    delta = abs(et.hour * 60 + et.minute - target_min)
                    if delta < best_diff:
                        best_diff = delta
                        best = dict(r)
                        best["et_time"] = et.isoformat()
                except Exception:
                    continue
            if best is not None:
                best["session_date"] = d
                rows.append(best)
        rows.sort(key=lambda r: r.get("session_date", ""))
        return rows
    except Exception:
        log.exception("load_intraday_at_time_of_day failed")
        return []
