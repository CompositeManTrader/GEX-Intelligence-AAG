"""
Password gate — lightweight auth layer on top of the dashboard.

Credentials live in Streamlit Secrets (editable without code deploy):

    # .streamlit/secrets.toml   (or Streamlit Cloud → Settings → Secrets)

    # --- Single shared password (simplest) ---
    APP_PASSWORD = "tu_password_aqui"

    # --- Multi-user mode (overrides APP_PASSWORD if both present) ---
    [APP_USERS]
    alice = "pass_alice"
    bob   = "pass_bob"
    carol = "pass_carol"

Behaviour:
  * If no password configured → gate is a no-op (dev mode, with a warning).
  * Single-password mode → just the password field.
  * Multi-user mode → username + password fields, logs which user entered.
  * Correct credentials → `st.session_state["_auth_ok"] = True` + rerun.
  * Wrong → stays on the gate, increments attempt counter.
  * Uses `hmac.compare_digest` to avoid timing attacks.
"""
from __future__ import annotations

import hmac
from typing import Optional

import streamlit as st

from auth.schwab import get_secret


_AUTH_OK = "_auth_ok"
_AUTH_USER = "_auth_user"
_AUTH_ATTEMPTS = "_auth_attempts"


def _get_single_password() -> Optional[str]:
    pw = get_secret("APP_PASSWORD", None)
    return pw.strip() if pw else None


def _get_users_map() -> dict[str, str]:
    """Return the multi-user map if configured, else {}."""
    try:
        users = st.secrets.get("APP_USERS", {})
        if not users:
            return {}
        # Coerce to dict[str, str]
        return {str(k): str(v) for k, v in dict(users).items()}
    except Exception:
        return {}


def _check_single(pw_input: str, pw_secret: str) -> bool:
    return hmac.compare_digest(pw_input.encode(), pw_secret.encode())


def _check_multi(user: str, pw: str, users: dict[str, str]) -> bool:
    expected = users.get(user)
    if not expected:
        return False
    return hmac.compare_digest(pw.encode(), expected.encode())


def is_authenticated() -> bool:
    return bool(st.session_state.get(_AUTH_OK))


def current_user() -> str:
    return st.session_state.get(_AUTH_USER, "")


def logout() -> None:
    st.session_state.pop(_AUTH_OK, None)
    st.session_state.pop(_AUTH_USER, None)
    st.session_state.pop(_AUTH_ATTEMPTS, None)


def require_login() -> bool:
    """Render the login UI if the user is not authenticated.

    Returns True if the gate passes (the caller can continue).
    Returns False if the gate is blocking (caller should NOT render the app).
    """
    if is_authenticated():
        return True

    single = _get_single_password()
    users = _get_users_map()

    # ── No password configured → dev bypass + warning ──
    if not single and not users:
        st.session_state[_AUTH_OK] = True
        st.session_state[_AUTH_USER] = "dev"
        st.warning(
            "🔓 No hay contraseña configurada — acceso abierto. "
            "Agrega `APP_PASSWORD = \"...\"` en Streamlit Secrets para proteger la app.",
            icon="⚠",
        )
        return True

    # ── Gate UI ──
    _render_gate(single, users)
    return False


def _render_gate(single: Optional[str], users: dict[str, str]) -> None:
    multi = bool(users)
    # Inject the app CSS so the gate matches the brand (without it the
    # primary button renders in the default RED theme colour — alarming on a
    # login screen — and the brand fonts never load).
    from ui.styles import CSS
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown(
            """
            <div style="text-align:center;margin-bottom:1.2rem;">
              <div style="display:flex;justify-content:center;align-items:center;gap:11px;margin-bottom:0.45rem;">
              <svg viewBox="0 0 64 64" width="42" height="42" style="flex-shrink:0" aria-label="Spread Trading Club">
                <path d="M6 50 C 18 50, 24 16, 32 15 C 40 16, 46 50, 58 50" fill="none" stroke="#F5A623" stroke-width="6" stroke-linecap="round"/>
                <line x1="24" y1="49" x2="24" y2="27" stroke="#F4F5F6" stroke-width="4.2"/>
                <line x1="40" y1="49" x2="40" y2="27" stroke="#F4F5F6" stroke-width="4.2"/>
                <circle cx="24" cy="27" r="4" fill="#F4F5F6"/>
                <circle cx="40" cy="27" r="4" fill="#F4F5F6"/>
              </svg>
              <span style="color:#F4F5F6;font-family:'Space Grotesk',system-ui,sans-serif;font-size:1.9rem;font-weight:700;letter-spacing:0.04em;line-height:1;">GEX</span>
              <span class="brand-cursor" style="width:13px;height:1.6rem;"></span>
              </div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:0.58rem;
                   color:#9AA1A9;letter-spacing:0.28em;margin-bottom:0.5rem;">SPREAD&nbsp;·&nbsp;TRADING&nbsp;·&nbsp;CLUB</div>
              <p style="font-family:'Inter',system-ui,sans-serif;font-size:0.78rem;
                   color:#7070a0;margin:0;">🔒 Acceso restringido</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("auth_form", clear_on_submit=False):
            user_val = ""
            if multi:
                user_val = st.text_input(
                    "Usuario",
                    key="_auth_user_input",
                    placeholder="tu usuario",
                )
            pw_val = st.text_input(
                "Contraseña",
                type="password",
                key="_auth_pw_input",
                placeholder="••••••••",
            )
            submitted = st.form_submit_button(
                "ENTRAR →", type="primary", use_container_width=True,
            )

        attempts = int(st.session_state.get(_AUTH_ATTEMPTS, 0))

        if submitted:
            ok = False
            who = ""
            if multi:
                if user_val and pw_val and _check_multi(user_val, pw_val, users):
                    ok = True
                    who = user_val
            elif single:
                if pw_val and _check_single(pw_val, single):
                    ok = True
                    who = "user"

            if ok:
                st.session_state[_AUTH_OK] = True
                st.session_state[_AUTH_USER] = who
                st.session_state.pop(_AUTH_ATTEMPTS, None)
                st.rerun()
            else:
                st.session_state[_AUTH_ATTEMPTS] = attempts + 1
                st.error(
                    f"❌ Credenciales incorrectas. "
                    f"Intentos: {attempts + 1}",
                    icon="🚫",
                )

        # (Developer hint about APP_PASSWORD/Secrets removed from the login
        # screen — it confused end users; the setup doc covers it.)
