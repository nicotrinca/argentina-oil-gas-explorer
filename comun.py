"""
Funciones compartidas por los preprocess_*.py.

Último mes completo
-------------------
El Cap. IV llega con atraso: las empresas cargan la declaración jurada del mes durante las semanas
siguientes, así que el o los últimos meses del archivo están incompletos. Ejemplo real (2026-11-12):
el CSV de 2026 traía septiembre con 23.956 pozos con producción y octubre con 48 (165 filas).
Recortar "al último mes con producción > 0" dejaba octubre y dibujaba una caída falsa.

Regla (`ultimo_mes_completo`): se cuentan, por mes, los pozos (idpozo) con petróleo > 0 o gas > 0.
Desde el final hacia atrás se descarta cada mes con menos del UMBRAL_MES_COMPLETO (90 %) del MÁXIMO de
los VENTANA_REF (3) meses anteriores a él. El primer mes que pasa es el último completo.
Se compara contra el máximo de 3 meses y no solo contra el anterior porque puede haber varios meses
parciales seguidos ([24000, 23900, 5000, 4800]: 4800 es 96 % de 5000 y pasaría) o ceros ([.., 0, 0]).
Por qué 90 %: entre meses completos el nº de pozos con producción baja poco (2022-2026, total país: el
peor mes quedó en 97,0 % del máximo de los 3 anteriores, jul-2024; solo no convencional desde 2015:
91,0 %, ene-2019, cerca del umbral: por eso curvas usa además el corte del total país), y un mes que pasa el 90 % ya trae casi toda su producción (may-2026, publicado con
22.843 pozos = 95,8 % de abril, tenía el 98,8 % del petróleo que se informó después). Un umbral más
alto recortaría meses útiles; uno más bajo dejaría pasar meses a medio cargar.
Limitación: si un día cae de verdad > 10 % de los pozos (p. ej. una empresa grande deja de producir),
la serie se frena hasta 3 meses, hasta que la ventana quede toda después de la caída.
Consecuencia: el último mes publicado puede crecer algunos % al mes siguiente (en pozos más que en
volumen); tools/actualizar.py lo tolera aparte (TOL_ULTIMO_PUBLICADO).

Caché: `ultimo_mes_produccion()` cuenta pozos por mes en TODOS los data/produccion-<AÑO>.csv y guarda
el resultado en data/_meses.json (se recalcula si cambia el tamaño o la fecha de algún CSV). Así
peryear, temporal y fractura usan exactamente el mismo corte sin releer 1,5 GB cada uno.
"""
import glob
import json
import os
import re

import pandas as pd

ANIO_INICIAL = 2022            # primer año que muestra el visor
UMBRAL_MES_COMPLETO = 0.90     # mes final con < 90 % del máximo de los 3 meses previos = incompleto
VENTANA_REF = 3                # meses previos contra los que se compara cada candidato
CACHE_MESES = "data/_meses.json"


def anios_produccion():
    """Años con data/produccion-<AÑO>.csv (desde ANIO_INICIAL). Un año nuevo entra solo."""
    anios = []
    for p in glob.glob("data/produccion-*.csv"):
        m = re.fullmatch(r"produccion-(\d{4})\.csv", os.path.basename(p))
        if m and int(m.group(1)) >= ANIO_INICIAL:
            anios.append(int(m.group(1)))
    if not anios:
        raise SystemExit("No hay data/produccion-<AÑO>.csv (ver README, 'How to run', o tools/actualizar.py)")
    return sorted(anios)


def pozos_por_mes(df):
    """Serie (Period mensual -> nº de idpozo con petróleo > 0 o gas > 0). Meses sin pozos = 0.
    df: columnas idpozo, prod_pet, prod_gas y 'periodo' (Period M) o anio + mes."""
    per = df["periodo"] if "periodo" in df else pd.PeriodIndex.from_fields(year=df["anio"], month=df["mes"], freq="M")
    per = pd.PeriodIndex(per, freq="M")
    act = (df["prod_pet"].fillna(0) > 0) | (df["prod_gas"].fillna(0) > 0)
    n = pd.Series(df["idpozo"].values[act.values], index=per[act.values]).groupby(level=0).nunique()
    todos = pd.period_range(per.min(), per.max(), freq="M")
    return n.reindex(todos, fill_value=0).astype(int)


