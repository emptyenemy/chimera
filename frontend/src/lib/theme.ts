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
let previewing = false
let initialized = false
let previewRunning = false
let previewFrame = 0
interface PreviewRequest {
  patch: AppearancePatch
  sequence: number
  resolve: (state: AppearanceState | null) => void
  reject: (error: unknown) => void
}
let queuedPreview: PreviewRequest | null = null
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
  for (const [key, value] of Object.entries(next.styles)) {
    if (state?.styles[key] !== value || root.style.getPropertyValue(key) !== value)
      root.style.setProperty(key, value)
  }
  if (JSON.stringify(state) !== JSON.stringify(next)) {
    state = next
    emit()
  }
}
if (state) apply(state)

async function refresh() {
  if (pending) return
  const sequence = previewSequence
  try {
    const next = await api<AppearanceState>("appearance_state")
    if (pending || sequence !== previewSequence) return
    if (previewing && next.mode === state?.mode) return
    previewing = false
    apply(next)
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
      if (
        state?.settings.theme === "system" ||
        state?.settings.appearance.accent_source === "windows"
      )
        void refresh()
    }, 1500)
    void api<{ updated: boolean; state: AppearanceState }>("appearance_refresh")
      .then((reply) => {
        if (reply.updated && !pending) void refresh()
      })
      .catch(() => {})
  }
}

function clearPreview() {
  ++previewSequence
  cancelAnimationFrame(previewFrame)
  previewFrame = 0
  queuedPreview?.resolve(null)
  queuedPreview = null
  previewing = false
}

function schedulePreview() {
  if (previewRunning || previewFrame || !queuedPreview) return
  previewFrame = requestAnimationFrame(() => {
    previewFrame = 0
    void runPreview()
  })
}

async function runPreview() {
  const request = queuedPreview
  if (!request || pending) return
  queuedPreview = null
  previewRunning = true
  try {
    const next = await api<AppearanceState>("appearance_preview", request.patch)
    if (request.sequence !== previewSequence || pending) request.resolve(null)
    else {
      apply(next)
      request.resolve(next)
    }
  } catch (error) {
    if (request.sequence !== previewSequence || pending) request.resolve(null)
    else request.reject(error)
  } finally {
    previewRunning = false
    schedulePreview()
  }
}

export function previewAppearance(
  patch: AppearancePatch
): Promise<AppearanceState | null> {
  if (pending) return Promise.resolve(null)
  previewing = true
  const sequence = ++previewSequence
  queuedPreview?.resolve(null)
  return new Promise((resolve, reject) => {
    queuedPreview = { patch, sequence, resolve, reject }
    schedulePreview()
  })
}

export async function discardAppearancePreview(): Promise<void> {
  const restore = previewing
  clearPreview()
  if (restore) await refresh()
}

export async function applyAppearance(patch: AppearancePatch): Promise<void> {
  if (pending) return
  pending = true
  clearPreview()
  emit()
  try {
    apply(await api<AppearanceState>("appearance_apply", patch))
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
