# EM Accuracy Tracker — Setup (GitHub Actions + Neon)

The tracker records, **every session and automatically**, the range the
RND model predicted at the open and whether the actual close landed
inside it — **without you opening the dashboard**. It runs on GitHub
Actions (free) and stores data in Neon Postgres (free, private).

This file is the one-time setup. After it, everything is automatic
**except a ~1-minute weekly Schwab re-login** (a Schwab limitation, see
the last section).

---

## What runs, and when

| Cron (UTC) | ET time | Mode |
|---|---|---|
| 13:35 / 14:35 Mon–Fri | ~09:35 ET | `predict` — store today's RND prediction |
| 20:05 / 21:05 Mon–Fri | ~16:05 ET | `settle` — record the close, check if inside bands |

(Two slots each because GitHub cron is UTC-only; the extra one covers
EST vs EDT. The code's INSERT-OR-IGNORE + date guards make the double
fire harmless.)

---

## Step 1 — Create a free Neon database (~3 min)

1. Go to <https://neon.tech> → sign up (free tier is plenty).
2. Create a project (any name, e.g. `gex-tracker`).
3. On the project dashboard, copy the **connection string**. It looks
   like:
   ```
   postgresql://USER:PASSWORD@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Keep it handy — it's the `DATABASE_URL` secret below.

You do **not** need to create any table — the runner creates it
automatically on first run.

---

## Step 2 — Get your Schwab refresh token

You already have Schwab API credentials (the app uses them). You need
three values:

- `SCHWAB_APP_KEY`     — your app key
- `SCHWAB_APP_SECRET`  — your app secret
- `SCHWAB_REFRESH_TOKEN` — the current refresh token

The refresh token is obtained by completing the OAuth login once (the
dashboard's "Connect Schwab" flow). After connecting, the refresh token
is what persists. If you're not sure where it is, run the dashboard,
connect, and the token lives in your session — or use Schwab's OAuth
playground to mint one.

> ⚠️ Schwab refresh tokens **expire every 7 days** and cannot be renewed
> via API — see the last section.

---

## Step 3 — Add the secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New
repository secret**. Add four secrets:

| Secret name | Value |
|---|---|
| `SCHWAB_APP_KEY` | your app key |
| `SCHWAB_APP_SECRET` | your app secret |
| `SCHWAB_REFRESH_TOKEN` | your current refresh token |
| `DATABASE_URL` | the Neon connection string from Step 1 |

(Optional) Add a **variable** (not secret) `EM_SYMBOLS` = `SPY,QQQ` to
track more than one symbol. Default is `SPY`.

> Secrets are encrypted and are **not** exposed to fork PRs. This
> workflow only runs on `schedule` + manual dispatch from your default
> branch, so the secrets are safe even in a public repo.

---

## Step 4 — Test it manually

1. Repo → **Actions** tab → **EM Accuracy Tracker** → **Run workflow**.
2. Choose `predict`, run it.
3. Check the run log — you should see:
   ```
   SPY: prediction STORED · spot=580.12 P10=577.30 P90=582.80 method=svi
   ```
4. During market hours, run it once with `settle` to verify the close
   path works (it will say "no pending" if there's nothing to settle yet).

After that, the cron schedule takes over — fully automatic.

---

## Step 5 — View the results in the dashboard

In the dashboard, the **Expected Range** tab shows an "EM Accuracy"
section once enough sessions accumulate. For the dashboard to read the
SAME Neon data the runner writes, add `DATABASE_URL` to your Streamlit
secrets too:

- Local: `.streamlit/secrets.toml` →
  ```toml
  DATABASE_URL = "postgresql://...neon.../neondb?sslmode=require"
  ```
- Streamlit Cloud: app → Settings → Secrets → same line.

If you DON'T set `DATABASE_URL` in the dashboard, it falls back to a
local SQLite file (the dashboard and the runner then use separate
stores — fine for testing, but they won't share data).

---

## The Schwab 7-day re-login (the one manual chore)

Schwab refresh tokens expire **7 days** after issue and **cannot be
refreshed via API** — this is a Schwab platform limitation, not a bug.

When the token expires, the runner log will show:
```
ERROR: token refresh HTTP 400 ... invalid_grant
... the refresh token expired (Schwab 7-day limit) — re-auth in the
dashboard and update the SCHWAB_REFRESH_TOKEN secret.
```

**The fix (≈1 minute, once a week):**
1. Open the dashboard, reconnect Schwab (completes OAuth, mints a fresh
   7-day refresh token).
2. Copy the new refresh token.
3. Update the `SCHWAB_REFRESH_TOKEN` secret in GitHub.

That's the only recurring manual step. Everything else is automatic.

> Tip: do it every Monday morning and you'll never hit an expired token
> mid-week.

---

## Cost

- **GitHub Actions**: free (public repo = unlimited minutes; this job
  uses ~1 min × 4 fires/day).
- **Neon**: free tier (0.5 GB — this data is kilobytes/year).
- **Total: $0/month.**
