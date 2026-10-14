"""
Áreas hidrocarburíferas NACIONALES (Sec. Energía, actualizado 2026) cruzadas
con los pozos de producción para enriquecer cada concesión con estadísticas.

Entrada:
  data/concesiones_shp/concesiones.shp  (298 concesiones de explotación, EPSG:4326)
  data/pozos_<AÑO>.js                    (pozos con [lat,lon,pet,gas,...])
Salida:
  data/areas.geojson  con props: nombre, operador, socios, n_pozos,
                       pet, gas, noconv, prov_pozos, mod (fecha modificación)
"""
import json
import re
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

POZOS_YEAR = 2025  # año de pozos para el cruce
I = dict(lat=0, lon=1, pet=2, gas=3, agua=4, emp=5, cu=6, prov=7, tr=8,
         form=9, ma=10, est=11, sigla=12)

# ── Cargar concesiones ──────────────────────────────────────────────────────
print("Cargando concesiones nacionales...")
SHP = "data/concesiones_shp/concesiones.shp"
areas      = gpd.read_file(SHP, encoding="cp1252").to_crs(4326)
areas_utf8 = gpd.read_file(SHP, encoding="utf-8")  # 2da lectura para campos UTF-8

import ftfy
def best_text(cp_val, utf_val):
    """El dbf mezcla cp1252 y UTF-8. Elegir la lectura limpia por valor."""
    u = utf_val if isinstance(utf_val, str) else ""
    c = cp_val if isinstance(cp_val, str) else ""
    # Si la lectura UTF-8 no tiene carácter de reemplazo, ese registro era UTF-8
    if u and "�" not in u:
        return ftfy.fix_text(u)
    return ftfy.fix_text(c)

def fix_moji(s):
    return ftfy.fix_text(s) if isinstance(s, str) else s

def clean_part(s):
    if not isinstance(s, str):
        return ""
    # "<br> X: 100 %<br> Y: 5 %" -> "X: 100% · Y: 5%"
    parts = [p.strip() for p in re.split(r"<br>", s) if p.strip()]
    return " · ".join(p.replace(" %", "%") for p in parts)

def col(name):
    return [best_text(a, b) for a, b in zip(areas[name], areas_utf8[name])]

areas_norm = gpd.GeoDataFrame({
    "nombre":   col("NOMBRE_DE_"),
    "operador": col("EMPRESA_OP"),
    "socios":   [clean_part(s) for s in col("PARTICIPAC")],
    "mod":      areas["MODIFICACI"].astype(str).str.slice(0, 10),
    "geometry": areas.geometry,
}, crs=4326)
areas_norm = areas_norm[areas_norm.geometry.notna() & ~areas_norm.geometry.is_empty].reset_index(drop=True)
print(f"  {len(areas_norm)} concesiones")

# ── Cargar pozos del año ────────────────────────────────────────────────────
print(f"Cargando pozos {POZOS_YEAR}...")
txt = open(f"data/pozos_{POZOS_YEAR}.js", encoding="utf-8").read()
rows = json.loads(txt[txt.index("=") + 1: txt.rindex(";")])
pozos = gpd.GeoDataFrame(
    {
        "pet":   [r[I["pet"]] for r in rows],
        "gas":   [r[I["gas"]] for r in rows],
        "emp":   [r[I["emp"]] for r in rows],
        "prov":  [r[I["prov"]] for r in rows],
        "noconv":[("NO CONV" in (r[I["tr"]] or "").upper()) for r in rows],
    },
    geometry=[Point(r[I["lon"]], r[I["lat"]]) for r in rows],
    crs=4326,
)
print(f"  {len(pozos):,} pozos")

# ── Cruce espacial pozos dentro de cada área ────────────────────────────────
print("Cruzando pozos x áreas (sjoin)...")
joined = gpd.sjoin(pozos, areas_norm[["geometry"]], predicate="within", how="inner")
g = joined.groupby("index_right")
stats = pd.DataFrame({
    "n_pozos": g.size(),
    "pet":     g["pet"].sum().round().astype("Int64"),
    "gas":     g["gas"].sum().round().astype("Int64"),
    "n_nc":    g["noconv"].sum(),
})
# operador dominante por pozos y provincia dominante
top_emp  = g["emp"].agg(lambda s: s.value_counts().idxmax() if len(s) else "")
top_prov = g["prov"].agg(lambda s: s.value_counts().idxmax() if len(s) else "")

areas_norm["n_pozos"] = stats["n_pozos"].reindex(areas_norm.index).fillna(0).astype(int)
areas_norm["pet"]     = stats["pet"].reindex(areas_norm.index).fillna(0).astype(int)
areas_norm["gas"]     = stats["gas"].reindex(areas_norm.index).fillna(0).astype(int)
areas_norm["noconv"]  = (stats["n_nc"].reindex(areas_norm.index).fillna(0) > 0)
areas_norm["prov_pozos"] = top_prov.reindex(areas_norm.index).fillna("")
# Si la concesión no informó operador, usar el dominante de los pozos
areas_norm["operador"] = areas_norm.apply(
    lambda r: r["operador"] if r["operador"] else top_emp.get(r.name, ""), axis=1)

# ── Simplificar y exportar ──────────────────────────────────────────────────
areas_norm["geometry"] = areas_norm.geometry.simplify(0.0005, preserve_topology=True)
out = "data/areas.geojson"
areas_norm.to_file(out, driver="GeoJSON")

con_pozos = (areas_norm.n_pozos > 0).sum()
print(f"\nGuardado {out}: {len(areas_norm)} áreas, {con_pozos} con pozos cruzados, "
      f"{areas_norm.noconv.sum()} con no convencional")
print("\nTop 8 áreas por producción de petróleo:")
top = areas_norm.sort_values("pet", ascending=False).head(8)
for _, r in top.iterrows():
    print(f"  {r['nombre'][:28]:28} {r['operador'][:24]:24} "
          f"{r['n_pozos']:>5} pozos  {r['pet']:>12,} m³ pet")
