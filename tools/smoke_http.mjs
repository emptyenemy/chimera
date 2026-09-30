// Проверка собранного фронта в headless Edge через HTTP-мост; своего окна нет.
import { spawn } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

const [browser, url, checksPath, mode] = process.argv.slice(2)
const profile = mkdtempSync(join(tmpdir(), "chimera-http-smoke-"))
const proc = spawn(browser, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { stdio: ["ignore", "ignore", "pipe"] })
let ws
try {
  const address = await new Promise((resolve, reject) => {
    let output = ""
    const timeout = setTimeout(() => reject(new Error("Headless browser did not start")), 20000)
    proc.once("exit", code => { clearTimeout(timeout); reject(new Error(`Browser exited: ${code}`)) })
    proc.stderr.on("data", d => {
      output += d
      const match = output.match(/DevTools listening on (ws:\/\/\S+)/)
      if (match) { clearTimeout(timeout); resolve(match[1]) }
    })
  })
  const port = new URL(address).port
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json()
  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject })
  let seq = 0
  const pending = new Map(), errors = []
  ws.onmessage = event => {
    const message = JSON.parse(event.data)
    if (message.id) { pending.get(message.id)?.(message); pending.delete(message.id) }
    else if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails?.exception?.description || message.params.exceptionDetails?.text)
  }
  const call = (method, params = {}) => new Promise(resolve => {
    const id = ++seq
    pending.set(id, resolve)
    ws.send(JSON.stringify({ id, method, params }))
  })
  await call("Runtime.enable")
  await call("Page.enable")
  await call("Emulation.setDeviceMetricsOverride", { width: 1280, height: 820, deviceScaleFactor: 1, mobile: false })
  await call("Page.navigate", { url })
  for (let attempt = 0; attempt < 300; attempt++) {
    const ready = await call("Runtime.evaluate", { expression: "document.body?.classList.contains('ready')", returnByValue: true })
    if (ready.result?.result?.value) break
    if (attempt === 299) throw new Error("Interface did not become ready")
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  const checks = (mode === "full" ? "window.__SMOKE_FULL__=true;\n" : "") + readFileSync(checksPath, "utf8")
  const result = await call("Runtime.evaluate", { expression: checks, awaitPromise: true, returnByValue: true, timeout: 180000 })
  const value = result.result?.result?.value
  if (!value) throw new Error(JSON.stringify(result.result?.exceptionDetails || result.error))
  console.log(JSON.stringify({ steps: JSON.parse(value), pageErrors: errors }))
} finally {
  ws?.close()
  proc.kill()
  await new Promise(resolve => setTimeout(resolve, 500))
  rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
}
