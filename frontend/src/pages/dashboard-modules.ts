/* Модули, которыми управляет «Обзор»: откуда брать состояние, как включать и выключать,
   когда переключатель отключён. Логика один в один со старым dashboard.js. */

import { GlobeIcon, LockOpenIcon, SendIcon, ShieldCheckIcon, type LucideIcon } from "lucide-react"

import { api } from "@/lib/bridge"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import type { AppInfo, HostsState, ModuleKey, ProxyState, TgState, WinwsState } from "@/lib/types"

export interface ModuleDef<S> {
  key: ModuleKey
  /** Страница модуля, куда ведёт карточка. */
  page: string
  icon: LucideIcon
  /** Ключ строки с названием модуля. */
  titleKey: string
  on(st: S | undefined): boolean
  /** Почему включить нельзя; пустая строка — можно. */
  blocked(st: S | undefined, app: AppInfo | undefined): string
  /** Одна строка под названием — суть модуля. */
  meta(st: S | undefined): string
  /** Команда включения/выключения. */
  toggle(st: S, on: boolean): Promise<unknown>
  /** Что оптимистично записать в стор до ответа бэкенда. */
  patch?(on: boolean): object
}

// Списки бывают и из доменов, и из IP/подсетей: для готовности прокси важна сумма.
const proxyTargets = (st?: ProxyState) => (st?.domains || 0) + (st?.ips || 0)

export function proxyScope(st: ProxyState): string {
  if (st.mode === "tun") return t("scope.all")
  const parts: string[] = []
  const apps = st.mode === "split" ? (st.apps ?? []).length : 0
  if (apps) parts.push(t("scope.apps", { count: apps, n: fmtNum(apps) }))
  if (st.domains) parts.push(t("scope.domains", { count: st.domains, n: fmtNum(st.domains) }))
  if (st.ips) parts.push(t("scope.ips", { n: fmtNum(st.ips) }))
  return parts.join(" · ") || t("scope.none")
}

const strategyOf = (st?: WinwsState) => st?.current || st?.last_strategy || st?.strategies?.[0]?.id

const winws: ModuleDef<WinwsState> = {
  key: "winws",
  page: "strategies",
  icon: ShieldCheckIcon,
  titleKey: "module.winws",
  on: (st) => !!st?.running,
  blocked(st, app) {
    if (!st) return t("blocked.loading")
    if (!st.running && !strategyOf(st)) return t("blocked.noStrategies")
    if (!st.running && app?.admin === false) return t("blocked.needAdmin")
    return ""
  },
  meta(st) {
    if (!st) return ""
    const name = st.strategies?.find((s) => s.id === (st.current || st.last_strategy))?.name
    if (st.running) return t("meta.strategy", { name: name || st.current || "?" })
    return name ? t("meta.strategy", { name }) : t("meta.strategyNone")
  },
  toggle: (st, on) => (on ? api("winws_start", strategyOf(st)) : api("winws_stop")),
}

const proxy: ModuleDef<ProxyState> = {
  key: "proxy",
  page: "proxy",
  icon: GlobeIcon,
  titleKey: "module.proxy",
  on: (st) => !!st?.running,
  blocked(st) {
    if (!st) return t("blocked.loading")
    if (st.running) return ""
    if (!st.core?.present) return t("blocked.noCore")
    if (!st.parsed) return t("blocked.noLink")
    if (st.mode === "split" && !proxyTargets(st) && !(st.apps ?? []).length) return t("blocked.noAppsAndLists")
    if ((st.mode || "pac") === "pac" && !proxyTargets(st)) return t("blocked.noLists")
    return ""
  },
  meta(st) {
    if (!st || (!st.running && !st.parsed)) return ""
    return `${st.parsed?.server || ""} · ${t(`meta.proxyMode.${st.mode ?? "pac"}`)}`
  },
  toggle: (_st, on) => (on ? api("proxy_start") : api("proxy_stop")),
}

const tg: ModuleDef<TgState> = {
  key: "tg",
  page: "telegram",
  icon: SendIcon,
  titleKey: "module.tg",
  on: (st) => !!st?.running,
  blocked: (st) => (st ? "" : t("blocked.loading")),
  meta: (st) => (st ? `${st.host || "127.0.0.1"}:${st.port ?? ""}` : ""),
  toggle: (_st, on) => (on ? api("tg_start") : api("tg_stop")),
}

const hosts: ModuleDef<HostsState> = {
  key: "hosts",
  page: "hosts",
  icon: LockOpenIcon,
  titleKey: "module.hosts",
  // у hosts «включено» — это applied, а не running
  on: (st) => !!st?.applied,
  blocked(st) {
    if (!st) return t("blocked.loading")
    const bound = Object.values(st.assignments ?? {}).some((l) => l?.length)
    if (!st.applied && !bound) return t("blocked.noServices")
    return ""
  },
  meta(st) {
    if (!st) return ""
    if (st.applied) {
      const n = st.count || 0
      return t("meta.hostsRecords", { count: n, n: fmtNum(n) })
    }
    const n = new Set(Object.values(st.assignments ?? {}).flat()).size
    return n ? t("meta.hostsServices", { count: n, n }) : ""
  },
  toggle: (_st, on) => api("hosts_set_enabled", on),
  patch: (on) => ({ applied: on }),
}

// Состояния у модулей разные, а список общий: приведение одно, здесь. Каждый модуль
// получает из стора именно своё состояние (по key), так что типы не разъедутся.
export const MODULES = [winws, proxy, tg, hosts] as unknown as ModuleDef<object>[]
