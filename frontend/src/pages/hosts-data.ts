/* Данные страницы Hosts. Лёгкое состояние (applied, assignments, count, health,
   last_switch, background) живёт в сторе под ключом "hosts" — хаб опрашивает его всегда.
   Провайдеры и списки в хаб не входят (тяжелее и меняются реже): страница грузит их
   вызовом hosts_overview и кэширует в сторе между заходами. */

import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { optimistic, store } from "@/lib/store"

export const OVERVIEW_KEY = "hosts.overview"

export interface Provider {
  id: string
  name: string
  type: "dns" | "static"
  builtin?: boolean
  /** Только у static: файл набора на месте и читается. */
  available?: boolean
  reason?: string
  servers?: string[]
  doh?: string
}

export interface HostList {
  name: string
  count: number
}

export interface Overview {
  providers: Provider[]
  lists: HostList[]
}

export interface Background {
  refresh_enabled?: boolean
  refresh_interval?: number
  check_enabled?: boolean
  check_interval?: number
  autoswitch_enabled?: boolean
  provider_order?: string[]
}

export interface Health {
  total?: number
  ratio?: number
  providers?: Record<string, { total?: number; ratio?: number }>
}

/** У dns-провайдера привязка — список имён списков, у static — просто true. */
export type Assignments = Record<string, string[] | boolean | null | undefined>

export interface HostsView {
  applied?: boolean
  enabled?: boolean
  assignments?: Assignments
  count?: number
  health?: Health | null
  last_switch?: { from: string; to: string; reason: string; when?: number } | null
  background?: Background
  error?: string
}

export interface Ping {
  ok: boolean
  ms?: number | null
}

export const isDns = (p: Provider) => p.type !== "static"
export const isUnavailable = (p: Provider) => p.type === "static" && p.available === false

let overviewGeneration = 0
export async function loadOverview(): Promise<void> {
  const generation = ++overviewGeneration
  const before = store.get("hosts")
  try {
    const data = await api<(Overview & { state: HostsView }) | null>("hosts_overview")
    if (!data || generation !== overviewGeneration) return
    store.set(OVERVIEW_KEY, { providers: data.providers, lists: data.lists } satisfies Overview)
    if (before === store.get("hosts") && !store.pending("hosts")) store.set("hosts", data.state)
  } catch (e) {
    if (generation === overviewGeneration) notify.error(t("hosts.load.failed"), e instanceof Error ? e.message : String(e))
  }
}

export function saveAssignments(change: (value: Assignments) => Assignments, errorTitle: string): Promise<unknown> {
  const patch = (value: unknown) => ({ assignments: change((value as HostsView | undefined)?.assignments ?? {}) })
  return optimistic("hosts", patch, () => api("hosts_set_assignments", patch(store.confirmed("hosts")).assignments), {
    errorTitle,
  }).catch(() => {})
}

export function toneClass(pct: number): string {
  return pct >= 80 ? "text-success" : pct >= 50 ? "text-warning" : "text-destructive"
}
