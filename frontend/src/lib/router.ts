/* Роутер страниц без библиотек: текущая страница — id в хеше адреса (#dashboard) и в
   localStorage "chimera.page" (тот же ключ, что у старого фронта). */

import { useSyncExternalStore } from "react"

const PAGE_KEY = "chimera.page"

let ids: string[] = []
let current = ""
const listeners = new Set<() => void>()

function emit(): void {
  for (const fn of listeners) fn()
}

function saved(): string | null {
  try {
    return localStorage.getItem(PAGE_KEY)
  } catch {
    return null
  }
}

export const router = {
  /** Задать список страниц и открыть стартовую: хеш адреса, потом сохранённая, потом первая. */
  init(pageIds: string[]): void {
    ids = pageIds
    const fromHash = location.hash.slice(1)
    const last = saved()
    current = ids.includes(fromHash) ? fromHash : last && ids.includes(last) ? last : ids[0]
    window.addEventListener("hashchange", () => router.go(location.hash.slice(1), { push: false }))
  },
  go(id: string, { push = true }: { push?: boolean } = {}): void {
    const page = ids.includes(id) ? id : ids[0]
    if (!page || page === current) return
    current = page
    if (push && location.hash !== "#" + page) history.replaceState(null, "", "#" + page)
    try {
      localStorage.setItem(PAGE_KEY, page)
    } catch {
      /* без localStorage страница просто не запомнится */
    }
    emit()
  },
  get current(): string {
    return current
  },
  subscribe(fn: () => void): () => void {
    listeners.add(fn)
    return () => listeners.delete(fn)
  },
}

/** Id открытой страницы; компонент перерисуется при переходе. */
export function useCurrentPage(): string {
  return useSyncExternalStore(router.subscribe, () => router.current)
}
