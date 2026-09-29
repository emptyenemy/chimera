/* Состояние страницы «Настройки». В хабе его нет: читается при открытии страницы и
   живёт в сторе под своими ключами, поэтому повторный вход рисует кэш сразу, а данные
   обновляются в фоне. */

import { api } from "@/lib/bridge"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store, useStore } from "@/lib/store"

/** config.json: то, что правится на этой странице. Режимы ui/tui/service — инструмент
    разработчика и остаются в файле. */
export interface AppConfig {
  close_to_tray?: boolean
  auto_elevate?: boolean
  ui_backend?: string
  update_channel?: string
  update_check?: boolean
  theme?: string
}

export interface AutostartState {
  enabled: boolean
  supported: boolean
}

/** app_info с признаком собранной программы (в ней нет pywebview и git). */
export interface AppInfoFull {
  frozen?: boolean
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

export async function refreshConfig(): Promise<void> {
  try {
    store.set(CONFIG_KEY, await api<AppConfig>("config_read"))
  } catch (e) {
    notify.error(t("settings.config.readFailed"), message(e))
  }
}

export async function refreshAutostart(): Promise<void> {
  try {
    store.set(AUTOSTART_KEY, await api<AutostartState>("autostart_get"))
  } catch {
    /* тумблер останется как был */
  }
}

/** Оптимистичная запись ключа config.json: сразу в стор, при ошибке откат и тост. */
export async function setConfig(key: keyof AppConfig, value: string | boolean): Promise<void> {
  const cur = store.get<AppConfig>(CONFIG_KEY)
  if (!cur || cur[key] === value) return
  const prev = cur[key]
  store.set(CONFIG_KEY, { ...cur, [key]: value })
  setPending(key, true)
  try {
    const res = await api<AppConfig>("config_set", key, value)
    if (res) store.set(CONFIG_KEY, res)
  } catch (e) {
    store.set(CONFIG_KEY, { ...store.get<AppConfig>(CONFIG_KEY), [key]: prev })
    notify.error(t("settings.saveFailed"), message(e))
  } finally {
    setPending(key, false)
  }
}

export async function toggleAutostart(target: boolean): Promise<void> {
  const cur = store.get<AutostartState>(AUTOSTART_KEY)
  if (!cur?.supported) return
  setPending("autostart", true)
  store.set(AUTOSTART_KEY, { ...cur, enabled: target })
  try {
    const res = await api<Partial<AutostartState>>("autostart_set", target)
    const next = { ...store.get<AutostartState>(AUTOSTART_KEY)!, ...res }
    store.set(AUTOSTART_KEY, next)
    notify.success(t(next.enabled ? "settings.autostart.on" : "settings.autostart.off"))
  } catch (e) {
    store.set(AUTOSTART_KEY, { ...store.get<AutostartState>(AUTOSTART_KEY)!, enabled: !target })
    notify.error(t("settings.autostart.failed"), message(e))
  } finally {
    setPending("autostart", false)
  }
}

/** Размер в байтах по-русски: 1 536 -> «1,5 КБ» (те же правила чисел, что у fmtNum). */
export function fmtBytes(b: number | null | undefined): string {
  if (b == null) return "—"
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
  let i = 0
  let v = Number(b)
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${fmtNum(i ? Math.round(v * 100) / 100 : v)} ${units[i]}`
}
