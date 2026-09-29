import { useSyncExternalStore } from "react"

import { api, onPush } from "@/lib/bridge"
import { setCatalog, t, type Language } from "@/lib/i18n"
import { notify } from "@/lib/notify"

export type LanguageSetting = "auto" | Language
export const LANGUAGE_SETTINGS: LanguageSetting[] = ["auto", "ru", "en"]
interface LanguageState { setting: LanguageSetting; lang: Language; pending: boolean }
let state: LanguageState = { setting: "auto", lang: "ru", pending: false }
const listeners = new Set<() => void>()
let generation = 0

function emit(): void { for (const fn of listeners) fn() }

export async function refreshLanguage(): Promise<void> {
  const current = ++generation
  const selection = await api<{ setting: LanguageSetting; lang: Language }>("lang_get")
  const reply = await api<{ lang: Language; catalog: Record<string, string> }>("i18n_get", selection.lang)
  if (current !== generation) return
  setCatalog(reply.catalog, reply.lang)
  state = { ...selection, pending: state.pending }
  emit()
}

export async function initLanguage(): Promise<void> {
  onPush("langChanged", () => { void refreshLanguage().catch(console.error) })
  try { await refreshLanguage() } catch { /* старый бэкенд — русский каталог */ }
}

export async function setLanguageSetting(next: LanguageSetting): Promise<void> {
  if (state.pending || next === state.setting) return
  state = { ...state, pending: true }
  emit()
  try {
    await api("config_set", "lang", next)
    await refreshLanguage()
  } catch (e) {
    notify.error(t("lang.saveFailed"), e instanceof Error ? e.message : String(e))
  } finally {
    state = { ...state, pending: false }
    emit()
  }
}

export function useLanguageSetting(): LanguageState {
  return useSyncExternalStore((fn) => {
    listeners.add(fn)
    return () => listeners.delete(fn)
  }, () => state)
}
