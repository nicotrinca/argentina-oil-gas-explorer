# HANDOFF — Pozos Petroleros Argentina

Fuente de verdad del proyecto para quien lo retome (personas o agentes). El README es la cara pública
en inglés; este archivo tiene las reglas, trampas e historial. Ideas a futuro: `PENDIENTES.md`.

## Qué es
Visor web de pozos y producción de hidrocarburos de Argentina (Capítulo IV, Sec. Energía), 2022–2026.
Python (pandas/geopandas) preprocesa los CSV/shapefiles oficiales a archivos livianos en `data/`;
`index.html` (un solo archivo, JS vanilla + Leaflet + markercluster + Chart.js, sin build) los muestra.
GitHub: nicotrinca/argentina-oil-gas-explorer. Todo `data/` está en `.gitignore` (se regenera).
Publicado en **https://pozos-argentina.web.app** (Firebase Hosting, proyecto `pozos-argentina`, plan gratis).

## Cómo publicar
- `firebase deploy --only hosting` desde la raíz (solo con OK del usuario y `tools/check.mjs` en verde).
  El `predeploy` corre `node tools/build_public.mjs`, que arma `public/` (ignorado por git) con `index.html` +
  una **whitelist** de `data/` (~31 MB; los `pozos_<año>.js` salen de los `<option>` de `#f-year`). Si agregás
  un archivo de datos que el visor pide, sumalo a la whitelist (el script avisa si ve uno sin listar).
- Headers: `index.html` no-cache; `data/**` max-age 1 h (tras un deploy, datos viejos pueden durar hasta 1 h).
- Probar el sitio publicado: `POZOS_URL=https://pozos-argentina.web.app/ node tools/check.mjs`
  (contra la red puede fallar algún chequeo por tiempos; repetir antes de alarmarse).

## Cómo correrlo
- `abrir.bat` (doble clic) levanta `python -m http.server 8765 --bind 127.0.0.1` (solo esta PC) y abre http://localhost:8765.
- Desde Claude Code: `preview_start {name: "pozos-petroleros"}` (puerto 8765).
- **Nunca** con doble clic en `index.html` (`file://`): el navegador bloquea los `fetch` → sin capas,
  gráficos ni evolución del pozo (los pozos sí aparecen porque cargan por `<script>`). La página muestra
  un aviso rojo en ese caso.
- Entorno Python: `.venv` del proyecto (`.venv/Scripts/python`). Sin scipy: los ajustes se hacen con numpy.

## Cómo probar
- `node tools/check.mjs` — prueba de humo en Chrome headless (servidor en :8765). Pozos, coordenadas,
  totales, idpozo único, capas (áreas + 5 capas geo lazy), popup con gráfico, 300 popups sin NaN,
  pestañas, gráficos, cambio de año, pedidos fallidos y errores de consola. Sale con código 1 si algo falla.
  Si agregás una pestaña o capa, sumale un chequeo.
- `node tools/shot.mjs <salida.png> [pestaña] [ancho] ["js previo"]` — captura (tarda ~2 min, usá timeout
  largo). Guardar en `capturas/qa/<tema>/` (ignorado por git).
- El screenshot del panel de vista previa de Claude se cuelga con el canvas de Leaflet (29k markers):
  usar `tools/shot.mjs` o evaluar JS en la página.
- En vistas sin tamaño (`#map` 0×0) `flyTo` puede tirar NaN; `flyToPozo` tiene try/catch + setView.

## Datos (pipeline)
Orden de los scripts (cada uno lee `data/` crudo y escribe `data/` procesado):
1. `preprocess_peryear.py` → `data/pozos_<AÑO>.js` (array compacto por pozo; índices en `const I` del HTML).
   Corrige lat/lon invertidas (swap si cae en el bbox de Argentina) y descarta irrecuperables (`KNOWN_BAD`).
2. `preprocess.py`, `preprocess_ranking.py`, `preprocess_temporal.py` (series nacional/cuencas/empresas,
   `sparklines.json` últimos 24 meses). Recorta al último mes completo (regla del 90 % en `comun.py`,
   ver "Actualización mensual"; Cap. IV llega con atraso).
3. `preprocess_areas.py` → `areas.geojson` (concesiones nacionales; dbf con encoding MIXTO cp1252+UTF-8,
   se lee dos veces y se elige por valor + ftfy).
