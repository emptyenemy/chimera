/* Внешние компоненты (git-источники): состояние в сторе и действия над ним. */

import { api, onPush } from "@/lib/bridge"
import { confirmDialog } from "@/lib/dialogs"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store } from "@/lib/store"

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export interface Source {
  name: string
  kind: string
  repo?: string
  version?: string
  current?: string
  latest?: string | null
  update?: boolean
  updatable?: boolean
  error?: string | null
  note?: string
}

export const SOURCES_KEY = "settings.sources"
export const BUSY_KEY = "settings.srcBusy"
let sourcesChecked = false // сверяли ли уже с GitHub в этой сессии

export type Busy = Record<string, "check" | "update">
const busyOf = () => store.get<Busy>(BUSY_KEY) ?? {}
function setBusy(name: string, mode: "check" | "update" | null) {
  const next = { ...busyOf() }
  if (mode) next[name] = mode
  else delete next[name]
  store.set(BUSY_KEY, next)
}

function mergeSource(s: Source | undefined | null) {
  if (!s) return
  const list = [...(store.get<Source[]>(SOURCES_KEY) ?? [])]
  const i = list.findIndex((x) => x.name === s.name)
  if (i >= 0) list[i] = s
  else list.push(s)
  store.set(SOURCES_KEY, list)
}

// Приходит по мере готовности каждого источника во время upstream_check_updates:
// строка гаснет сразу, не дожидаясь самой медленной сверки.
onPush("srcChecked", (raw) => {
  const s = raw as Source
  if (busyOf()[s.name] === "check") setBusy(s.name, null)
  mergeSource(s)
})

export async function refreshSources(): Promise<void> {
  try {
    store.set(SOURCES_KEY, await api<Source[]>("upstream_versions"))
  } catch (e) {
    notify.error(t("settings.src.readFailed"), errMsg(e))
  }
}

export async function checkOne(name: string) {
  if (busyOf()[name]) return
  setBusy(name, "check")
  try {
    const s = await api<Source>("upstream_check_one", name)
    if (!s) return
    mergeSource(s)
    if (s.error) notify.error(`${name}: ${s.error}`)
    else if (s.update) notify.info(t("settings.src.updateFound", { name, version: String(s.latest) }))
    else notify.success(t("settings.src.latest", { name }))
  } catch (e) {
    notify.error(t("settings.src.checkOneFailed", { name }), errMsg(e))
  } finally {
    setBusy(name, null)
  }
}

export async function checkAll() {
  const list = store.get<Source[]>(SOURCES_KEY)
  if (!list) return
  for (const s of list) if (!busyOf()[s.name]) setBusy(s.name, "check")
  try {
    const res = await api<Source[]>("upstream_check_updates")
    if (res) store.set(SOURCES_KEY, res)
    sourcesChecked = true
    const n = (res ?? list).filter((s) => s.update).length
    if (n) notify.info(t("settings.src.updatesCount", { count: n }))
    else notify.success(t("settings.src.allLatest"))
  } catch (e) {
    notify.error(t("settings.src.checkFailed"), errMsg(e))
  } finally {
    for (const s of store.get<Source[]>(SOURCES_KEY) ?? []) setBusy(s.name, null)
  }
}

async function updateSource(name: string, quiet?: boolean): Promise<boolean> {
  if (busyOf()[name]) return false
  setBusy(name, "update")
  try {
    const s = await api<Source>("upstream_update", name)
    mergeSource(s)
    if (!quiet) notify.success(`${name}: ${s?.note || t("settings.src.updated")}`)
    return true
  } catch (e) {
    notify.error(t("settings.src.updateFailed", { name }), errMsg(e))
    return false
  } finally {
    setBusy(name, null)
  }
}

export async function updateOneConfirm(name: string) {
  if (busyOf()[name]) return
  const ok = await confirmDialog({
    title: t("settings.src.confirmTitle", { name }),
    description: t("settings.src.confirmDesc") + (name === "Стратегии (Flowseal)" ? " " + t("settings.src.confirmStrategies") : ""),
    confirmText: t("settings.src.confirm"),
  })
  if (ok) await updateSource(name)
}

export async function updateAllConfirm() {
  if (!sourcesChecked) await checkAll()
  const names = (store.get<Source[]>(SOURCES_KEY) ?? []).filter((s) => s.update && s.updatable).map((s) => s.name)
  if (!names.length) {
    notify.info(t("settings.src.nothing"))
    return
  }
  const ok = await confirmDialog({
    title: t("settings.src.allTitle"),
    description: t("settings.src.allDesc", { count: names.length }),
    confirmText: t("settings.src.allConfirm"),
  })
  if (!ok) return
  let done = 0
  for (const name of names) if (await updateSource(name, true)) done++
  if (done === names.length) notify.success(t("settings.src.allDone", { count: done }))
  else notify.warning(t("settings.src.partial", { done, total: names.length }), t("settings.src.partialHint"))
}
