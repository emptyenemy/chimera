/* Тема оформления: system | light | dark. Настройка живёт в config.json (ключ theme),
   применяется без перезагрузки: класс dark и атрибут data-theme на <html>, color-scheme.

   До первой отрисовки тему ставит Python-часть (ui/theme.py, boot_script) — при старте мы
   её не трогаем, чтобы не мигать: только читаем настройку и слушаем prefers-color-scheme.
   Для system по этому же признаку тема следует за Windows, пока программа открыта. */

import { useSyncExternalStore } from "react"

import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"

export type ThemeSetting = "system" | "light" | "dark"
export const THEME_SETTINGS: ThemeSetting[] = ["system", "light", "dark"]

const isSetting = (v: unknown): v is ThemeSetting => THEME_SETTINGS.includes(v as ThemeSetting)

const media = window.matchMedia("(prefers-color-scheme: dark)")
const listeners = new Set<() => void>()
let setting: ThemeSetting = "system"

function resolve(s: ThemeSetting): "light" | "dark" {
  return s === "system" ? (media.matches ? "dark" : "light") : s
}

function apply(mode: "light" | "dark"): void {
  const root = document.documentElement
  root.classList.toggle("dark", mode === "dark")
  root.dataset.theme = mode
  root.style.colorScheme = mode
}

function emit(): void {
  for (const fn of listeners) fn()
}

media.addEventListener("change", () => {
  if (setting === "system") apply(resolve("system"))
})

/** Читает сохранённую настройку при старте. Тему не применяет: она уже стоит от Python. */
export async function initTheme(): Promise<void> {
  try {
    const cfg = await api<{ theme?: unknown }>("config_read")
    if (isSetting(cfg?.theme)) setting = cfg.theme
    emit()
  } catch {
    /* остаёмся на system: тему уже выставил бэкенд */
  }
}

/** Применить и сохранить; при ошибке записи вернуть прежнюю. */
export async function setThemeSetting(next: ThemeSetting): Promise<void> {
  if (next === setting) return
  const prev = setting
  setting = next
  apply(resolve(next))
  emit()
  try {
    await api("config_set", "theme", next)
  } catch (e) {
    setting = prev
    apply(resolve(prev))
    emit()
    notify.error(t("theme.saveFailed"), e instanceof Error ? e.message : String(e))
  }
}

export function useThemeSetting(): ThemeSetting {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => setting
  )
}
