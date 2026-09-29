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
  error: (key: string) => errors.get(key) ?? null,
  set(key: string, value: unknown): void {
    data.set(key, value)
    emit(key)
  },
  setError(key: string, err: string | null): void {
    if ((errors.get(key) ?? null) === err) return
    errors.set(key, err)
    emit(key)
  },
  /** Слияние с текущим значением (оптимистичные правки). */
  patch(key: string, part: object): void {
    data.set(key, { ...((data.get(key) as object | undefined) ?? {}), ...part })
    emit(key)
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

// Пуш хаба: { key, data, error, ts }. Пока идёт оптимистичная правка ключа, снимок в
// полёте мог уйти до команды и откатил бы тумблер назад — такие пропускаем: после
// команды хаб всё равно пришлёт свежий (poke).
const pendingKeys = new Map<string, number>()

interface HubPush {
  key?: string
  data?: unknown
  error?: string | null
}

onPush("hub", (raw) => {
  const p = raw as HubPush | null
  if (!p?.key || pendingKeys.get(p.key)) return
  if (p.data != null) store.set(p.key, p.data)
  store.setError(p.key, p.error || null)
})

/** Снимок хаба — всё, что уже опрошено; дальше живут пуши. */
export async function loadSnapshot(): Promise<void> {
  const snap = await api<Record<string, unknown>>("hub_snapshot")
  for (const [k, v] of Object.entries(snap ?? {})) store.set(k, v)
}

interface OptimisticOptions {
  applyResult?: boolean
  errorTitle?: string
}

/** Оптимистичное действие: сразу патчит стор, шлёт команду, результат (если это объект
    состояния) кладёт в стор, при ошибке откатывает и показывает тост. */
export async function optimistic<T = unknown>(
  key: string,
  patch: object | null,
  call: () => Promise<T>,
  { applyResult = true, errorTitle }: OptimisticOptions = {}
): Promise<T> {
  const before = data.get(key)
  pendingKeys.set(key, (pendingKeys.get(key) ?? 0) + 1)
  if (patch) store.patch(key, patch)
  try {
    const res = await call()
    if (applyResult && res && typeof res === "object" && !Array.isArray(res)) store.patch(key, res)
    return res
  } catch (e) {
    store.set(key, before)
    notify.error(errorTitle ?? t("common.failed"), e instanceof Error ? e.message : String(e))
    throw e
  } finally {
    const n = (pendingKeys.get(key) ?? 1) - 1
    if (n) pendingKeys.set(key, n)
    else pendingKeys.delete(key)
    api("hub_refresh", [key]).catch(() => {})
  }
}
