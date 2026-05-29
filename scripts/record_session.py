#!/usr/bin/env python3
"""
Headless session recorder for the EM accuracy tracker.

Runs WITHOUT Streamlit — designed for GitHub Actions cron (or any
scheduler). Two modes:

    python -m scripts.record_session --mode predict   # ~09:35 ET
    python -m scripts.record_session --mode settle    # ~16:05 ET

predict : authenticate to Schwab with the refresh token, fetch the 0DTE
          chain, build the RND, and store today's prediction (first of
          the day wins — INSERT OR IGNORE / ON CONFLICT DO NOTHING).

settle  : fetch the latest quote, and settle any pending predictions
          whose session date is today (or earlier) using the close.

Environment variables (set as GitHub Secrets):
    SCHWAB_APP_KEY
    SCHWAB_APP_SECRET
    SCHWAB_REFRESH_TOKEN
    DATABASE_URL          (Neon Postgres connection string)
    EM_SYMBOLS            (comma-sep, default "SPY")

Exit codes: 0 = ok, 1 = auth/fetch failure, 2 = config error.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import os
import sys

import requests

# Make the repo root importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ET_TZ, SCHWAB_TOKEN_URL, SCHWAB_BASE_URL  # noqa: E402
from data.parse import clean, parse_chain  # noqa: E402
from quant.rnd import build_rnd, rnd_levels  # noqa: E402
from quant.em_tracker import build_prediction, settle_record  # noqa: E402
from data import em_store  # noqa: E402


def _log(msg: str) -> None:
    ts = datetime.datetime.now(ET_TZ).strftime("%Y-%m-%d %H:%M:%S ET")
    print(f"[{ts}] {msg}", flush=True)


def _today_et() -> str:
    return datetime.datetime.now(ET_TZ).date().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
#  Schwab auth + fetch (no Streamlit)
# ─────────────────────────────────────────────────────────────────────────────
def get_access_token() -> str:
    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_APP_SECRET")
    refresh = os.environ.get("SCHWAB_REFRESH_TOKEN")
    if not all([app_key, app_secret, refresh]):
        _log("ERROR: missing SCHWAB_APP_KEY / APP_SECRET / REFRESH_TOKEN")
        sys.exit(2)
    creds = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    r = requests.post(
        SCHWAB_TOKEN_URL,
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": refresh},
        timeout=20,
    )
    if r.status_code != 200:
        _log(f"ERROR: token refresh HTTP {r.status_code}: {r.text[:200]}")
        _log("If this is a 400 invalid_grant, the refresh token expired "
             "(Schwab 7-day limit) — re-auth in the dashboard and update "
             "the SCHWAB_REFRESH_TOKEN secret.")
        sys.exit(1)
    return r.json()["access_token"]


def fetch_chain_headless(token: str, symbol: str) -> dict:
    today = datetime.date.today()
    r = requests.get(
        f"{SCHWAB_BASE_URL}/marketdata/v1/chains",
        headers={"Authorization": f"Bearer {token}"},
        params={"symbol": symbol, "contractType": "ALL",
                "strikeCount": 80, "includeUnderlyingQuote": "true",
                "fromDate": today.isoformat(),
                "toDate": (today + datetime.timedelta(days=7)).isoformat()},
        timeout=20,
    )
    if r.status_code != 200:
        _log(f"ERROR: chain HTTP {r.status_code} for {symbol}: {r.text[:200]}")
        return {}
    return r.json()


def _spot_from_underlying(ul: dict) -> float:
    for k in ("last", "mark", "close"):
        v = ul.get(k)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  Modes
# ─────────────────────────────────────────────────────────────────────────────
def run_predict(symbols: list[str]) -> int:
    token = get_access_token()
    em_store.init_db()
    date_iso = _today_et()
    snapshot_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rc = 0
    for sym in symbols:
        data = fetch_chain_headless(token, sym)
        if not data:
            rc = 1
            continue
        calls_raw, puts_raw, ul = parse_chain(data)
        calls = clean(calls_raw)
        puts = clean(puts_raw)
        spot = _spot_from_underlying(ul)
        if spot <= 0 or calls.empty:
            _log(f"{sym}: no spot/calls — skipped")
            continue
        # 0DTE filter
        if "DTE" in calls.columns:
            import pandas as pd
            c0 = calls[pd.to_numeric(calls["DTE"], errors="coerce") == 0]
            p0 = puts[pd.to_numeric(puts["DTE"], errors="coerce") == 0] if not puts.empty else puts
        else:
            c0, p0 = calls, puts
        if c0.empty:
            _log(f"{sym}: no 0DTE strikes today — skipped")
            continue
        rnd, meta = build_rnd(c0, p0, spot=spot, dte=0)
        if rnd is None:
            _log(f"{sym}: RND build failed — skipped")
            continue
        lv = rnd_levels(rnd, spot=spot)
        rec = build_prediction(sym, date_iso, snapshot_ts, spot, 0, lv, meta)
        if rec is None:
            _log(f"{sym}: incomplete RND levels — skipped")
            continue
        inserted = em_store.record_prediction(rec)
        _log(f"{sym}: prediction {'STORED' if inserted else 'already exists'} "
             f"· spot={spot:.2f} P10={lv['percentiles']['p10']:.2f} "
             f"P90={lv['percentiles']['p90']:.2f} method={meta.get('method')}")
    return rc


def run_settle(symbols: list[str]) -> int:
    token = get_access_token()
    em_store.init_db()
    today = _today_et()
    rc = 0
    for sym in symbols:
        # latest quote → close proxy
        r = requests.get(
            f"{SCHWAB_BASE_URL}/marketdata/v1/quotes",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbols": sym}, timeout=20,
        )
        if r.status_code != 200:
            _log(f"{sym}: quote HTTP {r.status_code} — skipped settle")
            rc = 1
            continue
        q = (r.json().get(sym, {}) or {}).get("quote", {}) or {}
        close = q.get("lastPrice") or q.get("closePrice") or q.get("mark")
        if not close:
            _log(f"{sym}: no close in quote — skipped")
            continue
        close = float(close)
        pending = em_store.load_pending(sym)
        for rec in pending:
            # Only settle rows whose date is today or earlier
            if str(rec.get("date")) > today:
                continue
            fields = settle_record(rec, close)
            ok = em_store.settle(sym, str(rec.get("date")), fields)
            verdict = "INSIDE" if fields["inside_p10_p90"] else "OUTSIDE"
            _log(f"{sym} {rec.get('date')}: settled close={close:.2f} "
                 f"P10-P90 {verdict} ({'ok' if ok else 'no-row'})")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["predict", "settle"], required=True)
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in
               os.environ.get("EM_SYMBOLS", "SPY").split(",") if s.strip()]
    _log(f"mode={args.mode} symbols={symbols} "
         f"backend={em_store.backend_info()['backend']}")
    return run_predict(symbols) if args.mode == "predict" else run_settle(symbols)


if __name__ == "__main__":
    sys.exit(main())
