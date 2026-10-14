"""
Genera datos temporales para la serie histórica 2022-2026:
  - data/serie_cuencas.json  → prod mensual por cuenca (para el gráfico del sidebar)
  - data/sparklines.json     → últimos 24 meses por pozo (para popup)
"""
import json
import pandas as pd

YEARS = [2022, 2023, 2024, 2025, 2026]
COLS  = ["idpozo", "anio", "mes", "prod_pet", "prod_gas", "cuenca", "provincia", "empresa"]

print("Cargando todos los años...")
frames = []
for yr in YEARS:
    path = f"data/produccion-{yr}.csv"
    print(f"  {yr}...", end=" ", flush=True)
    df = pd.read_csv(path, usecols=COLS, encoding="utf-8-sig", low_memory=False)
    frames.append(df)
    print(f"{len(df):,} filas")

prod = pd.concat(frames, ignore_index=True)
print(f"Total: {len(prod):,} filas")

# Columna periodo YYYY-MM para ordenar
prod["periodo"] = prod["anio"].astype(str) + "-" + prod["mes"].astype(str).str.zfill(2)

# ── Recortar meses sin datos reales (reporte incompleto) ───────────────────
# El último mes calendario suele venir vacío/parcial porque las empresas
# cargan el Cap. IV con atraso. Tomamos el último período con producción real.
tot_mes = prod.groupby("periodo")[["prod_pet", "prod_gas"]].sum().sum(axis=1)
periodos_validos = sorted(tot_mes[tot_mes > 0].index)
ult_valido = periodos_validos[-1]
desc = sorted(set(prod["periodo"]) - set(periodos_validos))
print(f"Último mes con datos: {ult_valido} | descartados (vacíos): {desc}")
prod = prod[prod["periodo"] <= ult_valido].copy()

# ── Serie mensual por cuenca ───────────────────────────────────────────────
print("Calculando serie por cuenca...")
serie = (
    prod.groupby(["cuenca", "periodo"])
    .agg(pet=("prod_pet", "sum"), gas=("prod_gas", "sum"))
    .reset_index()
    .sort_values(["cuenca", "periodo"])
)
serie["pet"] = serie["pet"].round(0).astype(int)
serie["gas"] = serie["gas"].round(0).astype(int)

# Pivotear a dict por cuenca para uso fácil en JS
cuencas_serie = {}
for cuenca, grp in serie.groupby("cuenca"):
    cuencas_serie[cuenca] = {
        "periodos": grp["periodo"].tolist(),
        "pet":      grp["pet"].tolist(),
        "gas":      grp["gas"].tolist(),
    }

with open("data/serie_cuencas.json", "w", encoding="utf-8") as f:
    json.dump(cuencas_serie, f, ensure_ascii=False, separators=(",", ":"))
print(f"  Guardado serie_cuencas.json ({len(cuencas_serie)} cuencas)")

# ── Serie mensual por empresa (top 15 por producción total) ────────────────
print("Calculando serie por empresa (top 15)...")
prod["empresa"] = prod["empresa"].fillna("(sin dato)")
top_emp = (prod.groupby("empresa")[["prod_pet", "prod_gas"]].sum().sum(axis=1)
           .sort_values(ascending=False).head(15).index.tolist())
todos_periodos = sorted(prod["periodo"].unique())
serie_e = (prod[prod["empresa"].isin(top_emp)]
           .groupby(["empresa", "periodo"])
           .agg(pet=("prod_pet", "sum"), gas=("prod_gas", "sum"))
           .reset_index())
empresas_serie = {}
for emp, grp in serie_e.groupby("empresa"):
    g = grp.set_index("periodo").reindex(todos_periodos).fillna(0)
    empresas_serie[emp] = {
        "periodos": todos_periodos,
        "pet":      g["pet"].round(0).astype(int).tolist(),
        "gas":      g["gas"].round(0).astype(int).tolist(),
    }
with open("data/serie_empresas.json", "w", encoding="utf-8") as f:
    json.dump(empresas_serie, f, ensure_ascii=False, separators=(",", ":"))
print(f"  Guardado serie_empresas.json ({len(empresas_serie)} empresas)")

# ── Sparklines por pozo: últimos 24 meses ────────────────────────────────
print("Calculando sparklines por pozo (últimos 24 meses)...")

# Obtener los últimos 24 periodos disponibles
all_periods = sorted(prod["periodo"].unique())
last_24 = all_periods[-24:]

recent = prod[prod["periodo"].isin(last_24)].copy()

sparklines = {}
# Agregar primero por pozo+periodo (un pozo puede tener múltiples formaciones).
# Clave idpozo: la sigla no es única en el padrón.
recent_agg = (
    recent.groupby(["idpozo", "periodo"])
    .agg(prod_pet=("prod_pet", "sum"), prod_gas=("prod_gas", "sum"))
    .reset_index()
)
for idpozo, grp in recent_agg.groupby("idpozo"):
    grp_s = grp.set_index("periodo").reindex(last_24)
    pet_vals = grp_s["prod_pet"].fillna(0).round(0).astype(int).tolist()
    gas_vals = grp_s["prod_gas"].fillna(0).round(0).astype(int).tolist()
    if max(pet_vals) > 0 or max(gas_vals) > 0:
        sparklines[int(idpozo)] = {"p": pet_vals, "g": gas_vals}

with open("data/sparklines.json", "w", encoding="utf-8") as f:
    json.dump({"periodos": last_24, "pozos": sparklines}, f,
              ensure_ascii=False, separators=(",", ":"))
print(f"  Guardado sparklines.json ({len(sparklines):,} pozos, {len(last_24)} meses)")

# ── Nacional mensual (para el header) ────────────────────────────────────
print("Calculando total nacional...")
nacional = (
    prod.groupby("periodo")
    .agg(pet=("prod_pet", "sum"), gas=("prod_gas", "sum"))
    .reset_index()
    .sort_values("periodo")
)
nacional["pet"] = nacional["pet"].round(0).astype(int)
nacional["gas"] = nacional["gas"].round(0).astype(int)
nacional_dict = {
    "periodos": nacional["periodo"].tolist(),
    "pet":      nacional["pet"].tolist(),
    "gas":      nacional["gas"].tolist(),
}
with open("data/serie_nacional.json", "w", encoding="utf-8") as f:
    json.dump(nacional_dict, f, ensure_ascii=False, separators=(",", ":"))
print(f"  Guardado serie_nacional.json ({len(nacional)} periodos)")

print("\nListo!")
