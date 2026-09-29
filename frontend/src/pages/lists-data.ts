/* Данные страницы «Списки»: кэш lists_all в сторе (переживает уход со страницы) и
   общие вспомогательные функции редактора и диалога записи доменов. */

import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store } from "@/lib/store"

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
  const all = store.get<ListInfo[]>(LISTS_KEY) ?? []
  store.set(
    LISTS_KEY,
    all.map((f) => (f.name === name ? { ...f, ...part } : f))
  )
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

export function track<T>(name: string, p: Promise<T>): Promise<T> {
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
  await inflight.get(name)
}
