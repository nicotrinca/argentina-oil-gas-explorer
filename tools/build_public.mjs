// Arma public/ para Firebase Hosting: index.html + SOLO los datos que pide el visor (whitelist).
// data/ pesa ~1,8 GB con CSV crudos y shapefiles que no se suben.
// Uso (desde cualquier carpeta): node tools/build_public.mjs
import { rmSync, mkdirSync, copyFileSync, existsSync, statSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "public");

// Archivos fijos que pide index.html (fetch, lazyGeo, <script src>).
// No van: data/pozos.js y data/pozos_produccion.geojson (el visor no los pide), CSV, shapefiles, top_empresas.json.
const FIJOS = [
  "index.html",
  "data/areas.geojson",
  "data/cuencas.geojson",
  "data/gasoductos.geojson",
  "data/refinerias.geojson",
  "data/yacimientos.geojson",
  "data/permisos.geojson",
  "data/sparklines.json",
  "data/serie_nacional.json",
  "data/serie_cuencas.json",
  "data/serie_empresas.json",
  "data/cuencas_stats.json",
  "data/ranking.json",
  "data/pozos_geo.json",
  "data/fractura.json",
  "data/geo_qa.json",
  "data/curvas.json",
  "data/curvas_pozos.json",
];

// data/pozos_${yr}.js: un archivo por cada año del selector #f-year de index.html.
const html = readFileSync(join(ROOT, "index.html"), "utf8");
const sel = html.match(/<select id="f-year">([\s\S]*?)<\/select>/);
if (!sel) { console.error("✘ No encontré <select id=\"f-year\"> en index.html"); process.exit(1); }
const anios = [...sel[1].matchAll(/value="(\d{4})"/g)].map(m => m[1]);
if (!anios.length) { console.error("✘ El selector #f-year no tiene años"); process.exit(1); }
const ARCHIVOS = [...FIJOS, ...anios.map(a => `data/pozos_${a}.js`)];

// Aviso si index.html menciona un data/... literal que no está en la lista (posible archivo nuevo sin sumar).
const citados = new Set([...html.matchAll(/data\/[\w.-]+\.(?:json|geojson|js)/g)].map(m => m[0]));
const fuera = [...citados].filter(f => !ARCHIVOS.includes(f));
if (fuera.length) console.warn("⚠ index.html menciona archivos fuera de la whitelist: " + fuera.join(", "));

const faltan = ARCHIVOS.filter(f => !existsSync(join(ROOT, f)));
if (faltan.length) {
  console.error("✘ Faltan archivos que pide el visor (corré los preprocess_*.py):\n  " + faltan.join("\n  "));
  process.exit(1);
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(join(OUT, "data"), { recursive: true });

let total = 0;
const mb = n => (n / 1048576).toFixed(2).padStart(7) + " MB";
for (const f of ARCHIVOS) {
  copyFileSync(join(ROOT, f), join(OUT, f));
  const n = statSync(join(OUT, f)).size;
  total += n;
  console.log(mb(n) + "  " + f);
}
console.log("─".repeat(40));
console.log(mb(total) + "  total (" + ARCHIVOS.length + " archivos) en " + OUT);
