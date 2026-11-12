"""
Datos de fractura (Adjunto IV) unidos con la producción mensual por sigla.

No es un cruce espacial: es un merge de pandas por la clave 'idpozo' (la sigla
no es única en el padrón, idpozo sí).
Para cada pozo fracturado calcula la producción de los 12 meses siguientes al
fin de la fractura, y con eso la productividad por etapa, por tn de arena y por
km de rama horizontal (comparación de diseños y operadores en Vaca Muerta).

Entrada:
  data/geo/fractura.csv            (Adjunto IV, ver README)
  data/produccion-<AÑO>.csv        (2022-2026)
Salida:
  data/fractura.json   pozos {sigla: [...]}, resumen por empresa (VM) y
                       evolución del diseño de fractura por año (VM)
"""
import json

import pandas as pd

from comun import anios_produccion, ultimo_mes_produccion

YEARS = anios_produccion()
MIN_POZOS_EMPRESA = 15
# Equivalencia energética 6:1 (6 Mcf de gas = 1 bbl): 1 m³ de petróleo = 1.069 m³ de gas.
# La producción de gas viene en Mm³ (miles de m³) -> m³ equivalentes de petróleo:
GAS_A_PET = 1000 / 1069
# Misma empresa con razón social nueva
EMPRESA_ALIAS = {"VISTA OIL & GAS ARGENTINA SAU": "VISTA ENERGY ARGENTINA SAU"}

# ── Fractura: una fila por campaña -> una fila por pozo ─────────────────────
print("Cargando fracturas (Adjunto IV)...")
f = pd.read_csv("data/geo/fractura.csv", encoding="utf-8-sig", low_memory=False)
f["empresa_informante"] = f["empresa_informante"].replace(EMPRESA_ALIAS)
f["arena"] = f["arena_bombeada_nacional_tn"].fillna(0) + f["arena_bombeada_importada_tn"].fillna(0)
f["fin"] = pd.to_datetime(f["fecha_fin_fractura"], errors="coerce").dt.to_period("M")
f = f.sort_values("arena")              # la campaña principal (más arena) queda última
g = f.groupby("idpozo")
fr = pd.DataFrame({
    "sigla":  g["sigla"].last(),
    "etapas": g["cantidad_fracturas"].sum(),
    "arena":  g["arena"].sum(),
    "agua":   g["agua_inyectada_m3"].sum(),
    "rama":   g["longitud_rama_horizontal_m"].max(),
    "fin":    g["fin"].max(),
    "form":   g["formacion_productiva"].last().str.strip().str.lower(),
    "tipo":   g["tipo_reservorio"].last(),
    "empresa": g["empresa_informante"].last(),
    "cuenca": g["cuenca"].last(),
})
print(f"  {len(f):,} campañas -> {len(fr):,} pozos fracturados")

# ── Producción mensual de esos pozos ────────────────────────────────────────
print(f"Cargando producción mensual {YEARS[0]}-{YEARS[-1]} (solo pozos fracturados)...")
prod = pd.concat(
    pd.read_csv(f"data/produccion-{yr}.csv", usecols=["idpozo", "anio", "mes", "prod_pet", "prod_gas"],
                encoding="utf-8-sig", low_memory=False).query("idpozo in @fr.index")
    for yr in YEARS
)
prod["periodo"] = pd.PeriodIndex.from_fields(year=prod["anio"], month=prod["mes"], freq="M")
prod = prod.groupby(["idpozo", "periodo"])[["prod_pet", "prod_gas"]].sum().reset_index()
# último mes completo de TODA la producción (regla compartida de comun.py: meses finales con < 90 %
# de los pozos del mes anterior = incompletos). Se calcula sobre todos los pozos, no solo los fracturados.
ultimo = ultimo_mes_produccion()
primero = prod["periodo"].min()
print(f"  producción {primero} .. {ultimo}")

