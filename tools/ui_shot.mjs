// Headless-браузер по CDP для проверки интерфейса без окна (запускается из
// tools/ui_preview.py shot). Без зависимостей: WebSocket встроен в Node 22.
//
//   node tools/ui_shot.mjs <browser.exe> <url> <out_dir> [scenario.json]
//
// Сценарий — JSON-массив шагов, выполняются по порядку:
//   { "go": "dns" }                 — открыть страницу (Pages.go)
//   { "wait": 500 }                 — подождать, мс
//   { "click": "css-селектор" }     — клик по элементу (el.click())
//   { "eval": "js-выражение" }      — выполнить в странице, результат печатается
//   { "shot": "имя.png" }           — скриншот видимой области в out_dir
//   { "full": "имя.png" }           — скриншот всей страницы (высота контента)
//   { "size": [1280, 800] }         — размер окна
// Без сценария: обойти все страницы и снять каждую ({id}.png).
// Ошибки JS и console.error печатаются с пометкой [ошибка страницы].

import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , browserExe, url, outDir, scenarioPath] = process.argv;
const profile = mkdtempSync(join(tmpdir(), "chimera-shot-"));
const W = 1280, H = 820;

const proc = spawn(browserExe, [
  "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio",
  "--no-first-run", "--no-default-browser-check", `--user-data-dir=${profile}`,
  "--remote-debugging-port=0", `--window-size=${W},${H}`, "about:blank",
], { stdio: ["ignore", "ignore", "pipe"] });

const wsUrl = await new Promise((resolve, reject) => {
  let buf = "";
  const t = setTimeout(() => reject(new Error("браузер не ответил")), 15000);
  proc.stderr.on("data", d => {
    buf += d;
    const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
    if (m) { clearTimeout(t); resolve(m[1]); }
  });
});
const port = new URL(wsUrl).port;
const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r, { once: true }));

let seq = 0;
const pending = new Map();
let errors = 0;
ws.addEventListener("message", ev => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  } else if (msg.method === "Runtime.exceptionThrown") {
    errors++;
    const d = msg.params.exceptionDetails;
    console.log("[ошибка страницы]", d.exception?.description || d.text, `@${d.url || ""}:${d.lineNumber}`);
  } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
    errors++;
    console.log("[ошибка страницы] console.error:", msg.params.args.map(a => a.value ?? a.description).join(" "));
  }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
const sleep = ms => new Promise(r => setTimeout(r, ms));
const evaluate = async expr => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
};
const shot = async (name, full = false) => {
  let clip;
  if (full) {
    const h = await evaluate("Math.max(document.getElementById('main')?.scrollHeight || 0, innerHeight)");
    await send("Emulation.setDeviceMetricsOverride", { width: W, height: h, deviceScaleFactor: 1, mobile: false });
    await sleep(150);
  }
  const r = await send("Page.captureScreenshot", { format: "png", clip });
  writeFileSync(join(outDir, name), Buffer.from(r.data, "base64"));
  if (full) await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  console.log("снимок:", join(outDir, name));
};

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url });
  await sleep(1500);
  // ждём, пока ядро поднимется (boot() ставит body.ready)
  for (let i = 0; i < 50 && !(await evaluate("document.body?.classList.contains('ready')")); i++) await sleep(100);

  let steps = scenarioPath ? JSON.parse(readFileSync(scenarioPath, "utf8")) : null;
  if (!steps) {
    const ids = await evaluate("Pages.list.map(p => p.id)");
    steps = ids.flatMap(id => [{ go: id }, { wait: 900 }, { shot: `${id}.png` }]);
  }
  for (const s of steps) {
    if (s.go) await evaluate(`Pages.go(${JSON.stringify(s.go)})`);
    else if (s.wait) await sleep(s.wait);
    else if (s.click) await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(s.click)}); if (!el) throw new Error("нет элемента: " + ${JSON.stringify(s.click)}); el.click(); })()`);
    else if (s.eval) console.log("eval:", JSON.stringify(await evaluate(s.eval)));
    else if (s.shot) await shot(s.shot);
    else if (s.full) await shot(s.full, true);
    else if (s.size) await send("Emulation.setDeviceMetricsOverride", { width: s.size[0], height: s.size[1], deviceScaleFactor: 1, mobile: false });
  }
  console.log(errors ? `ошибок страницы: ${errors}` : "ошибок страницы нет");
} catch (e) {
  console.log("сбой сценария:", e.message);
  process.exitCode = 1;
} finally {
  try { ws.close(); } catch {}
  proc.kill();
  await sleep(300);
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
}
