"""Tests mínimos del recorte del último mes completo (comun.ultimo_desde_conteo).
Uso (desde la raíz): .venv/Scripts/python tools/test_comun.py   -> sale con código 1 si algo falla.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comun import ultimo_desde_conteo  # noqa: E402


def serie(vals, inicio="2026-01"):
    return pd.Series(vals, index=pd.period_range(inicio, periods=len(vals), freq="M"))


def ultimo(vals):
    return str(ultimo_desde_conteo(serie(vals), verbose=False))


# (descripción, conteo de pozos por mes desde 2026-01, último mes completo esperado)
CASOS = [
    ("revisor: dos parciales chicos", [24000, 23900, 48, 45], "2026-02"),
    ("revisor: dos parciales grandes", [24000, 23900, 5000, 4800], "2026-02"),
    ("revisor: dos ceros al final", [24000, 23900, 0, 0], "2026-02"),
    ("tres parciales seguidos", [24000, 23900, 23800, 5000, 4800, 4700], "2026-03"),
    ("real 2026-11: octubre con 48", [23866, 23663, 23919, 23839, 24004, 23984, 23892, 23927, 23956, 48], "2026-09"),
    ("real publicado: mayo con 95,8 % de abril", [23866, 23663, 23919, 23839, 22843], "2026-05"),
    ("real publicado: mayo casi completo y junio en 0", [23866, 23663, 23919, 23839, 22843, 0], "2026-05"),
    ("todo completo, variación normal", [25611, 25559, 25543, 25553, 25618, 25352, 24858, 25293], "2026-08"),
    ("baja de 9 % (pasa el umbral)", [24000, 23900, 23800, 21900], "2026-04"),
    ("baja de 11 % (incompleto)", [24000, 23900, 23800, 21300], "2026-03"),
    ("un solo mes", [100], "2026-01"),
    ("cero adelante y datos después", [0, 100, 101, 99], "2026-04"),
    ("parcial al medio no importa (solo se recorta el final)", [24000, 5000, 23900, 23950], "2026-04"),
]

mal = 0
for nombre, vals, esperado in CASOS:
    r = ultimo(vals)
    ok = r == esperado
    mal += not ok
    print(f"{'✔' if ok else '✘'} {nombre}: {vals} -> {r}" + ("" if ok else f" (esperaba {esperado})"))

# sin ningún mes con producción: error claro, no un resultado silencioso
for vals in ([0, 0, 0], [0]):
    try:
        ultimo(vals)
        mal += 1
        print(f"✘ {vals}: esperaba SystemExit")
    except SystemExit as e:
        print(f"✔ sin producción {vals}: SystemExit ({e})")

print(f"\n{len(CASOS) + 2 - mal} ✔, {mal} ✘")
sys.exit(1 if mal else 0)
