"""
Curvas tipo y EUR (producción final estimada) de pozos no convencionales.

Para cada pozo no convencional:
  1. Serie mensual desde su primer mes con producción NO residual (>= RESIDUAL de petróleo o de
     gas; mes 1 = arranque). Los meses residuales previos al arranque no entran en la serie ni en
     la acumulada. Si el pozo nunca pasa RESIDUAL, se arranca en el primer mes > 0 (queda en el
     archivo como "poco_vol").
  2. Ajuste de declinación Arps hiperbólico sobre el caudal diario (m³/d), desde el
     pico de los primeros 12 meses. Ajuste en escala log con búsqueda en grilla (b, Di)
     y qi por mínimos cuadrados -> sin scipy, y no se cae con series ruidosas.
     Pozos JÓVENES (< MESES_JOVEN meses desde el pico, contando el mes del pico): la grilla
     se limita a b <= B_MAX_JOVEN (con poca historia el b alto no está determinado y dispara
     la EUR). Se marca por fluido en curvas_pozos.json: "jp":1 / "jg":1 (solo si el ajuste
     de ese fluido es "ok"; si no hay pronóstico el tope no tiene efecto).
  1b. PRODUCCIÓN RESIDUAL. El CSV trae meses de pozo cerrado con 0,1 / 0,07 / 0,02 m³. Para el
     ajuste, los motivos (parado, etc.) y el empalme, los meses < RESIDUAL[fluido] (1 m³/mes de
     petróleo, 1 Mm³/mes de gas) se toman como 0. La serie "p"/"g" del JSON guarda los valores
     reales redondeados (esos meses ya dan 0) y la acumulada usa los valores reales.
  2b. EMPALME con el último dato. Para ajustes "ok" se compara el caudal del primer mes de
     pronóstico contra la MEDIANA del caudal diario de los últimos 3 meses con producción > 0 de
     la serie sin residuales (regla A: SIN la máscara del ajuste, que descarta solo meses bajos y
     sesgaba la referencia hacia arriba). Con razón = primer mes de pronóstico / esa mediana:
       [ESC_MIN, ESC_MAX] = [0,5; 2]   no se toca
       (2; 5]                          se reescala qi HACIA ABAJO (mismos b y Di) para que el primer
                                       mes de pronóstico iguale la mediana
       [0,2; 0,5)                      se reescala qi HACIA ARRIBA hasta la mediana, con TOPE: el
                                       primer mes de pronóstico nunca supera el último mes real con
                                       producción (si ese último mes ya está por debajo del primer
                                       mes del ajuste, no se sube nada)
       fuera de [0,2; 5]               no se pronostica: motivo "empalme"
     Si qi cambió, marca "escp"/"escg":1.
     Decisión de formato: fp/fg pasan a 6 elementos
         [qi_pron, Di, b, pico, r2, qi_ajuste]
     qi_pron   = qi con el que se calcula el pronóstico y la EUR (reescalado si esc=1)
     qi_ajuste = qi original del ajuste sobre la historia (igual a qi_pron si no hubo esc)
     La UI dibuja la curva ajustada sobre la historia (t < len-pico) con qi_ajuste y el
     pronóstico (t >= len-pico, punteado) con qi_pron: así lo dibujado suma la EUR.
  3. Pronóstico con hiperbólica MODIFICADA: cuando la declinación instantánea baja a
     DMIN_ANUAL pasa a exponencial (evita EUR infladas por b > 1 en series cortas).
     Corta en el límite económico o a los VIDA_MESES desde el arranque.
  4. EUR = acumulada + pronóstico. En curvas_pozos.json "ep"/"eg" = suma de la serie mensual
     redondeada (la acumulada que muestra la UI) + pronóstico redondeado: EUR − acumulada
     mostrada = pronóstico exacto, nunca negativo.
  5. Control de calidad por fluido (claves "qp" / "qg" de curvas_pozos.json). Si el código
     no es "ok" NO hay pronóstico (EUR = acumulada real) y el pozo sigue en el archivo:
       ok               ajuste aceptado (con pronóstico)
       poco_vol         acumulada <= 300 (m³ o Mm³): no se intenta ajustar
       parado           0 en los últimos 12 meses: pronóstico = 0 (EUR = acumulada, que es
                        un valor real y SÍ entra en las medianas de EUR)
       parado_reciente  0 en los últimos 3 meses (pero no en 12): sin pronóstico, EUR =
                        acumulada; entra en las medianas igual que "parado"
       corto            menos de MIN_PUNTOS meses útiles desde el pico
       dmin             Di ajustado < declinación terminal (cae al piso de la grilla; típico
                        de mesetas/rampas por choke, sin declinación que extrapolar)
       r2               r² del ajuste (escala log) < R2_MIN
       empalme          el ajuste no empalma con la producción reciente (razón fuera de [0,2; 5])
     Medianas de EUR (cohortes, operadores, dispersión): códigos "ok", "parado" y
     "parado_reciente" (lista en curvas.json -> "mediana_motivos"). EUR de cohorte = None si
     hay menos de MIN_N_CURVA pozos con EUR válida.
  6. Avisos (no filtran pozos; textos en curvas_pozos.json -> "avisos"; cada marca está presente
     solo cuando vale 1):
       rq           rama exactamente 1000 m (posible valor redondeado)
       jp / jg      pozo joven: b limitado a B_MAX_JOVEN (ver 2.)
       escp / escg  pronóstico reescalado en el empalme (ver 2b.)
       reap / reag  pozo REACTIVADO: ajuste "ok" de ese fluido con >= MESES_REACT meses seguidos
                    < RESIDUAL dentro de los últimos 12 meses (como "ok" exige producción en los
                    últimos 3 meses, el pozo produce al final): pronóstico incierto. Sigue entrando
                    en las medianas.

Curvas tipo (solo Vaca Muerta): percentiles P10/P50/P90 de la producción mensual por
mes desde el arranque, por cohorte (año de arranque) y ventana (petróleo / gas), en
valor absoluto y por km de rama horizontal (rama del Adjunto IV de fractura).
La acumulada de la curva tipo ("acum", "acum_km") es la SUMA ACUMULADA de los percentiles
mensuales (P10 acum = cumsum(P10 mensual), etc.), continuando por la "cola": es monótona
y coherente con lo mensual (no es el percentil de las acumuladas de cada pozo).
Ranking de operadores: además de los filtros de cohorte/rama/n, la mediana de meses de
historia debe ser >= MESES_EMPRESA_MIN; los que no llegan van a "empresas_fuera".

Entrada:
  data/produccion-no-convencional.csv   (historia completa de pozos NC, ver README)
  data/geo/fractura.csv                 (rama horizontal)
Salida:
  data/curvas.json         curvas tipo, EUR por cohorte y por operador (VM)
  data/curvas_pozos.json   serie mensual + parámetros de ajuste de cada pozo NC
"""
import json

