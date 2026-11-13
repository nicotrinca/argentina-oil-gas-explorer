// Guardas del "modo privado" (fichas de yacimiento confidenciales y base comercial licenciada, data/privado/, SOLO LOCAL).
// Lo usan tools/build_public.mjs (falla el build) y tools/check.mjs (chequeo de public/).
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export const FICHAS = "data/privado/fichas.json";
export const BASE_COM = "data/privado/base_comercial.json";

// Archivos (recursivo) de un directorio, con ruta relativa a él y separador "/".
export function listar(dir, base = dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap(n => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? listar(p, base) : [relative(base, p).replace(/\\/g, "/")];
  });
}

// Textos propios de las fichas que no deberían aparecer en ningún archivo publicado: nombres de hoja y de ficha y
// textos con letras de ≥ 12 caracteres, o ≥ 10 con espacio (descripciones, notas, temas) y fechas
// dd/mm/aaaa anteriores a 2000. Se distinguen mayúsculas (los nombres del Cap. IV vienen en MAYÚSCULAS).
export function valoresDistintivos(root) {
  const p = join(root, FICHAS);
  if (!existsSync(p)) return [];
  const d = JSON.parse(readFileSync(p, "utf8"));
  const s = new Set(["nombre_ficha"]);
  const agregar = v => {
    if (typeof v !== "string") return;
    if ((/[a-záéíóúñ]/i.test(v) && (v.length >= 12 || (v.length >= 10 && / /.test(v.trim())))) || /^\d\d\/\d\d\/19\d\d$/.test(v)) s.add(v);
  };
  for (const f of d.fichas || []) {
    agregar(f.hoja); agregar(f.nombre_ficha);
    (f.cabecera || []).forEach(x => agregar(x.v));
    (f.secciones || []).forEach(sec => sec.filas.forEach(x => agregar(x.v)));
    (f.tablas || []).forEach(t => t.filas.forEach(fila => fila.forEach(agregar)));
  }
  return [...s].filter(v => v && v.length >= 5);
}

// Valores propios de la base comercial (data/privado/base_comercial.json), para buscarlos en public/:
// - textos: nombres oficiales con minúsculas y espacio (los alternativos no: coinciden con siglas públicas), como
//   literal entre comillas;
// - libres: textos libres de ≥ 20 caracteres (ensayos, comentarios, notas), como SUBSTRING en cualquier parte;
// - ids: ids propios de la base (8+ dígitos);
// - huellas: muestra de pares idpozo → [TD, spud] que el script eligió distintos de los del Cap. IV (público).
// Son decenas de miles: se buscan con Set/Map por tokens, no con un includes() por valor.
const TOKEN = /\p{L}[\p{L}\p{N}]*/gu;
const claveTexto = t => (t.match(TOKEN) || []).slice(0, 4).join("\u0001");

export function valoresBaseComercial(root) {
  const p = join(root, BASE_COM);
  if (!existsSync(p)) return null;
  const d = JSON.parse(readFileSync(p, "utf8"));
  const ix = c => d.campos.indexOf(c);
  const iN = ix("nombre"), iU = ix("uid");
  const iL = ["ensayo", "comentario", "obj_nota", "prof_nota"].map(ix).filter(i => i >= 0);
  const textos = new Set(), ids = new Set(), libres = new Map();
  for (const f of Object.values(d.pozos || {})) {
    const n = f[iN], u = f[iU];
    if (typeof n === "string" && /[a-z]/.test(n) && / /.test(n.trim()) && n.length >= 8) textos.add(n);
    if (u != null && /^\d{8,}$/.test(String(u))) ids.add(String(u));
    for (const i of iL) {
      const t = f[i];
      if (typeof t !== "string" || t.length < 20 || (t.match(TOKEN) || []).length < 3) continue;
      const k = claveTexto(t);
      if (!libres.has(k)) libres.set(k, new Set());
      libres.get(k).add(t);
    }
  }
  const huellas = new Map((d.huellas || []).map(([id, td, sp]) => [String(id), { td, sp }]));
  return { textos, ids, libres, huellas };
}