# ── Producción de los 12 meses posteriores a la fractura ────────────────────
# merge pozo-fractura con su producción, y quedarse con los meses fin+1 .. fin+12
m = prod.merge(fr[["fin"]], left_on="idpozo", right_index=True)
m = m[m["fin"].notna()]
k = (m["periodo"] - m["fin"]).apply(lambda d: d.n)
m = m[(k >= 1) & (k <= 12)]
p12 = m.groupby("idpozo")[["prod_pet", "prod_gas"]].sum()
# solo vale si la ventana de 12 meses entra entera en los datos
ok = fr["fin"].notna() & (fr["fin"] >= primero - 1) & (fr["fin"] + 12 <= ultimo)
fr["pet12"] = p12["prod_pet"].where(ok)
fr["gas12"] = p12["prod_gas"].where(ok)
fr.loc[ok & fr["pet12"].isna(), ["pet12", "gas12"]] = 0
fr["eq12"] = fr["pet12"] + fr["gas12"] * GAS_A_PET
print(f"  {fr.pet12.notna().sum():,} pozos con ventana completa de 12 meses")

# ── Vaca Muerta horizontal: por empresa y evolución por año ─────────────────
vm = fr[(fr["form"] == "vaca muerta") & (fr["rama"] > 0)].copy()
vm["eq12_km"] = vm["eq12"] / (vm["rama"] / 1000)
vm["arena_etapa"] = vm["arena"] / vm["etapas"].where(vm["etapas"] > 0)
vm["anio"] = vm["fin"].dt.year

emp = []
for e, d in vm[vm.pet12.notna()].groupby("empresa"):
    if len(d) < MIN_POZOS_EMPRESA:
        continue
    emp.append({"empresa": e, "n": len(d),
                "rama": round(d.rama.median()), "etapas": round(d.etapas.median()),
                "arena_etapa": round(d.arena_etapa.median()),
                "pet12": round(d.pet12.median()), "gas12": round(d.gas12.median()),
                "eq12": round(d.eq12.median()), "eq12_km": round(d.eq12_km.median()),
                "pct_gas": round(100 * (d.gas12 * GAS_A_PET).sum() / max(d.eq12.sum(), 1))})
emp.sort(key=lambda r: -r["eq12_km"])

evo = []
for a, d in vm.groupby("anio"):
    if len(d) < 10:
        continue
    q = d[d.pet12.notna()]
    evo.append({"anio": int(a), "n": len(d), "rama": round(d.rama.median()),
                "etapas": round(d.etapas.median()), "arena": round(d.arena.median()),
                "agua": round(d.agua.median()),
                "eq12": round(q.eq12.median()) if len(q) >= 10 else None,
                "eq12_km": round(q.eq12_km.median()) if len(q) >= 10 else None})
print(f"  Vaca Muerta horizontal: {len(vm):,} pozos, {len(emp)} empresas con >= {MIN_POZOS_EMPRESA} pozos")

# ── Salida ──────────────────────────────────────────────────────────────────
def num(v, nd=0):
    return None if pd.isna(v) else (round(float(v), nd) if nd else int(round(v)))

out = {
    "periodo_prod": [str(primero), str(ultimo)],
    "cols": ["etapas", "arena_tn", "agua_m3", "rama_m", "fin", "pet12_m3", "gas12_mm3", "formacion"],
    "gas_a_pet": GAS_A_PET,
    "pozos": {int(i): [num(r.etapas), num(r.arena), num(r.agua), num(r.rama),
                  None if pd.isna(r.fin) else str(r.fin), num(r.pet12), num(r.gas12), r.form]
              for i, r in fr.iterrows()},
    "empresas_vm": emp,
    "evolucion_vm": evo,
}
json.dump(out, open("data/fractura.json", "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))
print(f"  -> data/fractura.json")
print("\nVaca Muerta: diseño mediano por año de fractura")
for r in evo:
    print(f"  {r['anio']}  n={r['n']:4}  rama={r['rama']:5} m  etapas={r['etapas']:3}  "
          f"arena={r['arena']:6} tn  eq12={r['eq12']}  eq12/km={r['eq12_km']}")
