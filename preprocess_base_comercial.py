"""
Base comercial de pozos (shapefile licenciado, local) -> data/privado/base_comercial.json   (MODO PRIVADO, SOLO LOCAL)

La base es LICENCIADA: ni el shapefile, ni su config, ni el JSON van a git ni a Firebase. Todo queda en data/privado/
(ignorado por git y fuera de la whitelist de tools/build_public.mjs, que además falla si aparecen sus valores en
public/). El visor lo pide con fetch silencioso solo desde localhost: si no está, no muestra nada.
En este código no van rutas, nombres del proveedor, nombres de columnas ni el vocabulario de la base, ni nombres de
pozos: todo eso vive en la config local. El JSON sale con los valores YA traducidos (el visor no traduce nada).

Uso (desde la raíz del proyecto):
  .venv/Scripts/python preprocess_base_comercial.py "<ruta al .shp>" [ruta a la config]
  o con las variables de entorno BASE_COMERCIAL_SHP y BASE_COMERCIAL_CONFIG.
  Config por defecto: data/privado/config_base_comercial.json. Lee con pyogrio (si falla con `python -I`, sin -I).

Formato de la config (JSON)
  columnas            {clave: [columna del shp, tipo]}; tipo: s = texto, c = categórico (va a `tablas`), f = fecha,
                      n = número (0 = sin dato), q = precisión de una fecha (se traduce con `precision`).
                      Claves que usa el cruce: nombre, alt, desv, spud, spud_q, td (el resto se exporta tal cual).
  socios              [[columna nombre, columna participación 0-1], ...]
  col_id_alternativo  columna con un id alternativo que puede coincidir con el idpozo del Cap. IV
  col_actualizacion   columna con la fecha de última actualización de cada registro (texto aaaammdd... o fecha)
  nulos               textos que significan "sin dato"
  precision           {valor original: código}; códigos: exacta, semana, mes, trimestre, semestre, año, estimada
  traducciones        {clave | "*": {original: traducción}} (primero la de la clave, después "*")
  patrones            {clave: [[regex, reemplazo], ...]} para textos con números (años, etc.)
  tokens              {clave: {sep, unir, valores: {abreviatura: traducción}}} (listas como "A, B, C")
  Lo que no está en la config queda en el original (textos libres raros).

Entrada
  Shapefile de puntos (EPSG:4326), un registro por pozo. Pozos del visor: unión de data/pozos_<AÑO>.js (idpozo,
  sigla, coordenada ya corregida, cuenca) + profundidad e inicio de perforación de data/capitulo-iv-pozos.csv.

Cruce (cada pozo del visor con a lo sumo un registro de la base; la clave del visor es idpozo, nunca la sigla)
  Los pozos que empezaron a perforarse después del corte de la base (fecha del Cap. IV) no se cruzan.
  1. "nombre": sigla normalizada (mayúsculas, solo A-Z0-9) igual al nombre alternativo u oficial normalizado.
     Si hay varios candidatos, el más cercano. Se acepta a <= D_NOMBRE (1000 m): la base tiene corrimientos
     sistemáticos de datum de 150-450 m en algunas cuencas (en Golfo San Jorge ~440 m al este).
  2. "nombre_sin_sufijo": igual, sin los grupos entre paréntesis AL FINAL del nombre ("(d)", "(h)", ...). Si la sigla
     del visor marca pozo dirigido/horizontal y la base dice vertical sin sufijo, no se cruza, salvo que la
     profundidad del Cap. IV coincida ±5 % con la TD de la base.
  3. "id": el id alternativo de la base coincide con el idpozo, también a <= D_NOMBRE.
  Un registro de la base solo se comparte entre idpozo en el mismo lugar (<= 50 m: mismo pozo físico con varios
  idpozo en el Cap. IV); si no, se queda con el más cercano.
  4. Proximidad, para los que quedan: puntos de la base no usados a <= D_ESPACIAL (150 m), tras corregir el
     corrimiento local (mediana (dx, dy) de los pozos ya cruzados a <= 5 km; mínimo 5 y dispersión <= 75 m).
     A 150 m el vecino equivocado es tan probable como el correcto, así que se exige:
     "distancia_prof": el pozo tiene profundidad en el Cap. IV y exactamente UN candidato tiene TD a ±5 % y, si la
       base trae spud, fecha compatible con el inicio de perforación del Cap. IV (±90 días si es exacta/semana/mes,
       ±1 año si es trimestral/semestral/anual, ±2 años si es estimada).
     "distancia": sin profundidad en el Cap. IV, único candidato y a <= 50 m.
     Si no, sin match (ambiguo o rechazado). En el visor se muestra como "cruce por proximidad (verificar)".
  Se guarda método, distancia real entre coordenadas (m), la corregida si hubo corrección y los candidatos (> 1).

Salida: data/privado/base_comercial.json
  {generado, corte (última actualización de la base), aviso, umbrales_m, campos: [...], tablas: {campo: [valores]},
   pozos: {idpozo: [valor por campo]}, huellas: [[idpozo, td, spud], ...], stats}
  Categóricos como índice en `tablas[campo]`; null = sin dato. Fechas ISO "aaaa-mm-dd"; precisión en *_q (código).
  `huellas`: muestra de hasta 2000 pozos con TD o spud exacto DISTINTOS de los del Cap. IV (público), para que
  tools/privado.mjs detecte si pares idpozo-valor de la base llegan a public/.
"""
import datetime as dt
import json
import os
import re
import sys

