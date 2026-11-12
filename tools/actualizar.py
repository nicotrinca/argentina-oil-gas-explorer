"""
Actualización mensual de los datos del visor: baja lo nuevo del portal de la Secretaría de Energía (CKAN),
corre los preprocess, controla que nada se haya roto y (con --publicar) despliega en Firebase Hosting.
Corre igual en Windows (local) y en Linux (GitHub Actions, .github/workflows/actualizar.yml).

Uso (desde la raíz del proyecto):
  .venv/Scripts/python tools/actualizar.py               baja, procesa y controla (NO publica)
  .venv/Scripts/python tools/actualizar.py --publicar    ídem y, si todo da bien, firebase deploy
  .venv/Scripts/python tools/actualizar.py --solo-bajar  solo descarga (para probar por partes)
  .venv/Scripts/python tools/actualizar.py --sin-bajar   procesa y controla lo que ya está en data/
  --aceptar-cambios      los cambios > ±3 % en meses ya publicados pasan como aviso (primera corrida o
                         re-publicación conocida de la fuente). Revisar data/_informe.md antes de usarlo.
  --referencia URL|DIR   contra qué comparar (default: el sitio publicado). Si no responde, se usa la copia
                         local de la última corrida que pasó todos los controles (data/_previo/, con _ok.json;
                         se escribe al FINAL de una corrida exitosa). Si tampoco hay copia: falla (código 1).
  --sin-referencia       permite seguir sin ninguna referencia (los controles 1 y 3 no corren).

Códigos de salida: 0 ok · 1 falló un control o no hay referencia (no se publica) · 2 catálogo/descarga · 3 un preprocess falló
· 4 falló el deploy.

Qué baja (ver README, "How to run") — la elección es por NOMBRE del recurso, no por id fijo:
  produccion-<AÑO>.csv   dataset produccion-de-petroleo-y-gas-por-pozo, recursos "Producción de Pozos de Gas y
                         Petróleo – <AÑO>" o "- <AÑO>" (sin "DDJJ abiertas y cerradas", sin "No Convencional"),
                         todos los años >= ANIO_INICIAL: un año nuevo entra solo.
                         2024 y 2025 tienen DOS recursos con ese nombre (uno "–" y otro "-", el segundo creado
                         2025-04-29 con descripción "con identificador"). Verificado 2026-11-12: mismos totales
                         por mes (pozos con producción, petróleo, gas) entre sí y contra los CSV locales de
                         entonces. Las filas NO son idénticas: los dos de 2025 traen 991.936 filas y el CSV
                         local tenía 991.844 (92 filas más, todas en cero: 50 de PETROLERA DEL COMAHUE y 42 de
                         ENERGICON, nov-dic);
                         el "con identificador" de 2025 trae una columna extra `id` que el pipeline no usa.
                         Regla: entre los candidatos de un año se toma el de last_modified más reciente.
                         Si falta un año completo (ANIO_INICIAL .. año anterior) → error 2 con la lista de
                         nombres del catálogo. El año en curso puede faltar (enero) → aviso.
  produccion-no-convencional.csv, capitulo-iv-pozos.csv (mismo dataset), geo/fractura.csv (Adjunto IV,
  "Actualización diaria") y los shapefiles (zip → <carpeta>/<nombre>.shp/.dbf/.shx/.prj/.cpg).
  Se baja solo si cambió el recurso respecto de data/_fuentes.json (id + last_modified + tamaño del catálogo);
  después de bajar se compara el sha256: si es igual, "sin cambios".

Controles antes de publicar (umbrales abajo, en constantes):
  1. Meses ya publicados: pozos con producción, petróleo y gas de cada mes no cambian más de ±TOL_MES_PUBLICADO.
     El último mes publicado puede crecer hasta TOL_ULTIMO_PUBLICADO (se publica con ≥ 90 % de los pozos, ver
     comun.py, y las empresas que faltaban cargan después).
  2. Ningún mes nuevo (sin referencia: el último mes) cae más de MAX_CAIDA_ULTIMO_MES en pozos, petróleo ni
     petróleo equivalente contra: el mes anterior, la mediana de los 3 previos y (el primer mes nuevo) el valor
     publicado del último mes publicado. El gas solo avisa: estacionalidad fuerte (ago→sep 2025: −15,1 %).
     No depende de la referencia.
  3. Pozos del año (filas de pozos_<AÑO>.js) no bajan más de MAX_CAIDA_POZOS_ANIO contra lo publicado.
  4. node tools/check.mjs en verde (levanta python -m http.server 8765 si no hay servidor).
Informe: data/_informe.md (meses nuevos, totales por mes, diferencias vs lo publicado, archivos bajados).

GitHub Actions: el workflow corre este script sin --publicar y despliega en un paso aparte con una cuenta de
servicio de Firebase guardada en el secret FIREBASE_SERVICE_ACCOUNT (JSON completo de la clave). Para crearla:
Google Cloud Console del proyecto pozos-argentina → IAM → Cuentas de servicio → crear, con los roles
"Firebase Hosting Admin" y "API Keys Viewer" (o "Firebase Admin"), → Claves → Agregar clave JSON; en GitHub:
Settings → Secrets and variables → Actions → New repository secret FIREBASE_SERVICE_ACCOUNT = contenido del JSON.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ── Umbrales de los controles ────────────────────────────────────────────────
TOL_MES_PUBLICADO = 0.03              # ±3 % por mes ya publicado (pozos, petróleo, gas)
TOL_ULTIMO_PUBLICADO = (-0.03, 0.12)  # último mes publicado: puede crecer hasta +12 % (mes casi completo)
MAX_CAIDA_ULTIMO_MES = 0.15           # el último mes nuevo no cae > 15 % vs el anterior
MAX_CAIDA_POZOS_ANIO = 0.05           # pozos del año (pozos_<AÑO>.js) no bajan > 5 %

# ── Fuentes ──────────────────────────────────────────────────────────────────
CKAN = "http://datos.energia.gob.ar/api/3/action/package_show?id="   # solo http (https redirige a http)
URL_PUBLICADO = "https://pozos-argentina.web.app/data/"
PROYECTO_FIREBASE = "pozos-argentina"
ANIO_INICIAL = 2022
TIMEOUT = 300           # s sin recibir bytes antes de cortar
REINTENTOS = 4
ESPERAS = [15, 60, 180]  # s entre reintentos
UA = "pozos-actualizar/1.0 (+python-urllib)"
GAS_A_PET = 1000 / 1069

PKG_PROD = "produccion-de-petroleo-y-gas-por-pozo"
RE_PROD_ANIO = r"^produccion de pozos de gas y petroleo\s*-?\s*(\d{4})$"
# clave, dataset, formato, regex sobre el nombre normalizado (sin tildes, minúsculas, guiones "-"), destino, columnas
FUENTES = [
    ("no-convencional", PKG_PROD, "CSV", r"^produccion de pozos de gas y petroleo no convencional$",
     "produccion-no-convencional.csv",
     ["idpozo", "anio", "mes", "prod_pet", "prod_gas", "empresa", "sigla", "formacion", "sub_tipo_recurso",
      "coordenadax", "coordenaday", "areapermisoconcesion"]),
    ("padron", PKG_PROD, "CSV", r"^capitulo iv - pozos$", "capitulo-iv-pozos.csv",
     ["idpozo", "sigla", "geojson", "formacion", "profundidad", "tipopozo"]),
    ("fractura", "datos-de-fractura-de-pozos-adjunto-iv", "CSV", r"adjunto iv", "geo/fractura.csv",
     ["idpozo", "sigla", "cantidad_fracturas", "arena_bombeada_nacional_tn", "arena_bombeada_importada_tn",
      "agua_inyectada_m3", "longitud_rama_horizontal_m", "fecha_fin_fractura", "formacion_productiva",
      "tipo_reservorio", "empresa_informante", "cuenca"]),
    ("concesiones", "produccion-hidrocarburos-concesiones-de-explotacion", "SHP", r"concesiones de explotacion",
     "concesiones_shp/concesiones", None),
    ("cuencas", "exploracion-hidrocarburos-cuencas-sedimentarias", "SHP", r"cuencas sedimentarias",
     "geo/cuencas/cuencas", None),
    ("yacimientos", "produccion-hidrocarburos-yacimientos", "SHP", r"yacimientos", "geo/yacimientos/yacimientos", None),
    ("permisos", "exploracion-hidrocarburos-permisos-de-exploracion", "SHP", r"permisos de exploracion",
     "geo/permisos/permisos", None),
    ("gasoductos", "transporte-hidrocarburos-ductos-troncales-gasoductos", "SHP", r"^gasoductos de transporte",
     "geo/gasoductos/gasoductos", None),
    ("refinerias", "refinacion-hidrocarburos-refinerias", "SHP", r"refinerias", "geo/refinerias/refinerias", None),
    ("ductos319", "instalaciones-hidrocarburos-ductos-res--319-93", "SHP", r"ductos res", "geo/ductos319/ductos319",
     None),
]
COLS_PROD = ["idpozo", "anio", "mes", "prod_pet", "prod_gas", "prod_agua", "empresa", "sigla", "cuenca", "provincia",
             "tipo_de_recurso", "tipoestado", "formacion", "areapermisoconcesion", "sub_tipo_recurso"]

# Orden de HANDOFF.md ("Datos (pipeline)")
PASOS = ["preprocess_peryear.py", "preprocess.py", "preprocess_ranking.py", "preprocess_temporal.py",
         "preprocess_areas.py", "preprocess_geo.py", "preprocess_fractura.py", "preprocess_curvas.py",
         "preprocess_zonas.py"]


class ErrorFuente(Exception):
    pass


def log(*a):
    print(*a, flush=True)


def normaliza(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[‐-―−]", "-", s)        # –, —, ‐ ... -> "-"
    return re.sub(r"\s+", " ", s).strip().lower()


def abrir(url, timeout=TIMEOUT):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)


def con_reintentos(fn, que):
    for i in range(REINTENTOS):
        try:
            return fn()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError, ErrorFuente) as e:
            if i == REINTENTOS - 1:
                raise ErrorFuente(f"{que}: {e}") from e
            espera = ESPERAS[min(i, len(ESPERAS) - 1)]
            log(f"    ! {que}: {e} -> reintento en {espera} s")
            time.sleep(espera)


def paquete(pkg, _cache={}):
    if pkg not in _cache:
        _cache[pkg] = con_reintentos(lambda: json.load(abrir(CKAN + pkg, 120))["result"], f"catálogo {pkg}")
    return _cache[pkg]


def fecha(r):
    return r.get("last_modified") or r.get("created") or ""


def elegir(pkg, formato, patron, que):
    """Recurso del dataset cuyo nombre normalizado matchea `patron` (y formato). Varios -> el más reciente."""
    res = paquete(pkg)["resources"]
    cand = [r for r in res if (r.get("format") or "").upper() == formato and re.search(patron, normaliza(r["name"]))]
    if not cand:
        nombres = "\n    ".join(f"{r.get('format')}: {r['name']}" for r in res)
        raise ErrorFuente(f"{que}: ningún recurso {formato} de '{pkg}' coincide con /{patron}/. "
                          f"¿Cambió el catálogo? Recursos actuales:\n    {nombres}")
    cand.sort(key=fecha)
    return cand[-1], len(cand)


def recursos_produccion():
    """{año: recurso} de producción por año (no DDJJ, no NC), desde ANIO_INICIAL."""
    res = paquete(PKG_PROD)["resources"]
    por_anio = {}
    for r in res:
        if (r.get("format") or "").upper() != "CSV":
            continue
        m = re.match(RE_PROD_ANIO, normaliza(r["name"]))
        if m and int(m.group(1)) >= ANIO_INICIAL:
            por_anio.setdefault(int(m.group(1)), []).append(r)
    hoy = dt.date.today().year
    faltan = [a for a in range(ANIO_INICIAL, hoy) if a not in por_anio]
    if faltan:
        nombres = "\n    ".join(r["name"] for r in res)
        raise ErrorFuente(f"producción: no encontré recurso para {faltan} con /{RE_PROD_ANIO}/ "
                          f"(¿cambió el nombre en el catálogo?). Recursos actuales:\n    {nombres}")
    avisos = []
    if hoy not in por_anio:
        avisos.append(f"El catálogo todavía no tiene producción {hoy} (normal en enero/febrero).")
    elegidos = {}
    for a, cs in sorted(por_anio.items()):
        cs.sort(key=fecha)
        elegidos[a] = cs[-1]
        if len(cs) > 1:
            log(f"  producción {a}: {len(cs)} recursos con ese nombre -> el más reciente "
                f"({cs[-1]['id'][:8]}, {fecha(cs[-1])[:19]})")
    return elegidos, avisos


# ── Descarga ─────────────────────────────────────────────────────────────────
def descargar(url, tmp, tam_catalogo):
    """Baja a `tmp` en bloques de 1 MB. Devuelve (bytes, sha256). El servidor no manda Content-Length:
    se compara contra el tamaño del catálogo (si difiere, se reintenta; al último intento se acepta con aviso
    si el archivo pasa la validación de estructura)."""
    estado = {"intento": 0}

    def una():
        estado["intento"] += 1
        h, n = hashlib.sha256(), 0
        with abrir(url) as r, open(tmp, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                h.update(b)
                n += len(b)
        if n == 0:
            raise ErrorFuente("descarga vacía")
        if tam_catalogo and n != tam_catalogo and estado["intento"] < REINTENTOS:
            raise ErrorFuente(f"bajaron {n:,} bytes y el catálogo dice {tam_catalogo:,}")
        return n, h.hexdigest()

    return con_reintentos(una, f"descarga {url.rsplit('/', 1)[-1]}")


def validar_csv(path, columnas, anio=None):
    import pandas as pd
    head = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns.tolist()
    faltan = [c for c in columnas if c not in head]
    if faltan:
        raise ErrorFuente(f"{path.name}: faltan columnas {faltan} (¿cambió el formato?)")
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 2))
        if not f.read().endswith(b"\n"):
            raise ErrorFuente(f"{path.name}: no termina en salto de línea (¿descarga cortada?)")
    if anio is not None:
        a = pd.read_csv(path, usecols=["anio"], encoding="utf-8-sig")["anio"]
        otros = sorted(set(a.dropna().astype(int)) - {anio})
        if otros or a.empty:
            raise ErrorFuente(f"{path.name}: trae años {otros or 'ninguno'} además de {anio}")


def instalar_shp(tmp, destino):
    """Zip del portal -> destino.<ext> (nombres internos con tildes rotas: se renombran por extensión)."""
    with zipfile.ZipFile(tmp) as z:
        if z.testzip() is not None:
            raise ErrorFuente(f"{tmp.name}: zip dañado")
        miembros = [i for i in z.infolist() if not i.is_dir()]
        shps = [i for i in miembros if i.filename.lower().endswith(".shp")]
        if len(shps) != 1:
            raise ErrorFuente(f"{tmp.name}: esperaba 1 .shp y hay {len(shps)}")
        stem = shps[0].filename[:-4]
        propios = [i for i in miembros if i.filename.rsplit(".", 1)[0] == stem]
        exts = {i.filename.rsplit(".", 1)[-1].lower() for i in propios}
        if not {"shp", "shx", "dbf"} <= exts:
            raise ErrorFuente(f"{tmp.name}: faltan partes del shapefile (hay {sorted(exts)})")
        destino.parent.mkdir(parents=True, exist_ok=True)
        for viejo in destino.parent.glob(destino.name + ".*"):
            viejo.unlink()
        for i in propios:
            ext = i.filename.rsplit(".", 1)[-1].lower()
            with z.open(i) as src, open(destino.parent / f"{destino.name}.{ext}", "wb") as dst:
                shutil.copyfileobj(src, dst)


def bajar_todo(informe):
    """Resuelve recursos en CKAN y baja lo que cambió. Devuelve lista de filas para el informe."""
    reg_path = DATA / "_fuentes.json"
    reg = json.load(open(reg_path, encoding="utf-8")) if reg_path.exists() else {}
    tmpdir = DATA / "_descargas"
    tmpdir.mkdir(parents=True, exist_ok=True)

    trabajos = []   # (clave, recurso, tipo, destino, columnas, anio)
    prod, avisos = recursos_produccion()
    informe["avisos"] += avisos
    for a, r in prod.items():
        trabajos.append((f"produccion-{a}", r, "CSV", DATA / f"produccion-{a}.csv", COLS_PROD, a))
    for clave, pkg, fmt, patron, dest, cols in FUENTES:
        r, n = elegir(pkg, fmt, patron, clave)
        if n > 1:
            informe["avisos"].append(f"{clave}: {n} recursos coinciden con /{patron}/; se usó el más reciente "
                                     f"('{r['name']}').")
        trabajos.append((clave, r, fmt, DATA / dest, cols, None))

    filas = []
    for clave, r, fmt, destino, cols, anio in trabajos:
        lm, tam = fecha(r), r.get("size")
        prev = reg.get(clave, {})
        existe = destino.exists() if fmt == "CSV" else (destino.parent / f"{destino.name}.shp").exists()
        fila = {"clave": clave, "nombre": r["name"], "id": r["id"], "last_modified": lm, "tam_catalogo": tam}
        if existe and prev.get("id") == r["id"] and prev.get("last_modified") == lm and prev.get("tam_catalogo") == tam:
            fila.update(estado="sin cambios en el catálogo", bytes=prev.get("bytes"), sha256=prev.get("sha256"))
            filas.append(fila)
            log(f"  = {clave}: sin cambios ({lm[:19]})")
            continue
        log(f"  ↓ {clave}: {r['name']} ({lm[:19]}, {tam or '?'} bytes)")
        t0 = time.time()
        tmp = tmpdir / (clave + (".csv" if fmt == "CSV" else ".zip"))
        n, sha = descargar(r["url"], tmp, tam)
        fila.update(bytes=n, sha256=sha, segundos=round(time.time() - t0))
        if tam and n != tam:
            informe["avisos"].append(f"{clave}: bajaron {n:,} bytes y el catálogo dice {tam:,} (aceptado: "
                                     "pasó la validación de estructura).")
        if existe and prev.get("sha256") == sha:
            fila["estado"] = "re-descargado, mismo contenido"
            tmp.unlink()
        else:
            if fmt == "CSV":
                validar_csv(tmp, cols, anio)
                destino.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp, destino)
            else:
                instalar_shp(tmp, destino)
                tmp.unlink()
            fila["estado"] = "nuevo" if not prev else "actualizado"
        log(f"    {fila['estado']}: {n:,} bytes en {fila['segundos']} s")
        reg[clave] = {k: fila[k] for k in ("id", "nombre", "last_modified", "tam_catalogo", "bytes", "sha256")}
        reg[clave]["descargado"] = dt.datetime.now().isoformat(timespec="seconds")
        tmp_reg = reg_path.with_suffix(".json.tmp")
        with open(tmp_reg, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
        os.replace(tmp_reg, reg_path)
        filas.append(fila)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return filas


def fuentes_registradas():
    """Con --sin-bajar: lo que dice data/_fuentes.json (última descarga), para el informe."""
    try:
        reg = json.load(open(DATA / "_fuentes.json", encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [{"clave": k, "nombre": v.get("nombre", ""), "id": v.get("id", ""), "last_modified": v.get("last_modified", ""),
             "bytes": v.get("bytes"), "sha256": v.get("sha256"),
             "estado": f"sin bajar (descargado {v.get('descargado', '?')[:16]})"} for k, v in reg.items()]


# ── Referencia (lo publicado) ────────────────────────────────────────────────
def leer_ref(base, nombre):
    if re.match(r"https?://", base):
        return con_reintentos(lambda: abrir(base.rstrip("/") + "/" + nombre + f"?t={int(time.time())}", 120).read()
                              .decode("utf-8"), f"referencia {nombre}")
    return (Path(base) / nombre).read_text(encoding="utf-8")


def contar_pozos_js(txt):
    return len(json.loads(txt[txt.index("=") + 1: txt.rindex(";")]))


def cargar_referencia(base, informe):
    """serie_nacional + nº de pozos por año de lo publicado. Si no responde, la copia local de la última
    corrida que pasó los controles (data/_previo, solo si tiene la marca _ok.json). Sin ninguna -> None."""
    origenes = [base] if base else []
    if (DATA / "_previo" / "_ok.json").exists():
        origenes.append(str(DATA / "_previo"))
    for origen in origenes:
        try:
            serie = json.loads(leer_ref(origen, "serie_nacional.json"))
            anios = sorted({int(p[:4]) for p in serie["periodos"]})
            pozos_anio = {}
            for a in anios:
                try:
                    pozos_anio[a] = contar_pozos_js(leer_ref(origen, f"pozos_{a}.js"))
                except (ErrorFuente, OSError, ValueError) as e:
                    informe["avisos"].append(f"Referencia: no pude leer pozos_{a}.js en {origen} ({e}).")
            if origen != base:
                ok = json.load(open(DATA / "_previo" / "_ok.json", encoding="utf-8"))
                informe["avisos"].append(f"Referencia: el sitio publicado no respondió; se usó la copia local de la "
                                         f"última corrida que pasó los controles ({ok.get('fecha', '?')}).")
            return {"origen": origen, "serie": serie, "pozos_anio": pozos_anio}
        except (ErrorFuente, OSError, ValueError, KeyError) as e:
            log(f"  ! referencia {origen}: {e}")
    return None


def guardar_previo(publicado):
    """Copia de referencia local para cuando el sitio no responda. Se llama SOLO al final de una corrida que
    pasó todos los controles (y, si --publicar, después del deploy); la marca _ok.json la habilita."""
    prev = DATA / "_previo"
    shutil.rmtree(prev, ignore_errors=True)
    prev.mkdir()
    for p in [DATA / "serie_nacional.json", *DATA.glob("pozos_*.js")]:
        if p.exists():
            shutil.copy2(p, prev / p.name)
    json.dump({"fecha": dt.datetime.now().isoformat(timespec="seconds"), "publicado": publicado},
              open(prev / "_ok.json", "w", encoding="utf-8"))


# ── Pipeline ─────────────────────────────────────────────────────────────────
def correr_pipeline(informe):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for paso in PASOS:
        log(f"\n── {paso} " + "─" * (60 - len(paso)))
        t0 = time.time()
        r = subprocess.run([sys.executable, "-u", paso], cwd=ROOT, env=env)
        seg = round(time.time() - t0)
        informe["pasos"].append((paso, seg, r.returncode))
        if r.returncode != 0:
            raise RuntimeError(f"{paso} salió con código {r.returncode}")
        log(f"   ({seg} s)")


# ── Controles ────────────────────────────────────────────────────────────────
def var(n, o):
    if o == 0:
        return 0.0 if n == 0 else math.inf
    return n / o - 1


def pct(x):
    return "∞" if math.isinf(x) else f"{x * 100:+.1f} %".replace(".", ",")


def num(x):
    return f"{x:,.0f}".replace(",", ".")


def controles(ref, args, informe):
    nueva = json.load(open(DATA / "serie_nacional.json", encoding="utf-8"))
    idx = {p: i for i, p in enumerate(nueva["periodos"])}
    mets = ["pozos", "pet", "gas"]
    fallas, avisos = informe["fallas"], informe["avisos"]
    informe["serie"] = nueva

    # 1. meses ya publicados
    difs = []
    ult_pub = None
    if ref:
        rs = ref["serie"]
        ult_pub = rs["periodos"][-1]
        for i, p in enumerate(rs["periodos"]):
            if p not in idx:
                fallas.append(f"Control 1: {p} estaba publicado y ya no está en la serie nueva.")
                continue
            lo, hi = TOL_ULTIMO_PUBLICADO if p == ult_pub else (-TOL_MES_PUBLICADO, TOL_MES_PUBLICADO)
            fila = {"periodo": p}
            for m in mets:
                if m not in rs:
                    continue
                o, n = rs[m][i], nueva[m][idx[p]]
                d = var(n, o)
                fila[m] = (o, n, d)
                if not lo <= d <= hi:
                    msg = (f"Control 1: {p} {m} {num(o)} → {num(n)} ({pct(d)}, tolerancia "
                           f"{pct(lo)} / {pct(hi)}{' (último publicado)' if p == ult_pub else ''}).")
                    (avisos if args.aceptar_cambios else fallas).append(
                        msg + (" Aceptado con --aceptar-cambios." if args.aceptar_cambios else ""))
            difs.append(fila)
        if "pozos" not in rs:
            avisos.append("Control 1: lo publicado no trae 'pozos' por mes (serie anterior a esta herramienta): "
                          "solo se comparan petróleo y gas.")
        nuevos = [p for p in nueva["periodos"] if p not in set(rs["periodos"])]
    else:
        nuevos = []
    informe["difs"], informe["nuevos"] = difs, nuevos

    # 2. caída de los meses nuevos (sin referencia: el último mes). No depende de que haya referencia.
    #    Cada mes se compara contra el anterior y contra la mediana de los 3 previos; el primer mes nuevo,
    #    además, contra el valor PUBLICADO del último mes publicado. Gas: solo aviso (estacionalidad).
    per = nueva["periodos"]
    eq = [pt + g * GAS_A_PET for pt, g in zip(nueva["pet"], nueva["gas"])]
    series = [("pozos", "pozos", nueva["pozos"], True), ("petróleo", "pet", nueva["pet"], True),
              ("petróleo equivalente", None, eq, True), ("gas", "gas", nueva["gas"], False)]
    if ref and not nuevos:
        avisos.append("Sin meses nuevos respecto de lo publicado.")
    for p in (nuevos if ref else per[-1:]):
        j = idx[p]
        if j == 0:
            continue
        for nombre, clave, v, gate in series:
            comps = [(f"vs {per[j - 1]}", v[j - 1])]
            if j >= 3:
                comps.append((f"vs mediana {per[j - 3]}…{per[j - 1]}", statistics.median(v[j - 3:j])))
            if ref and p == nuevos[0] and clave in ref["serie"]:
                comps.append((f"vs {ult_pub} publicado", ref["serie"][clave][-1]))
            for etiqueta, o in comps:
                d = var(v[j], o)
                if d < -MAX_CAIDA_ULTIMO_MES:
                    msg = f"Control 2: {p} {nombre} cae {pct(d)} {etiqueta} ({num(o)} → {num(v[j])})."
                    if gate:
                        fallas.append(msg)
                    else:
                        avisos.append(msg + " (gas: solo aviso, estacionalidad)")

    # 3. pozos del año
    informe["pozos_anio"] = {}
    for p in sorted(DATA.glob("pozos_*.js")):
        m = re.fullmatch(r"pozos_(\d{4})\.js", p.name)
        if m:
            informe["pozos_anio"][int(m.group(1))] = contar_pozos_js(p.read_text(encoding="utf-8"))
    if ref:
        for a, o in sorted(ref["pozos_anio"].items()):
            n = informe["pozos_anio"].get(a)
            if n is None:
                fallas.append(f"Control 3: falta data/pozos_{a}.js (estaba publicado con {num(o)} pozos).")
            elif var(n, o) < -MAX_CAIDA_POZOS_ANIO:
                fallas.append(f"Control 3: pozos {a} {num(o)} → {num(n)} ({pct(var(n, o))}).")

    # años con datos que el visor no muestra (falta la <option> en #f-year de index.html)
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    sel = re.search(r'<select id="f-year">([\s\S]*?)</select>', html)
    en_html = {int(a) for a in re.findall(r'value="(\d{4})"', sel.group(1))} if sel else set()
    sin_opcion = sorted(set(informe["pozos_anio"]) - en_html)
    if sin_opcion:
        avisos.append(f"Hay pozos_{sin_opcion}.js pero index.html no tiene esos años en #f-year: el visor no los "
                      "muestra ni se publican hasta agregar la <option>.")


def servidor_arriba():
    try:
        abrir("http://localhost:8765/", 5).read(100)
        return True
    except (urllib.error.URLError, OSError):
        return False


def correr_check(informe):
    proc = None
    if not servidor_arriba():
        log("  levantando python -m http.server 8765 ...")
        proc = subprocess.Popen([sys.executable, "-m", "http.server", "8765"], cwd=ROOT,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            time.sleep(0.5)
            if servidor_arriba():
                break
    try:
        node = shutil.which("node") or "node"
        r = subprocess.run([node, "tools/check.mjs"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=1800)
        salida = (r.stdout or "") + (r.stderr or "")
        log(salida)
        ok = salida.count("✔")
        mal = [l for l in salida.splitlines() if l.startswith("✘")]
        informe["check"] = {"codigo": r.returncode, "ok": ok, "mal": mal}
        if r.returncode != 0:
            informe["fallas"].append(f"Control 4: tools/check.mjs salió con código {r.returncode} "
                                     f"({ok} ✔, {len(mal)} ✘).")
    except subprocess.TimeoutExpired:
        informe["fallas"].append("Control 4: tools/check.mjs no terminó en 30 min.")
    except FileNotFoundError as e:
        informe["fallas"].append(f"Control 4: no pude correr tools/check.mjs: no encontré Node.js ({e}). "
                                 "Instalá Node 22+ y que `node` esté en el PATH.")
    finally:
        if proc:
            proc.terminate()


# ── Informe ──────────────────────────────────────────────────────────────────
def escribir_informe(informe, ref):
    L = [f"# Actualización de datos — {informe['inicio']}", ""]
    estado = "✘ FALLÓ" if informe["fallas"] else "✔ OK"
    L.append(f"**Resultado: {estado}** · modo: {informe['modo']}"
             + (f" · referencia: `{ref['origen']}`" if ref else ""))
    L.append("")
    if informe["fallas"]:
        L += ["## Fallas (no se publica)", ""] + [f"- {f}" for f in informe["fallas"]] + [""]
    if informe["avisos"]:
        L += ["## Avisos", ""] + [f"- {a}" for a in informe["avisos"]] + [""]
    s = informe.get("serie")
    if s:
        meses = {}
        try:
            meses = json.load(open(DATA / "_meses.json", encoding="utf-8"))["meses"]
        except (OSError, ValueError, KeyError):
            pass
        desc = [f"{p} ({num(v['pozos'])} pozos)" for p, v in sorted(meses.items()) if p > s["periodos"][-1]]
        L += [f"## Serie publicable: {s['periodos'][0]} … {s['periodos'][-1]}", "",
              f"Último mes completo: **{s['periodos'][-1]}** (regla: se descartan desde el final los meses con < 90 % "
              f"de los pozos con producción del máximo de los 3 meses previos, ver `comun.py`)."
              + (f" Descartados por incompletos: {', '.join(desc)}." if desc else ""), ""]
        nuevos = informe.get("nuevos", [])
        L += [f"### Meses nuevos ({len(nuevos)})", ""]
        if nuevos:
            L += ["| Mes | Pozos con producción | Petróleo (m³) | Gas (Mm³) |", "|---|---:|---:|---:|"]
            for p in nuevos:
                i = s["periodos"].index(p)
                L.append(f"| {p} | {num(s['pozos'][i])} | {num(s['pet'][i])} | {num(s['gas'][i])} |")
        else:
            L.append("Ninguno.")
        L.append("")
        difs = informe.get("difs", [])
        if difs:
            cambian = [d for d in difs if any(abs(d[m][2]) >= 0.001 for m in ("pozos", "pet", "gas") if m in d)]
            L += [f"### Diferencias vs lo publicado ({len(cambian)} de {len(difs)} meses cambian ≥ 0,1 %)", ""]
            if cambian:
                L += ["| Mes | Pozos | Petróleo (m³) | Gas (Mm³) |", "|---|---|---|---|"]
                cel = lambda d, m: (f"{num(d[m][0])} → {num(d[m][1])} ({pct(d[m][2])})" if m in d else "—")
                for d in cambian:
                    L.append(f"| {d['periodo']} | {cel(d, 'pozos')} | {cel(d, 'pet')} | {cel(d, 'gas')} |")
            L.append("")
        L += ["### Totales por año", "", "| Año | Pozos (pozos_<año>.js) | Publicado | Petróleo (m³) | Gas (Mm³) |",
              "|---|---:|---:|---:|---:|"]
        for a, n in sorted(informe.get("pozos_anio", {}).items()):
            idx = [i for i, p in enumerate(s["periodos"]) if p.startswith(str(a))]
            o = ref["pozos_anio"].get(a) if ref else None
            L.append(f"| {a} | {num(n)} | {num(o) if o is not None else '—'} | "
                     f"{num(sum(s['pet'][i] for i in idx))} | {num(sum(s['gas'][i] for i in idx))} |")
        L.append("")
    if informe.get("fuentes"):
        L += ["## Archivos del portal", "", "| Archivo | Recurso | Modificado | Bytes | Estado | sha256 |",
              "|---|---|---|---:|---|---|"]
        for f in informe["fuentes"]:
            L.append(f"| {f['clave']} | {f['nombre']} (`{f['id'][:8]}`) | {f['last_modified'][:16]} | "
                     f"{num(f['bytes']) if f.get('bytes') else '—'} | {f['estado']} | "
                     f"`{(f.get('sha256') or '')[:12]}` |")
        L.append("")
    if informe["pasos"]:
        L += ["## Preprocess", ""] + [f"- {p}: {s_} s{'' if c == 0 else f' · código {c}'}"
                                      for p, s_, c in informe["pasos"]] + [""]
    c = informe.get("check")
    if c:
        L += ["## tools/check.mjs", "", f"{c['ok']} ✔, {len(c['mal'])} ✘ (código {c['codigo']})", ""]
        L += [f"- {m}" for m in c["mal"]] + ([""] if c["mal"] else [])
    (DATA / "_informe.md").write_text("\n".join(L), encoding="utf-8")
    log(f"\nInforme: {DATA / '_informe.md'}")


def publicar():
    fb = shutil.which("firebase")
    cmd = ([fb] if fb else [shutil.which("npx") or "npx", "--yes", "firebase-tools"]) + \
        ["deploy", "--only", "hosting", "--non-interactive", "--project", PROYECTO_FIREBASE]
    log("\n" + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1], formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--publicar", action="store_true", help="si todos los controles pasan, firebase deploy")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--solo-bajar", action="store_true", help="solo descarga (sin preprocess ni controles)")
    g.add_argument("--sin-bajar", action="store_true", help="no descarga: procesa y controla lo que hay en data/")
    ap.add_argument("--aceptar-cambios", action="store_true",
                    help="cambios > ±3 %% en meses ya publicados = aviso en vez de falla")
    ap.add_argument("--sin-referencia", action="store_true",
                    help="permitir correr sin referencia (sitio caído y sin copia previa): controles 1 y 3 no corren")
    ap.add_argument("--referencia", default=URL_PUBLICADO,
                    help="URL o carpeta con serie_nacional.json y pozos_<año>.js publicados (default: el sitio)")
    args = ap.parse_args()
    if args.publicar and args.solo_bajar:
        ap.error("--publicar no tiene sentido con --solo-bajar")
    os.chdir(ROOT)

    modo = "solo bajar" if args.solo_bajar else "sin bajar" if args.sin_bajar else "completo"
    informe = {"inicio": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "modo": modo + (" + publicar" if args.publicar
               else "") + (" + aceptar cambios" if args.aceptar_cambios else ""),
               "fallas": [], "avisos": [], "pasos": [], "fuentes": []}
    ref = None
    codigo = 0
    try:
        if not args.sin_bajar:
            log("== Descarga (CKAN datos.energia.gob.ar)")
            informe["fuentes"] = bajar_todo(informe)
        else:
            informe["fuentes"] = fuentes_registradas()
        if args.solo_bajar:
            return 0
        log("\n== Referencia")
        ref = cargar_referencia(args.referencia, informe)
        if ref:
            log(f"  {ref['origen']}: hasta {ref['serie']['periodos'][-1]}, pozos por año {ref['pozos_anio']}")
        elif args.sin_referencia:
            informe["avisos"].append("Sin referencia (--sin-referencia): los controles 1 (meses publicados) y 3 "
                                     "(pozos por año) no corrieron; el 2 (caída del último mes) y el 4 (check) sí.")
        else:
            informe["fallas"].append("Sin referencia: no respondió el sitio publicado y no hay copia local de una "
                                     "corrida exitosa (data/_previo/_ok.json). No se publica sin comparar; para "
                                     "forzarlo, --sin-referencia.")
        log("\n== Preprocess")
        correr_pipeline(informe)
        log("\n== Controles")
        controles(ref, args, informe)
        correr_check(informe)
        codigo = 1 if informe["fallas"] else 0
    except ErrorFuente as e:
        informe["fallas"].append(f"Catálogo/descarga: {e}")
        codigo = 2
    except RuntimeError as e:
        informe["fallas"].append(f"Preprocess: {e}")
        codigo = 3
    finally:
        escribir_informe(informe, ref)
        for f in informe["fallas"]:
            log("✘ " + f)
        for a in informe["avisos"]:
            log("! " + a)

    if codigo == 0 and args.publicar:
        if publicar() != 0:
            log("✘ firebase deploy falló")
            return 4
        log("✔ publicado")
    elif args.publicar:
        log("No se publica: hay fallas (ver data/_informe.md).")
    if codigo == 0:
        guardar_previo(publicado=args.publicar)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
