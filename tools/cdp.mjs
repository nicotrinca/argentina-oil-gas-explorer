// Chrome sin ventana manejado por DevTools Protocol: lo usan check.mjs y shot.mjs.
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Chrome/Edge/Chromium: primero CHROME_PATH (si está definida), después rutas estándar de Windows, Linux y macOS.
const CHROMES = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  "/snap/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);
// En CI con Linux (GitHub Actions, Ubuntu 24.04) el sandbox de Chrome no arranca por AppArmor: sin sandbox.
// Solo abre http://localhost, así que no hay riesgo. CHROME_NO_SANDBOX=1 lo fuerza en otros entornos.
const SIN_SANDBOX = process.platform === "linux" && (process.env.CI || process.env.CHROME_NO_SANDBOX === "1");
export const sleep = ms => new Promise(r => setTimeout(r, ms));
export const BASE = process.env.POZOS_URL || "http://localhost:8765/";

// Cada corrida usa su propio user-data-dir y deja que Chrome elija un puerto libre
// (--remote-debugging-port=0): el puerto real se lee de <dir>/DevToolsActivePort. Así dos check/shot
// en paralelo nunca se enganchan al Chrome del otro. Si se pasa `port`, se usa ese (sólo para depurar).
export async function launch({ port = 0, width = 1440, height = 900 } = {}) {
  const chrome = CHROMES.find(existsSync);
  if (!chrome) throw new Error("no encontré Chrome ni Edge (definí CHROME_PATH con la ruta al ejecutable)");
  const dir = mkdtempSync(join(tmpdir(), "pozos-"));
  const proc = spawn(chrome, ["--headless=new", "--disable-gpu", "--hide-scrollbars", `--remote-debugging-port=${port}`,
    `--user-data-dir=${dir}`, `--window-size=${width},${height}`, "--no-first-run", "--no-default-browser-check",
    ...(SIN_SANDBOX ? ["--no-sandbox", "--disable-dev-shm-usage"] : []),
    "about:blank"], { stdio: "ignore" });
  const portFile = join(dir, "DevToolsActivePort");
  let target, realPort = port || null;
  for (let i = 0; i < 60 && !target; i++) {
    await sleep(300);
    if (!realPort) {
      try { realPort = +readFileSync(portFile, "utf8").split(/\r?\n/)[0] || null; } catch {}
      if (!realPort) continue;
    }
    try { target = (await (await fetch(`http://127.0.0.1:${realPort}/json`)).json()).find(t => t.type === "page"); } catch {}
  }
  if (!target) { proc.kill(); throw new Error("Chrome headless no respondió"); }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0; const pending = new Map(), logs = [], failed = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown")
      logs.push("EXCEPCIÓN: " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error")
      logs.push("console.error: " + m.params.args.map(a => a.value ?? a.description).join(" "));
    if (m.method === "Network.responseReceived" && m.params.response.status >= 400
        && !m.params.response.url.endsWith("/favicon.ico"))
      failed.push(`${m.params.response.status} ${m.params.response.url}`);
    if (m.method === "Network.loadingFailed" && !m.params.canceled)
      failed.push(`FALLÓ ${m.params.errorText} (requestId ${m.params.requestId})`);
  };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const evalJS = async (expr, timeout = 120000) => {
    const r = await Promise.race([send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }),
      sleep(timeout).then(() => ({ timeout: true }))]);
    if (r.timeout) throw new Error("tiempo agotado evaluando en la página");
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
    return r.result?.result?.value;
  };
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  // Abre la página y espera a que estén los pozos y los datos async principales
  const open = async (url = BASE) => {
    await send("Page.navigate", { url });
    for (let i = 0; i < 160; i++) {
      await sleep(250);
      const ok = await evalJS(`document.readyState === 'complete' && !!window.POZOS && typeof sparkData !== 'undefined'
        && !!sparkData && typeof lastFiltered !== 'undefined' && lastFiltered.length > 0`).catch(() => false);
      if (ok) return;
    }
    throw new Error("la página no terminó de cargar: " + url);
  };
  const shot = async (path, clip) => {
    const { writeFileSync } = await import("node:fs");
    const r = await send("Page.captureScreenshot", { format: "png", ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
    writeFileSync(path, Buffer.from(r.result.data, "base64"));
  };
  return { send, evalJS, open, shot, logs, failed, port: realPort, close: () => {
    ws.close(); proc.kill();
    setTimeout(() => { try { rmSync(dir, { recursive: true, force: true }); } catch {} }, 1500).unref?.();
  } };
}