import numpy as np
import pandas as pd
import pyogrio

from comun import anios_produccion

SALIDA = "data/privado/base_comercial.json"
CONFIG = "data/privado/config_base_comercial.json"
CAP4 = "data/capitulo-iv-pozos.csv"
D_NOMBRE = 1000.0      # m, máximo para aceptar un cruce por nombre o id
D_ESPACIAL = 150.0     # m, radio del cruce por proximidad
R_CORRIMIENTO = 5000.0 # m, vecinos ya cruzados para estimar el corrimiento local
MIN_VECINOS = 5
MAX_DISPERSION = 75.0  # m
D_ESPACIAL_SIN_PROF = 50.0  # m, sin profundidad en el Cap. IV: único candidato y más cerca
TOL_PROF = 0.05        # tolerancia relativa TD de la base vs profundidad del Cap. IV
TOL_DIAS = {"exacta": 90, "semana": 90, "mes": 90}            # spud vs inicio de perforación del Cap. IV
TOL_ANIOS = {"trimestre": 1, "semestre": 1, "año": 1, "estimada": 2}
MISMO_POZO = 50.0      # m, idpozo distintos en el mismo lugar = mismo pozo físico (pueden compartir registro)
N_HUELLAS = 2000
CLAVES_CRUCE = ["nombre", "alt", "desv", "spud", "spud_q", "td"]
METODOS = ["nombre", "nombre_sin_sufijo", "id", "distancia_prof", "distancia"]
SUFIJO_FINAL = re.compile(r"(\s*\([^()]*\))+\s*$")
SUFIJO_DIRIGIDO = re.compile(r"\(\s*[hd]\s*\)\s*$", re.I)
VERTICAL = "Vertical"  # valor traducido de la trayectoria (la config traduce el original a este texto)


