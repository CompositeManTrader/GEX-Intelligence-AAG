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


def fetch_chain_headless(token: str, symbol: str, days: int = 7) -> dict:
    today = datetime.date.today()
    r = requests.get(
        f"{SCHWAB_BASE_URL}/marketdata/v1/chains",
        headers={"Authorization": f"Bearer {token}"},
        params={"symbol": symbol, "contractType": "ALL",
                "strikeCount": 80, "includeUnderlyingQuote": "true",
                "fromDate": today.isoformat(),
                "toDate": (today + datetime.timedelta(days=days)).isoformat()},
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


def _market_is_open_now() -> bool:
    """RTH guard for the orderflow recorder: 09:28–16:06 ET, Mon–Fri.
    The cron fires blindly every 10 minutes; this guard makes off-hours
    fires exit cleanly (exit 0, nothing written)."""
    now = datetime.datetime.now(ET_TZ)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return (9 * 60 + 28) <= mins <= (16 * 60 + 6)


def run_orderflow(symbols: list[str]) -> int:
    """Snapshot dealer exposures + walls + per-strike 0DTE activity and
    persist them (Neon/SQLite via data.of_store). One row per fire — this
    is what gives the Orderflow tab a FULL session of history even when
    the dashboard was never opened."""
    if not _market_is_open_now():
        _log("market closed — orderflow snapshot skipped")
        return 0
    import pandas as pd
    from quant.exposures import (
        compute_cex_profile, compute_dex_profile, compute_gex_profile,
        compute_vex_profile,
    )
    from data import of_store

    token = get_access_token()
    of_store.init_db()
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rc = 0
    for sym in symbols:
        data = fetch_chain_headless(token, sym, days=60)
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

        # Aggregate exposures (0–60d) with the true spot-grid flip.
        _, g = compute_gex_profile(calls, puts, spot, symbol=sym,
                                   max_dte=60, use_spot_grid_flip=True)
        _, d = compute_dex_profile(calls, puts, spot, max_dte=60)
        _, v = compute_vex_profile(calls, puts, spot, symbol=sym, max_dte=60)
        _, x = compute_cex_profile(calls, puts, spot, symbol=sym, max_dte=60)
        # 0DTE bucket (today's expiry only).
        g0_df, g0 = compute_gex_profile(calls, puts, spot, symbol=sym,
                                        max_dte=0, min_dte=0,
                                        use_spot_grid_flip=False)

        def mm(s, k):
            val = (s or {}).get(k)
            return round(float(val) / 1e6, 2) if val is not None else None

        tick = {
            "symbol": sym, "ts": ts, "spot": round(spot, 4),
            "net_gex_mm": mm(g, "total_gex"),
            "call_gex_mm": mm(g, "call_gex"), "put_gex_mm": mm(g, "put_gex"),
            "call_wall": (g or {}).get("call_wall"),
            "put_wall": (g or {}).get("put_wall"),
            "gamma_flip": (g or {}).get("gamma_flip"),
            "hvl": (g or {}).get("hvl"), "regime": (g or {}).get("regime"),
            "net_dex_mm": mm(d, "total_dex"),
            "net_vex_mm": mm(v, "total_vex"),
            "net_cex_mm": mm(x, "total_cex"),
            "gex_0dte_mm": mm(g0, "total_gex"),
            "call_wall_0dte": (g0 or {}).get("call_wall"),
            "put_wall_0dte": (g0 or {}).get("put_wall"),
            "hvl_0dte": (g0 or {}).get("hvl"),
        }

        # Per-strike 0DTE rows near the spot (±3%) — OI + cumulative volume
        # per side, so the dashboard can compute Δvolume (the intraday flow
        # proxy; OI itself only updates overnight).
        strikes: list[dict] = []
        gex_by_strike = {}
        if g0_df is not None and not g0_df.empty:
            gex_by_strike = dict(zip(g0_df["Strike"], g0_df["Net_GEX"]))
        lo, hi = spot * 0.97, spot * 1.03
        for df_side, oi_key, vol_key in ((calls, "call_oi", "call_vol"),
                                         (puts, "put_oi", "put_vol")):
            if df_side.empty or "DTE" not in df_side.columns:
                continue
            d0 = df_side[pd.to_numeric(df_side["DTE"], errors="coerce") == 0]
            d0 = d0[(d0["Strike"] >= lo) & (d0["Strike"] <= hi)]
            for _, row in d0.iterrows():
                k = float(row["Strike"])
                entry = next((s for s in strikes if s["strike"] == k), None)
                if entry is None:
                    entry = {"symbol": sym, "ts": ts, "strike": k,
                             "net_gex_mm": (round(gex_by_strike.get(k, 0.0)
                                            / 1e6, 2)
                                            if gex_by_strike else None),
                             "call_oi": 0.0, "put_oi": 0.0,
                             "call_vol": 0.0, "put_vol": 0.0}
                    strikes.append(entry)
                entry[oi_key] = float(row.get("OI") or 0)
                entry[vol_key] = float(row.get("Volume") or 0)

        inserted = of_store.record_tick(tick, strikes)
        _log(f"{sym}: orderflow tick {'STORED' if inserted else 'dup'} · "
             f"netGEX={tick['net_gex_mm']}M 0dte={tick['gex_0dte_mm']}M "
             f"CW={tick['call_wall']} PW={tick['put_wall']} "
             f"strikes={len(strikes)}")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["predict", "settle", "orderflow"],
                    required=True)
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in
               os.environ.get("EM_SYMBOLS", "SPY").split(",") if s.strip()]
    _log(f"mode={args.mode} symbols={symbols} "
         f"backend={em_store.backend_info()['backend']}")
    if args.mode == "predict":
        return run_predict(symbols)
    if args.mode == "orderflow":
        return run_orderflow(symbols)
    return run_settle(symbols)


if __name__ == "__main__":
    sys.exit(main())
