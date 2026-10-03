/* Мост к Python (ui/api.py: Api.dispatch) — тот же контракт, что у старого фронта
   (ui/web/js/core.js). Движков три, снаружи всё одно: Bridge.call(method, argsJson)
   -> Promise<resultJson>, а пуши приходят в обработчики onPush(fn, handler).

   Транспорты:
     • Qt WebChannel (PySide6): слот bridge.call(id, ...) отвечает сигналом resolved;
     • pywebview: window.pywebview.api.call, пуши — вызовом window.<fn>(payload);
     • HTTP (backend_browser.py): POST /api и long-poll GET /events, маркер
       window.__CHIMERA_HTTP__ пишет сам сервер (pywebview тоже отдаёт страницу по http). */

import { errorMessage, t, type Params } from "@/lib/i18n"

interface QtBridge {
  call(id: string, method: string, argsJson: string): void
  resolved: { connect(cb: (id: string, resultJson: string) => void): void }
  pushed: { connect(cb: (fn: string, payloadJson: string) => void): void }
}

declare global {
  interface Window {
    qt?: { webChannelTransport?: unknown }
    QWebChannel?: new (
      transport: unknown,
      ready: (channel: { objects: { bridge: QtBridge } }) => void
    ) => unknown
    pywebview?: { api?: { call(method: string, argsJson: string): Promise<string> } }
    __CHIMERA_HTTP__?: boolean
    __CHIMERA_TOKEN__?: string
    __CHIMERA_MOCK__?: { call(method: string, argsJson: string): Promise<string> }
  }
}

export interface BridgeApi {
  call: ((method: string, argsJson: string) => Promise<string>) | null
}

export const Bridge: BridgeApi = { call: null }

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

export function initBridge(): Promise<void> {
  if (window.__CHIMERA_MOCK__) {
    const mock = window.__CHIMERA_MOCK__
    Bridge.call = (m, a) => mock.call(m, a)
    return Promise.resolve()
  }
  if (window.qt?.webChannelTransport) return initQtBridge()
  if (window.__CHIMERA_HTTP__) return initHttpBridge()
  return initWebviewBridge()
}

// PySide6: слот bridge.call(callId, ...) отвечает сигналом resolved(callId, ...).
function initQtBridge(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!window.QWebChannel) return reject(new Error("qwebchannel.js не загружен"))
    new window.QWebChannel(window.qt!.webChannelTransport, (channel) => {
      try {
        const bridge = channel.objects.bridge
        if (!bridge) throw new Error(t("bridge.notReady"))
        const pending = new Map<string, (json: string) => void>()
        let seq = 0
        bridge.resolved.connect((id, resultJson) => {
          const done = pending.get(id)
          if (done) {
            pending.delete(id)
            done(resultJson)
          }
        })
        bridge.pushed.connect((fn, payloadJson) => {
          let payload: unknown
          try {
            payload = JSON.parse(payloadJson)
          } catch {
            return
          }
          deliverPush(fn, payload)
        })
        Bridge.call = (method, argsJson) =>
          new Promise((done, fail) => {
            const id = String(++seq)
            pending.set(id, done)
            try {
              bridge.call(id, method, argsJson)
            } catch (error) {
              pending.delete(id)
              fail(error)
            }
          })
        resolve()
      } catch (error) {
        reject(error)
      }
    })
  })
}

// pywebview: js_api отдаёт промис, пуши приходят вызовом window.<fn>() (evaluate_js).
function initWebviewBridge(): Promise<void> {
  return new Promise((resolve) => {
    const ready = () => {
      Bridge.call = (method, argsJson) => window.pywebview!.api!.call(method, argsJson)
      resolve()
    }
    if (window.pywebview?.api) ready()
    else window.addEventListener("pywebviewready", ready, { once: true })
  })
}

// Браузерный режим: JSON-RPC по POST /api и long-poll /events. Токен выдан один раз
// в адресе, дальше ходит заголовком и из адреса убирается.
function initHttpBridge(): Promise<void> {
  const token = window.__CHIMERA_TOKEN__ || new URLSearchParams(location.search).get("t") || ""
  if (location.search) history.replaceState(null, "", location.pathname + location.hash)
  Bridge.call = (method, argsJson) =>
    fetch("/api", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Chimera-Token": token },
      body: JSON.stringify({ method, args: argsJson }),
    }).then((r) => {
      if (!r.ok) throw new Error(t("bridge.failed", { status: r.status }))
      return r.text()
    })
  void pumpEvents(token)
  return Promise.resolve()
}

// long-poll очереди пушей; он же heartbeat — пропала вкладка, сервер гасит программу
async function pumpEvents(token: string): Promise<void> {
  let cursor = 0
  for (;;) {
    try {
      const r = await fetch(`/events?since=${cursor}`, { headers: { "X-Chimera-Token": token } })
      if (!r.ok) throw new Error(String(r.status))
      const data = (await r.json()) as { seq: number; events: { fn: string; payload: unknown }[] }
      cursor = data.seq
      for (const e of data.events) deliverPush(e.fn, e.payload)
    } catch {
      await sleep(1000)
    }
  }
}

interface ApiReply<T> {
  ok: boolean
  data?: T
  error?: string
  code?: string
  params?: Params
}

/** Вызов метода Api по имени. Бросает Error с текстом ошибки бэкенда. */
export async function api<T = unknown>(method: string, ...args: unknown[]): Promise<T> {
  if (!Bridge.call) throw new Error(t("bridge.notReady"))
  const res = JSON.parse(await Bridge.call(method, JSON.stringify(args))) as ApiReply<T>
  if (!res.ok) throw new Error(errorMessage(res))
  return res.data as T
}

// --- пуши из Python ------------------------------------------------------------
// Бэкенд зовёт window.<fn>(payload); на каждое имя ставится трамплин, а подписчики
// добавляются через onPush(fn, handler) — сколько угодно раз.

type PushHandler = (payload: unknown) => void
const pushHandlers = new Map<string, PushHandler[]>()

export function deliverPush(fn: string, payload: unknown): void {
  for (const h of pushHandlers.get(fn) ?? []) {
    try {
      h(payload)
    } catch (e) {
      console.error(e)
    }
  }
}

export function onPush(fn: string, handler: PushHandler): void {
  if (!pushHandlers.has(fn)) {
    pushHandlers.set(fn, [])
    ;(window as unknown as Record<string, unknown>)[fn] = (payload: unknown) => deliverPush(fn, payload)
  }
  pushHandlers.get(fn)!.push(handler)
}
