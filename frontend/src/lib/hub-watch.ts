import { useEffect } from "react"

import { api } from "@/lib/bridge"

const watchers = new Map<string, number>()
const sent = new Set<string>()
let scheduled = false

function reconcile(): void {
  if (scheduled) return
  scheduled = true
  queueMicrotask(() => {
    void (async () => {
      try {
        while (true) {
          const off = [...sent].filter((key) => !watchers.has(key))
          const on = [...watchers.keys()].filter((key) => !sent.has(key))
          const keys = off.length ? off : on
          if (!keys.length) return
          const enabled = !off.length
          for (const key of keys) {
            if (enabled) sent.add(key)
            else sent.delete(key)
          }
          await api("hub_watch", keys, enabled).catch(() => {})
        }
      } finally {
        scheduled = false
      }
    })()
  })
}

/** Включает ленивые источники хаба, пока страница открыта (аналог ctx.watch() старого
    фронта): хаб опрашивает их, только если кто-то смотрит. */
export function useHubWatch(keys: string[]): void {
  const joined = [...new Set(keys)].sort().join(",")
  useEffect(() => {
    const list = joined ? joined.split(",") : []
    if (!list.length) return
    for (const key of list) watchers.set(key, (watchers.get(key) ?? 0) + 1)
    reconcile()
    return () => {
      for (const key of list) {
        const remaining = (watchers.get(key) ?? 1) - 1
        if (remaining) watchers.set(key, remaining)
        else watchers.delete(key)
      }
      reconcile()
    }
  }, [joined])
}