import numpy as np
import pandas as pd

GAS_A_PET = 1000 / 1069          # Mm³ de gas -> m³ equivalentes de petróleo (6:1)
GOR_GAS = 3000                   # m³/m³: por encima, el pozo es de la ventana de gas
DMIN_ANUAL = 0.08                # declinación terminal (efectiva anual)
B_MAX = 1.5
VIDA_MESES = 360                 # 30 años desde el arranque
LIMITE = {"p": 1.0, "g": 1.0}    # límite económico: 1 m³/d de petróleo, 1 Mm³/d de gas
MIN_PUNTOS = 6
MESES_CURVA = 72
MIN_N_CURVA = 10
MIN_POZOS_EMPRESA = 15
EMPRESA_COHORTE_MIN = 2018       # ranking de operadores: pozos modernos...
EMPRESA_KM_MIN = 1.0             # ...con rama conocida >= 1 km
RAMA_MIN_M = 300                 # rama < 300 m = dato mal cargado -> sin rama
R2_MIN = 0.3
MIN_VOL = 300                    # acumulada mínima para intentar ajustar
MESES_PARADO = 12
MESES_PARADO_REC = 3             # 0 en los últimos 3 meses -> "parado_reciente"
MESES_REACT = 3                  # aviso "reactivado": >= 3 meses seguidos en 0 dentro de los últimos 12
MESES_JOVEN = 24                # < 24 meses desde el pico -> b con tope B_MAX_JOVEN
B_MAX_JOVEN = 1.2
ESC_MAX, ESC_MIN = 2.0, 0.5      # empalme: dentro de [0,5; 2] no se toca; fuera, se reescala...
EMP_MAX, EMP_MIN = 5.0, 0.2      # ...y fuera de [0,2; 5] no se pronostica (motivo "empalme")
RESIDUAL = {"p": 1.0, "g": 1.0}  # m³/mes y Mm³/mes: meses por debajo = pozo cerrado (se toman como 0)
MESES_EMPRESA_MIN = 12           # ranking: mediana de meses de historia >= 12
FRAC_CURVA = 0.5                 # la curva tipo se corta cuando quedan < 50 % de los pozos
MEDIANA_Q = ("ok", "parado", "parado_reciente")     # códigos que entran en las medianas de EUR
EMPRESA_ALIAS = {"VISTA OIL & GAS ARGENTINA SAU": "VISTA ENERGY ARGENTINA SAU"}
DIAS = 30.4375