4. `preprocess_geo.py` (después de areas) → cuencas/yacimientos/permisos/gasoductos/refinerías + `pozos_geo.json`
   + `geo_qa.json`. Distancias en LAEA lat0=-38 lon0=-65.
5. `preprocess_fractura.py` → `fractura.json` (Adjunto IV × producción, 12 meses post-fractura).
6. `preprocess_curvas.py` → `curvas.json` (0,2 MB) + `curvas_pozos.json` (3 MB). Lee `produccion-no-convencional.csv`
   y `geo/fractura.csv`. ~45 s. Esquema completo en el docstring del script. Resumen del método:
   - Arps hiperbólico modificado por pozo NC (grilla b 0,05–1,5 × Di, numpy), pico en los primeros 12 meses,
     Dmin 8 %/año, 30 años, límite 1 m³/d o 1 Mm³/d. EUR = acumulada real + pronóstico (nunca < acumulada).
   - Meses < 1 m³ (o Mm³) = residuales → 0 para ajuste, motivos y arranque.
   - Sin pronóstico (EUR = acumulada) según motivo `qp`/`qg`: poco_vol, parado (12 meses en 0),
     parado_reciente (3 meses en 0), corto, dmin (Di < Dmin: mesetas por choke), r2 (< 0,3), empalme.
   - Medianas de EUR con ok + parado + parado_reciente (`mediana_motivos`); cohortes con < 10 pozos → null.
   - Pozo joven (< 24 meses desde el pico): b ≤ 1,2, marca jp/jg.
   - Empalme: primer mes de pronóstico vs mediana de los últimos 3 meses con producción; [0,5;2] no se toca,
     [0,2;5] reescala qi (hacia arriba con tope en el último mes real), fuera → motivo "empalme".
     fp/fg = [qi_pron, Di, b, pico, r2, qi_ajuste]: la UI dibuja la historia con qi_ajuste y el pronóstico con qi_pron.
   - Avisos (no filtros): escp/escg (reescalado), reap/reag (reactivado), rq (rama de 1000 m justos).
   - Ramas < 300 m → sin rama. Curvas tipo: corte cuando quedan < 50 % de los pozos, resto en `cola` (punteado);
     acumulada tipo = cumsum de los percentiles mensuales. Ranking de operadores: cohorte ≥ 2018, rama ≥ 1 km,
     ≥ 15 pozos, historia mediana ≥ 12 meses (los demás en `empresas_fuera`).
   - Valores de referencia (VM, 2026-11): EUR mediana petróleo 2019–2024 ≈ 112–138 mil m³ (≈ 0,8 MMbbl),
     45–63 mil m³/km; gas 2021–2024 ≈ 370–420 MMm³, 137–163 MMm³/km.
7. `preprocess_zonas.py` (después de curvas; lee curvas_pozos.json/curvas.json + coordenada/concesión del CSV NC, ~10 s)
   → `zonas.json` (GeoJSON de hexágonos de 3 km entre lados planos + tabla `concesiones`, 0,13 MB) e
   `interferencia.json` (padre/hijo por pozo en `pozos` + estadísticas, 0,08 MB). Esquema en el docstring.
   Solo hay coordenada de SUPERFICIE: todo es zonal (la rama de 2–3 km puede estar en otro hexágono).
   Cifra principal: ratio hijo/padre de acum. 12 meses/km dentro de cada hexágono con ≥ 3 padres y ≥ 3 hijos
   (2026-11: petróleo ≈ 1,02 en 55 hexágonos; gas ≈ 0,90 en 18).

