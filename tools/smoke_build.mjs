// Подключается по CDP к странице собранной программы и выполняет в ней проверки
// (tools/smoke_checks.js). Запускается из tools/smoke_build.py. Без зависимостей:
// WebSocket встроен в Node 22.
//
//   node tools/smoke_build.mjs <cdp-port> <checks.js> [full]
import { readFileSync, writeFileSync } from "node:fs";

const [port, checksPath, mode, screenshot] = process.argv.slice(2);
// full — шаги с правами администратора, которые меняют систему (см. smoke_checks.js)
const checks = `window.__SMOKE_TG_PORT__ = ${Number(process.env.CHIMERA_SMOKE_TG_PORT) || 19443};\n` + (mode === "full" ? "window.__SMOKE_FULL__ = true;\n" : "") + readFileSync(checksPath, "utf8");

let page;
for (let attempt = 0; attempt < 300 && !page; attempt++) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const candidates = targets.filter(t => t.type === "page" &&
    (t.url?.includes("index.html") || /^http:\/\/127\.0\.0\.1:/.test(t.url || "")));
  page = candidates.find(t => t.title === "Chimera") || candidates[0];
  if (!page) await new Promise(resolve => setTimeout(resolve, 100));
}
if (!page) { console.error("страница программы не найдена"); process.exit(2); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
const call = (method, params = {}) => new Promise(resolve => {
  const n = ++id;
  pending.set(n, resolve);
  ws.send(JSON.stringify({ id: n, method, params }));
});
const errors = [];
ws.onmessage = m => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  else if (msg.method === "Runtime.exceptionThrown") errors.push(msg.params.exceptionDetails?.exception?.description || msg.params.exceptionDetails?.text);
};
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
await call("Runtime.enable");
for (let attempt = 0; attempt < 300; attempt++) {
  const ready = await call("Runtime.evaluate", {
    expression: "typeof api === 'function' && typeof Bridge !== 'undefined' && typeof Bridge.call === 'function' && !!document.querySelector('[data-testid=sidebar]')",
    returnByValue: true,
  });
  if (ready.result?.result?.value) break;
  if (attempt === 299) {
    const diagnostic = await call("Runtime.evaluate", {
      expression: "JSON.stringify({ title: document.title, origin: location.origin, state: document.readyState, api: typeof api, body: document.body?.className, http: !!window.__CHIMERA_HTTP__, text: document.body?.innerText.slice(0, 200) })",
      returnByValue: true,
    });
    throw new Error("интерфейс окна не загрузился: " + diagnostic.result?.result?.value + "; " + errors.join("; "));
  }
  await new Promise(resolve => setTimeout(resolve, 100));
}
await call("Emulation.setDeviceMetricsOverride", { width: 1280, height: 820, deviceScaleFactor: 1, mobile: false });
// WebView2 не всегда ожидает Promise в Runtime.evaluate. Результат читается
// отдельным синхронным вызовом после завершения проверок.
await call("Runtime.evaluate", {
  expression: `window.__chimeraSmokeResult = null; Promise.resolve((0, eval)(${JSON.stringify(checks)})).then(value => { window.__chimeraSmokeResult = { value }; }, error => { window.__chimeraSmokeResult = { error: String(error?.stack || error) }; }); "started"`,
  returnByValue: true,
});
let res;
for (let attempt = 0; attempt < 1800; attempt++) {
  res = await call("Runtime.evaluate", { expression: "JSON.stringify(window.__chimeraSmokeResult)", returnByValue: true });
  const serialized = res.result?.result?.value;
  if (typeof serialized === "string" && serialized !== "null") {
    const result = JSON.parse(serialized);
    if (result.error) throw new Error(result.error);
    res = { result: { result: { value: result.value } } };
    break;
  }
  await new Promise(resolve => setTimeout(resolve, 100));
  if (attempt === 1799) throw new Error("проверки не завершились за три минуты");
}
if (screenshot) {
  await call("Runtime.evaluate", { expression: "Pages.go('dashboard')" });
  await new Promise(resolve => setTimeout(resolve, 500));
  const capture = await call("Page.captureScreenshot", { format: "png" });
  if (!capture.result?.data) throw new Error(JSON.stringify(capture.error));
  writeFileSync(screenshot, Buffer.from(capture.result.data, "base64"));
}
ws.close();
const value = res.result?.result?.value;
if (!value) {
  console.error("проверки не выполнились:", JSON.stringify(res.result?.exceptionDetails || res.error || res).slice(0, 500));
  process.exit(2);
}
// WebView2 может вернуть сериализованный результат уже разобранным.
const steps = typeof value === "string" ? JSON.parse(value) : value;
if (!Array.isArray(steps) || !steps.length || steps.some(s => typeof s.ok !== "boolean")) {
  console.error("неверный результат проверок:", JSON.stringify(value).slice(0, 1000));
  process.exit(2);
}
console.log(JSON.stringify({ steps, pageErrors: errors }));
