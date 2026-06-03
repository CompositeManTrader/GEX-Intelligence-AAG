# Model Validation Dossier — GEX Intelligence

> **Propósito.** Cerrar la brecha de *conocimiento* (¿qué calcula cada parte
> del modelo y cómo?) y la brecha de *validación* (¿son correctos esos
> cálculos?) antes de operar dinero real. Este documento es una validación
> de modelo **independiente** al estilo bancario **SR 11-7**, no una simple
> revisión de código.
>
> **Fecha:** 2026-06-03 · **Rama:** `feat/model-validation`
> **Alcance:** todos los módulos cuantitativos de `quant/`.

---

## 0. Qué significa "validación independiente" aquí

Un test que comprueba que el código coincide con su propio docstring **no
valida nada** — solo confirma que dos copias del mismo supuesto concuerdan.
La validación de este dossier se apoya en **tres pilares SR 11-7** y, sobre
todo, en **referencias externas a la base de código**:

| Pilar SR 11-7 | Qué se preguntó | Cómo se respondió aquí |
|---|---|---|
| **1. Solidez conceptual** | ¿La teoría es correcta? | Re-derivación desde primeros principios de cada fórmula no trivial. |
| **2. Verificación de implementación** | ¿El código implementa la teoría? | Comparación contra **`py_vollib`** (librería auditada externa), **diferencias finitas** (definición de la derivada) y **formas cerradas conocidas** (lognormal). |
| **3. Análisis de resultados** | ¿El comportamiento es razonable? | *Property tests* de invariantes matemáticas + análisis de sesgos (look-ahead, etc.). |

**Técnicas concretas de independencia usadas:**
- **`py_vollib`** — implementación Black-Scholes-Merton / Black-76 auditada por
  terceros. Si nuestro griego coincide con el suyo a 1e-9, la implementación
  es correcta con altísima probabilidad.
- **Diferencias finitas** — un griego es *por definición* la derivada del
  precio/otro griego. Comparar la fórmula analítica contra un *bump* numérico
  es independiente de cómo escribimos la fórmula.
- **Formas cerradas** — alimentar al modelo un caso con respuesta analítica
  conocida (smile plano ⇒ densidad lognormal exacta) y exigir que la
  recupere.
- **Invariantes** — propiedades que *deben* cumplirse (una densidad integra a
  1; una densidad riesgo-neutral tiene media = forward; PoT ∈ [0,1]).

Las suites viven en `tests/validation/`. Total: **114 checks de validación**
(67 bs + 18 exposures + 17 rnd + 12 vol), todos en verde, más 244 tests del
repo completo.

```
python -m pytest tests/validation/ -q      # solo la validación de modelo
python -m pytest tests/ -q                  # batería completa (244)
```

---

## 1. Resumen ejecutivo — semáforo de confianza

🟢 VERDE = validado contra referencia independiente, apto para decidir.
🟡 AMARILLO = correcto pero con supuesto/etiqueta/aproximación que debes
conocer antes de usarlo. 🔴 ROJO = error que invalida el output (ninguno
queda abierto tras esta validación).

