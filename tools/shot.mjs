// Captura del visor en Chrome headless. Necesita el servidor en :8765.
// Uso: node tools/shot.mjs <salida.png> [pestaña] [ancho] ["js a ejecutar antes de capturar"]
//   pestaña: filtros (mapa) | tendencia | ranking | geo | ...   ancho por defecto 1440 (390 = celular)
// Ej.: node tools/shot.mjs capturas/qa/x/geo.png geo
//      node tools/shot.mjs capturas/qa/x/popup.png filtros 1440 "flyToPozo(lastFiltered.find(r=>r[I.pet]>5000)[I.id])"
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { launch, sleep } from "./cdp.mjs";

const [out, tab = "filtros", ancho = "1440", js] = process.argv.slice(2);
if (!out) { console.error("uso: node tools/shot.mjs <salida.png> [pestaña] [ancho] [js]"); process.exit(2); }
mkdirSync(dirname(out), { recursive: true });
const b = await launch({ width: +ancho, height: +ancho < 700 ? 844 : 900 });
try {
  await b.open();
  await b.evalJS(`document.querySelector('.tab-btn[data-tab="${tab}"]').click(); true`);
  await sleep(1500);
  if (js) { await b.evalJS(`(async () => { ${js}; })()`); await sleep(3000); }
  await sleep(1500);   // teselas del mapa
  await b.shot(out);
  console.log("captura: " + out);
  if (b.failed.length) console.log("pedidos fallidos:\n  " + b.failed.join("\n  "));
  if (b.logs.length) console.log("errores de consola:\n  " + b.logs.join("\n  "));
} finally { b.close(); }
