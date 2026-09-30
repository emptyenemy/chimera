/* Python sets the full palette before paint; live changes use the same validated tokens. */
import { useSyncExternalStore } from "react"
import { api, onPush } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import type { AppearancePatch, AppearanceState } from "@/lib/appearance-types"

export type ThemeSetting = "system" | "light" | "dark"
export const THEME_SETTINGS: ThemeSetting[] = ["system", "light", "dark"]
declare global {
  interface Window {
    __CHIMERA_APPEARANCE__?: AppearanceState
  }
}
const media = window.matchMedia("(prefers-color-scheme: dark)")
const listeners = new Set<() => void>()
let state = window.__CHIMERA_APPEARANCE__ ?? null
let pending = false
let previewSequence = 0
let initialized = false
const modeFor = (theme?: ThemeSetting) =>
  (theme ?? state?.settings.theme ?? "system") === "system"
    ? media.matches
      ? "dark"
      : "light"
    : (theme ?? state?.settings.theme)
function emit() {
  for (const fn of listeners) fn()
}
function apply(next: AppearanceState) {
  const root = document.documentElement
  root.classList.toggle("dark", next.mode === "dark")
  root.dataset.theme = next.mode
  root.dataset.palette = next.palette
  root.dataset.density = next.settings.appearance.density
  root.style.colorScheme = next.mode
  for (const [key, value] of Object.entries(next.styles))
    root.style.setProperty(key, value)
  state = next
  emit()
}
if (state) apply(state)

async function refresh() {
  if (pending) return
  try {
    apply(await api<AppearanceState>("appearance_state", modeFor()))
  } catch {
    /* retain boot palette offline */
  }
}
media.addEventListener("change", () => {
  if (state?.settings.theme === "system") void refresh()
})

export async function initTheme(): Promise<void> {
  await refresh()
  if (!initialized) {
    initialized = true
    onPush("appearanceChanged", () => {
      if (!pending) void refresh()
    })
    window.setInterval(() => {
      if (state?.settings.appearance.accent_source === "windows") void refresh()
    }, 1500)
    void api<{ updated: boolean; state: AppearanceState }>("appearance_refresh")
      .then((reply) => {
        if (reply.updated && !pending) void refresh()
      })
      .catch(() => {})
  }
}

export async function previewAppearance(
  patch: AppearancePatch
): Promise<AppearanceState | null> {
  const sequence = ++previewSequence
  const next = await api<AppearanceState>(
    "appearance_preview",
    patch,
    modeFor(patch.theme)
  )
  if (sequence !== previewSequence || pending) return null
  apply(next)
  return next
}

export async function applyAppearance(patch: AppearancePatch): Promise<void> {
  if (pending) return
  pending = true
  ++previewSequence
  emit()
  try {
    apply(
      await api<AppearanceState>(
        "appearance_apply",
        patch,
        modeFor(patch.theme)
      )
    )
  } catch (e) {
    pending = false
    await refresh()
    notify.error(
      t("theme.saveFailed"),
      e instanceof Error ? e.message : String(e)
    )
  } finally {
    pending = false
    emit()
  }
}

export async function refreshAppearanceCatalog(): Promise<string | null> {
  const reply = await api<{ updated: boolean; error: string | null }>(
    "appearance_refresh"
  )
  await refresh()
  return reply.error
}
export async function setThemeSetting(next: ThemeSetting): Promise<void> {
  await applyAppearance({ theme: next })
}
function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
export function useAppearance() {
  return useSyncExternalStore(subscribe, () => state)
}
export function useAppearancePending() {
  return useSyncExternalStore(subscribe, () => pending)
}
export function useThemeSetting(): ThemeSetting {
  return useSyncExternalStore(
    subscribe,
    () => state?.settings.theme ?? "system"
  )
}
