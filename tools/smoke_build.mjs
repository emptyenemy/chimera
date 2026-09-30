// Подключается по CDP к странице собранной программы и выполняет в ней проверки
// (tools/smoke_checks.js). Запускается из tools/smoke_build.py. Без зависимостей:
// WebSocket встроен в Node 22.
//
//   node tools/smoke_build.mjs <cdp-port> <checks.js> [full]
import { readFileSync } from "node:fs";

const [port, checksPath, mode] = process.argv.slice(2);
// full — шаги с правами администратора, которые меняют систему (см. smoke_checks.js)
const checks = (mode === "full" ? "window.__SMOKE_FULL__ = true;\n" : "") + readFileSync(checksPath, "utf8");

const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find(t => t.type === "page" && t.url?.includes("index.html")) || targets.find(t => t.type === "page");
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
await call("Emulation.setDeviceMetricsOverride", { width: 1280, height: 820, deviceScaleFactor: 1, mobile: false });
const res = await call("Runtime.evaluate", { expression: checks, awaitPromise: true, returnByValue: true, timeout: 180000 });
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