D_MIN = -np.log(1 - DMIN_ANUAL) / 12          # nominal mensual
B_GRID = np.arange(0.05, B_MAX + 1e-9, 0.05)
DI_GRID = np.logspace(np.log10(0.005), np.log10(5), 70)
BB, DD = np.meshgrid(B_GRID, DI_GRID, indexing="ij")
BB, DD = BB.ravel(), DD.ravel()


def arps_fit(q):
    """q: caudal diario por mes (desde el arranque).
    Devuelve (fit, motivo, prev): fit = (qi, Di, b, pico, r2, joven) o None; motivo = código de
    calidad; prev = (mediana del caudal de los últimos 3 meses con producción > 0, caudal del último
    mes con producción), para el empalme; se calcula sin la máscara del ajuste.
    joven = True si hay < MESES_JOVEN meses desde el pico (grilla con b <= B_MAX_JOVEN).
    q ya viene sin producción residual (meses < RESIDUAL en 0)."""
    if q.sum() * DIAS <= MIN_VOL:
        return None, "poco_vol", None
    if len(q) >= MESES_PARADO and q[-MESES_PARADO:].sum() <= 0:
        return None, "parado", None
    if len(q) >= MESES_PARADO_REC and q[-MESES_PARADO_REC:].sum() <= 0:
        return None, "parado_reciente", None
    if len(q) < MIN_PUNTOS or q.max() <= 0:
        return None, "corto", None
    pico = int(np.argmax(q[:12]))
    t = np.arange(len(q) - pico, dtype=float)
    y = q[pico:]
    # descartar meses con el pozo parado o casi (paradas, meses parciales)
    med = pd.Series(y).rolling(5, center=True, min_periods=1).median().to_numpy()
    ok = (y > 0) & (y >= 0.3 * med)
    if ok.sum() < MIN_PUNTOS:
        return None, "corto", None
    # referencia del empalme (regla A): mediana de los últimos 3 meses con producción > 0 de la
    # serie sin residuales, SIN la máscara (la máscara descarta solo meses bajos y sube la referencia)
    pos = q[q > 0]
    prev = (float(np.median(pos[-3:])), float(pos[-1]))
    t, ly = t[ok], np.log(y[ok])
    joven = len(q) - pico < MESES_JOVEN
    sel = BB <= B_MAX_JOVEN + 1e-9 if joven else np.ones(len(BB), bool)
    bb, dd = BB[sel], DD[sel]
    # f[combo, punto] = -(1/b) ln(1 + b Di t)
    f = -np.log1p(np.outer(bb * dd, t)) / bb[:, None]
    lqi = (ly[None, :] - f).mean(axis=1)
    sse = ((ly[None, :] - f - lqi[:, None]) ** 2).sum(axis=1)
    k = int(np.argmin(sse))
    sst = ((ly - ly.mean()) ** 2).sum()
    r2 = 1 - sse[k] / sst if sst > 0 else 0.0
    if dd[k] < D_MIN:
        return None, "dmin", None
    if r2 < R2_MIN:
        return None, "r2", None
    return (float(np.exp(lqi[k])), float(dd[k]), float(bb[k]), pico, float(r2), joven), "ok", prev


def arps_rate(t, qi, di, b):
    """Hiperbólica modificada (t en meses desde el pico)."""
    t = np.asarray(t, dtype=float)
    t_sw = (di / D_MIN - 1) / (b * di) if di > D_MIN else 0.0
    q_hyp = qi / (1 + b * di * t) ** (1 / b)
    q_sw = qi / (1 + b * di * t_sw) ** (1 / b)
    return np.where(t < t_sw, q_hyp, q_sw * np.exp(-D_MIN * (t - t_sw)))


