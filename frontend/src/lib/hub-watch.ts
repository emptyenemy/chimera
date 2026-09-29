import { useEffect } from "react"

import { api } from "@/lib/bridge"

/** Включает ленивые источники хаба, пока страница открыта (аналог ctx.watch() старого
    фронта): хаб опрашивает их, только если кто-то смотрит. */
export function useHubWatch(keys: string[]): void {
  const joined = keys.join(",")
  useEffect(() => {
    const list = joined ? joined.split(",") : []
    if (!list.length) return
    api("hub_watch", list, true).catch(() => {})
    return () => {
      api("hub_watch", list, false).catch(() => {})
    }
  }, [joined])
}
