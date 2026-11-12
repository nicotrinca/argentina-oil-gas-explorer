"""
Zonas productivas e interferencia entre pozos (padre/hijo) de Vaca Muerta.

Corre DESPUÉS de preprocess_curvas.py: lee sus salidas (no repite el ajuste Arps) y suma la
coordenada de superficie, la concesión y el operador desde el CSV crudo (solo esas columnas).

LIMITACIÓN: el Cap. IV trae UNA coordenada por pozo, la de SUPERFICIE (boca de pozo). No hay talón,
punta ni rumbo de la rama horizontal (2–3 km). Todo el análisis es ZONAL: un hexágono o una distancia
de superficie no dice dónde está la rama. La UI lo aclara.

Entradas
  data/curvas_pozos.json   s (arranque), v (fluido), km (rama), p/g (serie mensual), ep/eg (EUR), qp/qg (motivo)
  data/curvas.json         mediana_motivos, rama_min_m, ultimo
  data/produccion-no-convencional.csv   idpozo, formacion, coordenadax/y, areapermisoconcesion, empresa, sigla

Definiciones
  Pozo VM            formación "vaca muerta" (la misma de preprocess_curvas: la del último registro).
  Horizontal         rama conocida >= rama_min_m (300 m; en curvas_pozos.json "km" no nulo). Solo estos
                     se miden por km y se clasifican.
  Fluido             "v" de curvas_pozos.json (ventana por GOR de los primeros 12 meses, > 3000 m³/m³ = gas).
  EUR/km válida      motivo del fluido en mediana_motivos (ok, parado, parado_reciente), como las medianas de Curvas.
                     Unidades: petróleo m³/km, gas Mm³/km (la UI muestra mil m³/km y MMm³/km).
  Acum12/km          suma de los primeros 12 meses desde el arranque / km, DATO REAL. Solo pozos con >= 12
                     meses de historia (hasta "ultimo", último mes completo). No depende del motivo del ajuste
                     (entran también los pozos "dmin", "r2", etc., que tienen producción real).
  Arranque           "s" de curvas_pozos.json = primer mes con producción >= 1 m³ o >= 1 Mm³. Los pozos que nunca
                     pasan ese umbral no tienen arranque (no se clasifican ni cuentan como vecinos).
  Percentiles        P10 = optimista (percentil 90 de los valores), P90 = conservador (percentil 10), como Curvas.

A1. Hexágonos  (data/zonas.json, GeoJSON WGS84, coordenadas con 5 decimales)
  Grilla hexagonal "pointy-top" en LAEA lat0=-38 lon0=-65 (como preprocess_geo.py). HEX_ANCHO_M = 3000 m es
  el ANCHO ENTRE LADOS PLANOS (distancia entre centros vecinos); lado = radio = 3000/√3 ≈ 1732 m;
  área ≈ 7,8 km². Cada pozo horizontal va al hexágono de su coordenada de superficie.
  Se exporta todo hexágono con al menos un pozo horizontal (con EUR/km válida o con acum12/km).
  FeatureCollection con miembros extra:
    meta         {ultimo, hex_ancho_m, hex_lado_m, min_n_hex, min_n_conc, mediana_motivos, rama_min_m,
                  unidades, supuestos:[...]}
    concesiones  {"p": [...], "g": [...]} filas por concesión (areapermisoconcesion), ordenadas por EUR/km desc:
                   {c: nombre, n: pozos con EUR/km válida, e: mediana EUR/km, na: pozos con acum12,
                    a: mediana acum12/km, o: operador con más pozos, pocos: true si n < MIN_N_CONC}
    features[i]  geometry Polygon; properties:
                   id   "q_r" (coordenadas axiales del hexágono)
                   p, g fluido -> null si no hay pozos de ese fluido, o
                        {n: pozos con EUR/km válida, e: mediana EUR/km, e10: P10, e90: P90 (null si pocos),
                         na: pozos con acum12, a: mediana acum12/km (null si na = 0),
                         c: [cohorte mín, cohorte máx], o: [[operador, n], ...] hasta 3 (sobre todos los
                         horizontales del fluido en el hexágono), pocos: true si n < MIN_N_HEX}
                   (e/a son null si no hay pozos con ese dato)

A2. Padre / hijo  (data/interferencia.json)
  Vecinos de un pozo = otros pozos VM HORIZONTALES (rama conocida o sigla con "(h") con arranque, a < RADIO_M
  en superficie. Los verticales/dirigidos de VM (pilotos, "(d)") no cuentan: drenan un radio chico.
  (Con VECINOS_SOLO_HORIZ = False entran todos; el resumen impreso muestra la sensibilidad.)
    hermano     vecino a < HERMANO_M que arrancó dentro de ±HERMANO_MESES (misma locación, misma tanda): se ignora
    hijo        algún vecino (no hermano) arrancó >= MESES_HIJO meses antes
    padre       ningún vecino (no hermano) arrancó antes (arrancar el mismo mes no cuenta como "antes")
    intermedio  el vecino más viejo arrancó 1–5 meses antes
  Esquema:
    supuestos   {radio_m, hermano_m, hermano_meses, meses_hijo, coordenada, vecinos, eur_min_meses, min_zona,
                 textos:[...]}  (para la UI)
    tramos      [[6, 11], [12, 23], [24, 47], [48, null]] (meses calendario entre el arranque del vecino más viejo
                 y el del hijo)
    pozos       {idpozo: [clase, n_prev, meses_viejo, dist_m, n_hermanos]}  clase "P"/"H"/"I"; n_prev = vecinos
                 previos (no hermanos); meses_viejo = meses calendario entre el arranque del vecino más viejo y el
                 del pozo (no son meses produciendo: el vecino pudo estar parado) (null en
                 padres); dist_m = distancia al vecino previo más cercano (null en padres). Solo VM horizontales.
    clases      {"p": {P, H, I}, "g": {...}} conteo por fluido
    stats       {"p": {...}, "g": {...}}, cada uno:
      por_cohorte   [{cohorte, P: {na, a, ne, e}, H: {...}, I: {...}}]  medianas acum12/km (a) y EUR/km (e) con n
      por_tramo     [{tramo: [desde, hasta|null], na, a, ne, e}]  solo hijos; más "padres": {na, a, ne, e}
      controlado    {"hex": {...}, "conc": {...}}, cada uno {"a": R, "e": R} con
                    R = {zonas, mediana, p25, p75, detalle: [[zona, nP, nH, med_padre, med_hijo, ratio], ...]}
                    Zonas (hexágono / concesión) con >= MIN_ZONA padres y >= MIN_ZONA hijos con ese dato;
                    ratio = mediana hijos / mediana padres. CIFRA PRINCIPAL: controlado.hex.a.mediana.
    sensibilidad {"hijo12": {meses_hijo: 12, hijos: {p, g}, hex: {p|g: {a|e: {zonas, mediana, p25, p75}}}},
                  "todos_vm": {vecinos, hijos, hex: (igual)}}  cociente controlado por hexágono rehaciendo la
                 clasificación con hijo = vecino >= 12 meses antes (sin meses compartidos en la acum12 del padre)
                 o con todos los VM (verticales/dirigidos incluidos) como vecinos.
  Métrica principal: acum12/km (dato real). EUR/km es secundaria (pronóstico): en las estadísticas de
  interferencia solo entran pozos con >= EUR_MIN_MESES (24) meses de historia (a < 24 la EUR es casi todo
  pronóstico y depende de b). En los hexágonos (A1) la EUR/km usa todos los pozos válidos, igual que Curvas.
"""
import json
import math

