/* Формы состояния, которые хаб (ui/hub.py) пушит в стор. Описаны только поля,
   которые фронт читает; остальное бэкенд может добавлять свободно. */

export interface WinwsState {
  running?: boolean
  current?: string | null
  last_strategy?: string | null
  strategies?: { id: string; name?: string }[]
  error?: string
}

export interface ProxyState {
  running?: boolean
  mode?: "pac" | "tun" | "split"
  core?: { present?: boolean; version?: string }
  parsed?: { server?: string; protocol?: string } | null
  domains?: number
  ips?: number
  apps?: unknown[]
  error?: string
}

export interface TgState {
  running?: boolean
  host?: string
  port?: number
  error?: string
}

export interface HostsState {
  applied?: boolean
  count?: number
  assignments?: Record<string, string[] | null | undefined>
  error?: string
}

export interface AppInfo {
  admin?: boolean
  version?: string
  service_running?: boolean
}

export interface SelfUpdateState {
  update?: boolean
  latest?: string
}

/** Адаптеры, где стоит поставленный программой DNS (лёгкий источник хаба dnsStatus). */
export interface DnsStatus {
  active?: number[]
}

/** Ключи стора, которые пушит хаб. */
export type HubKey = "winws" | "proxy" | "tg" | "hosts" | "dnsStatus" | "app" | "selfupdate"

/** Модули с включателем: у каждого свой источник хаба и точка состояния в меню. */
export type ModuleKey = "winws" | "proxy" | "tg" | "hosts"

/** Точка у пункта меню: модули, DNS (включателя нет, но изменённый DNS — тоже «работает») и идущая автонастройка. */
export type DotKey = ModuleKey | "dns" | "autotune"
