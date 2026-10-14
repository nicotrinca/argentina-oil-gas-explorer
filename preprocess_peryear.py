"""
Genera data/pozos_YYYY.js para cada año disponible.

La clave del pozo es 'idpozo': la sigla NO es única en el padrón (ej. "T-22" es un
pozo de El Trébol en Cuyana y otro de Tecpetrol en el Noroeste). Agrupar o cruzar por
sigla suma la producción de pozos distintos y duplica ubicaciones.
"""
import json
import pandas as pd

YEARS = [2022, 2023, 2024, 2025, 2026]
USECOLS = ["idpozo", "sigla", "prod_pet", "prod_gas", "prod_agua",
           "empresa", "cuenca", "provincia", "tipo_de_recurso", "tipoestado", "mes"]

# Cargar coordenadas una sola vez
print("Cargando coordenadas...")
pozos = pd.read_csv("data/capitulo-iv-pozos.csv", encoding="utf-8-sig", low_memory=False)
def extract_coords(g):
    try:
        c = json.loads(g)["coordinates"]; return round(c[1],4), round(c[0],4)
    except: return None, None
pozos[["lat","lon"]] = pozos["geojson"].apply(lambda x: pd.Series(extract_coords(x)))
coords = pozos.dropna(subset=["lat","lon"]).set_index("idpozo")[["lat","lon","formacion","sigla"]]
print(f"  {len(coords):,} pozos con coords")

# ── Saneamiento de coordenadas ──────────────────────────────────────────────
# Bounding box aproximado de Argentina continental.
# El padrón oficial tiene algunos pozos con lat/lon invertidas (caen en la
# Antártida) o mal cargadas (caen en Paraguay). Corregimos por swap o descarte.
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = -56.0, -21.0, -74.0, -53.0
# Siglas con coordenada mal cargada e irrecuperable en el padrón oficial
# (un rectángulo no las excluye porque caen dentro del bbox pero fuera del país).
KNOWN_BAD = {"ENE.LP.CdP x-14"}  # prov. La Pampa pero geolocalizado en Paraguay
def in_ar(la, lo): return LAT_MIN <= la <= LAT_MAX and LON_MIN <= lo <= LON_MAX
def fix_coords(row):
    if str(row["sigla"]).strip() in KNOWN_BAD:
        return pd.Series([None, None])
    la, lo = row["lat"], row["lon"]
    if in_ar(la, lo):  return pd.Series([la, lo])
    if in_ar(lo, la):  return pd.Series([lo, la])   # lat/lon invertidas
    return pd.Series([None, None])                   # irrecuperable -> descartar
n0 = len(coords)
orig = coords[["lat","lon"]].copy()
coords[["lat","lon"]] = coords.apply(fix_coords, axis=1)
n_swap = int(((coords["lat"] == orig["lon"]) & (coords["lon"] == orig["lat"]) & (orig["lat"] != orig["lon"])).sum())
coords = coords.dropna(subset=["lat","lon"])
print(f"  Saneadas: {n_swap} con lat/lon invertidas corregidas, {n0 - len(coords)} descartadas")

for yr in YEARS:
    print(f"Procesando {yr}...", end=" ", flush=True)
    df = pd.read_csv(f"data/produccion-{yr}.csv", usecols=USECOLS, encoding="utf-8-sig", low_memory=False)
    agg = df.groupby("idpozo").agg(
        pet=("prod_pet","sum"), gas=("prod_gas","sum"), agua=("prod_agua","sum"),
        emp=("empresa","first"), cu=("cuenca","first"), prov=("provincia","first"),
        tr=("tipo_de_recurso","first"), est=("tipoestado","first"), ma=("mes","count")
    ).reset_index()
    agg = agg[(agg.pet > 0) | (agg.gas > 0)]
    merged = agg.join(coords, on="idpozo", how="inner")
    rows = []
    for _, r in merged.iterrows():
        rows.append([
            float(r.lat), float(r.lon),
            int(r.pet), int(r.gas), int(r.agua),
            r.emp or "", r.cu or "", r.prov or "",
            r.tr or "", r.formacion or "", int(r.ma), r.est or "",
            (r.sigla or "").strip(), int(r.idpozo),
        ])
    path = f"data/pozos_{yr}.js"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"window.POZOS=")
        json.dump(rows, f, ensure_ascii=False, separators=(",",":"))
        f.write(";")
    print(f"{len(rows):,} pozos -> {path}")

print("Listo!")
