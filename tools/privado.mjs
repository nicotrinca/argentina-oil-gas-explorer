// Guardas del "modo privado" (fichas de yacimiento confidenciales, data/privado/, SOLO LOCAL).
// Lo usan tools/build_public.mjs (falla el build) y tools/check.mjs (chequeo de public/).
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export const FICHAS = "data/privado/fichas.json";

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

// Busca fugas en un directorio publicable: rutas con "privado" o archivos .xlsx, y textos de las fichas.
// Devuelve una lista de problemas (vacía = limpio).
export function buscarFugas(dir, root) {
  const archivos = listar(dir);
  const mal = archivos.filter(f => /privado|\.xlsx$/i.test(f)).map(f => "archivo privado en public/: " + f);
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