def empalme(n, fit, prev):
    """n: meses de historia; fit de arps_fit ("ok"); prev = (mediana de los últimos 3 meses con
    producción > 0, último mes con producción). Devuelve (qi_pron, razon, tipo),
    razon = caudal del 1.er mes de pronóstico / mediana. b y Di no se tocan.
      razon en [ESC_MIN, ESC_MAX]   qi_pron = qi del ajuste; tipo None
      razon en (ESC_MAX, EMP_MAX]   reescalado hacia ABAJO: 1.er mes = mediana; tipo "abajo"
      razon en [EMP_MIN, ESC_MIN)   reescalado hacia ARRIBA hasta la mediana, con TOPE: el 1.er mes
                                    no supera el último mes con producción. tipo "arriba", o "tope"
                                    si el tope recortó la suba (si el último mes ya está por debajo
                                    del 1.er mes del ajuste no se sube nada: qi_pron = qi)
      fuera de [EMP_MIN, EMP_MAX]   qi_pron = None (no se pronostica: motivo "empalme"); tipo None"""
    qi, di, b, pico = fit[:4]
    med, ult = prev
    q1 = float(arps_rate(n - pico, qi, di, b))
    razon = q1 / med
    if razon > EMP_MAX or razon < EMP_MIN:
        return None, razon, None
    if razon > ESC_MAX:
        return qi * med / q1, razon, "abajo"
    if razon < ESC_MIN:
        if ult < med:
            return qi * max(ult, q1) / q1, razon, "tope"
        return qi * med / q1, razon, "arriba"
    return qi, razon, None


def pronostico(n, fit, stream):
    """n: meses de historia; fit = (qi_pron, Di, b, pico, ...). Volumen pronosticado desde el mes
    siguiente al último dato hasta el límite económico o VIDA_MESES (0 si no hay fit)."""
    if fit is None:
        return 0.0
    qi, di, b, pico = fit[:4]
    t = np.arange(n - pico, VIDA_MESES - pico, dtype=float)
    q = arps_rate(t, qi, di, b)
    q = q[: np.argmax(q < LIMITE[stream])] if (q < LIMITE[stream]).any() else q
    return float(q.sum() * DIAS)


def racha_ceros(x):
    """Racha más larga de meses en 0 (x ya viene sin residuales)."""
    mx = cur = 0
    for v in x:
        cur = cur + 1 if v <= 0 else 0
        mx = max(mx, cur)
    return mx


def fit_json(f):
    """(qi_pron, Di, b, pico, r2, qi_ajuste, joven) -> lista de 6 para curvas_pozos.json."""
    if not f:
        return None
    return [round(f[0], 2), round(f[1], 4), round(f[2], 2), int(f[3]), round(f[4], 2), round(f[5], 2)]


# ── Producción mensual NC ───────────────────────────────────────────────────
print("Cargando producción no convencional...")
cols = ["idpozo", "anio", "mes", "prod_pet", "prod_gas", "empresa", "sigla", "formacion", "sub_tipo_recurso"]
d = pd.read_csv("data/produccion-no-convencional.csv", usecols=cols, encoding="utf-8-sig", low_memory=False)
d["empresa"] = d["empresa"].replace(EMPRESA_ALIAS)
neg = (d["prod_pet"] < 0) | (d["prod_gas"] < 0)
print(f"  {int(neg.sum()):,} filas con producción negativa -> recortadas a 0")
d[["prod_pet", "prod_gas"]] = d[["prod_pet", "prod_gas"]].fillna(0).clip(lower=0)
d["periodo"] = pd.PeriodIndex.from_fields(year=d["anio"], month=d["mes"], freq="M")
tot = d.groupby("periodo")["prod_pet"].sum()
ultimo = tot[tot >= 0.8 * tot.iloc[-7:-1].median()].index.max()
d = d[d["periodo"] <= ultimo]
print(f"  {len(d):,} filas, {d.idpozo.nunique():,} pozos, hasta {ultimo}")

info = d.sort_values("periodo").groupby("idpozo").agg(
    sigla=("sigla", "last"), empresa=("empresa", "last"),
    form=("formacion", lambda s: str(s.iloc[-1]).strip().lower()), sub=("sub_tipo_recurso", "last"))
m = d.groupby(["idpozo", "periodo"])[["prod_pet", "prod_gas"]].sum()

# ── Rama horizontal (fractura) ──────────────────────────────────────────────
fr = pd.read_csv("data/geo/fractura.csv", usecols=["idpozo", "longitud_rama_horizontal_m"],
                 encoding="utf-8-sig", low_memory=False)
