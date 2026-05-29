#!/usr/bin/env python3
"""
Interactive helper to mint a Schwab REFRESH TOKEN from the terminal.

You need this token for the EM tracker's GitHub Actions secret
(SCHWAB_REFRESH_TOKEN). It runs the standard Schwab OAuth flow without
Streamlit:

    1. Prints the Schwab authorization URL.
    2. You open it, log in, approve. Schwab redirects your browser to
       your callback URL with a `?code=...` in the address bar.
    3. You paste that FULL redirected URL back here.
    4. The script exchanges the code and prints your refresh token.

Usage
-----
    python -m scripts.get_refresh_token

It will prompt for APP_KEY / APP_SECRET / CALLBACK_URL, OR read them
from environment variables:

    SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_CALLBACK_URL

Notes
-----
  · The callback URL must EXACTLY match what's registered in your Schwab
    developer app (commonly https://127.0.0.1).
  · The `code` expires ~30 seconds after the redirect — paste promptly.
  · Schwab refresh tokens last 7 days; re-run this weekly to refresh the
    GitHub secret. (Schwab platform limitation, not a bug.)
"""
from __future__ import annotations

import base64
import os
import sys
from urllib.parse import parse_qs, urlencode, urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SCHWAB_AUTH_URL, SCHWAB_TOKEN_URL  # noqa: E402


def _prompt(label: str, env: str, default: str = "") -> str:
    val = os.environ.get(env)
    if val:
        print(f"  {label}: (from ${env})")
        return val
    suffix = f" [{default}]" if default else ""
    got = input(f"  {label}{suffix}: ").strip()
    return got or default


def main() -> int:
    print("\n=== Schwab Refresh Token Helper ===\n")
    print("Enter your Schwab app credentials (or set them as env vars):\n")

    app_key = _prompt("APP_KEY", "SCHWAB_APP_KEY")
    app_secret = _prompt("APP_SECRET", "SCHWAB_APP_SECRET")
    callback = _prompt("CALLBACK_URL", "SCHWAB_CALLBACK_URL",
                       "https://127.0.0.1")

    if not app_key or not app_secret:
        print("\nERROR: APP_KEY and APP_SECRET are required.")
        return 2

    # Step 1 — authorization URL
    auth_url = f"{SCHWAB_AUTH_URL}?{urlencode({'client_id': app_key, 'redirect_uri': callback})}"
    print("\n" + "─" * 70)
    print("STEP 1 — Open this URL in your browser, log in, and approve:\n")
    print(auth_url)
    print("\n" + "─" * 70)
    print("STEP 2 — After approving, your browser redirects to your")
    print("callback URL with a `?code=...` in the address bar. It may show")
    print("a 'site can't be reached' page — that's fine, the code is still")
    print("in the URL bar. Copy the ENTIRE URL from the address bar.\n")

    redirect_url = input("Paste the full redirected URL here:\n  ").strip()
    if not redirect_url:
        print("\nERROR: no URL pasted.")
        return 2

    # Extract the code
    parsed = urlparse(redirect_url)
    code = parse_qs(parsed.query).get("code", [None])[0]
    if not code:
        print("\nERROR: no `?code=` found in that URL. Make sure you copied")
        print("the FULL redirected URL (the one after you approved).")
        return 2

    # Step 3 — exchange code for tokens
    creds = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    print("\nExchanging code for tokens…")
    r = requests.post(
        SCHWAB_TOKEN_URL,
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code",
              "code": code, "redirect_uri": callback},
        timeout=20,
    )
    if not r.ok:
        print(f"\nERROR: token exchange HTTP {r.status_code}")
        print(r.text[:400])
        if "invalid_grant" in r.text:
            print("\n→ The code likely expired (~30s lifetime). Re-run and")
            print("  paste the URL faster.")
        return 1

    tok = r.json()
    refresh = tok.get("refresh_token")
    access = tok.get("access_token")
    if not refresh:
        print("\nERROR: no refresh_token in response:")
        print(r.text[:400])
        return 1

    print("\n" + "=" * 70)
    print("✅ SUCCESS — copy this into your GitHub secret SCHWAB_REFRESH_TOKEN:\n")
    print(refresh)
    print("\n" + "=" * 70)
    print(f"(access_token also issued, valid ~{tok.get('expires_in', 1800)}s — "
          "you don't need it for the secret.)")
    print("Reminder: this refresh token expires in 7 days. Re-run weekly.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