def ultimo_desde_conteo(conteo, umbral=UMBRAL_MES_COMPLETO, nombre="", verbose=True):
    """conteo: Serie Period -> nº de pozos con producción (ordenable). Devuelve el último Period completo:
    desde el final se descarta cada mes con < umbral × máx(VENTANA_REF meses previos)."""
    conteo = conteo.sort_index()
    vals = conteo.tolist()
    if not vals:
        raise SystemExit(f"ultimo_mes_completo{f' ({nombre})' if nombre else ''}: serie vacía")
    i = len(vals) - 1
    while i > 0 and vals[i] < umbral * max(vals[max(0, i - VENTANA_REF):i]):
        i -= 1
    if vals[i] == 0:
        raise SystemExit(f"ultimo_mes_completo{f' ({nombre})' if nombre else ''}: no hay meses con producción")
    ult = conteo.index[i]
    if verbose:
        desc = [f"{p} ({v:,} pozos)" for p, v in zip(conteo.index[i + 1:], vals[i + 1:])]
        print(f"  Último mes completo{f' ({nombre})' if nombre else ''}: {ult} ({vals[i]:,} pozos con producción)"
              + (f" | descartados por incompletos: {', '.join(desc)}" if desc else ""))
    return ult


def ultimo_mes_completo(df, umbral=UMBRAL_MES_COMPLETO, nombre="", verbose=True):
    """Último mes completo (pd.Period): regla de ultimo_desde_conteo sobre los pozos con producción por mes. df: idpozo, prod_pet, prod_gas y periodo (o anio + mes)."""
    return ultimo_desde_conteo(pozos_por_mes(df), umbral, nombre, verbose)


def _firma(paths):
    return {os.path.basename(p): [os.path.getsize(p), int(os.path.getmtime(p))] for p in paths}


def conteo_produccion():
    """Pozos con producción por mes en todos los data/produccion-<AÑO>.csv, con caché en data/_meses.json.
    Devuelve (Serie Period -> nº pozos, dict 'YYYY-MM' -> {pet, gas, pozos})."""
    paths = [f"data/produccion-{a}.csv" for a in anios_produccion()]
    firma = _firma(paths)
    if os.path.exists(CACHE_MESES):
        try:
            c = json.load(open(CACHE_MESES, encoding="utf-8"))
            if c.get("firma") == firma:
                meses = c["meses"]
                s = pd.Series({pd.Period(k, freq="M"): v["pozos"] for k, v in meses.items()})
                return s.sort_index(), meses
        except (ValueError, KeyError):
            pass
    print("  Contando pozos con producción por mes (se guarda en data/_meses.json)...")
    partes, tot = [], []
    for p in paths:
        d = pd.read_csv(p, usecols=["idpozo", "anio", "mes", "prod_pet", "prod_gas"], encoding="utf-8-sig",
                        low_memory=False)
        d["periodo"] = pd.PeriodIndex.from_fields(year=d["anio"], month=d["mes"], freq="M")
        partes.append(pozos_por_mes(d))
        tot.append(d.groupby("periodo")[["prod_pet", "prod_gas"]].sum())
    s = pd.concat(partes).groupby(level=0).sum().sort_index()
    s = s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M"), fill_value=0)
    t = pd.concat(tot).groupby(level=0).sum()
    meses = {str(k): {"pozos": int(v), "pet": round(float(t.loc[k, "prod_pet"]) if k in t.index else 0.0),
                      "gas": round(float(t.loc[k, "prod_gas"]) if k in t.index else 0.0)} for k, v in s.items()}
    json.dump({"firma": firma, "umbral": UMBRAL_MES_COMPLETO, "meses": meses},
              open(CACHE_MESES, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return s, meses


def ultimo_mes_produccion(verbose=True):
    """Último mes completo del conjunto data/produccion-<AÑO>.csv (pd.Period), con la regla de arriba."""
    s, _ = conteo_produccion()
    return ultimo_desde_conteo(s, nombre="producción por año", verbose=verbose)