8. `preprocess_fichas.py "<ruta.xlsx>"` (o env `FICHAS_XLSX`; necesita `openpyxl` en el .venv) → `data/privado/fichas.json`.
   **MODO PRIVADO, SOLO LOCAL**: fichas técnicas de yacimiento confidenciales (planilla local). En git solo va el parser
   genérico; la descripción de la grilla está en `data/privado/plantilla_fichas.json` (local, formato en el docstring;
   sin ese archivo el script no corre). Nunca a git ni a Firebase: `data/privado/` y `*.xlsx` en `.gitignore`, `**/privado/**`
   en el `ignore` de `firebase.json`, y `build_public.mjs` falla (y borra `public/`) si ve una ruta "privado" o un texto
   de las fichas en `public/` (`tools/privado.mjs`). No escribir valores de las fichas en código ni comentarios: la guarda
   los detecta. El visor lo pide solo desde localhost (`modoPrivadoPermitido`); si no está, no muestra nada. Con el
   archivo: insignia "Privado" en el encabezado, botón "Ficha de yacimiento" en el popup del pozo (`por_pozo`, por
   idpozo que declaró ese `areayacimiento`) y en la capa Yacimientos (`por_yacimiento`, nombre normalizado), modal
   `abrirFicha(id)` con la fecha de actualización destacada. No está en `tools/actualizar.py` (se corre a mano).
   El servidor local escucha solo en 127.0.0.1 (`abrir.bat`, `.claude/launch.json`): data/privado no queda en la LAN.
9. `preprocess_base_comercial.py "<ruta.shp>" [config]` (o env `BASE_COMERCIAL_SHP` / `BASE_COMERCIAL_CONFIG`; después de
   peryear, lee `pozos_<AÑO>.js` y `capitulo-iv-pozos.csv`, ~20 s) → `data/privado/base_comercial.json` (~6,3 MB).
   **MODO PRIVADO, SOLO LOCAL**: base comercial de pozos LICENCIADA (shapefile de puntos con fechas de perforación,
   TD/PTD, cota, clasificación, trayectoria, estado, objetivo, ensayos). Mismas guardas que las fichas. En código, tests
   y docs: nunca el nombre del proveedor, la ruta del shapefile, nombres de columnas, el vocabulario de la base ni nombres
   de pozos; decir "base comercial". Esquema en el docstring.
   - El esquema del proveedor vive en `data/privado/config_base_comercial.json` (local, como `plantilla_fichas.json`;
     formato en el docstring; sin ese archivo el script no corre): columnas → claves genéricas, escala de precisión de
     fechas → códigos (exacta, semana, mes, trimestre, semestre, año, estimada) y traducciones (exactas, regex, y por
     tokens para listas de litología). El json sale YA traducido: `index.html` no tiene ningún término de la base.
   - Cruce por idpozo (cada pozo del visor con ≤ 1 registro): nombre (sigla normalizada = nombre alternativo u oficial)
     a ≤ 1 km → nombre sin el sufijo final entre paréntesis (vetado si la sigla dice (h)/(d) y la base dice vertical sin
     sufijo, salvo profundidad del Cap. IV ±5 % de la TD) → id alternativo de la base = idpozo → proximidad. Un registro
     solo se comparte entre idpozo en el mismo lugar (≤ 50 m: mismo pozo físico con varios idpozo en el Cap. IV).
   - La base tiene corrimientos de datum sistemáticos (Golfo San Jorge ≈ 440 m al este; Neuquina ≈ 150 m): por eso
     1 km para nombre. La proximidad corrige el corrimiento local (mediana de los vecinos cruzados a ≤ 5 km), busca a
     ≤ 150 m y EXIGE TD (no PTD) a ±5 % de la profundidad del Cap. IV y spud compatible con el inicio de perforación
     (±90 días exacta/semana/mes, ±1 año trimestre/semestre/año, ±2 años estimada); sin profundidad, único candidato a
     ≤ 50 m. Sin esas condiciones, ~55 % de los cruces por proximidad eran el vecino. En la UI: "cruce por proximidad
     (verificar)", nunca "confirmado".
   - Los pozos que empezaron a perforarse después del corte de la base (fecha del Cap. IV) no se cruzan.
   - Cobertura 2026-11: 82,8 % de los 32.417 pozos del visor (26.857); 96,3 % de los perforados antes del corte (casi
     todos los sin match son posteriores). El script imprime la tabla por cuenca y método (sin nombres de pozos).
   - Visor (`baseCom`, `cargarBaseComercial`): línea "Spud … · TD … m" en el popup (`baseComPopupHTML`, caja `.bc-pop`
     con el estilo de la ficha), modal `abrirBaseCom(id)` (subtítulo "Cruce por nombre · 5 m") y, en la ficha de
     yacimiento abierta desde el popup (`abrirFicha(fid, idpozo)`), chip "Base comercial del pozo ↓" arriba y sección al
     final. Fechas según precisión (estimadas como "≈ aaaa (estimada)"). Aviso si las coordenadas difieren > 150 m o si
     el cruce fue por proximidad. En celular (≤ 760 px) las grillas del modal se apilan.
   - `tools/privado.mjs` (`valoresBaseComercial`, `paresBaseComercial`) detecta en public/: el archivo, nombres oficiales
     (literal), ids propios, textos libres ≥ 20 caracteres como substring (por tokens, no includes por valor) y PARES
     idpozo ↔ TD/spud de la base (`huellas`: muestra de 2000 pozos con TD/spud distintos de los del Cap. IV; fuga si
     ≥ 20 pares y ≥ 20 % de los idpozo de la muestra presentes en el archivo). Suma ~2 s al build.
   - `tools/check.mjs` toma un pozo con dato del json en tiempo de ejecución ("base comercial ok"). Probar también SIN
     `data/privado/` (renombrar la carpeta, correr check.mjs, restaurarla): todo debe dar verde.