def norm(s, sin_sufijo=False):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).upper()
    if sin_sufijo:
        s = SUFIJO_FINAL.sub("", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def metros(lat0, lon0, lat1, lon1):
    """Distancia (m) y componentes (dx este, dy norte) en proyección equirectangular local."""
    dy = (lat1 - lat0) * 111320.0
    dx = (lon1 - lon0) * 111320.0 * np.cos(np.radians(lat0))
    return np.hypot(dx, dy), dx, dy


def fecha_mixta(serie):
    """Fecha de texto ("aaaammdd...", ISO, etc.) o ya fecha -> Timestamp (NaT si no se entiende)."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie, errors="coerce")
    s = serie.astype("string").str.strip()
    compacta = s.str.fullmatch(r"\d{8}(\d*(\.\d*)?)?").fillna(False)
    out = pd.to_datetime(s.where(~compacta).astype(object), errors="coerce", format="mixed")
    out[compacta] = pd.to_datetime(s[compacta].str[:8], format="%Y%m%d", errors="coerce")
    return out


def leer_config(ruta):
    if not ruta or not os.path.exists(ruta):
        raise SystemExit(f"Falta la config de la base comercial ({ruta or CONFIG}): ver el formato en el docstring.\n"
                         "Pasala como 2.º argumento o con BASE_COMERCIAL_CONFIG.")
    with open(ruta, encoding="utf8") as f:
        cfg = json.load(f)
    faltan = [k for k in ("columnas", "precision") if k not in cfg]
    faltan += [k for k in CLAVES_CRUCE if k not in cfg.get("columnas", {})]
    if faltan:
        raise SystemExit(f"Config incompleta, faltan: {faltan}")
    return cfg


def traductor(cfg, clave):
    exacto = {**cfg.get("traducciones", {}).get("*", {}), **cfg.get("traducciones", {}).get(clave, {})}
    patrones = [(re.compile(a), b) for a, b in cfg.get("patrones", {}).get(clave, [])]
    tok = cfg.get("tokens", {}).get(clave)

    def t(s):
        if s in exacto:
            return exacto[s]
        for rx, rep in patrones:
            if rx.search(s):
                return rx.sub(rep, s)
        if tok:
            partes = [p.strip() for p in s.split(tok.get("sep", ","))]
            if any(p in tok["valores"] for p in partes):
                return tok.get("unir", ", ").join(tok["valores"].get(p, p) for p in partes)
        return s
    return t


def pozos_visor():
    filas = []
    for a in anios_produccion():
        p = f"data/pozos_{a}.js"
        if not os.path.exists(p):
            continue
        t = open(p, encoding="utf8").read()
        for r in json.loads(t[t.index("["):t.rindex("]") + 1]):
            filas.append((int(r[13]), r[12], r[0], r[1], r[6] or "SIN CUENCA"))
    if not filas:
        raise SystemExit("No hay data/pozos_<AÑO>.js: correr antes preprocess_peryear.py")
    v = pd.DataFrame(filas, columns=["id", "sigla", "lat", "lon", "cu"]).drop_duplicates("id", keep="last")
    # Profundidad e inicio de perforación del Cap. IV: verifican el cruce y explican los sin match
    v["prof"], v["perf"] = np.nan, pd.NaT
    if os.path.exists(CAP4):
        c4 = pd.read_csv(CAP4, usecols=["idpozo", "profundidad", "adjiv_fecha_inicio_perf"]).drop_duplicates("idpozo")
        c4["perf"] = pd.to_datetime(c4.adjiv_fecha_inicio_perf, errors="coerce")
        v = v.drop(columns=["prof", "perf"]).merge(
            c4.rename(columns={"idpozo": "id", "profundidad": "prof"})[["id", "prof", "perf"]], on="id", how="left")
    else:
        print(f"Aviso: falta {CAP4}; el cruce por proximidad queda limitado a <= {D_ESPACIAL_SIN_PROF:.0f} m")
    return v.reset_index(drop=True)


def valor(x, tipo, nulos):
    if x is None or x is pd.NaT or (isinstance(x, float) and np.isnan(x)):
        return None
    if tipo == "f":
        try:
            return pd.Timestamp(x).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None
    if tipo == "n":
        try:
            f = float(x)
        except (ValueError, TypeError):
            return None
        return None if f == 0 or not np.isfinite(f) else (int(f) if f == int(f) else round(f, 1))
    s = str(x).strip()
    return s if s and s not in nulos else None


def leer_base(ruta, cfg):
    """Lee solo las columnas de la config, las renombra a las claves genéricas y deja los textos traducidos."""
    col = cfg["columnas"]
    ren = {c: k for k, (c, _) in col.items()}
    socios = cfg.get("socios", [])
    for i, (cn, cw) in enumerate(socios):
        ren[cn], ren[cw] = f"_socio{i}", f"_socio{i}_wi"
    if cfg.get("col_id_alternativo"):
        ren[cfg["col_id_alternativo"]] = "_id_alt"
    if cfg.get("col_actualizacion"):
        ren[cfg["col_actualizacion"]] = "_act"
    disponibles = set(pyogrio.read_info(ruta)["fields"])
    faltan = [c for c in ren if c not in disponibles]
    if faltan:
        raise SystemExit(f"La config nombra {len(faltan)} columna(s) que el shapefile no tiene")
    b = pyogrio.read_dataframe(ruta, columns=list(ren), read_geometry=True)
    b["lon"], b["lat"] = b.geometry.x, b.geometry.y
    b = b.drop(columns="geometry").rename(columns=ren)
    b = b[np.isfinite(b.lat) & np.isfinite(b.lon)].reset_index(drop=True)

    nulos = set(cfg.get("nulos", []))
    prec = cfg["precision"]
    for k, (_, tipo) in col.items():
        if tipo == "f":
            b[k] = pd.to_datetime(b[k], errors="coerce")
        elif tipo == "n":
            b[k] = pd.to_numeric(b[k], errors="coerce")
        elif tipo == "q":
            b[k] = b[k].map(lambda x: prec.get(str(x).strip()) if isinstance(x, str) else None)
        else:
            t = traductor(cfg, k)
            u = {x: (None if (s := valor(x, "s", nulos)) is None else t(s)) for x in b[k].dropna().unique()}
            b[k] = b[k].map(u)
    for i in range(len(socios)):
        b[f"_socio{i}"] = b[f"_socio{i}"].map(lambda x: valor(x, "s", nulos))
    return b


def cruzar_por_clave(v, b, clave_v, claves_b, metodo, asign, usados, filtro=None):
    """Candidatos por igualdad de clave, asignación codiciosa por distancia creciente (<= D_NOMBRE).
    Un registro ya usado solo se comparte con otro idpozo en el mismo lugar (<= MISMO_POZO m del primero).
    `filtro(par)` puede vetar pares. Devuelve (pozos con candidato sin asignar, pares vetados por el filtro)."""
    libres = v[~v.id.isin(asign.keys())]
    pares = []
    for kb in claves_b:
        m = libres[["id", "lat", "lon", "sigla", "prof", clave_v]].merge(
            b[[kb, "lat", "lon"]].reset_index().rename(columns={"index": "bi"}),
            left_on=clave_v, right_on=kb, suffixes=("", "_b"))
        m = m[m[clave_v] != ""]
        pares.append(m[["id", "bi", "lat", "lon", "lat_b", "lon_b", "sigla", "prof"]])
    m = pd.concat(pares).drop_duplicates(["id", "bi"])
    if m.empty:
        return 0, 0
    m["d"] = metros(m.lat.values, m.lon.values, m.lat_b.values, m.lon_b.values)[0]
    m["n"] = m.groupby("id").bi.transform("size")
    vetados = 0
    for r in m[m.d <= D_NOMBRE].sort_values("d").itertuples():
        if r.id in asign:
            continue
        if filtro and not filtro(r):
            vetados += 1
            continue
        if r.bi in usados and metros(r.lat, r.lon, *usados[r.bi])[0] > MISMO_POZO:
            continue
        asign[r.id] = (int(r.bi), metodo, float(r.d), None, int(r.n))
        usados.setdefault(r.bi, (r.lat, r.lon))
    return int(m.loc[~m.id.isin(asign.keys()), "id"].nunique()), vetados


def ventana(lat_ord, lat, radio_m):
    dlat = radio_m / 111320.0
    return np.searchsorted(lat_ord, lat - dlat), np.searchsorted(lat_ord, lat + dlat, side="right")


def prof_ok(td, prof):
    return bool(td and td > 0 and prof and prof > 0 and abs(td - prof) <= TOL_PROF * prof)


def fecha_ok(spud, q, perf):
    """Spud de la base compatible con el inicio de perforación del Cap. IV (True si falta alguno)."""
    if perf is None or pd.isna(perf) or spud is None or pd.isna(spud):
        return True
    if q in TOL_DIAS:
        return abs((spud - perf).days) <= TOL_DIAS[q]
    return abs(spud.year - perf.year) <= TOL_ANIOS.get(q, 2)


def cruzar_espacial(v, b, asign):
    hechos = pd.DataFrame([(k, x[0]) for k, x in asign.items()], columns=["id", "bi"])
    ref = hechos.merge(v[["id", "lat", "lon"]], on="id")
    ref = ref.join(b[["lat", "lon"]], on="bi", rsuffix="_b")
    _, ref["dx"], ref["dy"] = metros(ref.lat.values, ref.lon.values, ref.lat_b.values, ref.lon_b.values)
    ref = ref.sort_values("lat").reset_index(drop=True)
    rlat, rlon, rdx, rdy = ref.lat.values, ref.lon.values, ref.dx.values, ref.dy.values

    libre = np.ones(len(b), bool)
    libre[list({x[0] for x in asign.values()})] = False
    orden = np.argsort(b.lat.values)
    blat = b.lat.values[orden]
    tds = b.td.fillna(0).values
    spuds, qs = list(b.spud), list(b.spud_q)

    n_corr = n_amb = n_rech = 0
    for r in v[~v.id.isin(asign.keys())].itertuples():
        ox = oy = 0.0
        i0, i1 = ventana(rlat, r.lat, R_CORRIMIENTO)
        if i1 - i0 >= MIN_VECINOS:
            d = metros(r.lat, r.lon, rlat[i0:i1], rlon[i0:i1])[0]
            sel = d <= R_CORRIMIENTO
            if sel.sum() >= MIN_VECINOS:
                mx, my = np.median(rdx[i0:i1][sel]), np.median(rdy[i0:i1][sel])
                disp = np.median(np.hypot(rdx[i0:i1][sel] - mx, rdy[i0:i1][sel] - my))
                if disp <= MAX_DISPERSION:
                    ox, oy = mx, my
        # posición corregida del pozo del visor (en el "sistema" de la base)
        clat = r.lat + oy / 111320.0
        clon = r.lon + ox / (111320.0 * np.cos(np.radians(r.lat)))
        j0, j1 = ventana(blat, clat, D_ESPACIAL)
        idx = orden[j0:j1]
        idx = idx[libre[idx]]
        if not len(idx):
            continue
        dc = metros(clat, clon, b.lat.values[idx], b.lon.values[idx])[0]
        sel = dc <= D_ESPACIAL
        cand, dc = idx[sel], dc[sel]
        if not len(cand):
            continue
        prof = r.prof if r.prof and r.prof > 0 else None
        if prof:
            perf = None if pd.isna(r.perf) else r.perf
            okp = np.array([prof_ok(tds[i], prof) and fecha_ok(spuds[i], qs[i], perf) for i in cand])
            if okp.sum() != 1:
                n_amb += int(okp.sum() > 1)
                n_rech += int(okp.sum() == 0)
                continue
            k, metodo = int(np.flatnonzero(okp)[0]), "distancia_prof"
        elif len(cand) == 1 and dc[0] <= D_ESPACIAL_SIN_PROF:
            k, metodo = 0, "distancia"
        else:
            n_amb += int(len(cand) > 1)
            n_rech += int(len(cand) == 1)
            continue
        bi = int(cand[k])
        draw = float(metros(r.lat, r.lon, b.lat.values[bi], b.lon.values[bi])[0])
        corr = bool(ox or oy)
        n_corr += corr
        asign[r.id] = (bi, metodo, draw, float(dc[k]) if corr else None, len(cand))
        libre[bi] = False
    return int(n_corr), int(n_amb), int(n_rech)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ruta = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("BASE_COMERCIAL_SHP")
    if not ruta or not os.path.exists(ruta):
        raise SystemExit("Uso: preprocess_base_comercial.py <ruta al .shp> [config]  (o BASE_COMERCIAL_SHP / "
                         "BASE_COMERCIAL_CONFIG)")
    cfg = leer_config(sys.argv[2] if len(sys.argv) > 2 else os.environ.get("BASE_COMERCIAL_CONFIG", CONFIG))
    v = pozos_visor()
    b = leer_base(ruta, cfg)
    print(f"Pozos del visor: {len(v):,} · registros de la base: {len(b):,}")

    v["k"] = v.sigla.map(norm)
    v["k2"] = v.sigla.map(lambda s: norm(s, True))
    b["ka"], b["ko"] = b.alt.map(norm), b.nombre.map(norm)
    b["ka2"], b["ko2"] = b.alt.map(lambda s: norm(s, True)), b.nombre.map(lambda s: norm(s, True))
    v["kid"] = v.id.astype(str)
    b["kid"] = (pd.to_numeric(b["_id_alt"], errors="coerce").map(lambda x: "" if pd.isna(x) else str(int(x)))
                if "_id_alt" in b else "")

    # Pozos que empezaron a perforarse después del corte de la base no pueden estar en ella: no se cruzan.
    corte = fecha_mixta(b["_act"]).max() if "_act" in b else pd.NaT
    if pd.isna(corte):
        raise SystemExit("No pude leer la fecha de actualización de la base (col_actualizacion en la config)")
    ve = v[~(v.perf > corte)]

    # Paso "sin sufijo": sigla dirigida/horizontal contra registro vertical sin sufijo = otro pozo de la locación,
    # salvo que la profundidad del Cap. IV coincida con la TD.
    tiene_sufijo = lambda s: isinstance(s, str) and bool(SUFIJO_FINAL.search(s))
    sufijo_b = (b.alt.map(tiene_sufijo) | b.nombre.map(tiene_sufijo)).values
    desv, tdb = b.desv.values, b.td.values

    def trayectoria_ok(par):
        if not SUFIJO_DIRIGIDO.search(str(par.sigla)):
            return True
        if desv[par.bi] != VERTICAL or sufijo_b[par.bi]:
            return True
        return prof_ok(tdb[par.bi], par.prof)

    asign, usados = {}, {}
    lejos, vetos = {}, 0
    lejos["nombre"], _ = cruzar_por_clave(ve, b, "k", ["ka", "ko"], "nombre", asign, usados)
    lejos["nombre_sin_sufijo"], vetos = cruzar_por_clave(ve, b, "k2", ["ka2", "ko2"], "nombre_sin_sufijo", asign,
                                                         usados, trayectoria_ok)
    lejos["id"], _ = cruzar_por_clave(ve, b, "kid", ["kid"], "id", asign, usados)
    n_corr, n_amb, n_rech = cruzar_espacial(ve, b, asign)

    # Tablas categóricas y filas (valores ya traducidos)
    col = cfg["columnas"]
    campos = list(col) + ["socios", "metodo", "dist", "dist_corr", "candidatos"]
    tablas = {k: [] for k, (_, t) in col.items() if t in ("c", "q")}
    tablas["metodo"] = METODOS
    idx_t = {k: {} for k in tablas}
    idx_t["metodo"] = {m: i for i, m in enumerate(METODOS)}

    def cat(k, s):
        if s is None:
            return None
        if s not in idx_t[k]:
            idx_t[k][s] = len(tablas[k])
            tablas[k].append(s)
        return idx_t[k][s]

    nulos = set(cfg.get("nulos", []))
    n_socios = len(cfg.get("socios", []))
    pozos = {}
    for pid, (bi, met, d, dc, n) in sorted(asign.items()):
        r = b.iloc[bi]
        fila = []
        for k, (_, t) in col.items():
            x = valor(r[k], "s" if t in ("c", "q") else t, nulos)
            fila.append(cat(k, x) if t in ("c", "q") else x)
        socios = []
        for i in range(n_socios):
            nom, wi = r[f"_socio{i}"], r[f"_socio{i}_wi"]
            if isinstance(nom, str) and nom:
                socios.append(nom + (f" {wi * 100:.4g} %" if isinstance(wi, float) and 0 < wi <= 1 else ""))
        fila += ["; ".join(socios) or None, idx_t["metodo"][met], round(d), None if dc is None else round(dc),
                 n if n > 1 else None]
        while fila and fila[-1] is None:
            fila.pop()
        pozos[str(pid)] = fila

    # Huellas para la guarda de public/: TD no redonda y distinta de la profundidad del Cap. IV; spud exacto distinto
    # del inicio de perforación del Cap. IV.
    vi = v.set_index("id")
    huellas = []
    for pid, (bi, *_x) in asign.items():
        r = b.iloc[bi]
        td = valor(r["td"], "n", nulos)
        p4 = vi.at[pid, "prof"]
        td = td if td and td % 10 and not (p4 and abs(td - p4) < 1) else None
        sp = valor(r["spud"], "f", nulos) if r["spud_q"] in TOL_DIAS else None
        perf = vi.at[pid, "perf"]
        sp = sp if sp and not (pd.notna(perf) and perf.strftime("%Y-%m-%d") == sp) else None
        if td or sp:
            huellas.append([int(pid), td, sp])
    rng = np.random.default_rng(0)
    if len(huellas) > N_HUELLAS:
        huellas = [huellas[i] for i in sorted(rng.choice(len(huellas), N_HUELLAS, replace=False))]

    # Estadísticas (sin nombres de pozos)
    v["met"] = v.id.map(lambda i: asign[i][1] if i in asign else "sin_match")
    tab = pd.crosstab(v.cu, v.met, margins=True, margins_name="TOTAL")
    tab = tab.reindex(columns=[c for c in METODOS + ["sin_match", "TOTAL"] if c in tab.columns], fill_value=0)
    tab["% cruzado"] = (100 * (1 - tab.get("sin_match", 0) / tab["TOTAL"])).round(1)
    print("\nCobertura del cruce por cuenca (pozos del visor):")
    print(tab.to_string())
    ds = pd.Series({k: x[2] for k, x in asign.items()})
    ms = pd.Series({k: x[1] for k, x in asign.items()})
    for m in METODOS:
        d = ds[ms == m]
        if len(d):
            print(f"  {m:18s} {len(d):6,} pozos · distancia mediana {d.median():5.0f} m · p90 {d.quantile(.9):5.0f} m"
                  f" · máx {d.max():5.0f} m")
    print(f"  pozos con candidato pero sin asignar en cada paso (candidato a > {D_NOMBRE:.0f} m o registro ya usado"
          f" por otro pozo; siguen al paso siguiente): {lejos}")
    print(f"  sin sufijo: {vetos:,} pares vetados por trayectoria (sigla dirigida/horizontal vs registro vertical)")
    print(f"  proximidad: {n_corr:,} con corrección de corrimiento local; sin match: {n_amb:,} ambiguos (2+ candidatos"
          f" compatibles a <= {D_ESPACIAL:.0f} m) y {n_rech:,} con candidato rechazado (TD a más de {TOL_PROF:.0%} de la"
          f" profundidad del Cap. IV, spud incompatible o, sin profundidad, a más de {D_ESPACIAL_SIN_PROF:.0f} m)")
    multi = sum(1 for x in asign.values() if x[4] > 1 and not x[1].startswith("distancia"))
    print(f"  pozos con varios candidatos por nombre (se tomó el más cercano): {multi:,}")
    rep = pd.Series([x[0] for x in asign.values()]).value_counts()
    print(f"  registros de la base compartidos por varios idpozo en el mismo lugar (<= {MISMO_POZO:.0f} m, mismo pozo"
          f" físico): {(rep > 1).sum():,}")
    sin = v[v.met == "sin_match"]
    nuevos = int((sin.perf > corte).sum())
    print(f"  sin match: {len(sin):,}, de los cuales {nuevos:,} empezaron a perforarse después del corte de la "
          f"base ({corte:%Y-%m-%d}) según el Cap. IV (no se cruzan); cobertura del resto: "
          f"{100 * len(asign) / max(1, len(ve)):.1f} %")
    print(f"  huellas para la guarda de public/: {len(huellas):,}")

    out = {
        "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "corte": corte.strftime("%Y-%m-%d"),
        "aviso": "Base comercial licenciada. Uso local; no publicar.",
        "umbrales_m": {"nombre": D_NOMBRE, "distancia": D_ESPACIAL},
        "campos": campos,
        "tablas": tablas,
        "pozos": pozos,
        "huellas": huellas,
        "stats": {"visor": len(v), "base": len(b), "por_metodo": {k: int(x) for k, x in ms.value_counts().items()},
                  "sin_match": len(sin), "sin_match_post_corte": nuevos, "ambiguos": n_amb, "rechazados": n_rech,
                  "vetados_trayectoria": vetos},
    }
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n-> {SALIDA}: {len(pozos):,} pozos, {os.path.getsize(SALIDA) / 1048576:.2f} MB")


if __name__ == "__main__":
    main()
