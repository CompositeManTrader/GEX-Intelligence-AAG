"""
Charles Schwab OAuth — token refresh + authorization-code exchange.

Session-state writes are centralized here; UI screens just call these APIs.
"""
from __future__ import annotations

import base64
import datetime
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
import streamlit as st

from config import (
    SS,
    SCHWAB_AUTH_URL,
    SCHWAB_TOKEN_URL,
    TOKEN_REFRESH_MARGIN_S,
    get_logger,
    utcnow,
)

log = get_logger("auth.schwab")


def build_auth_url(app_key: str, callback_url: str) -> str:
    return f"{SCHWAB_AUTH_URL}?{urlencode({'client_id': app_key, 'redirect_uri': callback_url})}"


def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        return st.secrets[key]
    except Exception:
        return default


def _basic_auth(app_key: str, app_secret: str) -> str:
    return base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()


def refresh_access_token() -> None:
    tok = st.session_state.get(SS.TOKENS, {})
    if not tok:
        return
    expiry = tok.get("expiry")
    # Sentinel for "expiry unknown" must be a finite tz-aware datetime in
    # the past — using `datetime.min` (year 1) overflows when the line
    # below subtracts the refresh margin (`expiry - timedelta(60s)` →
    # year 0 → OverflowError → crash on every API call). Subtracting one
    # day from now is safe, well-defined, and still triggers the refresh
    # branch below.
    now = utcnow()
    if expiry is None:
        expiry = now - datetime.timedelta(days=1)
    elif expiry.tzinfo is None:
        # Naïve expiry on disk → treat as UTC explicitly. Don't silently
        # assume local tz, that has bitten this code before.
        expiry = expiry.replace(tzinfo=datetime.timezone.utc)

    if now < expiry - datetime.timedelta(seconds=TOKEN_REFRESH_MARGIN_S):
        return

    try:
        creds = _basic_auth(st.session_state[SS.APP_KEY],
                            st.session_state[SS.APP_SECRET])
        r = requests.post(
            SCHWAB_TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token",
                  "refresh_token": tok["refresh_token"]},
            timeout=15,
        )
    except requests.RequestException as exc:
        # Transient network error — DO NOT log the user out. Leave the
        # current (still valid for the margin) token in place; the next
        # call will retry. Wiping tokens on every blip caused logout
        # storms during minor connectivity hiccups.
        log.warning("Token refresh network error (transient): %s", exc)
        return

    # Distinguish hard auth errors (401/400 invalid_grant) from transient
    # 5xx so we only force re-login on the former.
    # 4xx of ANY kind = hard auth failure (the legacy code only listed
    # 400/401/403; codes like 422/451 fell through to `raise_for_status`
    # inside the try block, were caught and treated as transient → the
    # session zombied with an expired token and every subsequent
    # `_api_get` 401-spammed without recovery). Treat the whole 4xx
    # range as hard so the user sees the prompt to reconnect.
    if 400 <= r.status_code < 500:
        log.error("Token refresh hard-auth failure %s: %s",
                  r.status_code, r.text[:200])
        st.error("Sesión Schwab expirada. Reconéctate.")
        st.session_state.pop(SS.TOKENS, None)
        st.session_state.pop(SS.CONNECTED, None)
        st.rerun()
        return
    if r.status_code >= 500:
        log.warning("Token refresh transient %s — keeping current token",
                    r.status_code)
        return
    try:
        new = r.json()
        # Guard `expires_in == 0` (Schwab edge case) → would cause the
        # token to expire instantly → refresh loop on next `_api_get`.
        expires_in = max(int(new.get("expires_in") or 0), 60)
        tok.update({
            "access_token": new["access_token"],
            "refresh_token": new.get("refresh_token", tok["refresh_token"]),
            "expiry": utcnow() + datetime.timedelta(seconds=expires_in),
        })
        st.session_state[SS.TOKENS] = tok
    except Exception:
        log.exception("Token refresh parse failure (status=%s)", r.status_code)
        # Treat malformed response as transient; don't force-logout.
        return


def try_auto_connect() -> bool:
    if st.session_state.get(SS.CONNECTED):
        return True
    app_key = get_secret("APP_KEY")
    app_secret = get_secret("APP_SECRET")
    refresh_tok = get_secret("REFRESH_TOKEN")
    if not all([app_key, app_secret, refresh_tok]):
        return False
    try:
        creds = _basic_auth(app_key, app_secret)
        r = requests.post(
            SCHWAB_TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_tok},
            timeout=15,
        )
        r.raise_for_status()
        tok = r.json()
        st.session_state[SS.APP_KEY] = app_key
        st.session_state[SS.APP_SECRET] = app_secret
        st.session_state[SS.CALLBACK_URL] = get_secret("CALLBACK_URL", "https://127.0.0.1")
        st.session_state[SS.TOKENS] = {
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token", refresh_tok),
            "expiry": utcnow() + datetime.timedelta(seconds=tok.get("expires_in", 1800)),
        }
        st.session_state[SS.CONNECTED] = True
        return True
    except Exception:
        log.exception("auto-connect failed")
        return False


def finish_oauth(redirect_url: str) -> bool:
    parsed = urlparse(redirect_url.strip())
    params = parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    if not code:
        st.error("No se encontró `?code=` en la URL.")
        return False
    return exchange_code(code)


def exchange_code(code: str) -> bool:
    callback = st.session_state.get(SS.CALLBACK_URL) or get_secret("CALLBACK_URL", "https://127.0.0.1")
    app_key = st.session_state.get(SS.APP_KEY) or get_secret("APP_KEY")
    app_secret = st.session_state.get(SS.APP_SECRET) or get_secret("APP_SECRET")
    if not app_key or not app_secret:
        st.error("No se encontraron APP_KEY / APP_SECRET.")
        return False
    try:
        creds = _basic_auth(app_key, app_secret)
        r = requests.post(
            SCHWAB_TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "authorization_code",
                  "code": code, "redirect_uri": callback},
            timeout=15,
        )
    except Exception as exc:
        log.exception("token exchange network error")
        st.error(f"Error de red: {exc}")
        return False
    if not r.ok:
        log.error("exchange failed %s %s", r.status_code, r.text[:200])
        st.error(f"Schwab HTTP {r.status_code}: `{r.text}`")
        if "invalid_grant" in r.text:
            st.warning("**Código expirado** (~30s de vida). Reintenta.")
        return False
    tok = r.json()
    st.session_state.update({
        SS.APP_KEY: app_key, SS.APP_SECRET: app_secret,
        SS.CALLBACK_URL: callback, SS.CONNECTED: True,
        SS.TOKENS: {
            "access_token": tok["access_token"],
            "refresh_token": tok["refresh_token"],
            "expiry": utcnow() + datetime.timedelta(seconds=tok.get("expires_in", 1800)),
        },
    })
    return True