## Actualización mensual
- `tools/actualizar.py` (docstring = manual completo): consulta CKAN, baja lo que cambió (registro en
  `data/_fuentes.json`: id, last_modified, tamaño, sha256), descomprime/renombra, corre los 9 preprocess en el
  orden de arriba, controla y escribe `data/_informe.md`. Sin `--publicar` no publica. `--solo-bajar`,
  `--sin-bajar`, `--aceptar-cambios` (cambios > ±3 % en meses publicados pasan como aviso), `--referencia`,
  `--sin-referencia`. Códigos: 1 control (o sin referencia), 2 catálogo/descarga, 3 preprocess, 4 deploy.
- Referencia = el sitio publicado. Si no responde: `data/_previo/` (copia de la última corrida que PASÓ todos los
  controles; se escribe al final, con marca `_ok.json`). Sin ninguna de las dos → falla y no publica, salvo
  `--sin-referencia` explícito.
- Elección de recursos POR NOMBRE (regex sobre el nombre sin tildes), nunca por id: producción = "Producción de
  Pozos de Gas y Petróleo – <AÑO>" / "- <AÑO>" sin "DDJJ" ni "No Convencional", años ≥ 2022 (un año nuevo entra
  solo). 2024 y 2025 tienen dos recursos con ese nombre (uno "con identificador", creado 2025-04-29; el de 2025
  con columna extra `id`). Verificado 2026-11-12: mismos totales por mes (pozos, petróleo, gas) entre sí y contra
  lo local, pero NO las mismas filas: los dos de 2025 traen 92 filas más que el CSV local de junio (todas en cero,
  nov-dic: 50 de PETROLERA DEL COMAHUE y 42 de ENERGICON) → se toma el de last_modified más reciente. Si falta un año cerrado o un recurso no matchea → error con la lista de nombres del catálogo.
- **Último mes completo** (`comun.py`, lo usan peryear, temporal, fractura y curvas): se descartan desde el final
  los meses con < 90 % de los pozos con producción del MÁXIMO de los 3 meses previos (no solo del anterior: así
  caen también varios parciales seguidos, [24000, 23900, 5000, 4800], y ceros finales). Reemplaza las tres reglas
  viejas (total > 0, > 50 % del máximo, ≥ 80 % de la mediana) que dejaban pasar un mes con 48 pozos (oct-2026).
  Curvas (y zonas, que lee su `ultimo`) usan min(corte NC, corte país): todo el sitio termina en el mismo mes.
  Con los datos de 2026-11-11 el resultado es idéntico al anterior. Tests: `tools/test_comun.py`.
  `data/_meses.json` = caché de pozos/pet/gas por mes.
- `serie_nacional.json` trae además `pozos` (pozos con producción por mes) para comparar contra lo publicado.
- Controles (constantes arriba del script): meses publicados ±3 % en pozos/petróleo/gas (el último publicado
  puede crecer hasta +12 %, porque se publica con ≥ 90 % de los pozos); ningún mes nuevo cae > 15 % en
  pozos, petróleo ni petróleo equivalente contra el mes anterior, la mediana de los 3 previos y (el primero) lo
  publicado del último mes publicado — no depende de la referencia (el gas solo avisa: ago→sep 2025 cayó 15,1 %);
  pozos por año (`pozos_<año>.js`) no bajan > 5 %; `node tools/check.mjs` en verde.
