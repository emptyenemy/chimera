/* Состояние страницы «Настройки». В хабе его нет: читается при открытии страницы и
   живёт в сторе под своими ключами, поэтому повторный вход рисует кэш сразу, а данные
   обновляются в фоне. */

import { api } from "@/lib/bridge"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { optimistic, store, useStore } from "@/lib/store"

/** config.json: то, что правится на этой странице. Режимы ui/tui/service — инструмент
    разработчика и остаются в файле. */
export interface AppConfig {
  close_to_tray?: boolean
  auto_elevate?: boolean
  ui_backend?: string
  update_channel?: string
  update_check?: boolean
  theme?: string
  autotune_watch?: boolean
}

export interface AutostartState {
  enabled: boolean
  supported: boolean
}

/** app_info с признаком собранной программы (в ней нет pywebview и git). */
export interface AppInfoFull {
  frozen?: boolean
  flavor?: string
  ui_backends?: string[]
}

export const CONFIG_KEY = "settings.config"
export const PENDING_KEY = "settings.pending"
export const AUTOSTART_KEY = "settings.autostart"

export const useConfig = () => useStore<AppConfig>(CONFIG_KEY)
export const usePending = () => useStore<Record<string, boolean>>(PENDING_KEY) ?? {}

function setPending(key: string, on: boolean): void {
  const rest = { ...store.get<Record<string, boolean>>(PENDING_KEY) }
  if (on) rest[key] = true
  else delete rest[key]
  store.set(PENDING_KEY, rest)
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

let configGeneration = 0
export async function refreshConfig(): Promise<void> {
  if (store.pending(CONFIG_KEY)) return
  const generation = ++configGeneration
  try {
    const config = await api<AppConfig>("config_read")
    if (generation !== configGeneration || store.pending(CONFIG_KEY)) return
    store.set(CONFIG_KEY, config)
  } catch (e) {
    if (generation === configGeneration) notify.error(t("settings.config.readFailed"), message(e))
  }
}

let autostartGeneration = 0
export async function refreshAutostart(): Promise<void> {
  if (store.get<Record<string, boolean>>(PENDING_KEY)?.autostart) return
  const generation = ++autostartGeneration
  try {
    const state = await api<AutostartState>("autostart_get")
    if (generation === autostartGeneration && !store.get<Record<string, boolean>>(PENDING_KEY)?.autostart)
      store.set(AUTOSTART_KEY, state)
  } catch {
    /* тумблер останется как был */
  }
}

/** Оптимистичная запись ключа config.json: сразу в стор, при ошибке откат и тост. */
export async function setConfig(key: keyof AppConfig, value: string | boolean): Promise<void> {
  const cur = store.get<AppConfig>(CONFIG_KEY)
  if (!cur || cur[key] === value || store.get<Record<string, boolean>>(PENDING_KEY)?.[key]) return
  ++configGeneration
  setPending(key, true)
  try {
    await optimistic(CONFIG_KEY, { [key]: value }, () => api<AppConfig>("config_set", key, value), {
      errorTitle: t("settings.saveFailed"),
    })
  } catch {
    /* откат и тост уже выполнены */
  } finally {
    ++configGeneration
    setPending(key, false)
  }
}

export async function toggleAutostart(target: boolean): Promise<void> {
  const cur = store.get<AutostartState>(AUTOSTART_KEY)
  if (!cur?.supported || cur.enabled === target || store.get<Record<string, boolean>>(PENDING_KEY)?.autostart) return
  ++autostartGeneration
  setPending("autostart", true)
  store.set(AUTOSTART_KEY, { ...cur, enabled: target })
  try {
    const res = await api<Partial<AutostartState>>("autostart_set", target)
    const next = { ...store.get<AutostartState>(AUTOSTART_KEY)!, ...res }
    store.set(AUTOSTART_KEY, next)
    notify.success(t(next.enabled ? "settings.autostart.on" : "settings.autostart.off"))
  } catch (e) {
    store.set(AUTOSTART_KEY, { ...store.get<AutostartState>(AUTOSTART_KEY)!, enabled: cur.enabled })
    notify.error(t("settings.autostart.failed"), message(e))
  } finally {
    ++autostartGeneration
    setPending("autostart", false)
  }
}

/** Размер в байтах по-русски: 1 536 -> «1,5 КБ» (те же правила чисел, что у fmtNum). */
export function fmtBytes(b: number | null | undefined): string {
  if (b == null) return "—"
  const units = ["bytes", "kb", "mb", "gb", "tb"].map((key) => t(`units.${key}`))
  let i = 0
  let v = Number(b)
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${fmtNum(i ? Math.round(v * 100) / 100 : v)} ${units[i]}`
}
