"""
Cruces espaciales de los pozos con otras capas de la Sec. Energía (GeoPandas).

Cada bloque es una operación típica de GeoPandas (ver docs/geopandas_guide.ipynb):
  1. read_file + to_crs      leer shapefiles y llevarlos a un CRS común
  2. sjoin (within)          pozo -> cuenca / yacimiento / permiso / concesión
  3. sjoin_nearest           distancia al gasoducto troncal y a la refinería más cercanos
  4. overlay + length        km de ductos de yacimiento dentro de cada concesión
  5. simplify + to_file      capas livianas para el visor web

Entrada (data/geo/, ver README):
  cuencas/ ductos319/ gasoductos/ refinerias/ yacimientos/ permisos/   (shapefiles)
  data/pozos_<AÑO>.js   (preprocess_peryear.py)
  data/areas.geojson    (preprocess_areas.py) -> se le agregan los km de ductos
Salida:
  data/cuencas.geojson, gasoductos.geojson, refinerias.geojson,
  data/yacimientos.geojson, permisos.geojson     capas del mapa
  data/pozos_geo.json                             atributos espaciales por pozo
  data/geo_qa.json                                pozos con cuenca declarada != polígono
"""
import json
import time

import ftfy
import geopandas as gpd
import pandas as pd

YEARS = [2022, 2023, 2024, 2025, 2026]
STATS_YEAR = 2025          # año para sumar producción por cuenca / permiso
GEO = "data/geo"
I = dict(lat=0, lon=1, pet=2, gas=3, agua=4, emp=5, cu=6, prov=7, tr=8,
         form=9, ma=10, est=11, sigla=12, id=13)

# Proyección métrica para medir distancias/longitudes en todo el país:
# Lambert azimutal equivalente centrada en Argentina. En grados (EPSG:4326)
# las distancias no tienen sentido; acá 1 unidad = 1 metro.
METRIC = "+proj=laea +lat_0=-38 +lon_0=-65 +datum=WGS84 +units=m"

# Nombre de cuenca en el padrón (texto) -> nombre del polígono oficial
CUENCA_ALIAS = {"AUSTRAL": "AUSTRAL MARINA", "LOS BOLSONES": "BOLSONES INTERMONTANOS",
                "GENERAL LEVALLE": "LEVALLE"}

t0 = time.time()


def read(name, cols=None):
    """Shapefile de data/geo/<name>/<name>.shp en EPSG:4326, textos con ftfy."""
    g = gpd.read_file(f"{GEO}/{name}/{name}.shp", columns=cols).to_crs(4326)
    for c in g.columns:
        if g[c].dtype == object and c != "geometry":
            g[c] = g[c].map(lambda s: ftfy.fix_text(s).strip() if isinstance(s, str) else s)
    return g[g.geometry.notna() & ~g.geometry.is_empty].reset_index(drop=True)


