/* Запись доменов сайта: проверка найденных доменов и выбор, что добавить в список.
   Проверка — та же, что на странице «Проверка» (block_check_one), по одному домену. */

import { api } from "@/lib/bridge"

export interface RecDomain {
  domain: string
  hosts: string[]
  tracker?: boolean
}

export interface Reach {
  status: string
  reason?: string | null
}

export type ReachTone = "ok" | "warn" | "err" | "off"

// не открылся из-за блокировки: DPI, DNS или отказ по стране (его лечит прокси по списку)
const BLOCKED = new Set(["blocked", "dns", "denied"])
const OPEN = new Set(["ok", "challenge"])

export const isBlocked = (r: Reach | undefined) => !!r && BLOCKED.has(r.status)

/** Что проверять: имя, которое сайт реально запрашивал (у корня googlevideo.com адреса нет). */
export const probeName = (d: RecDomain) => d.hosts[0] || d.domain

/** Что отметить: заблокированные домены, кроме трекеров; не нашлось блокировок — все, кроме трекеров. */
export function preselect(domains: RecDomain[], reaches: Record<string, Reach>): Set<string> {
  const candidates = domains.filter((d) => !d.tracker)
  const blocked = candidates.filter((d) => isBlocked(reaches[d.domain]))
  return new Set((blocked.length ? blocked : candidates).map((d) => d.domain))
}

/** Подпись (ключ строки) и цвет точки для результата проверки домена. */
export function reachLabel(r: Reach | undefined): { key: string; tone: ReachTone } {
  if (!r) return { key: "checks.v.pending", tone: "off" }
  if (OPEN.has(r.status)) return { key: "checks.v.open", tone: "ok" }
  if (r.status === "blocked") return { key: "checks.v.unreachable", tone: "err" }
  if (r.status === "dns") return { key: "checks.v.noDns", tone: "warn" }
  if (r.status === "denied") return { key: "checks.v.denied", tone: "warn" }
  return { key: "checks.v.error", tone: "off" }
}

/** Проверяет домены по нескольку сразу; результат каждого — в onResult, как только готов. */
export async function checkDomains(
  domains: RecDomain[],
  onResult: (domain: string, reach: Reach) => void,
  limit = 6
): Promise<void> {
  const queue = [...domains]
  const worker = async () => {
    for (let d = queue.shift(); d; d = queue.shift()) {
      let reach: Reach
      try {
        reach = (await api<Reach | null>("block_check_one", probeName(d))) ?? { status: "error" }
      } catch {
        reach = { status: "error" }
      }
      onResult(d.domain, reach)
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, queue.length) }, worker))
}