| Módulo | Función núcleo | Confianza | Evidencia de validación |
|---|---|:---:|---|
| `bs.py` | Δ, Γ, Vanna, Charm, BSM | 🟢 | vs py_vollib + FD (67 checks). **Bug de Charm encontrado y corregido.** |
| `exposures.py` | GEX / VEX / CEX | 🟢 | Ensamblaje re-derivado + escala económica por FD (18 checks). |
| `exposures.py` | **DEX** | 🟡 | Usa delta crudo (call+/put−) **sin** el flip dealer de GEX/VEX/CEX. Es *imbalance direccional del OI*, no inventario dealer. |
| `rnd.py` | Densidad riesgo-neutral (SVI) | 🟢 | **Martingala (media=forward)** + **recupera lognormal exacta** + g(k) Gatheral (17 checks). *Modelo central.* |
| `vol.py` | HV (CC/Parkinson/GK/YZ) | 🟢 | vs fórmulas publicadas + constantes + Monte-Carlo (12 checks). |
| `levels.py` | max_pain, smile, RR/BF | 🟢🟡 | max_pain exacto; **RR/BF son proxy ±7%, no 25Δ** (etiqueta corregida). Fix DTE≥0. |
| `zones.py` | zonas Γ / clusters | 🟢 | Re-derivado por agente; sin errores. |
| `ic_picker.py` | métricas iron condor | 🟢🟡 | POP=1−(Δsp+Δsc) y PoT≈2·Δ correctos; **"VRP" = gradiente de IV, no varianza**; cushion en **% puntos** (0.30=0.30%). Etiquetas corregidas. |
| `expected_move.py` | bandas σ, PoT, IC | 🟢 | straddle×1.2533, 2·Δ, IC POP (colas disjuntas) verificados. |
| `flow.py` | HIRO | 🟡 | `compute_hiro_snapshot` = **volumen×delta (actividad bruta), no flujo firmado**. La variante `compute_hiro_oi_delta` (ΔOI firmado) sí es flujo. |
| `orderflow*.py` | snapshots, velocity, zscores | 🟢🟡 | velocity/zscores (ddof=1) correctos; **`session_vol_score` con término de vol realizada mal calibrado** (solo afecta cadencia de refresco). |
| `signals.py` | VWAP, bandas, ATR, señales | 🟢🟡 | VWAP y bandas **sin look-ahead**; **ATR es SMA, no Wilder**. |
| `backtest.py` | walk-forward, stats | 🟢 | **SIN look-ahead bias** (lo crítico). Orden stop-first conservador; blend TP1 exacto. **"sharpe" era un t-stat** → corregido. |
| `em_tracker.py` | calibración EM | 🟢🟡 | Test de calibración vs 68/80/90% correcto; **fallback p16/p84→p10/p90 sesga `hit_1sigma` al alza** (el veredicto principal usa p10-p90, está aislado). |

### Tres titulares

1. 🔴→🟢 **Bug crítico de Charm corregido.** El signo de la corrección
   put-side del charm estaba invertido (`+q·e^{−qT}` en lugar de `−q·e^{−qT}`),
   error de `2·q·e^{−qT}`. Afectaba el CEX de puts en subyacentes con
   dividendo (SPY/QQQ/DIA). Lo había introducido un "fix" previo del propio
   asistente; el test de paridad anterior *pasaba* porque era
   auto-referencial. **Solo la diferencia finita independiente lo detectó.**
   (commit `be00580`).

2. ✅ **El backtester NO tiene look-ahead bias.** Esto es lo que más podía
   invalidar todo. Verificado: las señales usan solo barras `0..i`, el
   snapshot de orderflow usa solo `ts ≤ ahora`, el *fill* es al *open de la
   barra siguiente*, y el riesgo se recalcula del fill real. El orden
   stop-primero es conservador (pesimista), no optimista.

3. 🟡→🟢 **"Sharpe" del backtest estaba mal etiquetado.** Era
   `media/σ·√N` = el **t-estadístico** de la media R (crece con el tamaño de
   muestra; no comparable entre backtests). Ahora `sharpe` es el Sharpe real
   por trade (`media/σ`) y se añadió `t_stat` para la significancia.

---

## 2. Hallazgos accionados (correcciones aplicadas)

