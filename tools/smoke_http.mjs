// Проверка собранного фронта в headless Edge через HTTP-мост; своего окна нет.
import { spawn, spawnSync } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"

const [browser, url, checksPath, mode, screenshot] = process.argv.slice(2)
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
    else if (message.method === "Runtime.bindingCalled" && message.params.name === "__smokeSystemMode") {
      void call("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: message.params.payload }] })
    }
    else if (message.method === "Runtime.bindingCalled" && message.params.name === "__smokePointer") {
      void (async () => {
        const { id, ...event } = JSON.parse(message.params.payload)
        await call("Input.dispatchMouseEvent", { button: "left", pointerType: "mouse", ...event })
        await call("Runtime.evaluate", { expression: `window.__SMOKE_POINTER_DONE__ = ${Number(id)}` })
      })()
    }
    else if (message.method === "Runtime.bindingCalled" && message.params.name === "__smokeViewport") {
      void (async () => {
        const { id, width, height } = JSON.parse(message.params.payload)
        await call("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false })
        await call("Runtime.evaluate", { expression: `window.__SMOKE_VIEWPORT_DONE__ = ${Number(id)}` })
      })()
    }
    else if (message.method === "Runtime.bindingCalled" && message.params.name === "__smokeKey") {
      void (async () => {
        await call("Input.dispatchKeyEvent", { type: "keyDown", key: message.params.payload, code: message.params.payload, windowsVirtualKeyCode: 39 })
        await call("Input.dispatchKeyEvent", { type: "keyUp", key: message.params.payload, code: message.params.payload, windowsVirtualKeyCode: 39 })
      })()
    }
  }
  const call = (method, params = {}) => new Promise(resolve => {
    const id = ++seq
    pending.set(id, resolve)
    ws.send(JSON.stringify({ id, method, params }))
  })
  await call("Runtime.enable")
  await call("Runtime.addBinding", { name: "__smokeSystemMode" })
  await call("Runtime.addBinding", { name: "__smokeKey" })
  await call("Runtime.addBinding", { name: "__smokePointer" })
  await call("Runtime.addBinding", { name: "__smokeViewport" })
  await call("Page.addScriptToEvaluateOnNewDocument", { source: `requestAnimationFrame(() => { window.__SMOKE_FIRST_FRAME__ = { palette: document.documentElement.dataset.palette, background: getComputedStyle(document.documentElement).getPropertyValue('--background').trim() }; });` })
  await call("Page.enable")
  await call("Emulation.setDeviceMetricsOverride", { width: 1280, height: 820, deviceScaleFactor: 1, mobile: false })
  await call("Page.navigate", { url })
  for (let attempt = 0; attempt < 300; attempt++) {
    const ready = await call("Runtime.evaluate", { expression: "document.body?.classList.contains('ready')", returnByValue: true })
    if (ready.result?.result?.value) break
    if (attempt === 299) throw new Error("Interface did not become ready")
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  const checks = `window.__SMOKE_TG_PORT__ = ${Number(process.env.CHIMERA_SMOKE_TG_PORT) || 19443};\n` + (mode === "full" ? "window.__SMOKE_FULL__=true;\n" : "") + readFileSync(checksPath, "utf8")
  const result = await call("Runtime.evaluate", { expression: checks, awaitPromise: true, returnByValue: true, timeout: 180000 })
  const value = result.result?.result?.value
  if (!value) throw new Error(JSON.stringify(result.result?.exceptionDetails || result.error))
  if (screenshot) {
    const capture = await call("Page.captureScreenshot", { format: "png" })
    writeFileSync(screenshot, Buffer.from(capture.result.data, "base64"))
  }
  console.log(JSON.stringify({ steps: JSON.parse(value), pageErrors: errors }))
} finally {
  ws?.close()
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore", timeout: 10000 })
  } else proc.kill()
  await new Promise(resolve => setTimeout(resolve, 500))
  if (dirname(resolve(profile)) !== resolve(tmpdir())) throw new Error("Unsafe browser profile cleanup path")
  try {
    rmSync(profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 250 })
  } catch (error) {
    if (!["EPERM", "EBUSY", "ENOTEMPTY"].includes(error.code)) throw error
    process.stderr.write(`Browser profile cleanup deferred (${error.code}): ${profile}\n`)
  }
}
