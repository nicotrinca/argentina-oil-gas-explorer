"""
Preprocesa datos Cap. IV - Pozos Petroleros Argentina
Genera:
  - data/pozos_produccion.geojson  → puntos por pozo con prod 2024 total
  - data/cuencas_stats.json        → estadísticas agregadas por cuenca
"""
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape

print("Cargando producción 2024...")
prod = pd.read_csv(
    "data/produccion-2024.csv",
    usecols=["idpozo", "sigla", "anio", "mes", "prod_pet", "prod_gas", "prod_agua",
             "empresa", "cuenca", "provincia", "tipo_de_recurso",
             "areapermisoconcesion", "tipoestado"],
    encoding="utf-8-sig",
    low_memory=False,
)

# Solo pozos con alguna producción en 2024 (clave idpozo: la sigla no es única)
prod_agg = prod.groupby("idpozo").agg(
    sigla=("sigla", "first"),
    prod_pet_total=("prod_pet", "sum"),
    prod_gas_total=("prod_gas", "sum"),
    prod_agua_total=("prod_agua", "sum"),
    empresa=("empresa", "first"),
    cuenca=("cuenca", "first"),
    provincia=("provincia", "first"),
    tipo_recurso=("tipo_de_recurso", "first"),
    concesion=("areapermisoconcesion", "first"),
    estado=("tipoestado", "first"),
    meses_activo=("mes", "count"),
).reset_index()

activos = prod_agg[(prod_agg.prod_pet_total > 0) | (prod_agg.prod_gas_total > 0)].copy()
print(f"  Pozos con producción > 0: {len(activos):,}")

print("Cargando registro de pozos (CSV con coordenadas)...")
pozos = pd.read_csv("data/capitulo-iv-pozos.csv", encoding="utf-8-sig", low_memory=False)
print(f"  Pozos en registro: {len(pozos):,}")

# Extraer lon/lat del campo geojson
def extract_coords(geojson_str):
    try:
        g = json.loads(geojson_str)
        coords = g["coordinates"]
        return coords[0], coords[1]
    except Exception:
        return None, None

pozos[["lon", "lat"]] = pozos["geojson"].apply(
    lambda x: pd.Series(extract_coords(x))
)
pozos = pozos.dropna(subset=["lon", "lat"])

# Join por sigla
merged = activos.merge(pozos[["idpozo", "lon", "lat", "formacion", "profundidad", "tipopozo"]], on="idpozo", how="left")
merged = merged.dropna(subset=["lon", "lat"])
print(f"  Pozos con coordenadas: {len(merged):,}")

# Convertir a GeoDataFrame
gdf = gpd.GeoDataFrame(
    merged,
    geometry=gpd.points_from_xy(merged.lon, merged.lat),
    crs="EPSG:4326",
)

# Redondear coords y producción para reducir tamaño
for col in ["prod_pet_total", "prod_gas_total", "prod_agua_total"]:
    gdf[col] = gdf[col].round(0).astype(int)
gdf["lon"] = gdf["lon"].round(4)
gdf["lat"] = gdf["lat"].round(4)

# Renombrar propiedades con nombres cortos para reducir GeoJSON
gdf = gdf.rename(columns={
    "prod_pet_total": "pet",
    "prod_gas_total": "gas",
    "prod_agua_total": "agua",
    "empresa": "emp",
    "cuenca": "cu",
    "provincia": "prov",
    "tipo_recurso": "tr",
    "formacion": "form",
    "meses_activo": "ma",
    "estado": "est",
})

# Exportar como array JS compacto: [lat, lon, pet, gas, agua, emp, cu, prov, tr, form, ma, est, sigla]
# Mucho más pequeño y rápido de parsear que GeoJSON
rows = []
for _, row in gdf.iterrows():
    rows.append([
        round(row.lat, 4),
        round(row.lon, 4),
        int(row.pet),
        int(row.gas),
        int(row.agua),
        row.emp or "",
        row.cu or "",
        row.prov or "",
        row.tr or "",
        row.form or "",
        int(row.ma),
        row.est or "",
        (row.sigla or "").strip(),
        int(row.idpozo),
    ])

out_path = "data/pozos.js"
with open(out_path, "w", encoding="utf-8") as f:
    f.write("window.POZOS=")
    json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";")
print(f"JS array guardado: {out_path}  ({len(rows):,} pozos)")
print(f"GeoJSON guardado: {out_path}  ({len(gdf):,} pozos)")

# Estadísticas por cuenca
print("Calculando stats por cuenca...")
cuenca_stats = (
    prod_agg.groupby("cuenca")
    .agg(
        pozos_activos=("idpozo", "count"),
        prod_pet_total=("prod_pet_total", "sum"),
        prod_gas_total=("prod_gas_total", "sum"),
    )
    .reset_index()
    .sort_values("prod_pet_total", ascending=False)
)
cuenca_stats["prod_pet_total"] = cuenca_stats["prod_pet_total"].round(0)
cuenca_stats["prod_gas_total"] = cuenca_stats["prod_gas_total"].round(0)
cuenca_stats.to_json("data/cuencas_stats.json", orient="records", force_ascii=False)
print("Stats por cuenca guardadas.")

# Stats por empresa (top 20)
top_empresas = (
    prod_agg.groupby("empresa")
    .agg(prod_pet_total=("prod_pet_total", "sum"), pozos=("idpozo", "count"))
    .sort_values("prod_pet_total", ascending=False)
    .head(20)
    .reset_index()
)
top_empresas["prod_pet_total"] = top_empresas["prod_pet_total"].round(0)
top_empresas.to_json("data/top_empresas.json", orient="records", force_ascii=False)
print("Top empresas guardado.")

print("\nListo!")
