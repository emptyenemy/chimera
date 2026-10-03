/* Стор состояния модулей — аналог Store из старого core.js на React.

   Главное правило скорости то же: интерфейс не ждёт бэкенд, чтобы что-то нарисовать.
   Состояние пушит хаб (ui/hub.py) событием "hub" ({key, data, error, ts}), компоненты
   читают его хуками useStore()/useStoreError(). Команды уходят в фоне; тумблеры
   переключаются сразу (optimistic) и откатываются, если бэкенд ответил ошибкой. */

import { useSyncExternalStore } from "react"

import { api, onPush } from "@/lib/bridge"
import { notify } from "@/lib/notify"
import { t } from "@/lib/i18n"

type Listener = () => void

const data = new Map<string, unknown>()
const errors = new Map<string, string | null>()
const listeners = new Map<string, Set<Listener>>()
const revisions = new Map<string, number>()
const hubTimestamps = new Map<string, number>()
type OptimisticPatch = object | ((value: unknown) => object)
interface Mutation {
  patch: OptimisticPatch | null
}
interface MutationQueue {
  confirmed: unknown
  edits: Mutation[]
  tail: Promise<void>
}
const mutations = new Map<string, MutationQueue>()

function merge(value: unknown, patch: OptimisticPatch): object {
  const part = typeof patch === "function" ? patch(value) : patch
  return { ...((value as object | undefined) ?? {}), ...part }
}

function publish(key: string, value: unknown): void {
  data.set(key, value)
  revisions.set(key, (revisions.get(key) ?? 0) + 1)
  emit(key)
}

function renderMutations(key: string, queue: MutationQueue): void {
  let value = queue.confirmed
  for (const edit of queue.edits) if (edit.patch) value = merge(value, edit.patch)
  publish(key, value)
}

function emit(key: string): void {
  for (const fn of listeners.get(key) ?? []) fn()
}

function subscribe(key: string, fn: Listener): () => void {
  let set = listeners.get(key)
  if (!set) listeners.set(key, (set = new Set()))
  set.add(fn)
  return () => set.delete(fn)
}

export const store = {
  get: <T = unknown>(key: string) => data.get(key) as T | undefined,
  confirmed: <T = unknown>(key: string) => (mutations.get(key)?.confirmed ?? data.get(key)) as T | undefined,
  error: (key: string) => errors.get(key) ?? null,
  pending: (key: string) => mutations.has(key),
  set(key: string, value: unknown): void {
    const queue = mutations.get(key)
    if (queue) {
      queue.confirmed = value
      renderMutations(key, queue)
    } else publish(key, value)
  },
  setError(key: string, err: string | null): void {
    if ((errors.get(key) ?? null) === err) return
    errors.set(key, err)
    emit(key)
  },
  /** Слияние с текущим значением (оптимистичные правки). */
  patch(key: string, part: object): void {
    const queue = mutations.get(key)
    store.set(key, merge(queue ? queue.confirmed : data.get(key), part))
  },
  subscribe,
}

/** Значение ключа стора; компонент перерисуется, когда оно изменится. */
export function useStore<T = unknown>(key: string): T | undefined {
  return useSyncExternalStore(
    (fn) => subscribe(key, fn),
    () => data.get(key) as T | undefined
  )
}

/** Ошибка последнего опроса источника хаба (null, если всё хорошо). */
export function useStoreError(key: string): string | null {
  return useSyncExternalStore(
    (fn) => subscribe(key, fn),
    () => errors.get(key) ?? null
  )
}

// Снимок хаба в полёте мог уйти до команды: после последней записи просим свежий.

interface HubPush {
  key?: string
  data?: unknown
  error?: string | null
  ts?: number
}

onPush("hub", (raw) => {
  const p = raw as HubPush | null
  if (!p?.key || mutations.has(p.key)) return
  if (typeof p.ts === "number" && Number.isFinite(p.ts)) {
    if (p.ts < (hubTimestamps.get(p.key) ?? -Infinity)) return
    hubTimestamps.set(p.key, p.ts)
  }
  if (p.data != null) store.set(p.key, p.data)
  store.setError(p.key, p.error || null)
})

/** Снимок хаба — всё, что уже опрошено; дальше живут пуши. */
export async function loadSnapshot(): Promise<void> {
  const before = new Map(revisions)
  const snap = await api<Record<string, unknown>>("hub_snapshot")
  for (const [key, value] of Object.entries(snap ?? {})) {
    if (before.get(key) === revisions.get(key) && !mutations.has(key)) store.set(key, value)
  }
}

interface OptimisticOptions {
  applyResult?: boolean
  errorTitle?: string
  notifyError?: boolean
}

/** Оптимистичное действие: сразу патчит стор, шлёт команду, результат (если это объект
    состояния) кладёт в стор, при ошибке откатывает и показывает тост. */
export async function optimistic<T = unknown>(
  key: string,
  patch: OptimisticPatch | null,
  call: () => Promise<T>,
  { applyResult = true, errorTitle, notifyError = true }: OptimisticOptions = {}
): Promise<T> {
  let queue = mutations.get(key)
  if (!queue) {
    queue = { confirmed: data.get(key), edits: [], tail: Promise.resolve() }
    mutations.set(key, queue)
  }
  const edit = { patch }
  const previous = queue.tail
  let release!: () => void
  queue.tail = new Promise<void>((resolve) => { release = resolve })
  queue.edits.push(edit)
  renderMutations(key, queue)
  await previous
  try {
    const res = await call()
    if (patch) queue.confirmed = merge(queue.confirmed, patch)
    if (applyResult && res && typeof res === "object" && !Array.isArray(res))
      queue.confirmed = merge(queue.confirmed, res)
    return res
  } catch (e) {
    if (notifyError)
      notify.error(errorTitle ?? t("common.failed"), e instanceof Error ? e.message : String(e))
    throw e
  } finally {
    queue.edits.splice(queue.edits.indexOf(edit), 1)
    if (!queue.edits.length) {
      mutations.delete(key)
      hubTimestamps.set(key, Math.max(hubTimestamps.get(key) ?? -Infinity, Date.now() / 1000))
    }
    renderMutations(key, queue)
    release()
    if (!mutations.has(key)) api("hub_refresh", [key]).catch(() => {})
  }
}
