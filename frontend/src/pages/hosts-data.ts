/* Данные страницы Hosts. Лёгкое состояние (applied, assignments, count, health,
   last_switch, background) живёт в сторе под ключом "hosts" — хаб опрашивает его всегда.
   Провайдеры и списки в хаб не входят (тяжелее и меняются реже): страница грузит их
   вызовом hosts_overview и кэширует в сторе между заходами. */

import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store } from "@/lib/store"

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

export async function loadOverview(): Promise<void> {
  try {
    const data = await api<(Overview & { state: HostsView }) | null>("hosts_overview")
    if (!data) return
    store.set(OVERVIEW_KEY, { providers: data.providers, lists: data.lists } satisfies Overview)
    store.set("hosts", data.state)
  } catch (e) {
    notify.error(t("hosts.load.failed"), e instanceof Error ? e.message : String(e))
  }
}

export function toneClass(pct: number): string {
  return pct >= 80 ? "text-success" : pct >= 50 ? "text-warning" : "text-destructive"
}
