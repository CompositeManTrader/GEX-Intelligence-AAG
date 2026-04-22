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
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown(
            """
            <div style="text-align:center;margin-bottom:1.2rem;">
              <span style="font-size:3.2rem;color:#f97316;">🔒</span>
              <h1 style="font-family:'JetBrains Mono',monospace;font-size:1.4rem;
                   font-weight:800;letter-spacing:0.08em;color:#e0e0f0;margin:0.4rem 0 0.2rem;">
                 OPTIONS TERMINAL
              </h1>
              <p style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;
                   color:#7070a0;margin:0;">Acceso restringido</p>
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

        st.markdown(
            """
            <p style="font-size:0.66rem;color:#505070;text-align:center;
                 font-family:'JetBrains Mono',monospace;margin-top:1rem;">
              La contraseña se configura en <b>Streamlit Secrets</b>
              (<code>APP_PASSWORD</code> o <code>[APP_USERS]</code>).
            </p>
            """,
            unsafe_allow_html=True,
        )
