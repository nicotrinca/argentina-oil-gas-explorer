"""
Genera data/ranking.json:
  top_crecimiento: pozos con mayor suba de prod_pet 2024→2025
  top_caida:       pozos con mayor baja de prod_pet 2024→2025
  top_productores: pozos con mayor prod_pet acumulada 2025
Incluye coords y metadata para mostrar en la tabla.
"""
import json
import pandas as pd

COLS = ["sigla", "anio", "mes", "prod_pet", "prod_gas", "empresa", "cuenca", "provincia", "tipo_de_recurso"]

print("Cargando 2024 y 2025...")
df24 = pd.read_csv("data/produccion-2024.csv", usecols=COLS, encoding="utf-8-sig", low_memory=False)
df25 = pd.read_csv("data/produccion-2025.csv", usecols=COLS, encoding="utf-8-sig", low_memory=False)

# Agregar por pozo y año
def agg_year(df):
    return df.groupby("sigla").agg(
        pet=("prod_pet", "sum"),
        gas=("prod_gas", "sum"),
        empresa=("empresa", "first"),
        cuenca=("cuenca", "first"),
        provincia=("provincia", "first"),
        tipo=("tipo_de_recurso", "first"),
        meses=("mes", "count"),
    ).reset_index()

agg24 = agg_year(df24).rename(columns={"pet":"pet24","gas":"gas24","meses":"m24"})
agg25 = agg_year(df25).rename(columns={"pet":"pet25","gas":"gas25","meses":"m25"})

# Join
m = agg24.merge(agg25[["sigla","pet25","gas25","m25"]], on="sigla", how="inner")
m = m[(m.pet24 > 500) & (m.pet25 > 500)]  # filtrar pozos con producción relevante

m["delta_abs"] = m.pet25 - m.pet24
m["delta_pct"] = ((m.pet25 - m.pet24) / m.pet24 * 100).round(1)

# Normalizar por mes para que los que tienen menos meses en 2025 no queden penalizados
m["pet24_m"] = (m.pet24 / m.m24).round(0).astype(int)
m["pet25_m"] = (m.pet25 / m.m25).round(0).astype(int)
m["delta_pct_norm"] = ((m.pet25_m - m.pet24_m) / m.pet24_m * 100).round(1)

def to_records(df, n=20):
    return df.head(n)[["sigla","empresa","cuenca","provincia","tipo",
                         "pet24","pet25","delta_abs","delta_pct_norm"]].rename(
        columns={"delta_pct_norm":"dpct"}).assign(
        pet24=lambda x: x.pet24.round(0).astype(int),
        pet25=lambda x: x.pet25.round(0).astype(int),
        delta_abs=lambda x: x.delta_abs.round(0).astype(int),
    ).to_dict(orient="records")

top_crec  = to_records(m.sort_values("delta_pct_norm", ascending=False))
top_caida = to_records(m.sort_values("delta_pct_norm", ascending=True))
top_prod  = to_records(m.sort_values("pet25", ascending=False))

out = {"top_crecimiento": top_crec, "top_caida": top_caida, "top_productores": top_prod}
with open("data/ranking.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

print(f"Guardado ranking.json")
print(f"  Top crecimiento: {top_crec[0]['sigla']} +{top_crec[0]['dpct']}%")
print(f"  Top caída:       {top_caida[0]['sigla']} {top_caida[0]['dpct']}%")
print(f"  Top productor:   {top_prod[0]['sigla']} {top_prod[0]['pet25']:,} m³")
