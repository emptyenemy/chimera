// Подключается по CDP к странице собранной программы и выполняет в ней проверки
// (tools/smoke_checks.js). Запускается из tools/smoke_build.py. Без зависимостей:
// WebSocket встроен в Node 22.
//
//   node tools/smoke_build.mjs <cdp-port> <checks.js>
import { readFileSync } from "node:fs";

const [port, checksPath] = process.argv.slice(2);
const checks = readFileSync(checksPath, "utf8");

const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find(t => t.type === "page");
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
const res = await call("Runtime.evaluate", { expression: checks, awaitPromise: true, returnByValue: true, timeout: 180000 });
ws.close();
const value = res.result?.result?.value;
if (!value) {
  console.error("проверки не выполнились:", JSON.stringify(res.result?.exceptionDetails || res.error || res).slice(0, 500));
  process.exit(2);
}
console.log(JSON.stringify({ steps: JSON.parse(value), pageErrors: errors }));