import numpy as np
import pandas as pd
from pyproj import Transformer

HEX_ANCHO_M = 3000.0             # ancho entre lados planos (= distancia entre centros vecinos)
HEX_LADO_M = HEX_ANCHO_M / math.sqrt(3)
MIN_N_HEX = 3                    # hexágono con < 3 pozos con EUR/km -> pocos (gris rayado)
MIN_N_CONC = 5                   # concesión con < 5 -> pocos
RADIO_M = 1000.0                 # vecindad en superficie
HERMANO_M = 100.0                # misma locación
HERMANO_MESES = 3                # misma tanda (± meses)
MESES_HIJO = 6                   # hijo: vecino previo con >= 6 meses de ventaja
MESES_HIJO_SENS = 12             # sensibilidad: hijo = vecino con >= 12 meses de ventaja (sin meses compartidos)
EUR_MIN_MESES = 24               # interferencia con EUR/km: solo pozos con >= 24 meses de historia
MIN_ZONA = 3                     # comparación controlada: >= 3 padres y >= 3 hijos en la zona
TRAMOS = [(6, 11), (12, 23), (24, 47), (48, None)]
VECINOS_SOLO_HORIZ = True
EMPRESA_ALIAS = {"VISTA OIL & GAS ARGENTINA SAU": "VISTA ENERGY ARGENTINA SAU"}
METRIC = "+proj=laea +lat_0=-38 +lon_0=-65 +datum=WGS84 +units=m"
A_M = Transformer.from_crs(4326, METRIC, always_xy=True)
A_GEO = Transformer.from_crs(METRIC, 4326, always_xy=True)