// Primer valor de la base que aparece en un texto: nombre como literal, id propio, o texto libre como substring.
function hitBaseComercial(txt, vb) {
  for (const m of txt.matchAll(/(["'`])((?:(?!\1)[^\\\n]|\\.){8,400})\1/g)) {
    const v = m[2].replace(/\\(["'`\\/])/g, "$1");
    if (vb.textos.has(v)) return v;
  }
  for (const m of txt.matchAll(/\d{8,}/g)) if (vb.ids.has(m[0])) return m[0];
  if (vb.libres.size) {
    const toks = txt.match(TOKEN) || [];
    for (let i = 0; i < toks.length; i++) {
      const cands = vb.libres.get(toks.slice(i, i + 4).join("\u0001"))
        || vb.libres.get(toks.slice(i, i + 3).join("\u0001"));
      if (!cands) continue;
      for (const t of cands) {
        if (txt.includes(t) || txt.includes(JSON.stringify(t).slice(1, -1))) return t;
      }
    }
  }
  return null;
}

// Pares idpozo ↔ valor de la base: cuántos idpozo de la muestra tienen cerca (±120 caracteres) su TD exacta (como
// número) o su spud (aaaa-mm-dd o dd/mm/aaaa). Hay fuga si son ≥ 20 y ≥ 20 % de los idpozo de la muestra que aparecen
// en el archivo (por azar, un número vecino puede coincidir con la TD de unos pocos).
export function paresBaseComercial(txt, vb) {
  let ids = 0, hits = 0;
  if (!vb.huellas.size) return { fuga: false, ids, hits };
  const vistos = new Set();
  for (const m of txt.matchAll(/(?<![\d.])\d{1,7}(?![\d.])/g)) {
    const h = vb.huellas.get(m[0]);
    if (!h || vistos.has(m[0])) continue;
    vistos.add(m[0]);
    ids++;
    const w = txt.slice(Math.max(0, m.index - 120), m.index + m[0].length + 120);
    let ok = false;
    if (h.td != null) {
      const td = Number(h.td);
      for (const n of w.matchAll(/(?<![\d.])\d+(?:\.\d+)?(?![\d.])/g)) if (Math.abs(Number(n[0]) - td) < 0.01) { ok = true; break; }
    }
    if (!ok && h.sp) {
      const [y, mo, d] = h.sp.split("-");
      ok = w.includes(h.sp) || w.includes(`${d}/${mo}/${y}`);
    }
    if (ok) hits++;
  }
  return { fuga: hits >= 20 && hits >= 0.2 * ids, ids, hits };
}

// Busca fugas en un directorio publicable: rutas con "privado", "base_comercial" o archivos .xlsx, textos de las
// fichas y valores de la base comercial. Devuelve una lista de problemas (vacía = limpio).
export function buscarFugas(dir, root) {
  const archivos = listar(dir);
  const mal = archivos.filter(f => /privado|base_comercial|\.xlsx$/i.test(f)).map(f => "archivo privado en public/: " + f);
  const vb = valoresBaseComercial(root);
  if (vb) {
    for (const f of archivos) {
      const txt = readFileSync(join(dir, f), "utf8");
      const hit = hitBaseComercial(txt, vb);
      if (hit) mal.push(`valor de la base comercial en public/${f}: "${hit.slice(0, 3)}…" (${hit.length} caracteres)`);
      const par = paresBaseComercial(txt, vb);
      if (par.fuga) mal.push(`pares idpozo-valor de la base comercial en public/${f}: ${par.hits} de ${par.ids} pozos de muestra`);
    }
  }
  const vals = valoresDistintivos(root);
  if (vals.length) {
    for (const f of archivos) {
      const txt = readFileSync(join(dir, f), "utf8");
      const hit = vals.find(v => txt.includes(v));
      if (hit) mal.push(`valor de una ficha privada en public/${f}: "${hit.slice(0, 40)}"`);
    }
  }
  return mal;
}