| # | Severidad | Módulo | Hallazgo | Acción | Commit |
|---|:---:|---|---|---|---|
| 1 | 🔴 | `bs.charm` | Signo put-side invertido (error 2·q·e^{−qT}); afecta CEX de puts con dividendo. | Corregido `+`→`−`; suite FD añadida. | `be00580` |
| 2 | 🟡 | `backtest.compute_stats` | "sharpe" = t-stat (media/σ·√N), crece con N. | `sharpe`=media/σ real; nuevo `t_stat`. | `39840a8` |
| 3 | 🟡 | `levels.risk_reversal_25d` | `.min()` de DTE sin filtrar negativos → fila vencida podía ganar. | Filtra `DTE≥0` antes del `.min()`. | `39840a8` |
| 4 | 🟡 | `ic_picker.pop` | Comentario decía `1−max(p_touch)`; el código hace `1−(Δsp+Δsc)`. | Comentario corregido al código (correcto). | `39840a8` |
| 5 | 🟡 | `ic_picker.vrp_*` | "VRP" no es variance risk premium, es gradiente de IV short−long. | Documentado en el dataclass. | `39840a8` |
| 6 | 🟡 | `ic_picker.gex_gate` | `min_cushion_pct=0.30` significa 0.30%, no 30% (trampa de unidades). | Documentado en el docstring. | `39840a8` |
| 7 | 🟡 | `levels.skew_metrics` | Comentario "±10%" pero código ±7%; `rr25/bf25` no son 25Δ reales. | Comentario corregido; aclarado proxy. | `39840a8` |
| 8 | 🟡 | `tests/test_bs.py` | 3 defectos de test heredados (aserción γ-dividendo falsa; `float()` sobre array numpy 2.x). | Tests corregidos (no el código). | `be00580` |

---

## 3. Supuestos y limitaciones vivos (documentados, NO "arreglados")

Estos no son bugs: son decisiones de modelado o aproximaciones que **debes
conocer**. No se cambian porque cambiarlos requeriría su propia validación o
porque son interpretaciones legítimas.

1. **Convención dealer "long calls / short puts" (SqueezeMetrics).** Todo el
   GEX/VEX/CEX asume que el dealer está largo calls y corto puts. Es *el*
   supuesto estándar de la industria (GEXbot/SqueezeMetrics), pero es un
   **supuesto, no una medición**. Si el posicionamiento real del dealer
   difiere, los signos se invierten. No es verificable sin datos de
   posicionamiento del dealer.

2. **DEX usa convención distinta a GEX/VEX/CEX.** DEX usa el signo *crudo* del
   delta (call δ>0 → +, put δ<0 → −), **sin** el flip dealer. Por tanto DEX
   mide "imbalance de delta del OI" (call-heavy vs put-heavy) — un proxy de
   *posicionamiento direccional*, no el inventario delta del dealer. Es
   coherente internamente, pero **no lo leas como las otras tres exposiciones**.

3. **HIRO `compute_hiro_snapshot` = actividad bruta, no flujo firmado.** Es
   volumen×delta. Sin datos de lado de la transacción (bid/ask), un día de
   *venta* neta de calls produce el mismo número positivo que un día de
   *compra*. La historia "+call → dealer compra → alcista" es un **supuesto**.
   Para flujo firmado real, usa `compute_hiro_oi_delta` (ΔOI sí está firmado).

4. **`em_tracker`: fallback p16/p84 → p10/p90 sesga `hit_1sigma`.** Cuando la
   RND no emite p16/p84 verdaderos, se sustituyen por p10/p90, así que la
   banda "1σ/68%" pasa a medir la banda 80% y `hit_1sigma` sale **sesgada al
   alza**. El veredicto principal usa p10-p90, así que está **aislado**, pero
   no leas `hit_1sigma` como el 68% en filas con fallback.

5. **`backtest`: atribución R de tamaño-medio infla levemente el win-rate.**
   Un *runner* que toca TP1 y luego sale en break-even reporta una R pequeña
   *positiva* (media ganancia de TP1 ÷ riesgo full-size) y cuenta como
   ganador. La aritmética es auto-consistente; solo conócela.

6. **`signals.atr` es SMA-ATR, no Wilder (RMA).** Variante legítima, pero
   reacciona más rápido y difiere numéricamente del ATR por defecto de
   TradingView. Afecta las distancias de stop.

7. **`session_vol_score`: término de vol realizada mal calibrado.** El
   término `min(1.5, √390·σ_1min)` necesitaría ~100% de vol diaria para
   aportar 1.0; en la práctica está casi muerto. Solo afecta la **cadencia de
   refresco**, no ninguna decisión de trading.

