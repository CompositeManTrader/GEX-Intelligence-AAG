"""
Volume Trigger (VT) y Call Bridge (CB) — niveles basados en la actividad de la
SESIÓN, no en el posicionamiento acumulado del Open Interest.

Distinción clave (estilo ScalpingAgresivo / mesas de flujo):
  · Los muros (call_wall, put_wall) y el HVL salen del OI — posicionamiento
    acumulado del cierre anterior (estructura "vieja").
  · El Volume Trigger sale del VOLUMEN negociado HOY — dinero que entra en
    tiempo real durante la sesión.

  VT-C : strike de CALLS con mayor volumen de sesión (imán/atención al alza).
  VT-P : strike de PUTS  con mayor volumen de sesión (imán/atención a la baja).
  Ratio de dominancia : qué lado (calls/puts) concentra más volumen total y
    por cuánto (ej. "VT-C 1.5×" = los calls mueven 1.5× el volumen de los puts).

  Call Bridge (CB) : strike con mayor OI TOTAL (calls + puts). No es un nivel
    de gamma sino de LIQUIDEZ — suele ser un número redondo que los
    institucionales usan de referencia. (Distinto de max-pain.)

Funciones puras: reciben los DataFrames de la cadena (con columnas Strike,
Volume, OI) ya filtrados al alcance deseado (0DTE o agregado) y devuelven
escalares. Sin dependencias del resto del modelo.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def _by_strike(df: Optional[pd.DataFrame], col: str) -> Optional[pd.Series]:
    """Suma `col` por strike. None si no hay datos utilizables."""
    if df is None or df.empty or "Strike" not in df.columns or col not in df.columns:
        return None
    s = (df[[("Strike"), col]]
         .assign(**{col: pd.to_numeric(df[col], errors="coerce").fillna(0)})
         .groupby("Strike")[col].sum())
    return s if not s.empty else None


def volume_trigger(calls: Optional[pd.DataFrame],
                   puts: Optional[pd.DataFrame]) -> dict:
    """VT-C / VT-P (strike de mayor volumen por lado) + ratio de dominancia.

    Devuelve siempre las mismas claves (con None cuando no hay volumen), para
    que el resumen GEX las pueda incorporar sin condicionales.
    """
    out = {"vt_c": None, "vt_p": None, "vt_c_vol": None, "vt_p_vol": None,
           "vt_dom_side": None, "vt_dom_ratio": None}

    c = _by_strike(calls, "Volume")
    p = _by_strike(puts, "Volume")
    if c is not None and float(c.max()) > 0:
        out["vt_c"] = float(c.idxmax())
        out["vt_c_vol"] = int(c.max())
    if p is not None and float(p.max()) > 0:
        out["vt_p"] = float(p.idxmax())
        out["vt_p_vol"] = int(p.max())

    cvol = float(c.sum()) if c is not None else 0.0
    pvol = float(p.sum()) if p is not None else 0.0
    if cvol > 0 and pvol > 0:
        if cvol >= pvol:
            out["vt_dom_side"] = "C"
            out["vt_dom_ratio"] = round(cvol / pvol, 2)
        else:
            out["vt_dom_side"] = "P"
            out["vt_dom_ratio"] = round(pvol / cvol, 2)
    return out


def call_bridge(calls: Optional[pd.DataFrame],
                puts: Optional[pd.DataFrame]) -> Optional[float]:
    """Strike con mayor OI TOTAL (calls + puts) — nivel de liquidez."""
    c = _by_strike(calls, "OI")
    p = _by_strike(puts, "OI")
    if c is None and p is None:
        return None
    total = None
    if c is not None and p is not None:
        total = c.add(p, fill_value=0)
    else:
        total = c if c is not None else p
    if total is None or total.empty or float(total.max()) <= 0:
        return None
    return float(total.idxmax())


def vt_dominance_label(gex_sum: Optional[dict]) -> Optional[dict]:
    """Helper de presentación: traduce el ratio de dominancia a etiqueta/color.
    Devuelve {text, color, side} o None."""
    if not gex_sum:
        return None
    side = gex_sum.get("vt_dom_side")
    ratio = gex_sum.get("vt_dom_ratio")
    if not side or not ratio:
        return None
    if side == "C":
        return {"text": f"VT-C {ratio:.1f}× · calls dominan el volumen",
                "color": "#22c55e", "side": "C"}
    return {"text": f"VT-P {ratio:.1f}× · puts dominan el volumen",
            "color": "#f43f5e", "side": "P"}