rama = fr.groupby("idpozo")["longitud_rama_horizontal_m"].max()
info["rama"] = rama.reindex(info.index)
mal = info.rama.notna() & (info.rama < RAMA_MIN_M)
print(f"  ramas < {RAMA_MIN_M} m (mal cargadas, se toman como sin rama): {int(mal.sum())}")
info.loc[mal, "rama"] = np.nan
info["rq"] = info.rama == 1000
print(f"  ramas de exactamente 1000 m (aviso: posible valor redondeado, se usan igual): {int(info.rq.sum())}")

# ── Ajuste por pozo ─────────────────────────────────────────────────────────
print("Ajustando Arps por pozo...")
pozos, filas = {}, []
for idp, g in m.groupby(level=0):
    g = g.droplevel(0)
    # arranque = primer mes con producción no residual; si el pozo solo tiene residuales, el primero
    # > 0 (sigue en el archivo, como "poco_vol")
    act = g[(g.prod_pet >= RESIDUAL["p"]) | (g.prod_gas >= RESIDUAL["g"])]
    if act.empty:
        act = g[(g.prod_pet > 0) | (g.prod_gas > 0)]
    if act.empty:
        continue
    ini = act.index.min()
    idx = pd.period_range(ini, ultimo, freq="M")
    g = g.reindex(idx, fill_value=0)
    p, gs = g["prod_pet"].to_numpy(float), g["prod_gas"].to_numpy(float)
    # sin producción residual (pozo cerrado con 0,1 / 0,02 m³): solo para ajuste, motivos y empalme
    pa = np.where(p < RESIDUAL["p"], 0.0, p)
    ga = np.where(gs < RESIDUAL["g"], 0.0, gs)
    fp, qp, prev_p = arps_fit(pa / DIAS)
    fg, qg, prev_g = arps_fit(ga / DIAS)
    # empalme: fit -> (qi_pron, Di, b, pico, r2, qi_ajuste, joven)
    esc, razon, tipo, reac = {}, {}, {}, {}
    if fp:
        qi_pron, razon["p"], tipo["p"] = empalme(len(p), fp, prev_p)
        if qi_pron is None:
            fp, qp = None, "empalme"
        else:
            esc["p"] = qi_pron != fp[0]
            fp = (qi_pron,) + fp[1:5] + (fp[0], fp[5])
    if fg:
        qi_pron, razon["g"], tipo["g"] = empalme(len(gs), fg, prev_g)
        if qi_pron is None:
            fg, qg = None, "empalme"
        else:
            esc["g"] = qi_pron != fg[0]
            fg = (qi_pron,) + fg[1:5] + (fg[0], fg[5])
    # aviso "reactivado": ajuste ok y >= MESES_REACT meses seguidos < RESIDUAL dentro de los últimos 12
    # (como "ok" excluye 0 en los últimos 3 meses, la racha siempre termina antes del final)
    for k_, serie, fit_ in (("p", pa, fp), ("g", ga, fg)):
        reac[k_] = bool(fit_) and racha_ceros(serie[-MESES_PARADO:]) >= MESES_REACT
    # EUR = acumulada mostrada (suma de la serie redondeada) + pronóstico redondeado
    p_js, g_js = [int(round(x)) for x in p], [int(round(x)) for x in gs]
    ep = sum(p_js) + int(round(pronostico(len(p), fp, "p")))
    eg = sum(g_js) + int(round(pronostico(len(gs), fg, "g")))
    n12 = min(12, len(p))
    gor = gs[:n12].sum() * 1000 / p[:n12].sum() if p[:n12].sum() > 0 else np.inf
    ventana = "g" if gor > GOR_GAS else "p"
    it = info.loc[idp]
    km = it.rama / 1000 if pd.notna(it.rama) else None
    pz = {
        "s": str(ini), "v": ventana, "km": round(km, 2) if km else None,
        "p": p_js, "g": g_js,
        "fp": fit_json(fp), "fg": fit_json(fg),
        "ep": ep, "eg": eg, "qp": qp, "qg": qg,
    }
    if fp and fp[6]:
        pz["jp"] = 1
    if fg and fg[6]:
        pz["jg"] = 1
    if esc.get("p"):
        pz["escp"] = 1
    if esc.get("g"):
        pz["escg"] = 1
    if reac["p"]:
        pz["reap"] = 1
    if reac["g"]:
        pz["reag"] = 1
    if it.rq:
        pz["rq"] = 1
    pozos[int(idp)] = pz
    fv = fp if ventana == "p" else fg
    filas.append({"id": int(idp), "ini": ini, "ventana": ventana, "km": km, "meses": len(p),
                  "form": it.form, "empresa": it.empresa, "p": p, "g": gs,
                  "ep": ep, "eg": eg, "eq": ep + eg * GAS_A_PET,
                  "q": qp if ventana == "p" else qg,
                  "ajuste": (qp if ventana == "p" else qg) in MEDIANA_Q,
                  "joven": bool(fv and fv[6]), "rq": bool(it.rq),
                  "jp": bool(fp and fp[6]), "jg": bool(fg and fg[6]),
                  "escp": bool(esc.get("p")), "escg": bool(esc.get("g")),
                  "tp": tipo.get("p"), "tg": tipo.get("g"), "reap": reac["p"], "reag": reac["g"],
                  "rzp": razon.get("p"), "rzg": razon.get("g"), "qp_all": qp, "qg_all": qg,
                  "acp": float(p.sum()), "acg": float(gs.sum())})