- Año nuevo: los preprocess lo toman solos, pero el visor y `build_public.mjs` usan los `<option>` de `#f-year` en
  `index.html` → hay que agregar el año a mano (el informe avisa).
- GitHub Actions: `.github/workflows/actualizar.yml`, día 20 a las 07:00 AR + manual. Caché de datos crudos
  (`actions/cache`, clave por corrida, restaura la última; ~240 MB comprimida). GitHub borra cachés sin uso en
  7 días: la corrida mensual casi siempre baja todo (~1,6 GB); la caché sirve para re-correr a mano. Deploy con el secret `FIREBASE_SERVICE_ACCOUNT`
  (JSON de una cuenta de servicio con Firebase Hosting Admin + API Keys Viewer; pasos en el README,
  "Monthly update"); `trap` borra la credencial aunque falle. `firebase-tools` fijo en 15.28.1
  (`FIREBASE_TOOLS_VERSION`). El cron publica; el disparo manual solo si se tilda *publicar* (default no).
  Antes de actualizar corre `tools/test_comun.py`. `tools/cdp.mjs` busca Chrome en `CHROME_PATH` y rutas de Linux/macOS; en CI Linux usa
  `--no-sandbox`.

## Reglas del dominio (no negociables)
- **La clave de pozo es `idpozo`, NUNCA la sigla.** La sigla no es única (85.380 idpozo vs 78.128 siglas;
  "T-22" existe en Cuyana y en NOA). Agrupar o cruzar por sigla infló los totales 5–7 % (bug de oct-2026).
  En JS: `r[I.id]`; sparklines, pozos_geo, fractura y curvas están indexados por idpozo.
- **Unidades:** `prod_pet` en m³; `prod_gas` en **Mm³ = miles de m³**. MMm³ = millones. Gas → petróleo
  equivalente 6:1: 1 m³ pet = 1.069 m³ gas, o sea `Mm³ × 1000/1069` = m³eq.
- El último mes calendario suele estar incompleto (atraso de las empresas): recortarlo, nunca mostrar una
  caída a cero falsa.
- Alias de empresa: VISTA OIL & GAS ARGENTINA SAU → VISTA ENERGY ARGENTINA SAU.
- No dibujar datos inventados o estimados como si fueran reales: un pronóstico va punteado y rotulado.
- Validaciones de datos = avisos (ej. QA cuenca declarada vs polígono), no filtros que escondan pozos.

## Trampas del código (`index.html`)
- **El bloque `init` (populateFilters/applyFilters) va AL FINAL del `<script>`**, después de todas las
  funciones y `let`; si no, TDZ ("Cannot access before initialization"). Variables de estado compartido se
  declaran temprano (ver `areaFilter`, `lastFiltered`, `animActive`).
- Capas nuevas: usar `lazyGeo(url, opts)` (se descargan al prenderlas) y sumarlas a `L.control.layers`.
- Pestaña nueva: botón en `#tabs`, `<div id="tab-X" class="tab-pane">`, y construir sus gráficos la
  primera vez que se abre (patrón `buildGeoTab` con flag `geoBuilt`, y `chart.resize()` al volver).
- Coloreo del mapa config-driven en `METRICS{}`.
- Caché: tras regenerar `data/`, el navegador puede servir JSON/JS viejo → Ctrl+F5 (check.mjs ya desactiva caché).
- Basemap oscuro = Esri World_Dark_Gray (CARTO pide API key).
- Diseño: variables CSS en `:root`, tipografía grande (body 16px) a pedido del usuario; Chart.js 13px.
  Textos nuevos ≥ 14 px (tablas `.geo-table` 14 px, ticks SVG de barras 12 px).
- Popups de pozo: `className: 'pozo-popup'`; su `.leaflet-popup-content` es SIEMPRE el contenedor de scroll
  (si no, el encabezado sticky `.lf-popup-head` se engancha a `.leaflet-container` y aparece a mitad del popup).