def save(gdf, name, tol):
    """Simplifica (tolerancia en grados) y guarda GeoJSON con coordenadas recortadas."""
    out = gdf.copy()
    out["geometry"] = out.geometry.simplify(tol, preserve_topology=True)
    out.to_file(f"data/{name}.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
    print(f"  -> data/{name}.geojson ({len(out)} features)")


# ── 0. Pozos: unión de todos los años (última ubicación conocida) ──────────
# Clave idpozo: la sigla NO es única en el padrón (hay siglas repetidas en pozos distintos).
print("Cargando pozos 2022-2026...")
rows = {}
prod = {}
for yr in YEARS:
    txt = open(f"data/pozos_{yr}.js", encoding="utf-8").read()
    for r in json.loads(txt[txt.index("=") + 1: txt.rindex(";")]):
        rows[r[I["id"]]] = r
        if yr == STATS_YEAR:
            prod[r[I["id"]]] = (r[I["pet"]], r[I["gas"]])
pozos = gpd.GeoDataFrame(
    {
        "id":     list(rows),
        "sigla":  [r[I["sigla"]] for r in rows.values()],
        "cu_decl": [r[I["cu"]] for r in rows.values()],
        "emp":    [r[I["emp"]] for r in rows.values()],
        "pet":    [prod.get(k, (0, 0))[0] for k in rows],
        "gas":    [prod.get(k, (0, 0))[1] for k in rows],
    },
    # points_from_xy: columnas lon/lat -> geometrías Point (¡x = lon, y = lat!)
    geometry=gpd.points_from_xy([r[I["lon"]] for r in rows.values()],
                                [r[I["lat"]] for r in rows.values()]),
    crs=4326,
)
print(f"  {len(pozos):,} pozos únicos")


# ── 1-2. Cuencas sedimentarias: sjoin 'within' ─────────────────────────────
print("Cuencas sedimentarias...")
cuencas = read("cuencas").rename(columns={"CUENCA": "cuenca", "TIPO": "tipo",
                                          "UBICACION": "ubicacion"})
cuencas = cuencas[["cuenca", "tipo", "ubicacion", "geometry"]]
# sjoin agrega a cada pozo las columnas del polígono que lo contiene.
# how="left" conserva los pozos que no caen en ninguna cuenca (quedan NaN).
j = gpd.sjoin(pozos, cuencas[["cuenca", "geometry"]], predicate="within", how="left")
j = j[~j.index.duplicated()]            # por si un pozo cae en 2 polígonos solapados
pozos["cu_poly"] = j["cuenca"]

# Control de calidad: cuenca declarada vs polígono que realmente la contiene
decl = pozos["cu_decl"].map(lambda c: CUENCA_ALIAS.get(c, c))
bad = pozos[decl.ne(pozos["cu_poly"])].copy()
# ¿qué tan lejos está del polígono de la cuenca declarada? (en km, CRS métrico)
cu_m = cuencas.set_index("cuenca").to_crs(METRIC)
bad_m = bad.to_crs(METRIC)
bad["dist_km"] = [
    round(g.distance(cu_m.geometry[d]) / 1000, 1) if d in cu_m.index else None
    for g, d in zip(bad_m.geometry, decl[bad.index])
]
print(f"  {len(bad)} pozos con cuenca declarada distinta al polígono")

# Estadísticas por cuenca (dissolve sería la otra forma: agrupar geometrías)
g = pozos.groupby("cu_poly")
cuencas["n_pozos"] = cuencas["cuenca"].map(g.size()).fillna(0).astype(int)
cuencas["pet"] = cuencas["cuenca"].map(g["pet"].sum()).fillna(0).round().astype(int)
cuencas["gas"] = cuencas["cuenca"].map(g["gas"].sum()).fillna(0).round().astype(int)
cuencas["km2"] = (cuencas.to_crs(METRIC).area / 1e6).round().astype(int)
save(cuencas, "cuencas", 0.01)


# ── Yacimientos, permisos de exploración y concesiones: sjoin 'within' ─────
print("Yacimientos y permisos de exploración...")
yac = read("yacimientos", ["AREAYACIMI", "EMPRESA_OP"]).rename(
    columns={"AREAYACIMI": "nombre", "EMPRESA_OP": "operador"})
per = read("permisos", ["NOMBRE_DE_", "EMPRESA_OP", "PARTICIPAC"]).rename(
    columns={"NOMBRE_DE_": "nombre", "EMPRESA_OP": "operador", "PARTICIPAC": "socios"})
per["socios"] = per["socios"].fillna("").str.replace(r"\s*<br>\s*", " · ", regex=True).str.strip(" ·")
areas = gpd.read_file("data/areas.geojson")
# read_file interpreta "2025-12-15" como fecha y al reescribir le agrega la hora
areas["mod"] = areas["mod"].astype(str).str.slice(0, 10)

for layer, col in [(yac, "yac"), (per, "permiso"), (areas, "concesion")]:
    j = gpd.sjoin(pozos, layer[["nombre", "geometry"]], predicate="within", how="left")
    pozos[col] = j[~j.index.duplicated()]["nombre"]
pozos["fuera"] = pozos["concesion"].isna() & pozos["yac"].isna()
print(f"  en yacimiento: {pozos.yac.notna().sum():,} | en permiso exploratorio: "
      f"{pozos.permiso.notna().sum():,} | fuera de concesión y yacimiento: {pozos.fuera.sum():,}")

gp = pozos.groupby("permiso")
per["n_pozos"] = per["nombre"].map(gp.size()).fillna(0).astype(int)
per["pet"] = per["nombre"].map(gp["pet"].sum()).fillna(0).round().astype(int)
per["gas"] = per["nombre"].map(gp["gas"].sum()).fillna(0).round().astype(int)
save(yac, "yacimientos", 0.0005)
save(per, "permisos", 0.0005)


# ── 3. Infraestructura: sjoin_nearest (requiere CRS métrico) ───────────────
print("Gasoductos troncales y refinerías...")
gasod = read("gasoductos", ["NOMBRE", "NOMBRE_DE_", "EMPRESA_LI", "SUBTIPO_DE"]).rename(
    columns={"NOMBRE": "nombre", "NOMBRE_DE_": "tramo", "EMPRESA_LI": "empresa",
             "SUBTIPO_DE": "subtipo"})
refi = read("refinerias", ["PLANTA", "EMPRESA", "PROVINCIA"]).rename(
    columns={"PLANTA": "planta", "EMPRESA": "empresa", "PROVINCIA": "provincia"})
# la misma planta aparece dos veces (una sin empresa): quedarse con la que tiene datos
clave = refi["planta"].str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii").str.upper()
refi = refi[~(clave.duplicated(keep=False) & refi["empresa"].isna())].reset_index(drop=True)

pozos_m = pozos[["geometry"]].to_crs(METRIC)
# sjoin_nearest busca, para cada pozo, la geometría más cercana de la otra capa
# y devuelve la distancia en las unidades del CRS (metros) en distance_col.
ng = gpd.sjoin_nearest(pozos_m, gasod[["nombre", "geometry"]].to_crs(METRIC),
                       how="left", distance_col="d")
ng = ng[~ng.index.duplicated()]
pozos["gasod"] = ng["nombre"]
pozos["d_gasod"] = (ng["d"] / 1000).round(1)
nr = gpd.sjoin_nearest(pozos_m, refi[["planta", "geometry"]].to_crs(METRIC),
                       how="left", distance_col="d")
nr = nr[~nr.index.duplicated()]
pozos["refi"] = nr["planta"]
pozos["d_refi"] = (nr["d"] / 1000).round(0)
print(f"  distancia mediana al gasoducto troncal: {pozos.d_gasod.median():.1f} km | "
      f"a refinería: {pozos.d_refi.median():.0f} km")
# Cada gasoducto viene partido en miles de segmentos de 2 puntos, que simplify no
# puede achicar: line_merge los une en líneas continuas antes de simplificar.
gasod["geometry"] = gasod.geometry.line_merge()
save(gasod, "gasoductos", 0.003)
refi.to_file("data/refinerias.geojson", driver="GeoJSON")
print(f"  -> data/refinerias.geojson ({len(refi)} features)")


# ── 4. Ductos de yacimiento (Res. 319/93) por concesión: overlay + length ──
print("Ductos de yacimiento x concesiones (overlay, puede tardar ~1 min)...")
duc = gpd.read_file(f"{GEO}/ductos319/ductos319.shp", columns=["TIPO"]).to_crs(METRIC)
duc = duc[duc.TIPO.isin(["OLEODUCTO", "GASODUCTO", "ACUEDUCTO"])]
# Hay tramos cargados dos veces (mismo trazado, distinto nombre): deduplicar por
# geometría. normalize() ordena los vértices para que A->B y B->A comparen igual.
n0 = len(duc)
duc = duc[~duc.geometry.normalize().to_wkb().duplicated()]
print(f"  {n0 - len(duc):,} tramos duplicados descartados")
areas_m = areas[["nombre", "geometry"]].to_crs(METRIC)
# overlay(intersection) recorta cada ducto por los límites de cada concesión:
# un ducto que cruza dos áreas se parte en dos pedazos, uno por área.
inter = gpd.overlay(duc, areas_m, how="intersection", keep_geom_type=True)
inter["km"] = inter.length / 1000
km = inter.pivot_table(index="nombre", columns="TIPO", values="km", aggfunc="sum").fillna(0)
for tipo, col in [("OLEODUCTO", "km_oleo"), ("GASODUCTO", "km_gas"), ("ACUEDUCTO", "km_agua")]:
    areas[col] = areas["nombre"].map(km.get(tipo, pd.Series(dtype=float))).fillna(0).round().astype(int)
print(f"  {duc.length.sum()/1000:,.0f} km de ductos en total, "
      f"{inter.km.sum():,.0f} km dentro de concesiones")
areas.to_file("data/areas.geojson", driver="GeoJSON")
print("  -> data/areas.geojson (+ km_oleo, km_gas, km_agua)")


# ── 5. Salidas compactas para el visor ──────────────────────────────────────
def lookup(series):
    """Strings repetidos -> tabla + índices (achica mucho el JSON)."""
    vals = sorted(series.dropna().unique())
    idx = {v: i for i, v in enumerate(vals)}
    return vals, [idx.get(v, -1) if isinstance(v, str) else -1 for v in series]

tabs, cols = {}, {}
for c in ["cu_poly", "yac", "permiso", "concesion", "gasod", "refi"]:
    tabs[c], cols[c] = lookup(pozos[c])
out = {
    "cols": ["cuenca", "yacimiento", "permiso", "concesion", "gasoducto", "d_gasod_km",
             "refineria", "d_refi_km"],
    "tablas": {"cuenca": tabs["cu_poly"], "yacimiento": tabs["yac"], "permiso": tabs["permiso"],
               "concesion": tabs["concesion"], "gasoducto": tabs["gasod"], "refineria": tabs["refi"]},
    "pozos": {
        int(s): [cols["cu_poly"][i], cols["yac"][i], cols["permiso"][i], cols["concesion"][i],
            cols["gasod"][i], float(pozos.d_gasod.iat[i]), cols["refi"][i], int(pozos.d_refi.iat[i])]
        for i, s in enumerate(pozos.id)
    },
}
json.dump(out, open("data/pozos_geo.json", "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))
print(f"  -> data/pozos_geo.json ({len(out['pozos']):,} pozos)")

# Producción por banda de distancia al gasoducto troncal
bands = [(0, 10), (10, 25), (25, 50), (50, 100), (100, 1e9)]
dist = []
for a, b in bands:
    m = pozos.d_gasod.ge(a) & pozos.d_gasod.lt(b)
    dist.append({"desde": a, "hasta": None if b > 1e8 else b, "n": int(m.sum()),
                 "pet": int(pozos.pet[m].sum()), "gas": int(pozos.gas[m].sum())})

bad = bad.sort_values("dist_km", ascending=False, na_position="first")
qa = {
    "anio_stats": STATS_YEAR,
    "n_pozos": len(pozos),
    "cuenca_distinta": [
        {"id": int(r.id), "sigla": r.sigla, "declarada": r.cu_decl, "poligono": r.cu_poly if isinstance(r.cu_poly, str) else None,
         "dist_km": r.dist_km, "emp": r.emp, "lat": round(r.geometry.y, 4), "lon": round(r.geometry.x, 4)}
        for r in bad.itertuples()
    ],
    "fuera_de_areas": int(pozos.fuera.sum()),
    "dist_gasoducto": dist,
}
json.dump(qa, open("data/geo_qa.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"  -> data/geo_qa.json")
print(f"\nListo en {time.time()-t0:.0f}s")