8. **`cumulative_hedge_flow` es un proxy direccional, no volumen real.**
   Σ GEX×Δspot% tiene el signo correcto (positivo = dealer long-γ vendiendo en
   rallies), pero asume cobertura instantánea y completa cada tick. Léelo como
   "hacia dónde se ha inclinado la cobertura", no como volumen ejecutado.

---

## 4. Fichas por módulo

### 4.1 `bs.py` — Black-Scholes-Merton 🟢

- **Qué calcula.** Griegos vectorizados con dividendo continuo `q` y `T`
  fraccional (cola intradía 0DTE): `d1/d2`, delta, gamma, vanna (∂Δ/∂σ),
  charm (∂Δ/∂t en tiempo-calendario), más interpolación de tasa por DTE.
- **Fórmula y referencia.** Hull, *Options, Futures and Other Derivatives*
  11e, Cap. 19. Charm: ∂Δ/∂t con paridad de delta
  `Δ_put = Δ_call − e^{−qT}` ⇒ `charm_put = charm_call − q·e^{−qT}`.
- **Cómo se verifica** (`tests/validation/test_val_bs.py`, 67 checks):
  delta/gamma/vega vs **py_vollib** a 1e-9; vanna por **FD** de ∂Δ/∂σ; charm
  por **FD** de −∂Δ/∂T; paridad put-call de delta; gamma pico ATM y ≥0;
  NaN en inputs inválidos; vectorización; 7 combinaciones de
  (S,K,T,σ,r,q) incluyendo 0DTE y dividendo.
- **Hallazgo.** Bug de signo en charm put-side (ver §2 #1). **Corregido.**
- **Supuestos/límites.** BSM (vol constante por contrato, sin salto). `q`
  continuo por símbolo desde `config.DIVIDEND_YIELDS`.
- **Confianza: 🟢** — la base de todo lo demás, doblemente validada.

### 4.2 `exposures.py` — GEX / VEX / CEX / DEX 🟢 (DEX 🟡)

- **Qué calcula.** Exposiciones de cobertura del dealer por strike y
  agregadas, gamma-flip sobre malla de spot, y detección de muros (walls).
- **Fórmula y referencia.** Convención SqueezeMetrics/GEXbot:
  - `GEX = Γ·OI·100·S²·0.01·signo` — $ que el dealer debe operar por
    movimiento de **1%**. Derivación: el dealer cubre `d(Δ·OI·100)/dS·dS`
    acciones; en dólares por 1% = `Γ·OI·100·S²·0.01`. ✔ verificado.
  - `VEX = Vanna·OI·100·S·0.01·signo` — $ por **+1 punto de vol**.
  - `CEX = Charm·OI·100·S·signo` — $ por **1 día calendario**.
  - `DEX = Δ·OI·100·S` — sesgo direccional (ver límite abajo).
  - signo: call=+1, put=−1 (dealer long calls / short puts).
- **Cómo se verifica** (`test_val_exposures.py`, 18 checks): re-cómputo a mano
  elemento-a-elemento de cada exposición; **escala económica de GEX validada
  por FD del delta del dealer** (independiente de `bs.gamma`); gamma-flip
  confirmado como **cruce-cero real** del GEX (`|GEX(flip)|/escala < 5%`);
  detección de muro localiza pico/valle y respeta el lado del spot; fronteras
  de buckets DTE inclusivas/disjuntas/exhaustivas; CEX put-side con q>0 (SPY)
  ejercita el signo de charm corregido.
- **Supuestos/límites.** §3 #1 (convención dealer) y §3 #2 (DEX usa delta
  crudo sin flip).
- **Confianza: 🟢** (GEX/VEX/CEX) · **🟡** (DEX — convención).

### 4.3 `rnd.py` — Densidad Riesgo-Neutral (SVI) 🟢 — *modelo central*

- **Qué calcula.** La densidad riesgo-neutral f(K) de la que salen Expected
  Range, percentiles exactos (P5–P95), moda, P16/P84 y probabilidades de
  toque. Es el modelo que en última instancia dimensiona trades.