w = pd.DataFrame(filas)
w["cohorte"] = w["ini"].apply(lambda x: x.year)
print(f"  {len(w):,} pozos, {w.ajuste.sum():,} con EUR válida (ok/parado/parado_reciente) en su fluido principal")

# ── Curvas tipo Vaca Muerta ─────────────────────────────────────────────────
vm = w[w.form == "vaca muerta"].copy()
vm["eq_km"] = vm["eq"] / vm["km"]
print(f"  Vaca Muerta: {len(vm):,} pozos ({(vm.ventana == 'p').sum():,} petróleo, {(vm.ventana == 'g').sum():,} gas)")


def pct(mat):
    """mat: lista de series (pueden ser de distinto largo). Percentiles por mes.
    Tramo principal (p10/p50/p90/n): mientras n >= max(MIN_N_CURVA, FRAC_CURVA * pozos).
    "cola": mismo formato, los meses siguientes mientras n >= MIN_N_CURVA (sesgada a los
    pozos más viejos/sobrevivientes: dibujar punteada con su n). cola[i] = mes len(n)+i+1."""
    out = {"p10": [], "p50": [], "p90": [], "n": [],
           "cola": {"p10": [], "p50": [], "p90": [], "n": []}}
    corte = max(MIN_N_CURVA, FRAC_CURVA * len(mat))
    for k in range(MESES_CURVA):
        col = np.array([s[k] for s in mat if len(s) > k])
        if len(col) < MIN_N_CURVA:
            break
        dst = out if len(col) >= corte and not out["cola"]["n"] else out["cola"]
        # P10 = optimista (convención de reservas): percentil 90 de los valores
        dst["p10"].append(round(float(np.percentile(col, 90)), 1))
        dst["p50"].append(round(float(np.percentile(col, 50)), 1))
        dst["p90"].append(round(float(np.percentile(col, 10)), 1))
        dst["n"].append(int(len(col)))
    return out


def acum_de(men):
    """Acumulada de una curva tipo = cumsum de cada percentil mensual, siguiendo por la cola.
    Mismo formato que pct(); n = el n del mensual."""
    out = {"p10": [], "p50": [], "p90": [], "n": list(men["n"]),
           "cola": {"p10": [], "p50": [], "p90": [], "n": list(men["cola"]["n"])}}
    k = len(men["n"])
    for pc in ("p10", "p50", "p90"):
        c = np.cumsum(men[pc] + men["cola"][pc])
        out[pc] = [round(float(x), 1) for x in c[:k]]
        out["cola"][pc] = [round(float(x), 1) for x in c[k:]]
    return out


