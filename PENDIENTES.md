# Ideas pendientes (propuestas 2026-11-10)

1. ~~**Curvas tipo + EUR (Vaca Muerta)**~~ — HECHO 2026-11-11 (pestaña Curvas + Declinación en el popup).
   Posibles mejoras: letra 12 px que queda en Geo (`.geo-note`, `.band-row .pct`, `.qa-row .d`, ticks de fractura);
   ~150 pozos ok cuyo pronóstico arranca > 2× el último mes (meses parciales al final); curvas tipo de otras
   formaciones NC; ajuste combinado petróleo+gas en m³eq.
1b. ~~**Zonas productivas VM + interferencia padre/hijo**~~ — HECHO 2026-11-12 (capa de hexágonos, tabla por
   concesión e interferencia en Curvas, línea en el popup). Resultado: petróleo hijo/padre ≈ 1,0 (55 hex), gas ≈ 0,90.
   Detalles: verdes de gas apagados poco distinguibles; ticks de los minigráficos del popup ~11 px;
   falta probar en celular (el panel tapa el mapa a 400 px, problema general).
2. ~~**Publicarlo online**~~ — HECHO 2026-11-11: https://pozos-argentina.web.app (Firebase Hosting).
   Detalles menores: en celular (400 px) el control de capas del mapa asoma recortado a la derecha;
   falta `favicon.ico` (404 en consola).
3. **Actualización mensual automática**: tarea programada que baje el Cap. IV, corra los preprocess y republique.
4. **Pozos que entran y salen de producción**: conexiones nuevas, cierres y reactivaciones por mes, operador y área.
5. **Ficha por área de concesión**: serie temporal, mezcla petróleo/gas, top pozos, GOR y corte de agua en el tiempo.
   Incluye arreglar las concesiones superpuestas (LOMA LA LATA - SIERRA BARROSA / LA ANGOSTURA SUR I, mismos 57 pozos).
6. **Detección de anomalías**: caídas bruscas, saltos de corte de agua, GOR disparado (suma al QA de la pestaña Geo).