- **Fórmula y referencia.**
  - Breeden-Litzenberger (1978): `f(K) = e^{rT}·∂²C/∂K²`.
  - SVI raw (Gatheral 2004): `w(k) = a + b[ρ(k−m) + √((k−m)²+σ²)]`, con
    `w = σ²T`, `k = ln(K/F)`. Libre de arbitraje vía `g(k) ≥ 0` de Gatheral.
  - Centrado en el **forward** `F = S·e^{(r−q)T}`, no en spot.
  - Black-76 para el precio call (medida forward).
- **Cómo se verifica** (`test_val_rnd.py`, 17 checks) — contra **verdad de
  forma cerrada**, no contra sí mismo:
  - **Axiomas de densidad:** integra a 1; f(K)≥0; CDF monótona en [0,1].
  - **Martingala / forward-pricing:** `E_Q[S_T] = ∫K·f dK = F` (no spot),
    verificado con q=0 y con q>r (donde F<spot); error BL <0.4%.
  - **Recuperación lognormal:** smile **plano** ⇒ reproduce la densidad
    lognormal Black-Scholes **punto a punto** (<2% del pico) y sus percentiles
    = cuantiles analíticos `K_p = F·e^{−½σ²T+σ√T·z_p}` a 0.2%; `std` =
    `F·√(e^{σ²T}−1)`.
  - **g(k) de Gatheral:** derivadas analíticas w′,w″ vs FD de alta precisión.
  - `fit_svi` round-trip; `_black76_call` vs **py_vollib.black**; paridad
    put-call; smile con put-skew ⇒ densidad sesgada a la izquierda.
- **Supuestos/límites.** La precisión de los percentiles depende de la
  densidad/calidad del smile observado y de la cobertura de strikes. La
  fiabilidad *real* (no la matemática) se mide con el `em_tracker` acumulando
  sesiones — ver §5.
- **Confianza: 🟢** matemáticamente. La calibración empírica es trabajo en
  curso (tracker).

### 4.4 `vol.py` — Volatilidad realizada 🟢

- **Qué calcula.** HV close-to-close, Parkinson, Garman-Klass, Yang-Zhang;
  IV rank/percentile; cono de vol.
- **Fórmula y referencia.** Parkinson (1980) `1/(4ln2)·E[ln²(H/L)]`;
  Garman-Klass (1980) `0.5·ln²(H/L) − (2ln2−1)·ln²(C/O)`; Yang-Zhang (2000)
  `σ²_on + k·σ²_oc + (1−k)·σ²_RS`, `k=0.34/(1.34+(n+1)/(n−1))`. Anualizado
  ×√252.
- **Cómo se verifica** (`test_val_vol.py`, 12 checks): cada estimador
  re-implementado desde su referencia y exigido igual sobre un OHLC fijo;
  **constantes publicadas fijadas** (Parkinson 0.360674, GK 0.386294);
  close-to-close **recupera una σ conocida** vía GBM Monte-Carlo de 6000
  pasos; **guard de regresión Yang-Zhang** que prueba que usa el retorno
  intradía `ln(C/O)` y no close-to-close (el fix de doble-conteo de gap
  documentado).
- **Confianza: 🟢**.

### 4.5 `levels.py` — niveles, smile, term structure 🟢🟡

- **Qué calcula.** max_pain, smile de IV por expiry, risk-reversal/butterfly,
  term structure ATM.
- **Verificación.** max_pain re-derivado por agente (exacto: minimiza el dolor
  total del comprador). EM √T conceptualmente sólido.
- **Hallazgos.** RR/BF son **proxy ±7% moneyness, no 25Δ reales** (etiqueta
  corregida); `risk_reversal_25d` ahora filtra **DTE≥0** antes de elegir el
  expiry más cercano.
- **Confianza: 🟢** (max_pain) · **🟡** (RR/BF — proxy).

### 4.6 `zones.py` — zonas gamma 🟢

- **Qué calcula.** Clustering de strikes por exposición para identificar
  zonas de soporte/resistencia gamma.