def med(x):
    return float(np.median(x)) if len(x) else None


def rnd(x, d=0):
    if x is None:
        return None
    return int(round(x)) if d == 0 else round(float(x), d)


# ── Salidas de preprocess_curvas.py ─────────────────────────────────────────
print("Leyendo curvas_pozos.json y curvas.json...")
cp = json.load(open("data/curvas_pozos.json", encoding="utf-8"))
cj = json.load(open("data/curvas.json", encoding="utf-8"))
MOTIVOS = set(cj["mediana_motivos"])
ultimo = pd.Period(cj["ultimo"], freq="M")

# ── CSV crudo: solo lo que falta (coordenada, concesión, operador, sigla) ──
print("Leyendo coordenadas de superficie del CSV no convencional...")
cols = ["idpozo", "anio", "mes", "formacion", "coordenadax", "coordenaday", "areapermisoconcesion", "empresa", "sigla"]
d = pd.read_csv("data/produccion-no-convencional.csv", usecols=cols, encoding="utf-8-sig", low_memory=False)
d = d.sort_values(["anio", "mes"]).groupby("idpozo").last()
d = d[d.formacion.astype(str).str.strip().str.lower() == "vaca muerta"]
d["empresa"] = d["empresa"].replace(EMPRESA_ALIAS)

filas = []
for idp, r in d.iterrows():
    z = cp["pozos"].get(str(int(idp)))
    if not z or pd.isna(r.coordenadax) or pd.isna(r.coordenaday):
        continue
    v = "g" if z["v"] == "g" else "p"
    serie = z[v]
    # arranque real: algún mes >= 1 m³ o >= 1 Mm³ (si no, "s" es el primer mes > 0 y no cuenta)
    arranca = max(z["p"] or [0]) >= 1 or max(z["g"] or [0]) >= 1
    km = z["km"]
    meses = len(serie)
    eur = z["e" + v]
    filas.append({
        "id": int(idp), "lon": float(r.coordenadax), "lat": float(r.coordenaday),
        "conc": str(r.areapermisoconcesion).strip(), "emp": str(r.empresa).strip(),
        "horiz": km is not None, "h_sigla": "(h" in str(r.sigla).lower(),
        "ini": pd.Period(z["s"], freq="M") if arranca else None, "v": v, "km": km, "meses": meses,
        "eur_km": eur / km if km and z["q" + v] in MOTIVOS else None,
        "a12_km": sum(serie[:12]) / km if km and meses >= 12 else None,
    })
w = pd.DataFrame(filas)
w["cohorte"] = w.ini.apply(lambda p: p.year if p is not None else None)
x, y = A_M.transform(w.lon.to_numpy(), w.lat.to_numpy())
w["x"], w["y"] = x, y
w["mi"] = w.ini.apply(lambda p: p.year * 12 + p.month - 1 if p is not None else np.nan)
print(f"  {len(w):,} pozos VM con serie y coordenada; {int(w.horiz.sum()):,} horizontales (rama >= "
      f"{cj['rama_min_m']} m); {int(w.eur_km.notna().sum()):,} con EUR/km válida, "
      f"{int(w.a12_km.notna().sum()):,} con acum12/km")

