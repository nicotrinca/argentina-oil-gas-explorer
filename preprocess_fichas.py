"""
Fichas técnicas de yacimiento (planilla local) -> data/privado/fichas.json   (MODO PRIVADO, SOLO LOCAL)

Las fichas son CONFIDENCIALES: el JSON queda en data/privado/ (ignorado por git y fuera de la whitelist de
tools/build_public.mjs, que además falla si algo de "privado" aparece en public/). Nunca se publica.
El visor lo pide con fetch silencioso solo desde localhost: si no está, no muestra nada.
En git queda solo este parser genérico: la descripción de la grilla de la planilla (celdas, títulos, grupos,
columnas) vive en data/privado/plantilla_fichas.json, también local e ignorado.

Uso (desde la raíz del proyecto):
  .venv/Scripts/python preprocess_fichas.py "<ruta al xlsx>" [ruta a plantilla_fichas.json]
  o con las variables de entorno FICHAS_XLSX y FICHAS_PLANTILLA. Ninguna ruta va en el código.
  Plantilla por defecto: data/privado/plantilla_fichas.json. Necesita openpyxl (pip install openpyxl en el .venv).

Entrada
  Libro con una hoja por ficha, todas con la MISMA grilla de formulario que una hoja plantilla vacía.
  Se toma como valor toda celda no vacía que difiere de la plantilla. Se saltean las hojas listadas, las que
  no tienen nombre propio (celda de nombre vacía o con el texto de relleno) y las que no tienen valores.
  Etiquetas y unidades salen de la plantilla TAL CUAL (sin corregir); los números solo se formatean (es-AR).

Formato de plantilla_fichas.json (claves; celdas en notación A1, filas como [desde, hasta] inclusive)
  hoja_plantilla, hojas_saltear[], celda_nombre, relleno_nombre, celda_fecha_act
  prefijos_nombre[]      prefijos a quitar del nombre para el título y el matcheo
  etiquetas_anio         regex: etiquetas cuyos enteros son años (sin separador de miles)
  unidades_en_etiqueta[] fragmentos que marcan "(unidad)" dentro de una etiqueta (se separa a "u")
  anios_sueltos          {celdas[], col, desde_fila}: enteros que son años, para "ultimo_dato"
  orden_secciones[]      orden final de las secciones por id
  cabecera[]             {e, celda}
  bloques[]              uno de:
    lista   {col_etiqueta, cols_valor[], col_unidad, filas, secciones:{fila:[id, titulo, abierta?]},
             unidad_por_columna:{unidad:{col:sufijo}}, sin_etiqueta:{unidad:sufijo}, renombrar_unidad:{u:u2}}
            Una sección nueva en cada fila título; fila = etiqueta + valores (unidos con " · ") + unidad.
            Fila sin etiqueta cuya unidad está en sin_etiqueta -> etiqueta anterior + sufijo.
    pares   {id, titulo, abierta?, intercalar, partes:[{col_etiqueta, valores:[{col, sufijo}], filas, unidad?,
             unidad_de_etiqueta?, fmt_con_etiqueta?, grupos:[{fila, texto | prefijo+de_etiqueta, saltear}]}],
             celdas_sueltas:[{celda, g, e}]}
            Una sección; cada valor es una fila {g, e, v, u?}. intercalar: recorre fila por fila todas las partes
            (si no, parte por parte). Un grupo cambia el subtítulo "g" desde su fila (saltear: la fila es solo título).
    tabla   {id, titulo, filas, cols:[[col, titulo]], col_fecha, requiere_desde_col, relleno_desde_plantilla[],
             quitar_cols_vacias}
            Una fila por fila de la hoja con algún valor desde requiere_desde_col.

Matcheo con el visor
  Nombre de la ficha (celda de nombre y nombre de la hoja) sin tildes, en mayúsculas, sin prefijos ni sufijo
  romano (I, II) -> se compara con `areayacimiento` de data/produccion-<AÑO>.csv (yacimiento declarado).
  Exacto primero; si no, un único nombre que lo contenga. Las fichas sin match se exportan igual (sin pozos)
  y se reportan. Los pozos van por idpozo (nunca sigla): todo idpozo que declaró ese yacimiento en algún año.
  `poligono`: nombre del polígono de data/yacimientos.geojson con el mismo nombre normalizado (capa Yacimientos).

Salida: data/privado/fichas.json
  {generado, fuente, aviso,
   fichas: [{id, hoja, titulo, nombre_ficha, yacimiento, poligono, fecha_act, fecha_act_iso, ultimo_dato,
             cabecera: [{e, v}], secciones: [{id, titulo, abierta?, filas: [{g?, e, v, u?}]}],
             tablas: [{id, titulo, cols: [...], filas: [[...]]}], pozos: [idpozo, ...]}],
   por_pozo: {idpozo: [id de ficha, ...]},  por_yacimiento: {NOMBRE NORMALIZADO: [id, ...]}}
"""
import datetime as dt
import json
import os
import re
import sys
import unicodedata