curvas, cohortes, empresas, empresas_fuera = {}, {}, {}, {}
for v, col in (("p", "p"), ("g", "g")):
    sub = vm[vm.ventana == v]
    curvas[v], cohortes[v] = {}, []
    for c, dc in sub.groupby("cohorte"):
        if len(dc) < MIN_N_CURVA:
            continue
        series = list(dc[col])
        conkm = dc[dc.km.notna()]
        series_km = [s / k for s, k in zip(conkm[col], conkm.km)]
        men, men_km = pct(series), pct(series_km)
        curvas[v][int(c)] = {"mensual": men, "acum": acum_de(men),
                             "mensual_km": men_km, "acum_km": acum_de(men_km)}
        aj = dc[dc.ajuste]
        ajk = aj[aj.km.notna()]
        eur_col = "ep" if v == "p" else "eg"
        cohortes[v].append({
            "cohorte": int(c), "n": len(dc), "n_ajuste": len(aj), "n_km": len(ajk),
            "rama": int(conkm.km.median() * 1000) if len(conkm) else None,
            "eur": int(aj[eur_col].median()) if len(aj) >= MIN_N_CURVA else None,
            "eur_km": int((ajk[eur_col] / ajk.km).median()) if len(ajk) >= MIN_N_CURVA else None,
            "eur_con_km": int(ajk[eur_col].median()) if len(ajk) >= MIN_N_CURVA else None,
            "eur_eq": int(aj["eq"].median()) if len(aj) >= MIN_N_CURVA else None,
            "meses": int(dc.meses.median()),
        })
    emp, fuera = [], []
    sel = sub[sub.ajuste & (sub.cohorte >= EMPRESA_COHORTE_MIN) & (sub.km >= EMPRESA_KM_MIN)]
    for e, de in sel.groupby("empresa"):
        if len(de) < MIN_POZOS_EMPRESA:
            continue
        eur_col = "ep" if v == "p" else "eg"
        dk = de[de.km.notna()]
        r = {"empresa": e, "n": len(de),
             "desde": int(de.cohorte.min()), "rama": int(dk.km.median() * 1000) if len(dk) else None,
             "eur": int(de[eur_col].median()),
             "eur_km": int((dk[eur_col] / dk.km).median()) if len(dk) >= 5 else None,
             "eur_eq": int(de["eq"].median()),
             "meses": float(de.meses.median()), "cohorte_med": float(de.cohorte.median())}
        (emp if r["meses"] >= MESES_EMPRESA_MIN else fuera).append(r)
    emp.sort(key=lambda r: -(r["eur_km"] or 0))
    empresas[v], empresas_fuera[v] = emp, fuera

# Dispersión EUR vs rama (petróleo y gas, pozos con ajuste y rama)
disp = {v: [[int(round(r.km * 1000)), int(r.ep if v == "p" else r.eg), int(r.cohorte), int(r.id), int(r.joven)]
            for r in vm[(vm.ventana == v) & vm.ajuste & vm.km.notna()].itertuples()]
        for v in ("p", "g")}