# ── A1. Hexágonos ───────────────────────────────────────────────────────────
S = HEX_LADO_M


def hex_de(x, y):
    """Coordenadas axiales (q, r) del hexágono pointy-top de lado S que contiene (x, y)."""
    q = (math.sqrt(3) / 3 * x - y / 3) / S
    r = (2 / 3 * y) / S
    cx, cz = q, r
    cy = -cx - cz
    rx, ry, rz = round(cx), round(cy), round(cz)
    dx, dy, dz = abs(rx - cx), abs(ry - cy), abs(rz - cz)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return int(rx), int(rz)


def hex_poly(q, r):
    cx = S * math.sqrt(3) * (q + r / 2)
    cy = S * 1.5 * r
    ang = [math.radians(60 * k - 30) for k in range(6)]
    xs = [cx + S * math.cos(a) for a in ang]
    ys = [cy + S * math.sin(a) for a in ang]
    lo, la = A_GEO.transform(xs, ys)
    ring = [[round(a, 5), round(b, 5)] for a, b in zip(lo, la)]
    return ring + [ring[0]]


hz = w[w.horiz].copy()
hz["hex"] = [hex_de(a, b) for a, b in zip(hz.x, hz.y)]
hz["hex_id"] = hz.hex.apply(lambda t: f"{t[0]}_{t[1]}")


def resumen_fluido(g, min_n):
    e = g.eur_km.dropna().to_numpy()
    a = g.a12_km.dropna().to_numpy()
    coh = g.cohorte.dropna()
    ops = g.emp.value_counts()
    pocos = len(e) < min_n
    out = {"n": int(len(e)), "e": rnd(med(e)),
           "e10": None if pocos else rnd(np.percentile(e, 90)),
           "e90": None if pocos else rnd(np.percentile(e, 10)),
           "na": int(len(a)), "a": rnd(med(a)),
           "c": [int(coh.min()), int(coh.max())] if len(coh) else None,
           "o": [[k, int(n)] for k, n in ops.head(3).items()]}
    if pocos:
        out["pocos"] = True
    return out


feats = []
for hid, g in hz.groupby("hex_id"):
    q, r = g.hex.iloc[0]
    props = {"id": hid}
    for v in ("p", "g"):
        gv = g[g.v == v]
        props[v] = resumen_fluido(gv, MIN_N_HEX) if len(gv) and (gv.eur_km.notna().any() or gv.a12_km.notna().any()) else None
    if props["p"] is None and props["g"] is None:
        continue
    feats.append({"type": "Feature", "properties": props,
                  "geometry": {"type": "Polygon", "coordinates": [hex_poly(q, r)]}})

conc = {}
for v in ("p", "g"):
    rows = []
    for c, g in hz[hz.v == v].groupby("conc"):
        e, a = g.eur_km.dropna(), g.a12_km.dropna()
        if not len(e) and not len(a):
            continue
        row = {"c": c, "n": int(len(e)), "e": rnd(med(e)), "na": int(len(a)), "a": rnd(med(a)),
               "o": g.emp.value_counts().index[0]}
        if len(e) < MIN_N_CONC:
            row["pocos"] = True
        rows.append(row)
    rows.sort(key=lambda r: (bool(r.get("pocos")), -(r["e"] if r["e"] is not None else -1)))
    conc[v] = rows

