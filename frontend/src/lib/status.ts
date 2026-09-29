/* «Включён ли модуль» — одно место, чтобы обзор, меню и подписи не разъезжались
   (аналог Status из старого shell.js). */

import { useStore } from "@/lib/store"
import type { HostsState, ProxyState, TgState, WinwsState } from "@/lib/types"

export interface Status {
  winws: boolean
  proxy: boolean
  tg: boolean
  hosts: boolean
  /** Любой способ обхода, который реально трогает трафик. */
  guard: boolean
  /** Сколько из четырёх модулей включено. */
  count: number
}

export const MODULE_TOTAL = 4

export function useStatus(): Status {
  const winws = !!useStore<WinwsState>("winws")?.running
  const proxy = !!useStore<ProxyState>("proxy")?.running
  const tg = !!useStore<TgState>("tg")?.running
  const hosts = !!useStore<HostsState>("hosts")?.applied
  return {
    winws,
    proxy,
    tg,
    hosts,
    guard: winws || proxy || hosts,
    count: [winws, proxy, tg, hosts].filter(Boolean).length,
  }
}
