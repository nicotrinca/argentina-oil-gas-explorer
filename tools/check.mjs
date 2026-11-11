// Prueba de humo del visor en Chrome headless. Necesita el servidor en :8765 (abrir.bat o preview_start).
// Uso: node tools/check.mjs        -> imprime ✔/✘ por chequeo y sale con código 1 si algo falla.
import { launch, sleep } from "./cdp.mjs";

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

  await check("pestañas: ninguna desborda su botón (sidebar angosto)", `(() => {
    const b = [...document.querySelectorAll('#tabs .tab-btn')].filter(x => x.scrollWidth > x.clientWidth + 1);
    return {ok: b.length === 0, info: document.getElementById('tabs').offsetHeight + ' px de alto', mal: b.map(x => x.textContent)}; })()`);

  for (const tab of ["tendencia", "ranking", "geo", "curvas", "filtros"]) {
    await check(`pestaña ${tab} abre`, `(async () => {
      document.querySelector('.tab-btn[data-tab="${tab}"]').click();
      await new Promise(r => setTimeout(r, 1500));
      return document.getElementById('tab-${tab}').classList.contains('active'); })()`);
  }
  await check("gráficos de Tendencia y Geo creados", `({ok: !!chartNac && !!chartFrac})`);
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

  await check("cambio de año (2025)", `(async () => {
    const s = document.getElementById('f-year'); s.value = '2025'; s.dispatchEvent(new Event('change'));
    for (let i = 0; i < 80; i++) { await new Promise(r => setTimeout(r, 250));
      if (document.querySelector('.t-year')?.textContent === '2025' && lastFiltered.length > 1000) break; }
    return {ok: document.querySelector('.t-year').textContent === '2025' && lastFiltered.length > 1000,
      info: lastFiltered.length + ' visibles'}; })()`);

  await sleep(500);
} catch (e) {
  bad++; console.log("✘ carga de la página · " + e.message);
} finally {
  if (b.failed.length) { bad++; console.log("✘ pedidos fallidos:\n  " + b.failed.join("\n  ")); }
  if (b.logs.length) { bad++; console.log("✘ errores de consola:\n  " + b.logs.join("\n  ")); }
  console.log(`\n${ok} bien, ${bad} mal`);
  b.close();
  process.exit(bad ? 1 : 0);
}