- **Verificación.** Re-derivado por agente; sin errores lógicos.
- **Confianza: 🟢**.

### 4.7 `ic_picker.py` — selección de iron condors 🟢🟡

- **Qué calcula.** Smile 0DTE con delta, métricas de iron condor (crédito,
  max loss, POP, PoT), comparación de wings, y la "compuerta" GEX para vender
  ICs con seguridad.
- **Fórmula y referencia.** PoT ≈ `2·|Δ|` (principio de reflexión, GBM sin
  drift, acotado a 1); POP del IC = `1 − (Δsp + Δsc)` (colas disjuntas, sin
  doble conteo) — convención TastyTrade.
- **Verificación.** PoT y POP re-derivados por agente (sólidos; PoT es cota
  superior ligeramente conservadora).
- **Hallazgos.** "VRP" = gradiente de IV short−long, **no** variance risk
  premium (documentado); `min_cushion_pct` en **puntos %** (0.30=0.30%,
  documentado); comentario de `pop` corregido al código.
- **Confianza: 🟢** (matemática de prob.) · **🟡** (etiquetas, ya aclaradas).

### 4.8 `expected_move.py` — bandas σ / PoT / IC 🟢

- **Qué calcula.** Bandas multi-σ, probabilidad de toque, sugeridor de IC.
- **Fórmula.** Straddle×1.2533 = 1σ (√(π/2)); `E[|Z|]=√(2/π)=0.79788`;
  2·Δ PoT; IC POP por colas disjuntas. Todo verificado por agente.
- **Confianza: 🟢**.

### 4.9 `flow.py` — HIRO 🟡

- **Qué calcula.** Flujo de cobertura intradía. `compute_hiro_snapshot`
  (volumen×delta), `compute_hiro_by_strike`, `compute_hiro_oi_delta` (ΔOI×Δ),
  `hiro_zscore`.
