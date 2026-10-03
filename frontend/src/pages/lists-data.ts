/* Данные страницы «Списки»: кэш lists_all в сторе (переживает уход со страницы) и
   общие вспомогательные функции редактора и диалога записи доменов. */

import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { optimistic, store } from "@/lib/store"

export const LISTS_KEY = "lists.all"

export interface ListInfo {
  name: string
  count: number
  proxy?: boolean
  winws?: boolean
  hosts?: boolean
}

/** Ответ lists_save / lists_delete: ошибки применения не отменяют сохранение. */
export interface SaveInfo {
  count: number
  apply_errors?: { module: string; error: string }[]
}

export function patchList(name: string, part: Partial<ListInfo>): void {
  const all = store.get<ListInfo[]>(LISTS_KEY)
  if (!all) return
  store.set(
    LISTS_KEY,
    all.map((f) => (f.name === name ? { ...f, ...part } : f))
  )
}

interface ListsState { lists?: string[] }

function listSelection(value: unknown, key: "proxy" | "winws"): string[] {
  return (value as ListsState | undefined)?.lists ?? (store.get<ListInfo[]>(LISTS_KEY) ?? []).filter(f => f[key]).map(f => f.name)
}

export function applySelections(items: ListInfo[], before?: { proxy: unknown; winws: unknown }): ListInfo[] {
  return items.map(item => {
    const next = { ...item }
    for (const key of ["proxy", "winws"] as const) {
      if (store.pending(key) || (before && before[key] !== store.get(key))) next[key] = listSelection(store.get(key), key).includes(item.name)
    }
    return next
  })
}

/** Полные списки подключений строятся от подтверждённого состояния при отправке. */
export async function setTransport(
  name: string, key: "proxy" | "winws", on: boolean,
  { notifyInfo = true, errorTitle }: { notifyInfo?: boolean; errorTitle?: string } = {}
): Promise<void> {
  const label = t(key === "proxy" ? "lists.transport.label.proxy" : "lists.transport.label.winws")
  const change = (value: unknown) => {
    const lists = listSelection(value, key).filter(n => n !== name)
    if (on) lists.push(name)
    return { lists }
  }
  if (!Array.isArray(store.confirmed<ListsState>(key)?.lists))
    store.patch(key, { lists: listSelection(store.confirmed(key), key) })
  const saving = optimistic(key, change, () => {
    const { lists } = change(store.confirmed(key))
    return key === "proxy" ? api("proxy_set_lists", lists) : api("winws_set_lists", lists)
  }, { errorTitle: errorTitle ?? t("lists.transport.failed", { label }) })
  patchList(name, { [key]: on })
  if (notifyInfo) notify.info(t(on ? "lists.transport.on" : "lists.transport.off", { name, label }))
  try {
    await saving
  } catch {
    /* откат и тост уже выполнены */
  } finally {
    const active = new Set(listSelection(store.get(key), key))
    const items = store.get<ListInfo[]>(LISTS_KEY)
    if (items) store.set(LISTS_KEY, items.map(item => ({ ...item, [key]: active.has(item.name) })))
  }
}

const MODULE_KEYS: Record<string, string> = {
  winws: "lists.module.winws",
  proxy: "lists.module.proxy",
  hosts: "lists.module.hosts",
}

/** Список сохранён и применяется сам; если какой-то модуль не смог — говорим, какой. */
export function applyErrors(info: SaveInfo | null | undefined, titleKey: string): void {
  for (const err of info?.apply_errors ?? []) {
    const module = MODULE_KEYS[err.module] ? t(MODULE_KEYS[err.module]) : err.module
    notify.error(t(titleKey, { module }), err.error)
  }
}

// Сохранения в полёте по именам: чтение списка ждёт, пока уйдёт последняя правка.
const inflight = new Map<string, Promise<void>>()

export function track<T>(name: string, call: () => Promise<T>): Promise<T> {
  const p = (inflight.get(name) ?? Promise.resolve()).then(call)
  const settled = p.then(
    () => undefined,
    () => undefined
  )
  inflight.set(name, settled)
  void settled.then(() => {
    if (inflight.get(name) === settled) inflight.delete(name)
  })
  return p
}

export async function waitSaved(name: string): Promise<void> {
  while (inflight.has(name)) await inflight.get(name)
}

export interface ListDraft {
  text: string
  error: string | null
}
const drafts = new Map<string, ListDraft>()

export function readListDraft(name: string): ListDraft | undefined {
  return drafts.get(name)
}

export function writeListDraft(name: string, text: string): void {
  drafts.set(name, { text, error: null })
}

export function settleListDraft(name: string, draft: ListDraft | undefined, error: string | null): boolean {
  if (!draft || drafts.get(name) !== draft) return false
  if (error !== null) draft.error = error
  else drafts.delete(name)
  return true
}

interface Editor {
  flush: () => Promise<boolean>
  freeze: (on: boolean) => void
  retire: () => void
}
const editors = new Map<string, Editor>()
const locks = new Map<string, number>()

export function registerEditor(name: string, editor: Editor): () => void {
  editors.set(name, editor)
  if (locks.has(name)) editor.freeze(true)
  return () => {
    if (editors.get(name) === editor) editors.delete(name)
  }
}

/** Перед изменением файла сохраняет черновик и блокирует ввод до завершения. */
export async function withSavedList<T>(name: string, call: () => Promise<T>, retire = false): Promise<T> {
  const editor = editors.get(name)
  locks.set(name, (locks.get(name) ?? 0) + 1)
  editor?.freeze(true)
  try {
    if (editor) {
      if (!await editor.flush()) throw new Error(t("lists.status.error"))
    } else {
      await waitSaved(name)
      const draft = readListDraft(name)
      if (draft) {
        try {
          const info = await track(name, () => api<SaveInfo | null>("lists_save", name, draft.text))
          if (info) patchList(name, { count: info.count })
          applyErrors(info, "lists.saveApplyFailed")
          settleListDraft(name, draft, null)
        } catch (error) {
          settleListDraft(name, draft, error instanceof Error ? error.message : String(error))
          throw error
        }
      }
    }
    const result = await track(name, call)
    if (retire) {
      editor?.retire()
      if (editors.get(name) !== editor) editors.get(name)?.retire()
    }
    return result
  } finally {
    const remaining = (locks.get(name) ?? 1) - 1
    if (remaining) locks.set(name, remaining)
    else {
      locks.delete(name)
      editor?.freeze(false)
      if (editors.get(name) !== editor) editors.get(name)?.freeze(false)
    }
  }
}