import pandas as pd

from comun import anios_produccion

SALIDA = "data/privado/fichas.json"
PLANTILLA = "data/privado/plantilla_fichas.json"


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sufijo_romano(s):
    m = re.search(r"\s(I|II|III|IV)\s*$", str(s))
    return m.group(1) if m else ""


def es_vacio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def fmt_fecha(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%d/%m/%Y")
    return None


def fmt_num(x, agrupar=True):
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    if isinstance(x, int):
        s = f"{x:,}" if agrupar else str(x)
        return s.replace(",", ".")
    s = f"{x:,.6f}".rstrip("0").rstrip(".")
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def limpio(s):
    return re.sub(r"\s+", " ", str(s)).strip().rstrip(":").strip()


def celda(col, fila):
    return f"{col}{fila}"


class Parser:
    def __init__(self, cfg, base):
        self.cfg, self.base = cfg, base
        self.re_anio = re.compile(cfg["etiquetas_anio"], re.I)
        u = "|".join(re.escape(x) for x in cfg["unidades_en_etiqueta"])
        self.re_unidad = re.compile(r"\(([^()]*(?:" + u + r")[^()]*)\)")
        self.prefijos = [p.upper() for p in cfg.get("prefijos_nombre", [])]

    # ── formato ──
    def fmt_val(self, v, etiqueta="", anio=False):
        f = fmt_fecha(v)
        if f:
            return f
        if isinstance(v, (int, float)):
            return fmt_num(v, agrupar=not (anio or (etiqueta and self.re_anio.search(etiqueta))))
        return re.sub(r"\s+", " ", str(v)).strip()

    def unidad_de_etiqueta(self, et):
        m = self.re_unidad.search(et)
        if not m:
            return et.strip(), ""
        e = (et[:m.start()] + et[m.end():]).replace("  ", " ").strip()
        return e, m.group(1).strip()

    def sin_prefijo(self, s):
        for p in self.prefijos:
            s = re.sub(r"^" + re.escape(p) + r"\s+", "", s, flags=re.I)
        return s

    def nombre_base(self, s):
        return re.sub(r"\s+(I|II|III|IV)$", "", self.sin_prefijo(norm(s)))

    # ── hoja ──
    def leer(self, ws):
        out = {}
        for row in ws.iter_rows():
            for c in row:
                if es_vacio(c.value) or self.base.get(c.coordinate) == c.value:
                    continue
                out[c.coordinate] = c.value
        return out

    def bloque_lista(self, b, val):
        B = self.base.get
        secciones, sec, ultima_et = [], None, ""
        tit = {int(k): v for k, v in b["secciones"].items()}
        for r in range(b["filas"][0], b["filas"][1] + 1):
            if r in tit:
                sec = {"id": tit[r][0], "titulo": tit[r][1], "filas": []}
                if len(tit[r]) > 2 and tit[r][2]:
                    sec["abierta"] = True
                secciones.append(sec)
                continue
            if sec is None:
                continue
            et = B(celda(b["col_etiqueta"], r))
            u = B(celda(b["col_unidad"], r)) or ""
            if et:
                ultima_et = limpio(et)
            elif u in b.get("sin_etiqueta", {}):
                et = ultima_et + b["sin_etiqueta"][u]
            else:
                et = ""
            vs = [(c, val[celda(c, r)]) for c in b["cols_valor"] if celda(c, r) in val]
            if not vs or not et:
                continue
            if u in b.get("unidad_por_columna", {}):
                suf = b["unidad_por_columna"][u]
                sec["filas"].append({"e": limpio(et), "v": " · ".join(self.fmt_val(v, et) + suf.get(c, "") for c, v in vs)})
                continue
            fila = {"e": limpio(et), "v": " · ".join(self.fmt_val(v, et) for _, v in vs)}
            if u:
                fila["u"] = b.get("renombrar_unidad", {}).get(u, u)
            sec["filas"].append(fila)
        return secciones

    def bloque_pares(self, b, val):
        B = self.base.get
        filas = []
        estado = [None] * len(b["partes"])

        def procesar(i, p, r):
            gr = next((g for g in p.get("grupos", []) if g["fila"] == r), None)
            t = B(celda(p["col_etiqueta"], r))
            if gr:
                estado[i] = (gr["prefijo"] + limpio(t).capitalize()) if gr.get("de_etiqueta") else gr.get("texto")
                if gr.get("saltear"):
                    return
            if not t:
                return
            e, u = self.unidad_de_etiqueta(limpio(t)) if p.get("unidad_de_etiqueta") else (limpio(t), p.get("unidad", ""))
            for v in p["valores"]:
                k = celda(v["col"], r)
                if k in val:
                    f = {"g": estado[i], "e": e + v.get("sufijo", ""),
                         "v": self.fmt_val(val[k], e if p.get("fmt_con_etiqueta") else "")}
                    if u:
                        f["u"] = u
                    filas.append(f)

        rangos = [range(p["filas"][0], p["filas"][1] + 1) for p in b["partes"]]
        if b.get("intercalar"):
            for r in sorted(set().union(*rangos)):
                for i, p in enumerate(b["partes"]):
                    if r in rangos[i]:
                        procesar(i, p, r)
        else:
            for i, p in enumerate(b["partes"]):
                for r in rangos[i]:
                    procesar(i, p, r)
        for s in b.get("celdas_sueltas", []):
            if s["celda"] in val:
                filas.append({"g": s["g"], "e": s["e"], "v": self.fmt_val(val[s["celda"]])})
        sec = {"id": b["id"], "titulo": b["titulo"], "filas": filas}
        if b.get("abierta"):
            sec["abierta"] = True
        return [sec]

    def bloque_tabla(self, b, val):
        B = self.base.get
        cols = b["cols"]
        filas = []
        for r in range(b["filas"][0], b["filas"][1] + 1):
            if not any(celda(c, r) in val for c, _ in cols[b["requiere_desde_col"]:]):
                continue
            fila = []
            for i, (c, _) in enumerate(cols):
                v = val.get(celda(c, r))
                if v is None and i in b.get("relleno_desde_plantilla", []):
                    v = B(celda(c, r))
                fila.append(None if es_vacio(v) else self.fmt_val(v, anio=(i == b.get("col_fecha"))))
            filas.append(fila)
        if not filas:
            return None
        usar = list(range(len(cols)))
        if b.get("quitar_cols_vacias"):
            usar = [i for i in usar if any(f[i] is not None for f in filas)]
        return {"id": b["id"], "titulo": b["titulo"], "cols": [cols[i][1] for i in usar],
                "filas": [[f[i] for i in usar] for f in filas]}

    def ficha(self, ws):
        cfg = self.cfg
        val = self.leer(ws)
        nombre = val.get(cfg["celda_nombre"])
        if not val or nombre in (None, cfg.get("relleno_nombre")):
            return None
        cab = [{"e": c["e"], "v": self.fmt_val(val[c["celda"]], c["e"])} for c in cfg["cabecera"] if c["celda"] in val]
        secciones, tablas = [], []
        for b in cfg["bloques"]:
            if b["tipo"] == "lista":
                secciones += self.bloque_lista(b, val)
            elif b["tipo"] == "pares":
                secciones += self.bloque_pares(b, val)
            elif b["tipo"] == "tabla":
                t = self.bloque_tabla(b, val)
                if t:
                    tablas.append(t)
            else:
                raise SystemExit(f"Tipo de bloque desconocido en la plantilla: {b['tipo']}")
        orden = cfg["orden_secciones"]

        # Actualización y dato más reciente (datetimes de Excel y años sueltos en celdas de fecha)
        fa = val.get(cfg["celda_fecha_act"])
        fechas = [v for v in val.values() if isinstance(v, (dt.datetime, dt.date))]
        ans = cfg.get("anios_sueltos", {})
        def es_celda_anio(k):
            m = re.fullmatch(r"([A-Z]+)(\d+)", k)
            return k in ans.get("celdas", []) or (m and m.group(1) == ans.get("col")
                                                  and int(m.group(2)) >= ans.get("desde_fila", 10**9))
        anios = [v for k, v in val.items() if isinstance(v, int) and 1900 < v < 2100 and es_celda_anio(k)]
        ult = max(fechas) if fechas else None
        if ult and anios and max(anios) > ult.year:
            ult = None
        anios += [v.year for v in fechas]
        titulo = self.sin_prefijo(limpio(nombre))
        titulo = titulo[:1].upper() + titulo[1:]
        suf = sufijo_romano(ws.title)
        if suf:
            titulo += " " + suf
        return {
            "hoja": ws.title, "titulo": titulo, "nombre_ficha": limpio(nombre),
            "fecha_act": fmt_fecha(fa) if fmt_fecha(fa) else (self.fmt_val(fa) if fa is not None else None),
            "fecha_act_iso": fa.strftime("%Y-%m-%d") if isinstance(fa, (dt.datetime, dt.date)) else None,
            "ultimo_dato": ult.strftime("%d/%m/%Y") if ult else (str(max(anios)) if anios else None),
            "cabecera": cab,
            "secciones": sorted((s for s in secciones if s["filas"]),
                                key=lambda s: orden.index(s["id"]) if s["id"] in orden else len(orden)),
            "tablas": tablas,
        }


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", norm(s).lower()).strip("-")


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FICHAS_XLSX")
    ruta_pl = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("FICHAS_PLANTILLA", PLANTILLA)
    if not ruta:
        raise SystemExit("Falta la ruta del xlsx: preprocess_fichas.py <ruta> (o variable FICHAS_XLSX)")
    if not os.path.exists(ruta):
        raise SystemExit("No existe el archivo de fichas (ver argumento o FICHAS_XLSX)")
    if not os.path.exists(ruta_pl):
        raise SystemExit(f"No existe la plantilla de la grilla ({ruta_pl}); ver el docstring")
    with open(ruta_pl, encoding="utf-8") as fh:
        cfg = json.load(fh)
    import openpyxl
    wb = openpyxl.load_workbook(ruta, data_only=True, read_only=False)
    if cfg["hoja_plantilla"] not in wb.sheetnames:
        raise SystemExit("El libro no tiene la hoja plantilla indicada en plantilla_fichas.json")
    base = {c.coordinate: c.value for row in wb[cfg["hoja_plantilla"]].iter_rows() for c in row if not es_vacio(c.value)}
    P = Parser(cfg, base)

    fichas = []
    saltear = set(cfg.get("hojas_saltear", [])) | {cfg["hoja_plantilla"]}
    for ws in wb.worksheets:
        if ws.title in saltear:
            continue
        f = P.ficha(ws)
        if f is None:
            print(f"  (hoja '{ws.title}' vacía o sin nombre: se saltea)")
            continue
        fichas.append(f)

    # ── Nombres del visor: yacimiento declarado (CSV) + polígonos de yacimientos.geojson ──
    print("Leyendo yacimiento declarado (areayacimiento) de los CSV de producción…")
    partes = []
    for a in anios_produccion():
        partes.append(pd.read_csv(f"data/produccion-{a}.csv", usecols=["idpozo", "areayacimiento"],
                                  dtype={"areayacimiento": str}).drop_duplicates())
    dec = pd.concat(partes).drop_duplicates().dropna()
    dec["n"] = dec["areayacimiento"].map(norm)
    nombres = dec.groupby("n")["areayacimiento"].agg(lambda s: s.value_counts().index[0]).to_dict()
    pozos_por_n = dec.groupby("n")["idpozo"].agg(lambda s: sorted({int(x) for x in s})).to_dict()
    poligonos = {}
    if os.path.exists("data/yacimientos.geojson"):
        with open("data/yacimientos.geojson", encoding="utf-8") as fh:
            for ft in json.load(fh)["features"]:
                poligonos.setdefault(norm(ft["properties"]["nombre"]), ft["properties"]["nombre"])

    usados = set()
    por_pozo, por_yac = {}, {}
    print("\nMatcheo de nombres (ficha -> yacimiento del visor):")
    for f in fichas:
        cands = [P.nombre_base(f["nombre_ficha"]), P.nombre_base(f["hoja"])]
        n = next((c for c in cands if c in nombres), None)
        modo = "exacto"
        if n is None:
            cont = sorted({k for c in cands for k in nombres if c and (c in k)})
            n = cont[0] if len(cont) == 1 else None
            modo = "contiene" if n else ("ambiguo: " + ", ".join(cont[:5]) if cont else "sin match")
        base_id = slug(f["titulo"])
        fid, k = base_id, 2
        while fid in usados:
            fid, k = f"{base_id}-{k}", k + 1
        usados.add(fid)
        f["id"] = fid
        f["yacimiento"] = nombres.get(n) if n else None
        f["poligono"] = poligonos.get(n) or next((poligonos[c] for c in cands if c in poligonos), None)
        f["pozos"] = pozos_por_n.get(n, []) if n else []
        for p in f["pozos"]:
            por_pozo.setdefault(str(p), []).append(fid)
        for nn in {n, *(c for c in cands if c in poligonos)} - {None}:
            por_yac.setdefault(nn, [])
            if fid not in por_yac[nn]:
                por_yac[nn].append(fid)
        print(f"  {f['hoja']!r:40} -> {f['yacimiento'] or '—':30} ({modo}; {len(f['pozos'])} pozos; "
              f"polígono: {f['poligono'] or 'no'}; actualizada: {f['fecha_act'] or 'sin fecha'}; "
              f"dato más reciente: {f['ultimo_dato'] or '—'})")

    salida = {
        "generado": dt.date.today().isoformat(),
        "fuente": "planilla local",
        "aviso": "Datos locales, no se publican",
        "fichas": fichas,
        "por_pozo": por_pozo,
        "por_yacimiento": por_yac,
    }
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, separators=(",", ":"))
    n_val = sum(len(s["filas"]) for f in fichas for s in f["secciones"])
    print(f"\n{SALIDA}: {len(fichas)} fichas, {n_val} valores, {len(por_pozo)} pozos con ficha, "
          f"{os.path.getsize(SALIDA) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