SUP_ZONAS = [
    "Ubicación por coordenada de superficie (boca de pozo); la rama horizontal puede extenderse 2–3 km "
    "en cualquier dirección: el hexágono no es donde produce el pozo, es desde dónde se perforó.",
    f"Hexágonos de {HEX_ANCHO_M / 1000:g} km de ancho entre lados planos (lado {HEX_LADO_M / 1000:.2f} km, "
    f"≈ {1.5 * math.sqrt(3) * HEX_LADO_M ** 2 / 1e6:.1f} km²).",
    f"Pozos horizontales de Vaca Muerta con rama conocida ≥ {cj['rama_min_m']} m. EUR/km: pozos con EUR válida "
    f"({', '.join(cj['mediana_motivos'])}), es pronóstico. Acum. 12 meses/km: dato real, pozos con ≥ 12 meses.",
    f"Con menos de {MIN_N_HEX} pozos con EUR/km el hexágono va gris rayado (pocos pozos), sin color.",
    "Cada pozo cuenta en el fluido de su ventana (GOR de los primeros 12 meses).",
]
meta = {"ultimo": str(ultimo), "hex_ancho_m": HEX_ANCHO_M, "hex_lado_m": round(HEX_LADO_M, 1),
        "min_n_hex": MIN_N_HEX, "min_n_conc": MIN_N_CONC, "mediana_motivos": cj["mediana_motivos"],
        "rama_min_m": cj["rama_min_m"],
        "unidades": {"p": "m³/km (EUR y acum12)", "g": "Mm³/km (EUR y acum12)"}, "supuestos": SUP_ZONAS}