- **Verificación.** Aritmética y z-scores (ddof=1) correctos.
- **Hallazgo.** `compute_hiro_snapshot` es **actividad bruta, no flujo
  firmado** (§3 #3). `compute_hiro_oi_delta` sí es flujo firmado (ΔOI).
- **Confianza: 🟡** — úsalo sabiendo qué mide cada variante.

### 4.10 `orderflow*.py` — snapshots y derivados 🟢🟡

- **Qué calcula.** Snapshots persistidos con gate de materialidad; buckets por
  DTE (0dte/semana/mes); velocity (∂GEX/∂t), z-scores intradía, hedge flow
  acumulado, estabilidad de muros.
- **Verificación.** `velocity` = pendiente por diferencia finita sobre
  resample 1-min (verificado: serie lineal +2/min ⇒ 2.0 exacto); z-scores
  ddof=1; buckets disjuntos/exhaustivos a 60 DTE.
- **Hallazgos.** `session_vol_score` con término de vol realizada mal calibrado
  (§3 #7, solo cadencia); `cumulative_hedge_flow` es proxy direccional (§3 #8).
- **Confianza: 🟢** (núcleo) · **🟡** (los dos proxies anteriores).

### 4.11 `signals.py` — VWAP / ATR / señales 🟢🟡

- **Qué calcula.** VWAP anclado de sesión, bandas de VWAP, ATR, opening range,
  generación de señales (mean-reversion en +Γ, breakout en −Γ).
- **Verificación.** VWAP = precio típico (H+L+C)/3 ponderado por volumen
  acumulado ✔; bandas usan stdev rolling **solo de barras pasadas** (ddof=1) —
  **sin look-ahead** ✔; generación determinista; breakout exige ruptura fresca.
- **Hallazgo.** ATR es **SMA-ATR, no Wilder** (§3 #6).
- **Confianza: 🟢** (sin look-ahead) · **🟡** (ATR es SMA).

### 4.12 `backtest.py` — walk-forward 🟢

- **Qué calcula.** Backtest walk-forward, gestión de posición con scale-out en
  TP1, y estadísticas (win-rate, profit factor, Sharpe, max DD).
- **Verificación (la más importante).** **NO hay look-ahead bias:** señales
  solo con barras `0..i`; snapshot orderflow solo `ts ≤ ahora`; fill al **open
  de la barra siguiente**; riesgo recalculado del fill real con gap-guard. El
  orden stop-primero es **conservador** (pesimista). El blend 50/50 de TP1
  `(TP1+final)/2` es **aritméticamente exacto** (sin doble-blending).
  `max_drawdown_r`, `profit_factor`, expectancy: fórmulas correctas.
- **Hallazgo.** "sharpe" era el t-stat (§2 #2). **Corregido** + `t_stat` nuevo.
- **Confianza: 🟢** — la integridad walk-forward está intacta.

### 4.13 `em_tracker.py` — calibración EM 🟢🟡

- **Qué calcula.** Registra la predicción RND al open, la liquida al close, y
  computa hit-rates de las bandas vs sus niveles de confianza teóricos.
- **Fórmula.** Test de calibración frecuentista: `hit(p16-p84)` vs 68%,
  `hit(p10-p90)` vs 80%, `hit(p05-p95)` vs 90%. Correcto por construcción de
  una RND bien especificada.
- **Hallazgo.** Fallback p16/p84→p10/p90 sesga `hit_1sigma` al alza (§3 #4); el
  veredicto principal (p10-p90) está aislado.
- **Confianza: 🟢** (test de calibración) · **🟡** (`hit_1sigma` en filas
  con fallback).

---

## 5. Qué NO está validado todavía (honestidad científica)

La validación de **implementación** (¿el código calcula lo que dice?) está
hecha y es sólida. Pero validación de modelo ≠ "el modelo gana dinero". Lo que
**falta** para confiar el capital:

1. **Calibración empírica de la RND.** Matemáticamente la densidad es
   impecable, pero *¿predice bien el rango real?* Eso solo lo dirá el
   `em_tracker` acumulando ≥30-50 sesiones y comparando hit-rates contra
   68/80/90%. Hasta entonces, la RND es una *hipótesis bien construida*, no un
   edge probado.

2. **Backtest out-of-sample del sistema de señales.** El backtester es
   correcto (sin look-ahead), pero un backtest correcto sobre datos limitados
   o in-sample no es evidencia de edge. Hace falta: muestra grande,
   separación train/test temporal, y `t_stat > 2` con costes realistas
   (comisiones + slippage, que el backtester aún no modela explícitamente).

3. **Probabilidad riesgo-neutral ≠ probabilidad real.** PoT y POP salen de la
   medida riesgo-neutral (incluye prima de riesgo). La frecuencia *real* de
   toque puede diferir sistemáticamente. No leas un POP de 70% como "gano 70%
   de las veces" sin calibrarlo.

4. **Supuesto de convención dealer** (§3 #1) — no verificable con los datos
   disponibles; es la mayor fuente de incertidumbre estructural del GEX.

> **Conclusión.** Tras esta validación puedes confiar en que **el modelo
> calcula correctamente lo que afirma calcular** (con las etiquetas/supuestos
> de §3 presentes). Lo que aún **no** puedes afirmar es que esos cálculos
> correctos constituyan un edge rentable neto de costes — eso requiere los
> pasos de §5.1–5.2, que son el siguiente bloque de trabajo (backtesting +
> acumulación del tracker).

---

## 6. Cómo reproducir esta validación

```bash
pip install py_vollib                  # referencia externa BSM/Black-76
python -m pytest tests/validation/ -q  # 114 checks de validación de modelo
python -m pytest tests/ -q             # batería completa (244)
```

Suites de validación:
- `tests/validation/test_val_bs.py` — griegos vs py_vollib + FD.
- `tests/validation/test_val_exposures.py` — ensamblaje GEX/VEX/CEX/DEX.
- `tests/validation/test_val_rnd.py` — RND vs forma cerrada (martingala,
  lognormal, g(k)).
- `tests/validation/test_val_vol.py` — estimadores HV vs fórmulas publicadas.