- Ancho del panel: `aplicarAnchoPanel()` fija `--sb-w` en `#sidebar` (Mapa ≈ 40 % 460–640 px; el resto, con
  `body.sb-wide`, ≈ 60 % mín. 560 px; mapa nunca < 280 px). Divisor `#sb-divisor` arrastrable; ancho por pestaña
  en `localStorage['pozos.anchoPanel']` (doble clic = default). "Ampliar" = `body.sb-full` (oculta el mapa; la
  pestaña Mapa lo restaura). Tras cambiar el ancho, `relayoutPanel()` (invalidateSize + resize de Chart.js).
  `#tabs` hace wrap a 2 filas solo con el panel < 440 px. En celular (≤ 760 px) no hay divisor ni Ampliar.
- Capa "Zonas productivas VM": pane propio `zonas` (z 350, DEBAJO del canvas de puntos, `pointer-events:none`) y
  hexágonos `interactive:false`. El canvas de puntos cubre todo el mapa y se come los clics, así que el popup del
  hexágono sale de `map.on('click')` → `abrirZonaEn` (punto en polígono), salvo que el clic ya haya abierto otro popup
  (contador `popupSeq` entre `preclick` y `click`). Con la capa prendida, `#map.zonas-on` deja los clusters al 50 %.
  `zonas.json` lo comparten capa y pestaña Curvas
  (`loadZonas`, promesa cacheada; `lazyGeo` acepta un tercer parámetro `load`). Rayado = `<pattern id="zonas-rayado">`.
- `interferencia.json` (`loadInterf`) lo usan la pestaña Curvas y la línea padre/hijo de `fillDecl`.
- `curvas_pozos.json` (3 MB) se baja una sola vez (`loadCurvasPozos`, promesa cacheada) al abrir un popup NC o la pestaña.
- Gas: barras del popup y `sparklines.json` ya vienen en Mm³ (no dividir por 1000; bug corregido 2026-11-11).
  En Curvas y textos de EUR el gas se muestra en MMm³.
- `tools/cdp.mjs` usa un puerto de Chrome libre por corrida, pero el `http.server` de Python no aguanta dos
  check/shot en paralelo: correrlos en serie.

## Historial
- 2026-06: base del visor, GOR/corte de agua, filtro por área, animación 24 meses, buscador, comparador
  de empresas, export CSV, concesiones nacionales.
- 2026-10-14: clave idpozo (fix totales inflados), cruces geo, fractura VM, guía GeoPandas (`docs/`).
- 2026-11-10: aviso `file://` + `abrir.bat`; herramientas `tools/check.mjs` y `tools/shot.mjs`; equipo de
  agentes en `.claude/agents/` (supervisor, dev, revisor, qa-visual); `preprocess_curvas.py` escrito.
- 2026-11-11: curvas tipo + EUR de Vaca Muerta. `preprocess_curvas.py` corrido y corregido en 4 tandas de
  revisión (mesetas por choke infladas 9–17×, pozos parados con pronóstico, ramas mal cargadas, residuales,
  empalme optimista). Pestaña "Curvas" y sección "Declinación" en el popup. Arreglos de paso: encabezado fijo
  del popup, unidad de gas en las barras del popup (/1000 de más), letra chica, scroll horizontal en Geo,
  `.catch` de ranking.json, aviso ámbar de ajuste pobre (r² < 0,6). check.mjs: 30 chequeos.
- 2026-11-11: publicado en Firebase Hosting (pozos-argentina.web.app): `tools/build_public.mjs`, `firebase.json`
  con predeploy, `.firebaserc`; línea de atribución a la Secretaría de Energía (CC-BY 4.0) en el encabezado.

- 2026-11-12: zonas productivas VM (hexágonos por EUR/km, tabla por concesión) e interferencia padre/hijo
  (`preprocess_zonas.py`, sección al final de Curvas, línea en el popup). Revisión: clic en pozos con la capa
  prendida, clusters translúcidos, sensibilidad hijo ≥ 12 meses. check.mjs: 35 chequeos.
- 2026-11-12: modo privado local (fichas de yacimiento) y base comercial licenciada (paso 9). check.mjs: 50 chequeos,
  verde con y sin `data/privado/`.

## Pendiente conocido
- Concesiones solapadas: LOMA LA LATA - SIERRA BARROSA y LA ANGOSTURA SUR I salen con los mismos 57 pozos.