out = {
    "ultimo": str(ultimo), "gas_a_pet": GAS_A_PET, "gor_gas": GOR_GAS,
    "dmin_anual": DMIN_ANUAL, "b_max": B_MAX, "vida_meses": VIDA_MESES, "limite": LIMITE,
    "r2_min": R2_MIN, "rama_min_m": RAMA_MIN_M, "frac_curva": FRAC_CURVA, "min_n_curva": MIN_N_CURVA,
    "b_max_joven": B_MAX_JOVEN, "meses_joven": MESES_JOVEN, "esc_rango": [ESC_MIN, ESC_MAX],
    "emp_rango": [EMP_MIN, EMP_MAX], "residual": RESIDUAL,
    "meses_empresa_min": MESES_EMPRESA_MIN, "mediana_motivos": list(MEDIANA_Q),
    "empresas_filtro": f"cohorte>={EMPRESA_COHORTE_MIN}, rama>={EMPRESA_KM_MIN:g}km, "
                       f"EUR {'/'.join(MEDIANA_Q)}, >={MIN_POZOS_EMPRESA} pozos, "
                       f"mediana de historia >={MESES_EMPRESA_MIN} meses",
    "curvas": curvas, "cohortes": cohortes, "empresas": empresas, "empresas_fuera": empresas_fuera,
    "dispersion": disp,
}
json.dump(out, open("data/curvas.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
MOTIVOS = {"ok": "ajuste aceptado", "poco_vol": f"acumulada <= {MIN_VOL}, no se ajusta",
           "parado": f"sin producción en los últimos {MESES_PARADO} meses: pronóstico 0",
           "parado_reciente": f"sin producción en los últimos {MESES_PARADO_REC} meses: sin pronóstico, "
                              "EUR = acumulada",
           "corto": f"menos de {MIN_PUNTOS} meses útiles",
           "dmin": "declinación ajustada menor a la terminal", "r2": f"ajuste pobre (r² < {R2_MIN})",
           "empalme": "el ajuste no empalma con la producción reciente"}
AVISOS = {"jp": f"pozo joven (< {MESES_JOVEN} meses desde el pico): b del petróleo limitado a {B_MAX_JOVEN:g}",
          "jg": f"pozo joven (< {MESES_JOVEN} meses desde el pico): b del gas limitado a {B_MAX_JOVEN:g}",
          "escp": "pronóstico de petróleo reescalado para empalmar con la producción reciente (mediana de "
                  "los últimos 3 meses con producción; hacia arriba, sin superar el último mes producido)",
          "escg": "pronóstico de gas reescalado para empalmar con la producción reciente (mediana de "
                  "los últimos 3 meses con producción; hacia arriba, sin superar el último mes producido)",
          "reap": "pozo reactivado en los últimos 12 meses: pronóstico incierto",
          "reag": "pozo reactivado en los últimos 12 meses: pronóstico incierto",
          "rq": "rama de exactamente 1000 m: posible valor redondeado"}
json.dump({"ultimo": str(ultimo), "dmin_anual": DMIN_ANUAL, "vida_meses": VIDA_MESES, "limite": LIMITE,
           "r2_min": R2_MIN, "b_max_joven": B_MAX_JOVEN, "meses_joven": MESES_JOVEN,
           "esc_rango": [ESC_MIN, ESC_MAX], "emp_rango": [EMP_MIN, EMP_MAX], "residual": RESIDUAL,
           "mediana_motivos": list(MEDIANA_Q), "fit_campos": ["qi_pron", "di", "b", "pico", "r2", "qi_ajuste"],
           "motivos": MOTIVOS, "avisos": AVISOS, "pozos": pozos},
          open("data/curvas_pozos.json", "w", encoding="utf-8"), separators=(",", ":"))
print("  -> data/curvas.json, data/curvas_pozos.json")

for v, nom, u in (("p", "PETRÓLEO", "m³"), ("g", "GAS", "Mm³")):
    print(f"\nVaca Muerta ventana {nom}: EUR mediana por cohorte ({u})")
    for r in cohortes[v]:
        print(f"  {r['cohorte']}  n={r['n']:4} ajuste={r['n_ajuste']:4} rama={r['rama']} "
              f"EUR={str(r['eur']):>9} EUR/km={r['eur_km']} meses={r['meses']}")
    print(f"  calidad ({nom.lower()}, fluido principal): "
          + ", ".join(f"{k}={n}" for k, n in vm[vm.ventana == v].q.value_counts().items()))
    print(f"  operadores: " + ", ".join(f"{e['empresa'][:18]} {e['eur_km']}" for e in empresas[v][:6]))
    if empresas_fuera[v]:
        print(f"  fuera del ranking (mediana < {MESES_EMPRESA_MIN} meses de historia): "
              + ", ".join(f"{e['empresa'][:24]} ({e['n']} pozos, {e['meses']:g} m)" for e in empresas_fuera[v]))

for k_, nom in (("p", "petróleo"), ("g", "gas")):
    rz = w["rz" + k_].dropna()
    tp_ = w["t" + k_]
    print(f"\nTodos los NC, {nom}: jóvenes (b<={B_MAX_JOVEN:g}) {int(w['j' + k_].sum())}, reescalados "
          f"{int(w['esc' + k_].sum())} (abajo {int((tp_ == 'abajo').sum())}, arriba {int((tp_ == 'arriba').sum())}, "
          f"arriba con tope en el último mes {int((tp_ == 'tope').sum())}), "
          f"reactivados (aviso) {int(w['rea' + k_].sum())}, "
          f"motivo empalme {int((w['q' + k_ + '_all'] == 'empalme').sum())}")
    print("    razón de empalme (1.er mes pronóstico / mediana de los últimos 3 meses con producción):")
    print(f"    <{EMP_MIN:g}x sin pronóstico: {int((rz < EMP_MIN).sum())} | "
          f"[{EMP_MIN:g}; {ESC_MIN:g}) reescalado: {int(((rz >= EMP_MIN) & (rz < ESC_MIN)).sum())} | "
          f"[{ESC_MIN:g}; {ESC_MAX:g}] sin tocar: {int(((rz >= ESC_MIN) & (rz <= ESC_MAX)).sum())} | "
          f"({ESC_MAX:g}; {EMP_MAX:g}] reescalado: {int(((rz > ESC_MAX) & (rz <= EMP_MAX)).sum())} | "
          f">{EMP_MAX:g}x sin pronóstico: {int((rz > EMP_MAX).sum())}")
    print(f"    motivos ({nom}, todos los NC): "
          + ", ".join(f"{k}={n}" for k, n in w["q" + k_ + "_all"].value_counts().items()))
print(f"Ramas de exactamente 1000 m (rq): {int(w.rq.sum())} pozos NC, {int(vm.rq.sum())} en VM")