json.dump({"type": "FeatureCollection", "meta": meta, "concesiones": conc, "features": feats},
          open("data/zonas.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


# ── A2. Padre / hijo ───────────────────────────────────────────────────────
def clasificar(solo_horiz, meses_hijo=MESES_HIJO):
    """Devuelve DataFrame (index id) con clase, n_prev, meses_viejo, dist_m, n_herm para los VM horizontales.
    meses_hijo: ventaja mínima (meses entre arranques) del vecino más viejo para ser hijo."""
    vec = w[w.ini.notna() & ((w.horiz | w.h_sigla) if solo_horiz else True)]
    vx, vy, vm_, vid = vec.x.to_numpy(), vec.y.to_numpy(), vec.mi.to_numpy(), vec.id.to_numpy()
    obj = w[w.horiz & w.ini.notna()]
    out = []
    for o in obj.itertuples():
        dist = np.hypot(vx - o.x, vy - o.y)
        sel = (dist < RADIO_M) & (vid != o.id)
        dd, dm = dist[sel], o.mi - vm_[sel]         # dm > 0: el vecino arrancó antes
        herm = (dd < HERMANO_M) & (np.abs(dm) <= HERMANO_MESES)
        prev = (~herm) & (dm >= 1)
        if not prev.any():
            out.append((o.id, "P", 0, None, None, int(herm.sum())))
            continue
        viejo = int(dm[prev].max())
        clase = "H" if viejo >= meses_hijo else "I"
        out.append((o.id, clase, int(prev.sum()), viejo, int(round(dd[prev].min())), int(herm.sum())))
    return pd.DataFrame(out, columns=["id", "clase", "n_prev", "meses_viejo", "dist_m", "n_herm"]).set_index("id")


def stats(cl):
    """Estadísticas por fluido sobre la clasificación cl (unida a hz)."""
    t = hz.join(cl, on="id", how="inner")
    t["eur_st"] = t.eur_km.where(t.meses >= EUR_MIN_MESES)
    res = {}
    for v in ("p", "g"):
        tv = t[t.v == v]
        dmed = lambda g: {"na": int(g.a12_km.notna().sum()), "a": rnd(med(g.a12_km.dropna())),
                          "ne": int(g.eur_st.notna().sum()), "e": rnd(med(g.eur_st.dropna()))}
        coh = []
        for c, g in tv.groupby("cohorte"):
            coh.append({"cohorte": int(c), **{k: dmed(g[g.clase == k]) for k in ("P", "H", "I")}})
        tr = []
        hij = tv[tv.clase == "H"]
        for a, b in TRAMOS:
            g = hij[(hij.meses_viejo >= a) & ((hij.meses_viejo <= b) if b is not None else True)]
            tr.append({"tramo": [a, b], **dmed(g)})
        ctrl = {}
        for zona, col in (("hex", "hex_id"), ("conc", "conc")):
            ctrl[zona] = {}
            for met, mcol in (("a", "a12_km"), ("e", "eur_st")):
                det = []
                for zid, g in tv.groupby(col):
                    pp = g[(g.clase == "P")][mcol].dropna()
                    hh = g[(g.clase == "H")][mcol].dropna()
                    if len(pp) >= MIN_ZONA and len(hh) >= MIN_ZONA and pp.median() > 0:
                        det.append([zid, int(len(pp)), int(len(hh)), rnd(pp.median()), rnd(hh.median()),
                                    round(float(hh.median() / pp.median()), 3)])
                rat = np.array([r[-1] for r in det])
                ctrl[zona][met] = {"zonas": len(det), "mediana": round(med(rat), 3) if len(rat) else None,
                                   "p25": round(float(np.percentile(rat, 25)), 3) if len(rat) else None,
                                   "p75": round(float(np.percentile(rat, 75)), 3) if len(rat) else None,
                                   "detalle": sorted(det, key=lambda r: r[-1])}
        res[v] = {"por_cohorte": coh, "por_tramo": tr, "padres": dmed(tv[tv.clase == "P"]), "controlado": ctrl}
    return res, t


cl = clasificar(VECINOS_SOLO_HORIZ)
st, tt = stats(cl)
clases = {v: {k: int(((tt.v == v) & (tt.clase == k)).sum()) for k in ("P", "H", "I")} for v in ("p", "g")}
SUP_INT = [
    "Coordenada de SUPERFICIE: dos pozos a 300 m en superficie pueden tener las ramas a 2 km (o paralelas a "
    "200 m). La vecindad es aproximada; no hay talón, punta ni rumbo de rama en los datos.",
    f"Vecinos: otros pozos horizontales de Vaca Muerta a menos de {RADIO_M:g} m en superficie, con producción "
    "(arranque = primer mes con ≥ 1 m³ o ≥ 1 Mm³). Los verticales y dirigidos no cuentan.",
    f"Hermanos (se ignoran): vecinos a menos de {HERMANO_M:g} m que arrancaron dentro de ±{HERMANO_MESES} meses "
    "(misma locación, misma tanda).",
    f"Hijo: algún vecino arrancó {MESES_HIJO} meses o más antes. Padre: ningún vecino arrancó antes. "
    f"Intermedio: el más viejo arrancó 1–{MESES_HIJO - 1} meses antes (no entra en la comparación).",
    "Métrica principal: acumulada de los primeros 12 meses por km de rama (dato real). EUR/km es pronóstico y "
    f"solo usa pozos con {EUR_MIN_MESES} meses o más de historia.",
    f"Comparación controlada: dentro de cada hexágono (o concesión) con ≥ {MIN_ZONA} padres y ≥ {MIN_ZONA} hijos, "
    "mediana de hijos / mediana de padres; se informa la mediana de esos cocientes. Evita comparar hijos de "
    "zonas buenas con padres de zonas malas.",
    f"Sesgo hacia 1 en hijos con vecino de {MESES_HIJO}–11 meses: los primeros 12 meses del padre ya incluyen meses "
    "en que el hijo producía al lado (el padre también se degrada), así que la comparación de acum. 12 meses "
    f"subestima la interferencia. Sensibilidad: con hijo = vecino {MESES_HIJO_SENS} meses o más antes (línea debajo de la cifra).",
    "Exploratorio: correlación, no causa. Los hijos son más nuevos (otro diseño de fractura, más arena y etapas) "
    "y eso puede compensar o esconder la interferencia.",
]


def resumen_sens(st_):
    """Cociente controlado por hexágono (acum12 y EUR) por fluido, sin el detalle."""
    return {v: {m: {k: st_[v]["controlado"]["hex"][m][k] for k in ("zonas", "mediana", "p25", "p75")}
                for m in ("a", "e")} for v in ("p", "g")}


# Sensibilidad 1: hijo = vecino previo con >= 12 meses (saca a los hijos cuyo padre comparte meses en su acum12)
cl12 = clasificar(VECINOS_SOLO_HORIZ, MESES_HIJO_SENS)
st12, tt12 = stats(cl12)
# Sensibilidad 2: todos los VM (incluidos verticales/dirigidos) como vecinos
cl2 = clasificar(not VECINOS_SOLO_HORIZ)
st2, tt2 = stats(cl2)
sens = {
    "hijo12": {"meses_hijo": MESES_HIJO_SENS, "hex": resumen_sens(st12),
               "hijos": {v: int(((tt12.v == v) & (tt12.clase == "H")).sum()) for v in ("p", "g")}},
    "todos_vm": {"vecinos": "todos los VM" if VECINOS_SOLO_HORIZ else "VM horizontales", "hex": resumen_sens(st2),
                 "hijos": {v: int(((tt2.v == v) & (tt2.clase == "H")).sum()) for v in ("p", "g")}},
}
inter = {
    "ultimo": str(ultimo),
    "supuestos": {"radio_m": RADIO_M, "hermano_m": HERMANO_M, "hermano_meses": HERMANO_MESES,
                  "meses_hijo": MESES_HIJO, "coordenada": "superficie",
                  "vecinos": "VM horizontales" if VECINOS_SOLO_HORIZ else "todos los VM",
                  "eur_min_meses": EUR_MIN_MESES, "min_zona": MIN_ZONA, "hex_ancho_m": HEX_ANCHO_M,
                  "textos": SUP_INT},
    "tramos": [[a, b] for a, b in TRAMOS],
    "clases": clases,
    "pozos": {str(i): [r.clase, int(r.n_prev), None if pd.isna(r.meses_viejo) else int(r.meses_viejo),
                       None if pd.isna(r.dist_m) else int(r.dist_m), int(r.n_herm)] for i, r in cl.iterrows()},
    "stats": st,
    "sensibilidad": sens,
}
json.dump(inter, open("data/interferencia.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("  -> data/zonas.json, data/interferencia.json")

# ── Resumen ────────────────────────────────────────────────────────────────
npocos = {v: sum(1 for f in feats if f["properties"][v] and f["properties"][v].get("pocos")) for v in ("p", "g")}
ncol = {v: sum(1 for f in feats if f["properties"][v] and not f["properties"][v].get("pocos")) for v in ("p", "g")}
print(f"\nHexágonos ({HEX_ANCHO_M / 1000:g} km entre lados planos): {len(feats)} con pozos · "
      f"petróleo {ncol['p']} con color + {npocos['p']} pocos · gas {ncol['g']} con color + {npocos['g']} pocos")
for v, nom in (("p", "petróleo"), ("g", "gas")):
    cc = conc[v]
    print(f"Concesiones {nom}: {len(cc)} ({sum(1 for r in cc if r.get('pocos'))} con n < {MIN_N_CONC}); top: "
          + ", ".join(f"{r['c'][:22]} {r['e']} (n {r['n']})" for r in cc[:4]))
print(f"\nPadre/hijo (vecinos: {inter['supuestos']['vecinos']}, radio {RADIO_M:g} m):")
for v, nom in (("p", "petróleo"), ("g", "gas")):
    c = clases[v]
    s = st[v]
    print(f"  {nom}: padres {c['P']}, hijos {c['H']}, intermedios {c['I']}")
    for zona in ("hex", "conc"):
        for met, mn in (("a", "acum12/km"), ("e", f"EUR/km (>= {EUR_MIN_MESES} m)")):
            R = s["controlado"][zona][met]
            print(f"    controlado por {zona:4} {mn:20}: ratio hijo/padre mediana {R['mediana']} "
                  f"(P25–P75 {R['p25']}–{R['p75']}) en {R['zonas']} zonas")
    print("    tramos (hijos, acum12/km): " + ", ".join(
        f"{t['tramo'][0]}-{t['tramo'][1] or ''}: {t['a']} (n {t['na']})" for t in s["por_tramo"])
          + f" · padres {s['padres']['a']} (n {s['padres']['na']})")
for v, nom in (("p", "petróleo"), ("g", "gas")):
    for k, txt in (("hijo12", f"hijo = vecino >= {MESES_HIJO_SENS} meses antes"), ("todos_vm", sens["todos_vm"]["vecinos"] + " como vecinos")):
        R = sens[k]["hex"][v]["a"]
        print(f"  sensibilidad ({txt}) {nom}: hijos {sens[k]['hijos'][v]}, ratio hex acum12 {R['mediana']} "
              f"(P25–P75 {R['p25']}–{R['p75']}) en {R['zonas']} zonas")
