// Prueba de humo del visor en Chrome headless. Necesita el servidor en :8765 (abrir.bat o preview_start).
// Uso: node tools/check.mjs        -> imprime ✔/✘ por chequeo y sale con código 1 si algo falla.
import { launch, sleep, BASE } from "./cdp.mjs";
import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { FICHAS, buscarFugas, listar } from "./privado.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(BASE);
const HAY_FICHAS = LOCAL && existsSync(join(ROOT, FICHAS));

const b = await launch();
let ok = 0, bad = 0;
const check = async (nombre, expr) => {
  try {
    const r = await b.evalJS(expr);
    if (r === true || (r && r.ok)) { ok++; console.log(`✔ ${nombre}${r && r.info ? " · " + r.info : ""}`); }
    else { bad++; console.log(`✘ ${nombre} · ${JSON.stringify(r)}`); }
  } catch (e) { bad++; console.log(`✘ ${nombre} · ${e.message.split("\n")[0]}`); }
};

try {
  await b.open();

  await check("pozos cargados y filtrados", `({ok: POZOS.length > 1000 && lastFiltered.length > 1000,
    info: POZOS.length + ' pozos, ' + lastFiltered.length + ' visibles'})`);
  await check("coordenadas válidas (dentro de Argentina, sin NaN)", `(() => {
    const m = POZOS.filter(r => !(r[I.lat] > -56 && r[I.lat] < -21 && r[I.lon] > -74 && r[I.lon] < -53));
    return {ok: m.length === 0, info: m.length + ' fuera', ej: m.slice(0,3).map(r => r[I.sigla])}; })()`);
  await check("totales sin '—' ni NaN", `(() => { const t = ['t-pozos','t-pet','t-gas','t-emp']
    .map(i => document.getElementById(i).textContent); return {ok: t.every(x => x && x !== '—' && !/NaN|undefined/.test(x)), info: t.join(' | ')}; })()`);
  await check("idpozo único en el año", `(() => { const s = new Set(POZOS.map(r => r[I.id]));
    return {ok: s.size === POZOS.length, info: s.size + ' ids / ' + POZOS.length + ' filas'}; })()`);

  await check("capa áreas de concesión", `({ok: areasLayer.getLayers().length > 100, info: areasLayer.getLayers().length + ' áreas'})`);
  await check("capas geo cargan al prenderlas", `(async () => {
    const L = {cuencas: cuencasLayer, yacimientos: yacLayer, permisos: permLayer, gasoductos: gasodLayer, refinerias: refiLayer};
    Object.values(L).forEach(l => map.addLayer(l));
    for (let i = 0; i < 40 && Object.values(L).some(l => !l.getLayers().length); i++) await new Promise(r => setTimeout(r, 250));
    const n = Object.fromEntries(Object.entries(L).map(([k, l]) => [k, l.getLayers().length]));
    Object.values(L).forEach(l => map.removeLayer(l));
    return {ok: Object.values(n).every(v => v > 0), info: JSON.stringify(n)}; })()`);

  await check("capa Zonas VM: hexágonos con color, rayado en pocos pozos, leyenda y popup", `(async () => {
    map.addLayer(zonasLayer);
    for (let i = 0; i < 40 && !zonasLayer.getLayers().length; i++) await new Promise(r => setTimeout(r, 250));
    const est = () => { const ls = zonasLayer.getLayers();
      return {n: ls.length, color: ls.filter(l => l.options.fill !== false && /^#/.test(l.options.fillColor)).length,
              rayado: ls.filter(l => l.options.fill !== false && /url\\(#zonas-rayado\\)/.test(l.options.fillColor)).length}; };
    const p = est();
    const leg = document.querySelector('.zonas-leg');
    const legOk = !!leg && /mil m³\\/km/.test(leg.textContent) && /pocos pozos/.test(leg.textContent) && leg.querySelectorAll('.sw').length >= 6
      && parseFloat(getComputedStyle(leg).fontSize) >= 14;
    const lyr = zonasLayer.getLayers().find(l => { const q = l.feature.properties.p; return q && !q.pocos && q.e10 != null; });
    abrirZonaEn(lyr.getBounds().getCenter());
    await new Promise(r => setTimeout(r, 300));
    const pop = document.querySelector('.leaflet-popup.pozo-popup');
    const t = pop ? pop.textContent : '';
    const popOk = /coordenada de superficie; la rama puede extenderse 2–3 km/.test(t) && /EUR\\/km rango P90–P10/.test(t) && /P90 conservador – P10 optimista/.test(t) && !/NaN|undefined/.test(t);
    map.closePopup();
    leg.querySelector('[data-zv="g"]').click();
    const g = est();
    const legG = /MMm³\\/km/.test(document.querySelector('.zonas-leg').textContent);
    document.querySelector('.zonas-leg [data-zv="p"]').click();
    map.removeLayer(zonasLayer);
    const sinLeg = !document.querySelector('.zonas-leg');
    return {ok: p.n > 50 && p.color > 50 && p.rayado > 0 && g.color > 10 && legOk && legG && popOk && sinLeg,
      info: p.n + ' hexágonos · petróleo ' + p.color + ' con color / ' + p.rayado + ' rayados · gas ' + g.color + ' / ' + g.rayado
        + ' · popup: ' + t.slice(0, 80)}; })()`);

  await check("capa Zonas VM prendida: clic en un pozo abre el del pozo; clic en zona sin pozo abre el del hexágono; clusters translúcidos", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    map.closePopup();
    map.addLayer(zonasLayer);
    for (let i = 0; i < 40 && !zonasLayer.getLayers().length; i++) await espera(250);
    const translucido = map.getContainer().classList.contains('zonas-on');
    const r = lastFiltered.find(r => /vaca muerta/i.test(r[I.form] || '') && zonaEn(r[I.lat], r[I.lon]));
    if (!r) { map.removeLayer(zonasLayer); return {ok: false, info: 'ningún pozo VM dentro de un hexágono'}; }
    map.setView([r[I.lat], r[I.lon]], 14, {animate: false});
    await espera(1200);
    const clic = (pt) => {
      const rect = map.getContainer().getBoundingClientRect();
      const x = rect.left + pt.x, y = rect.top + pt.y;
      const el = document.elementFromPoint(x, y);
      const o = {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, view: window};
      ['mousedown', 'mouseup', 'click'].forEach(t => el.dispatchEvent(new MouseEvent(t, o)));
      return el;
    };
    const el1 = clic(map.latLngToContainerPoint([r[I.lat], r[I.lon]]));
    await espera(600);
    const pop1 = document.querySelector('.leaflet-popup');
    const t1 = pop1 ? (pop1.querySelector('.lf-popup-sub') || pop1).textContent : '';
    const okPozo = !!pop1 && t1.trim() === String(r[I.sigla]).trim() && !/Zona Vaca Muerta/.test(pop1.textContent);
    map.closePopup(); await espera(200);
    // Punto dentro del mismo hexágono a más de 20 px de cualquier pozo visible
    const f = zonaEn(r[I.lat], r[I.lon]);
    const ring = f.geometry.coordinates[0];
    const c = ring.slice(0, 6).reduce((a, q) => [a[0] + q[0] / 6, a[1] + q[1] / 6], [0, 0]);
    const cands = [c].concat(ring.slice(0, 6).flatMap(q => [0.3, 0.55, 0.8].map(k => [c[0] + (q[0] - c[0]) * k, c[1] + (q[1] - c[1]) * k])));
    const pts = lastFiltered.map(p => map.latLngToContainerPoint([p[I.lat], p[I.lon]]));
    const sz = map.getSize();
    const libre = cands.map(q => map.latLngToContainerPoint([q[1], q[0]]))
      .find(pt => pt.x > 30 && pt.y > 30 && pt.x < sz.x - 300 && pt.y < sz.y - 30 && pts.every(p => p.distanceTo(pt) > 20));
    let okZona = false, t2 = 'sin punto libre dentro del hexágono';
    if (libre) {
      clic(libre); await espera(600);
      const pop2 = document.querySelector('.leaflet-popup');
      t2 = pop2 ? pop2.textContent.slice(0, 60) : 'sin popup';
      okZona = !!pop2 && /Zona Vaca Muerta/.test(pop2.textContent);
      map.closePopup();
    }
    map.removeLayer(zonasLayer);
    const vuelve = !map.getContainer().classList.contains('zonas-on');
    return {ok: okPozo && okZona && translucido && vuelve,
      info: 'clic sobre ' + (el1 && el1.tagName) + ' → ' + (t1.trim() || 'sin popup') + ' (esperado ' + r[I.sigla] + ') · zona: '
        + t2.replace(/\\s+/g, ' ') + ' · clase zonas-on ' + translucido + '/' + !vuelve}; })()`);

  await check("popup de pozo con gráfico de evolución", `(async () => {
    const r = lastFiltered.find(r => r[I.pet] > 1000 && sparkData.pozos[r[I.id]]);
    const h = pozoPopupHTML(r);
    return {ok: h.includes('<svg') && !/NaN|undefined/.test(h), info: r[I.sigla]}; })()`);
  await check("popup sin NaN/undefined en 300 pozos al azar", `(() => {
    const malos = [];
    for (let k = 0; k < 300; k++) { const r = lastFiltered[Math.floor(Math.random() * lastFiltered.length)];
      if (/NaN|undefined/.test(pozoPopupHTML(r))) malos.push(r[I.sigla]); }
    return {ok: malos.length === 0, ej: malos.slice(0, 5)}; })()`);

  await check("popup de pozo NC con ajuste muestra Declinación sin NaN", `(async () => {
    const cp = await loadCurvasPozos();
    const r = lastFiltered.find(r => { const z = cp.pozos[r[I.id]]; return z && z['q' + z.v] === 'ok' && z['f' + z.v]; });
    if (!r) return {ok: false, info: 'ningún pozo NC con ajuste ok en el año'};
    flyToPozo(r[I.id]);
    let box = null;
    for (let i = 0; i < 40; i++) { await new Promise(res => setTimeout(res, 250));
      box = document.querySelector('.leaflet-popup .decl-box'); if (box && box.querySelector('canvas') && declChart) break; }
    const h = box ? box.innerHTML : '';
    const ok = !!declChart && h.includes('Declinación') && h.includes('pronóstico') && !/NaN|undefined|Infinity/.test(h)
      && declChart.data.datasets.every(d => d.data.every(p => p.y == null || isFinite(p.y)));
    map.closePopup();
    return {ok, info: 'idpozo ' + r[I.id] + ' · ' + (box ? box.querySelector('.decl-txt').textContent.slice(0, 90) : 'sin sección')}; })()`);

  await check("popup 161577: aviso de hasta qué año llega el gráfico y el pronóstico, sin NaN", `(async () => {
    await loadCurvasPozos();
    if (!window.POZOS.some(r => r[I.id] === 161577)) return {ok: false, info: '161577 no está en el año cargado'};
    flyToPozo(161577);
    let box = null;
    for (let i = 0; i < 40; i++) { await new Promise(res => setTimeout(res, 250));
      box = document.querySelector('.leaflet-popup .decl-box'); if (box && box.querySelector('.decl-txt') && declChart) break; }
    const t = box && box.querySelector('.decl-txt') ? box.querySelector('.decl-txt').textContent : '';
    const head = document.querySelector('.leaflet-popup .lf-popup-head');
    const ok = t.includes('El gráfico muestra hasta el año') && !/NaN|undefined|Infinity/.test(box.innerHTML)
      && !!head && getComputedStyle(head).position === 'sticky';
    map.closePopup();
    return {ok, info: (t.match(/El gráfico muestra[^.]*\\./) || [t.slice(0, 90)])[0]}; })()`);
  // Encabezado sticky del popup: siempre pegado al borde superior del contenedor que scrollea
  // (CH.CH.EaLE-3 de COLHUE HUAPI y 42905 lo mostraban a mitad o al pie del popup)
  for (const [nom, buscar] of [["CH.CH.EaLE-3", "r => r[I.sigla] === 'CH.CH.EaLE-3' && /COLHUE/.test(r[I.emp])"],
                               ["42905", "r => r[I.id] === 42905"]]) {
    await check(`popup ${nom}: encabezado arriba al abrir y scrolleado al fondo (±2 px)`, `(async () => {
      await loadCurvasPozos().catch(() => {});
      const r = window.POZOS.find(${buscar});
      if (!r) return {ok: false, info: '${nom} no está en el año cargado'};
      flyToPozo(r[I.id]);
      for (let i = 0; i < 40; i++) { await new Promise(res => setTimeout(res, 250));
        const b = document.querySelector('.leaflet-popup .decl-box');
        if (i > 8 && (!b || b.querySelector('canvas'))) break; }
      await new Promise(res => setTimeout(res, 800));
      const pop = document.querySelector('.leaflet-popup');
      const sc = pop && pop.querySelector('.leaflet-popup-content'), head = pop && pop.querySelector('.lf-popup-head');
      if (!sc || !head) { map.closePopup(); return {ok: false, info: 'sin popup o sin encabezado'}; }
      const dif = () => Math.round(head.getBoundingClientRect().top - sc.getBoundingClientRect().top);
      const d0 = dif();
      sc.scrollTop = sc.scrollHeight; await new Promise(res => setTimeout(res, 300));
      const d1 = dif(), st1 = sc.scrollTop;
      // Forzar un popup bajo (con scroll seguro) y repetir al fondo
      const popup = map._popup; popup.options.maxHeight = 300; popup._updateLayout();
      sc.scrollTop = sc.scrollHeight; await new Promise(res => setTimeout(res, 300));
      const d2 = dif(), st2 = sc.scrollTop;
      map.closePopup();
      return {ok: Math.abs(d0) <= 2 && Math.abs(d1) <= 2 && Math.abs(d2) <= 2 && st2 > 0,
        info: 'idpozo ' + r[I.id] + ' · dif abierto ' + d0 + ' px, al fondo ' + d1 + ' px (scroll ' + st1 + '), forzado 300 px ' + d2 + ' px (scroll ' + st2 + ')'}; })()`);
  }

  await check("popup 163977: barras de gas en Mm³ sin dividir por 1000 (último = sparklines)", `(() => {
    const sp = sparkData.pozos[163977];
    const r = window.POZOS.find(r => r[I.id] === 163977);
    if (!sp || !r) return {ok: false, info: 'sin sparkline o sin pozo 163977 en el año'};
    const div = document.createElement('div'); div.innerHTML = pozoPopupHTML(r); document.body.appendChild(div);
    const lab = [...div.querySelectorAll('.spark-label')].find(e => e.textContent.startsWith('Gas Mm³/mes'));
    const ult = sp.g[sp.g.length - 1], esperado = '(último: ' + fmtGasMes(ult) + ' Mm³)';
    const svg = lab && lab.nextElementSibling;
    const tit = svg ? [...svg.querySelectorAll('title')].map(t => t.textContent) : [];
    const fs = svg ? [...svg.querySelectorAll('text')].map(t => +t.getAttribute('font-size')) : [];
    const fsLab = lab ? [lab, lab.querySelector('.ult')].map(e => e ? parseFloat(getComputedStyle(e).fontSize) : 0) : [0];
    const res = {ok: !!lab && lab.textContent.includes(esperado) && ult > 0 && tit[tit.length - 1].endsWith(fmtGasMes(ult) + ' Mm³')
      && fs.length > 0 && fs.every(f => f >= 12) && fsLab.every(f => f >= 14),
      info: lab ? lab.textContent.trim() + ' · ticks ' + fs.join('/') + ' px · rótulo ' + fsLab.join('/') + ' px' : 'sin rótulo de gas'};
    div.remove();
    return res; })()`);

  await check("popup NC con pronóstico vacío: 'Sin pronóstico: el primer mes…' sin año ni 0,000", `(async () => {
    const cp = await loadCurvasPozos();
    const ids = new Set(window.POZOS.map(r => r[I.id]));
    const id = Object.keys(cp.pozos).find(k => { const z = cp.pozos[k], v = z.v === 'g' ? 'g' : 'p';
      if (!ids.has(+k) || z['q' + v] !== 'ok' || !z['f' + v]) return false;
      const ac = (z[v] || []).reduce((a, b) => a + b, 0); return z['e' + v] != null && z['e' + v] - ac < 0.5; });
    if (!id) return {ok: true, info: 'no hay pozos ok sin pronóstico en el año (nada que probar)'};
    flyToPozo(+id);
    let t = '';
    for (let i = 0; i < 40; i++) { await new Promise(res => setTimeout(res, 250));
      const b = document.querySelector('.leaflet-popup .decl-txt'); if (b && declChart) { t = b.textContent; break; } }
    const pron = declChart ? declChart.data.datasets.some(d => d.label === 'pronóstico') : null;
    map.closePopup();
    return {ok: t.startsWith('Sin pronóstico: el primer mes') && t.includes('límite económico') && t.includes('EUR = acumulada')
      && !/primer mes de pronóstico|termina en el año|sigue hasta el año|0,000|NaN|undefined/.test(t) && pron === false,
      info: 'idpozo ' + id + ' · ' + t.slice(0, 140)}; })()`);

  await check("fmtMM(0) = '0' y empalme punteado ≥ 2 px del color del pronóstico", `(async () => {
    const cp = await loadCurvasPozos();
    const r = lastFiltered.find(r => { const z = cp.pozos[r[I.id]]; return z && z['q' + z.v] === 'ok' && z['f' + z.v]
      && (z['e' + z.v] - (z[z.v] || []).reduce((a, b) => a + b, 0)) > 100; });
    if (!r) return {ok: false, info: 'sin pozo con pronóstico'};
    flyToPozo(r[I.id]);
    for (let i = 0; i < 40 && !declChart; i++) await new Promise(res => setTimeout(res, 250));
    const ds = declChart ? declChart.data.datasets : [];
    const e = ds.find(d => d.label === 'empalme'), p = ds.find(d => d.label === 'pronóstico');
    map.closePopup();
    return {ok: fmtMM(0) === '0' && !!e && !!p && e.borderWidth >= 2 && e.borderColor === p.borderColor && !!e.borderDash,
      info: 'idpozo ' + r[I.id] + (e ? ' · empalme ' + e.borderWidth + ' px ' + e.borderColor : ' · sin empalme')}; })()`);

  // Declinación: ajuste gris distinto del real y del pronóstico; aviso ámbar si r² < R2_POBRE; empalme sin salto
  for (const [id, pobre] of [[163977, true], [10073, false]]) {
    await check(`popup ${id}: colores real/ajuste/pronóstico distintos, aviso de ajuste pobre ${pobre ? 'presente' : 'ausente'}, empalme en el último real`, `(async () => {
      await loadCurvasPozos();
      if (!window.POZOS.some(r => r[I.id] === ${id})) return {ok: false, info: '${id} no está en el año cargado'};
      flyToPozo(${id});
      let box = null;
      for (let i = 0; i < 40; i++) { await new Promise(res => setTimeout(res, 250));
        box = document.querySelector('.leaflet-popup .decl-box'); if (box && box.querySelector('.decl-txt') && declChart) break; }
      const ds = declChart ? declChart.data.datasets : [];
      const g = l => ds.find(d => d.label === l);
      const re = g('real'), aj = g('ajuste'), pr = g('pronóstico'), em = g('empalme');
      const colores = [re, aj, pr].map(d => d ? d.borderColor : null);
      const distintos = colores.every(c => c) && new Set(colores).size === 3 && !aj.borderDash && aj.borderWidth < re.borderWidth;
      const amb = box ? box.querySelector('.decl-txt .aviso.ambar') : null;
      const tAmb = amb ? amb.textContent : '';
      const fsAmb = amb ? parseFloat(getComputedStyle(amb).fontSize) : 0;
      const avisoOk = ${pobre} ? (/ajuste pobre \\(r² \\d+,\\d+\\): el pronóstico es poco confiable/.test(tAmb) && fsAmb >= 14) : !amb;
      let empOk = false, empInfo = 'sin empalme';
      if (em && pr && re) {
        const reales = re.data.filter(p => p.y != null), ult = reales[reales.length - 1];
        empOk = em.data[0].x === ult.x && em.data[0].y === ult.y && em.data[1].x === pr.data[0].x && em.data[1].y === pr.data[0].y;
        empInfo = 'último real ' + fmtNum(ult.y) + ' → pron[0] ' + fmtNum(pr.data[0].y);
      }
      map.closePopup();
      return {ok: distintos && avisoOk && empOk,
        info: 'colores ' + colores.join('/') + ' · ' + (tAmb || 'sin aviso ámbar') + ' · ' + empInfo}; })()`);
  }

  for (const [clase, re] of [["H", "Pozo hijo: \\\\d+ vecinos? previos? a < 1 km \\\\(el vecino más viejo arrancó \\\\d+ meses antes"],
                             ["P", "Pozo padre: sin productores previos a < 1 km"]]) {
    await check(`popup VM: línea padre/hijo (clase ${clase})`, `(async () => {
      const [cp, inf] = await Promise.all([loadCurvasPozos(), loadInterf()]);
      const r = lastFiltered.find(r => { const z = inf.pozos[r[I.id]]; return z && z[0] === '${clase}' && cp.pozos[r[I.id]]; });
      if (!r) return {ok: false, info: 'ningún pozo de clase ${clase} en el año'};
      flyToPozo(r[I.id]);
      let t = '';
      for (let i = 0; i < 40; i++) { await new Promise(res => setTimeout(res, 250));
        const b = document.querySelector('.leaflet-popup .decl-txt .ph'); if (b) { t = b.textContent; break; } }
      const fs = t ? parseFloat(getComputedStyle(document.querySelector('.leaflet-popup .decl-txt .ph')).fontSize) : 0;
      map.closePopup();
      return {ok: new RegExp('${re}').test(t) && !/NaN|undefined|null/.test(t) && fs >= 14,
        info: 'idpozo ' + r[I.id] + ' · ' + t}; })()`);
  }

  await check("pestañas: ninguna desborda su botón (sidebar angosto)", `(() => {
    const b = [...document.querySelectorAll('#tabs .tab-btn')].filter(x => x.scrollWidth > x.clientWidth + 1);
    return {ok: b.length === 0, info: document.getElementById('tabs').offsetHeight + ' px de alto', mal: b.map(x => x.textContent)}; })()`);

  // ── Ancho del panel lateral, divisor y "Ampliar" ──
  await check("panel: Mapa ≈ 40 % y Ranking ≈ 60 % del ancho; 5 pestañas y 4 KPIs en una fila", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    const sb = document.getElementById('sidebar'), W = innerWidth;
    const filas = sel => new Set([...document.querySelectorAll(sel)].map(e => Math.round(e.getBoundingClientRect().top))).size;
    document.querySelector('.tab-btn[data-tab="filtros"]').click(); await espera(300);
    const wMapa = sb.offsetWidth, tabsMapa = filas('#tabs .tab-btn'), kpis = filas('#totales .stat-box');
    const kpiCortado = [...document.querySelectorAll('#totales .val')].some(e => e.scrollWidth > e.clientWidth + 1);
    document.querySelector('.tab-btn[data-tab="ranking"]').click(); await espera(300);
    const wRank = sb.offsetWidth, tabsRank = filas('#tabs .tab-btn'), mapaW = document.getElementById('map').offsetWidth;
    document.querySelector('.tab-btn[data-tab="filtros"]').click(); await espera(300);
    return {ok: wRank > wMapa + 100 && Math.abs(wMapa - Math.min(640, Math.max(460, W * 0.4))) <= 2
      && Math.abs(wRank - Math.max(560, W * 0.6)) <= 2 && mapaW >= 280 && tabsMapa === 1 && tabsRank === 1 && kpis === 1 && !kpiCortado,
      info: 'viewport ' + W + ' · Mapa ' + wMapa + ' px · Ranking ' + wRank + ' px (mapa ' + mapaW + ' px) · pestañas '
        + tabsMapa + '/' + tabsRank + ' fila(s) · KPIs ' + kpis + ' fila(s)'}; })()`);

  await check("ranking: ninguna cifra recortada (ancho por defecto y panel a 320 px); nombres con … y title", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    document.querySelector('.tab-btn[data-tab="ranking"]').click();
    for (let i = 0; i < 40 && !document.querySelector('#ranking-list .rank-row'); i++) await espera(250);
    const sb = document.getElementById('sidebar');
    const medir = () => { const filas = [...document.querySelectorAll('#ranking-list .rank-row')];
      const mal = filas.filter(f => { const v = f.querySelector('.rank-val'), rv = v.getBoundingClientRect(), rf = f.getBoundingClientRect();
        return v.scrollWidth > v.clientWidth || rv.right > rf.right + 0.5 || rv.left < f.querySelector('.rank-info').getBoundingClientRect().right; });
      return {n: filas.length, mal: mal.map(f => f.querySelector('.rname').textContent + ' ' + f.querySelector('.rank-val').textContent)}; };
    const res = {};
    for (const k of ['top_productores', 'top_crecimiento', 'top_caida']) {
      document.querySelector('.rank-btn[data-rank="' + k + '"]').click(); await espera(100);
      res[k] = medir();
      sb.style.setProperty('--sb-w', '320px'); await espera(100);
      res[k + '@320'] = medir();
      aplicarAnchoPanel(); await espera(100);
    }
    document.querySelector('.rank-btn[data-rank="top_productores"]').click();
    const titulos = [...document.querySelectorAll('#ranking-list .rname')].every(e => e.title === e.textContent);
    const elip = getComputedStyle(document.querySelector('#ranking-list .remp')).textOverflow === 'ellipsis';
    const fs = Math.min(...['.rname', '.remp', '.rank-val'].map(s => parseFloat(getComputedStyle(document.querySelector('#ranking-list ' + s)).fontSize)));
    document.querySelector('.tab-btn[data-tab="filtros"]').click();
    const malos = Object.entries(res).filter(([k, v]) => v.mal.length || !v.n);
    return {ok: malos.length === 0 && titulos && elip && fs >= 14,
      info: Object.entries(res).map(([k, v]) => k + ' ' + v.n + ' filas').join(' · ') + ' · letra mín. ' + fs + ' px',
      mal: malos.map(([k, v]) => k + ': ' + v.mal.slice(0, 3).join(', '))}; })()`);

  await check("Ampliar oculta el mapa; 'Ver mapa' y la pestaña Mapa lo restauran", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    const btn = document.getElementById('btn-ampliar'), m = document.getElementById('map'), sb = document.getElementById('sidebar');
    document.querySelector('.tab-btn[data-tab="filtros"]').click(); await espera(200);
    const ocultoEnMapa = btn.offsetWidth === 0;
    document.querySelector('.tab-btn[data-tab="tendencia"]').click(); await espera(300);
    btn.click(); await espera(400);
    const a = {mapa: m.offsetWidth, panel: sb.offsetWidth, txt: btn.textContent};
    btn.click(); await espera(400);
    const b2 = {mapa: m.offsetWidth, txt: btn.textContent};
    btn.click(); await espera(200);
    document.querySelector('.tab-btn[data-tab="filtros"]').click(); await espera(400);
    const c = {mapa: m.offsetWidth, full: document.body.classList.contains('sb-full')};
    const mapOk = map.getSize().x === m.clientWidth;
    return {ok: ocultoEnMapa && a.mapa === 0 && a.panel >= innerWidth - 1 && a.txt === 'Ver mapa'
      && b2.mapa >= 280 && b2.txt === 'Ampliar' && c.mapa >= 280 && !c.full && mapOk,
      info: 'ampliado: mapa ' + a.mapa + ' px, panel ' + a.panel + ' px · Ver mapa: ' + b2.mapa + ' px · pestaña Mapa: ' + c.mapa
        + ' px · Leaflet ' + map.getSize().x + ' px'}; })()`);

  await check("divisor: arrastrar cambia el ancho, se recuerda por pestaña y doble clic vuelve al default", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    const d = document.getElementById('sb-divisor'), sb = document.getElementById('sidebar');
    document.querySelector('.tab-btn[data-tab="filtros"]').click(); await espera(200);
    const w0 = sb.offsetWidth, r = d.getBoundingClientRect(), x = r.left + 4, y = r.top + 200;
    const ev = (t, cx) => d.dispatchEvent(new PointerEvent(t, {bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse',
      button: 0, buttons: t === 'pointerup' ? 0 : 1, clientX: cx, clientY: y, isPrimary: true}));
    ev('pointerdown', x); ev('pointermove', x - 40); ev('pointermove', x - 100); ev('pointerup', x - 100);
    await espera(400);
    const w1 = sb.offsetWidth, guardado = JSON.parse(localStorage.getItem('pozos.anchoPanel') || '{}').filtros;
    const mapOk = map.getSize().x === document.getElementById('map').clientWidth;
    document.querySelector('.tab-btn[data-tab="ranking"]').click(); await espera(200);
    const wRank = sb.offsetWidth;
    document.querySelector('.tab-btn[data-tab="filtros"]').click(); await espera(200);
    const w2 = sb.offsetWidth;
    ev('pointerdown', x - 100); ev('pointermove', x - 5000); ev('pointerup', x - 5000); await espera(200);
    const wMin = sb.offsetWidth;
    d.dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); await espera(300);
    const w3 = sb.offsetWidth, borrado = !('filtros' in JSON.parse(localStorage.getItem('pozos.anchoPanel') || '{}'));
    return {ok: Math.abs(w1 - (w0 - 100)) <= 2 && guardado === w1 && mapOk && wRank !== w1 && w2 === w1 && wMin === 320 && w3 === w0 && borrado,
      info: 'default ' + w0 + ' → arrastrado ' + w1 + ' (guardado ' + guardado + ') · Ranking ' + wRank + ' · vuelve a Mapa ' + w2
        + ' · tope mín. ' + wMin + ' · doble clic ' + w3}; })()`);

  for (const tab of ["tendencia", "ranking", "geo", "curvas", "filtros"]) {
    await check(`pestaña ${tab} abre`, `(async () => {
      document.querySelector('.tab-btn[data-tab="${tab}"]').click();
      await new Promise(r => setTimeout(r, 1500));
      return document.getElementById('tab-${tab}').classList.contains('active'); })()`);
  }
  await check("gráficos de Tendencia y Geo creados", `({ok: !!chartNac && !!chartFrac})`);
  await check("serie nacional: último mes completo (vs el anterior y vs la mediana de los 3 previos)", `(() => {
    const s = serieNacional, n = s.periodos.length, p = s.pozos;
    const med3 = a => { const v = a.slice(n - 4, n - 1).sort((x, y) => x - y); return v[1]; };
    const okPozos = !p || (p.length === n && p[n - 1] >= 0.9 * p[n - 2] && p[n - 1] >= 0.9 * med3(p));
    const okPet = s.pet[n - 1] >= 0.85 * s.pet[n - 2] && s.pet[n - 1] >= 0.85 * med3(s.pet);
    const okGas = s.gas[n - 1] > 0.5 * s.gas[n - 2] && s.gas[n - 1] > 0.5 * med3(s.gas);
    return {ok: n > 12 && okPozos && okPet && okGas,
      info: s.periodos[n - 1] + (p ? ' · ' + p[n - 1] + ' pozos (mediana 3 previos ' + med3(p) + ')' : ' · (sin pozos por mes)')}; })()`);
  await check("pestaña Curvas: 2 gráficos, tablas con filas y supuestos", `({
    ok: !!chartCurvas && !!chartEur && chartCurvas.data.datasets.length > 0 && chartEur.data.datasets.some(d => d.data.length)
      && document.querySelectorAll('#cv-coh tr').length > 1 && document.querySelectorAll('#cv-emp tr').length > 1
      && document.getElementById('cv-supuestos').textContent.includes('Arps')
      && !/NaN|undefined/.test(document.getElementById('tab-curvas').innerText),
    info: chartCurvas && (chartCurvas.data.datasets.length + ' series, ' + (document.querySelectorAll('#cv-coh tr').length - 1)
      + ' cohortes, ' + (document.querySelectorAll('#cv-emp tr').length - 1) + ' operadores') })`);
  await check("Curvas: cambiar a gas / acumulada / por km / log sin error", `(async () => {
    for (const sel of ['#cv-v [data-v="g"]', '#cv-modo [data-modo="acum"]', '#cv-km [data-km="1"]', '#cv-log',
                       '#cv-v [data-v="p"]', '#cv-modo [data-modo="mensual"]', '#cv-km [data-km="0"]', '#cv-log']) {
      document.querySelector(sel).click(); await new Promise(r => setTimeout(r, 100)); }
    return {ok: !!chartCurvas && chartCurvas.data.datasets.length > 0 && !cvLog && cvV === 'p'}; })()`);

  await check("Curvas gas: EUR en MMm³ (sin 'mil Mm³') y encabezados /km", `(async () => {
    document.querySelector('.tab-btn[data-tab="curvas"]').click();
    await new Promise(r => setTimeout(r, 300));
    document.querySelector('#cv-v [data-v="g"]').click(); await new Promise(r => setTimeout(r, 150));
    const h = document.getElementById('cv-coh').rows[0].textContent, txt = document.getElementById('tab-curvas').innerText;
    const ticks = chartEur.scales.y.ticks.map(t => t.label).join(' ');
    document.querySelector('#cv-v [data-v="p"]').click(); await new Promise(r => setTimeout(r, 150));
    const hp = document.getElementById('cv-coh').rows[0].textContent;
    document.querySelector('.tab-btn[data-tab="filtros"]').click();
    return {ok: h.includes('EUR P50 (MMm³)') && h.includes('MMm³/km') && h.includes('Con EUR válida') && hp.includes('(m³/km)')
      && !/mil Mm³|NaN|undefined/.test(txt) && !/mil/.test(ticks), info: h}; })()`);

  await check("Curvas: tabla por concesión e interferencia padre/hijo con números (petróleo y gas, EUR/km)", `(async () => {
    document.querySelector('.tab-btn[data-tab="curvas"]').click();
    for (let i = 0; i < 40 && !(chartIntCoh && document.querySelectorAll('#cv-conc tr').length > 1); i++)
      await new Promise(r => setTimeout(r, 250));
    const leer = () => {
      const cifra = document.getElementById('int-cifra').textContent;
      const nums = ds => ds.flatMap(d => d.data).filter(v => v != null && isFinite(v)).length;
      return {cifra, ok: /\\d+,\\d+×/.test(cifra) && /\\d+ hexágonos/.test(cifra) && !!chartIntCoh && !!chartIntTramo
        && nums(chartIntCoh.data.datasets) >= 4 && nums(chartIntTramo.data.datasets) >= 3};
    };
    const p = leer();
    const conc = document.querySelectorAll('#cv-conc tr').length - 1;
    const sup = document.getElementById('int-supuestos').textContent;
    const supOk = /superficie/i.test(sup) && /Hermanos/.test(sup) && /correlación, no causa/.test(document.getElementById('tab-curvas').innerText);
    document.querySelector('#int-met [data-m="e"]').click(); await new Promise(r => setTimeout(r, 300));
    const e = leer();
    document.querySelector('#cv-v [data-v="g"]').click(); await new Promise(r => setTimeout(r, 400));
    const g = leer();
    const concG = document.getElementById('cv-conc').rows[0].textContent;
    document.querySelector('#int-met [data-m="a"]').click();
    document.querySelector('#cv-v [data-v="p"]').click(); await new Promise(r => setTimeout(r, 300));
    const txt = document.getElementById('tab-curvas').innerText;
    document.querySelector('.tab-btn[data-tab="filtros"]').click();
    const sensOk = [p, e, g].every(x => /Sensibilidad, hijo = vecino 12 meses o más antes[^]*\\d+,\\d+× en \\d+ hexágonos/.test(x.cifra))
      && /Sesgo hacia 1/.test(sup);
    return {ok: p.ok && e.ok && g.ok && conc > 5 && supOk && sensOk && concG.includes('MMm³/km') && !/NaN|undefined|Infinity/.test(txt),
      info: conc + ' concesiones · ' + p.cifra.replace(/\\s+/g, ' ').slice(0, 150)}; })()`);

  for (const tab of ["geo", "curvas"]) {
    await check(`pestaña ${tab}: sin scroll horizontal con la barra a 350 px`, `(async () => {
      document.querySelector('.tab-btn[data-tab="${tab}"]').click();
      const sb = document.getElementById('sidebar'); sb.style.width = '350px';
      await new Promise(r => setTimeout(r, 1200));
      const p = document.getElementById('tab-${tab}');
      // .table-scroll (tabla de operadores de Geo) tampoco debe esconder columnas detrás de un scroll propio
      const tablas = [...p.querySelectorAll('.table-scroll')].filter(w => w.scrollWidth > w.clientWidth + 1).length;
      const res = {ok: sb.offsetWidth <= 352 && p.scrollWidth <= p.clientWidth + 1 && tablas === 0,
        info: 'barra ' + sb.offsetWidth + ' px · scrollWidth ' + p.scrollWidth + ' / clientWidth ' + p.clientWidth
          + (tablas ? ' · ' + tablas + ' tabla(s) con scroll propio' : '')};
      sb.style.width = '';
      document.querySelector('.tab-btn[data-tab="filtros"]').click();
      return res; })()`);
  }

  await check("gráficos de Tendencia y Geo: ticks, leyendas y tooltips ≥ 14 px", `(async () => {
    document.querySelector('.tab-btn[data-tab="tendencia"]').click();
    await new Promise(r => setTimeout(r, 600));
    const charts = {nacional: chartNac, cuenca: chartCuenca, empresa: chartEmpresa, frac: chartFrac};
    const res = {}, mal = [];
    for (const [k, c] of Object.entries(charts)) {
      if (!c) { if (k === 'nacional' || k === 'frac') mal.push(k + ' sin crear'); continue; }
      const t = Object.values(c.scales).map(s => s.options.ticks.font.size);
      const otros = [c.options.plugins.legend.labels.font.size, c.options.plugins.tooltip.titleFont.size, c.options.plugins.tooltip.bodyFont.size];
      res[k] = t.concat(otros).join('/');
      if (t.concat(otros).some(f => !(f >= 14))) mal.push(k + ' ' + res[k]);
    }
    const css = ['#tab-tendencia .chart-label', '#tab-tendencia .section-title', '#tab-tendencia .cuenca-chip', '#tab-geo .geo-note']
      .map(s => document.querySelector(s)).filter(Boolean).map(e => parseFloat(getComputedStyle(e).fontSize));
    if (css.some(f => f < 14)) mal.push('textos del panel ' + css.join('/'));
    document.querySelector('.tab-btn[data-tab="filtros"]').click();
    return {ok: mal.length === 0, info: JSON.stringify(res) + ' · rótulos ' + css.join('/') + ' px', mal}; })()`);

  // Viewport chico de escritorio (800 px): el mapa nunca queda por debajo de 280 px
  await b.send("Emulation.setDeviceMetricsOverride", { width: 800, height: 800, deviceScaleFactor: 1, mobile: false });
  await check("viewport 800 px: mapa ≥ 280 px en todas las pestañas (Curvas incluida) y arrastrando el divisor al máximo", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    await espera(500);
    const m = document.getElementById('map'), res = {};
    for (const t of ['curvas', 'tendencia', 'ranking', 'geo', 'filtros']) {
      document.querySelector('.tab-btn[data-tab="' + t + '"]').click(); await espera(400);
      res[t] = m.offsetWidth;
    }
    const d = document.getElementById('sb-divisor'), r = d.getBoundingClientRect(), y = r.top + 200;
    const ev = (t, cx) => d.dispatchEvent(new PointerEvent(t, {bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse',
      button: 0, buttons: t === 'pointerup' ? 0 : 1, clientX: cx, clientY: y, isPrimary: true}));
    ev('pointerdown', r.left + 4); ev('pointermove', 5000); ev('pointerup', 5000); await espera(300);
    res.arrastre = m.offsetWidth;
    d.dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); await espera(300);
    return {ok: innerWidth === 800 && Object.values(res).every(w => w >= 280), info: JSON.stringify(res)}; })()`);
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await sleep(500);

  // Celular (400 px): sin scroll horizontal en ninguna pestaña, sin divisor ni "Ampliar"
  await b.send("Emulation.setDeviceMetricsOverride", { width: 400, height: 800, deviceScaleFactor: 1, mobile: true });
  await check("celular 400 px: sin scroll horizontal, sin divisor ni Ampliar", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    await espera(400);
    const res = [];
    for (const t of ['filtros', 'tendencia', 'ranking', 'geo', 'curvas']) {
      document.querySelector('.tab-btn[data-tab="' + t + '"]').click(); await espera(500);
      const p = document.getElementById('tab-' + t);
      const de = document.documentElement;
      const bm = document.getElementById('btn-movil'), rb = bm.getBoundingClientRect();
      res.push({t, doc: de.scrollWidth - de.clientWidth, body: document.body.scrollWidth - innerWidth, pane: p.scrollWidth - p.clientWidth,
        panel: document.getElementById('sidebar').offsetWidth, boton: rb.height >= 44 && rb.left >= 0 && rb.right <= innerWidth
          && parseFloat(getComputedStyle(bm).fontSize) >= 14 && bm.textContent === 'Ver mapa'});
    }
    // Ranking en touch: empresa · cuenca hace wrap (sin "…") y la cifra sigue entera en su columna
    document.querySelector('.tab-btn[data-tab="ranking"]').click(); await espera(400);
    const remp = [...document.querySelectorAll('#ranking-list .remp')];
    const cortadas = remp.filter(e => e.scrollWidth > e.clientWidth + 1).length;
    const wrap = remp.length > 0 && getComputedStyle(remp[0]).whiteSpace === 'normal';
    const valMal = [...document.querySelectorAll('#ranking-list .rank-val')].filter(v => v.scrollWidth > v.clientWidth
      || v.getBoundingClientRect().right > v.closest('.rank-row').getBoundingClientRect().right + 0.5).length;
    document.querySelector('.tab-btn[data-tab="filtros"]').click(); await espera(300);
    const ocultos = document.getElementById('sb-divisor').offsetWidth === 0 && document.getElementById('btn-ampliar').offsetWidth === 0;
    const mal = res.filter(x => x.doc > 0 || x.body > 0 || x.pane > 1 || x.panel !== 400 || !x.boton);
    return {ok: mal.length === 0 && ocultos && innerWidth === 400 && wrap && cortadas === 0 && valMal === 0,
      info: 'viewport ' + innerWidth + ' px · panel 400 px y botón "Ver mapa" en las 5 pestañas · ranking: ' + remp.length
        + ' empresas con wrap, ' + cortadas + ' cortadas, ' + valMal + ' cifras mal', mal}; })()`);

  await check("celular 400 px: 'Ver mapa' → mapa a pantalla completa (capas y leyenda enteras, botón sin tapar), 'Ver panel' vuelve; clic en el ranking muestra el mapa", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    const bm = document.getElementById('btn-movil'), m = document.getElementById('map'), sb = document.getElementById('sidebar');
    const dentro = el => { if (!el) return true; const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 0.5 && r.top >= 0 && r.bottom <= innerHeight + 0.5; };
    const pisa = (a, b) => { if (!a || !b) return false; const p = a.getBoundingClientRect(), q = b.getBoundingClientRect();
      return p.left < q.right && q.left < p.right && p.top < q.bottom && q.top < p.bottom; };
    document.querySelector('.tab-btn[data-tab="filtros"]').click(); await espera(300);
    bm.click(); await espera(500);
    const leg = document.querySelector('.legend'), capas = document.querySelector('.leaflet-control-layers'),
          atr = document.querySelector('.leaflet-control-attribution');
    const a = {mapa: m.offsetWidth, leaflet: map.getSize().x, panel: sb.offsetWidth, txt: bm.textContent,
      capas: dentro(capas), leyenda: dentro(leg), atribucion: dentro(atr), tapaLeyenda: pisa(bm, leg), tapaAtrib: pisa(bm, atr)};
    bm.click(); await espera(400);
    const v = {mapa: m.offsetWidth, panel: sb.offsetWidth, txt: bm.textContent};
    document.querySelector('.tab-btn[data-tab="ranking"]').click();
    for (let i = 0; i < 20 && !document.querySelector('#ranking-list .rank-row'); i++) await espera(250);
    document.querySelector('#ranking-list .rank-row').click(); await espera(1800);
    const r = {mapa: m.offsetWidth, panel: sb.offsetWidth, txt: bm.textContent, popup: !!document.querySelector('.leaflet-popup')};
    map.closePopup();
    const ok = a.mapa >= 398 && a.leaflet === a.mapa && a.panel === 0 && a.txt === 'Ver panel' && a.capas && a.leyenda && a.atribucion
      && !a.tapaLeyenda && !a.tapaAtrib && v.panel === 400 && v.mapa === 0 && v.txt === 'Ver mapa'
      && r.mapa >= 398 && r.panel === 0 && r.popup && r.txt === 'Ver panel';
    return {ok, info: 'Ver mapa: ' + JSON.stringify(a) + ' · Ver panel: ' + JSON.stringify(v) + ' · ranking: ' + JSON.stringify(r)}; })()`);
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await sleep(500);

  await check("de celular (con el mapa a pantalla completa) a escritorio: layout coherente", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    await espera(400);
    const sb = document.getElementById('sidebar'), m = document.getElementById('map');
    const ok = !document.body.classList.contains('m-mapa') && !document.body.classList.contains('sb-full')
      && sb.offsetWidth >= 460 && m.offsetWidth >= 280 && map.getSize().x === m.clientWidth
      && document.getElementById('btn-movil').offsetWidth === 0 && document.getElementById('sb-divisor').offsetWidth > 0;
    return {ok, info: 'panel ' + sb.offsetWidth + ' px · mapa ' + m.offsetWidth + ' px'}; })()`);

  await check("cambio de año (2025)", `(async () => {
    const s = document.getElementById('f-year'); s.value = '2025'; s.dispatchEvent(new Event('change'));
    for (let i = 0; i < 80; i++) { await new Promise(r => setTimeout(r, 250));
      if (document.querySelector('.t-year')?.textContent === '2025' && lastFiltered.length > 1000) break; }
    return {ok: document.querySelector('.t-year').textContent === '2025' && lastFiltered.length > 1000,
      info: lastFiltered.length + ' visibles'}; })()`);

  // ── Modo privado (fichas de yacimiento, data/privado/fichas.json, SOLO LOCAL) ──
  // Este archivo va a git: ni nombres ni valores de fichas en el código. Todo sale de fichas.json en tiempo de
  // ejecución y la consola solo dice "ficha ok, N secciones" (los fallos devuelven booleanos y conteos).
  if (HAY_FICHAS) {
    await check("modo privado: insignia 'Privado' y ficha desde el popup de un pozo (idpozo) y desde la capa Yacimientos", `(async () => {
      const espera = ms => new Promise(r => setTimeout(r, ms));
      for (let i = 0; i < 40 && !fichasPriv; i++) await espera(250);
      if (!fichasPriv) return {ok: false, info: 'fichas.json no cargó'};
      const badge = document.querySelector('#sidebar header .privado-badge');
      const badgeOk = !!badge && badge.textContent === 'Privado' && badge.title === 'Datos locales, no se publican'
        && parseFloat(getComputedStyle(badge).fontSize) >= 14;
      const enAnio = new Set(window.POZOS.map(r => r[I.id]));
      const fi = fichasPriv.fichas.find(f => (f.pozos || []).some(id => enAnio.has(id)));
      if (!fi) return {ok: false, info: 'ninguna ficha con pozos en el año'};
      const r = window.POZOS.find(r => fi.pozos.includes(r[I.id]));
      flyToPozo(r[I.id]);
      const sel = '.leaflet-popup .ficha-pop button[onclick*="' + "'" + fi.id + "'" + '"]';
      for (let i = 0; i < 20 && !document.querySelector(sel); i++) await espera(250);
      const btn = document.querySelector(sel);
      if (!btn) return {ok: false, info: 'el popup del pozo de prueba no tiene el botón de ficha'};
      const btnOk = btn.textContent.includes(fi.titulo) && parseFloat(getComputedStyle(btn).fontSize) >= 14;
      btn.click(); await espera(300);
      const m = document.getElementById('ficha-modal');
      const t = m ? m.textContent : '';
      const fecha = m && m.querySelector('.fm-fecha');
      const chicos = m ? [...m.querySelectorAll('*')].filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
        && parseFloat(getComputedStyle(e).fontSize) < 14).length : -1;
      const det = m ? m.querySelectorAll('details').length : 0;
      const fAct = fi.fecha_act || fi.ultimo_dato;
      const unValor = fi.secciones.flatMap(s => s.filas).find(x => /[a-z]/i.test(x.v));
      const modalOk = !!m && !!fecha && !!fAct && fecha.textContent.includes(fAct) && parseFloat(getComputedStyle(fecha).fontSize) >= 16
        && !!unValor && t.includes(unValor.v) && det === fi.secciones.length + (fi.tablas || []).length && det >= 1
        && chicos === 0 && !/NaN|undefined|null/.test(t);
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
      await espera(100);
      const cierra = !document.getElementById('ficha-modal');
      map.closePopup();
      const conPol = fichasPriv.fichas.find(f => f.poligono);
      const yacOk = !conPol || fichaYacHTML(conPol.poligono).includes("abrirFicha('" + conPol.id + "')");
      const conFicha = new Set(Object.keys(fichasPriv.por_yacimiento));
      const otroYac = (pozosGeo ? pozosGeo.tablas.yacimiento : []).find(n => n && !conFicha.has(normYac(n)));
      const sinYacOk = !!otroYac && fichaYacHTML(otroYac) === '';
      const sinFicha = window.POZOS.find(x => !fichasPriv.por_pozo[x[I.id]]);
      const limpio = !/ficha-pop/.test(pozoPopupHTML(sinFicha));
      return {ok: badgeOk && btnOk && modalOk && cierra && yacOk && sinYacOk && limpio,
        info: 'ficha ok, ' + det + ' secciones', badgeOk, btnOk, modalOk, cierra, yacOk, sinYacOk, limpio, chicos}; })()`);
  } else {
    ok++; console.log("✔ modo privado (con archivo) · se omite: " + (LOCAL ? "no existe " + FICHAS : "sitio no local"));
  }

  await check("modo privado: online no se pide (solo localhost)", `({ok: modoPrivadoPermitido('localhost') && modoPrivadoPermitido('127.0.0.1')
    && !modoPrivadoPermitido('pozos-argentina.web.app') && !modoPrivadoPermitido('pozos-argentina.firebaseapp.com'),
    info: 'hostname actual ' + location.hostname})`);

  // Sin el archivo (pedido bloqueado, como si faltara): no aparece nada y no hay errores.
  // Pozos y polígono de prueba: los de una ficha si hay fichas.json local (leídos acá, no escritos en el código).
  const prueba = { pozos: [], poligono: null };
  if (HAY_FICHAS) {
    const fx = JSON.parse(readFileSync(join(ROOT, FICHAS), "utf8"));
    prueba.pozos = fx.fichas.flatMap(f => f.pozos || []);
    prueba.poligono = (fx.fichas.find(f => f.poligono) || {}).poligono || null;
  }
  await b.send("Network.setBlockedURLs", { urls: ["*data/privado/*"] });
  await b.open();
  await check("modo privado: sin data/privado/fichas.json no aparece nada (ni insignia, ni ficha en popups, ni errores)", `(async () => {
    const espera = ms => new Promise(r => setTimeout(r, ms));
    const P = ${JSON.stringify(prueba)};
    await espera(1500);
    const ids = new Set(P.pozos);
    const r = window.POZOS.find(r => ids.has(r[I.id])) || window.POZOS[0];
    const popup = pozoPopupHTML(r);
    const pol = P.poligono || (pozosGeo ? pozosGeo.tablas.yacimiento[0] : 'X');
    const nada = fichasPriv === null && !document.querySelector('.privado-badge') && !document.getElementById('ficha-modal')
      && !/ficha-pop|Ficha de yacimiento/.test(popup) && fichaYacHTML(pol) === ''
      && !/Privado/.test(document.getElementById('sidebar').textContent);
    return {ok: nada, info: 'pozo ' + (ids.has(r[I.id]) ? 'con ficha local' : 'cualquiera') + ' sin botón; fichasPriv = ' + fichasPriv}; })()`);
  await b.send("Network.setBlockedURLs", { urls: [] });

  await sleep(500);
} catch (e) {
  bad++; console.log("✘ carga de la página · " + e.message);
} finally {
  // public/ (lo que se sube a Firebase) sin nada privado: se arma con build_public.mjs y se revisa
  if (LOCAL) {
    try {
      execFileSync(process.execPath, [join(ROOT, "tools/build_public.mjs")], { stdio: "pipe" });
      const pub = join(ROOT, "public");
      const fugas = buscarFugas(pub, ROOT);
      const datos = listar(pub).filter(f => f.startsWith("data/") && readFileSync(join(pub, f), "utf8").includes("privado"));
      const html = readFileSync(join(pub, "index.html"), "utf8");
      const menciones = (html.match(/data\/privado\/[\w.-]+/g) || []);
      const okPub = !fugas.length && !datos.length && menciones.every(x => x === FICHAS);
      if (okPub) { ok++; console.log(`✔ public/ sin datos privados · ${listar(pub).length} archivos, ninguna ruta "privado", ningún dato con "privado", `
        + `0 valores de fichas${HAY_FICHAS ? "" : " (sin fichas locales para comparar)"}; index.html solo nombra ${FICHAS} (fetch local)`); }
      else { bad++; console.log("✘ public/ con datos privados · " + JSON.stringify({ fugas, datos, menciones })); }
    } catch (e) {
      bad++; console.log("✘ public/ sin datos privados · build_public.mjs falló: " + String(e.stderr || e.message).split("\n").slice(0, 4).join(" | "));
    }
  }
  if (b.failed.length) { bad++; console.log("✘ pedidos fallidos:\n  " + b.failed.join("\n  ")); }
  if (b.logs.length) { bad++; console.log("✘ errores de consola:\n  " + b.logs.join("\n  ")); }
  console.log(`\n${ok} bien, ${bad} mal`);
  b.close();
  process.exit(bad ? 1 : 0);
}
