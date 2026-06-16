"""
Diagnóstico de la fuente de gamma — ¿con qué T calcula Schwab su gamma?

El perfil GEX usa la gamma REPORTADA por Schwab (no la recalcula). Para 0DTE
eso importa muchísimo porque gamma ∝ 1/√T: si Schwab floorea la T (p.ej. a 1
día calendario) en vez de usar las horas reales que faltan al cierre, el GEX
0DTE queda subvaluado varias veces.

Esta utilidad back-solvea la T IMPLÍCITA en la gamma de Schwab (para strikes
near-ATM, donde gamma es monótona decreciente en T) y la compara con la T
intradía real. Si T_implícita ≈ T_intradía → Schwab usa la convención correcta.
Si T_implícita ≈ 1/365 (o más) → Schwab floorea y el modelo debe recalcular.

Puro y testeable: no toca red ni Streamlit.
"""
from __future__ import annotations

from typing import Optional

from quant import bs

try:
    from scipy.optimize import brentq
except Exception:  # pragma: no cover
    brentq = None


def implied_T_from_gamma(g_obs: float, S: float, K: float, iv: float,
                         r: float = 0.045, q: float = 0.0,
                         lo: float = 1e-7, hi: float = 0.05) -> Optional[float]:
    """T (años) que reproduce la gamma observada `g_obs` bajo Black-Scholes.

    Válido para strikes NEAR-ATM, donde gamma decrece monótonamente en T
    (gamma_ATM ∝ 1/√T). Para OTM lejano gamma no es monótona → devuelve None
    si no hay raíz acotada. Devuelve None ante inputs no físicos.
    """
    if brentq is None:
        return None
    if not (g_obs and g_obs > 0 and iv and iv > 0 and S and S > 0 and K and K > 0):
        return None

    def f(T: float) -> float:
        return float(bs.gamma(S, K, T, iv, r, q)) - g_obs

    try:
        if f(lo) * f(hi) > 0:
            return None
        return float(brentq(f, lo, hi, maxiter=100))
    except Exception:
        return None


def gamma_scale_factor(T_intraday: float, T_implied: Optional[float]) -> Optional[float]:
    """Cuánto habría que escalar la gamma de Schwab para llevarla a la T
    intradía. gamma ∝ 1/√T → factor = sqrt(T_implied / T_intraday).
    >1 significa que el GEX está subvaluado por ese factor."""
    if not T_implied or not T_intraday or T_intraday <= 0:
        return None
    return float((T_implied / T_intraday) ** 0.5)
