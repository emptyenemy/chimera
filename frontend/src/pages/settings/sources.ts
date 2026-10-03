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
export const GROUP_KEY = "settings.srcGroup"
export interface SourceGroup { checking?: boolean; updating?: boolean }

let sourcesChecked = false
let readGeneration = 0
let checking: Promise<void> | null = null
let allTokens: Map<string, number> | null = null
let allRequest: string | null = null
let requestSequence = 0
const revisions = new Map<string, number>()
const confirming = new Set<string>()

export type Busy = Record<string, "check" | "update">
const busyOf = () => store.get<Busy>(BUSY_KEY) ?? {}
function setBusy(name: string, mode: "check" | "update" | null) {
  const next = { ...busyOf() }
  if (mode) next[name] = mode
  else delete next[name]
  store.set(BUSY_KEY, next)
}
function setGroup(part: SourceGroup) {
  store.set(GROUP_KEY, { ...store.get<SourceGroup>(GROUP_KEY), ...part })
}
function revise(name: string): number {
  const revision = (revisions.get(name) ?? 0) + 1
  revisions.set(name, revision)
  return revision
}
function mergeSource(s: Source | undefined | null) {
  if (!s) return
  const list = [...(store.get<Source[]>(SOURCES_KEY) ?? [])]
  const i = list.findIndex((x) => x.name === s.name)
  if (i >= 0) list[i] = s
  else list.push(s)
  store.set(SOURCES_KEY, list)
}

onPush("srcChecked", (raw) => {
  const s = raw as (Source & { _request_id?: string }) | null
  if (!s?.name || s._request_id !== allRequest || !allTokens?.has(s.name) || allTokens.get(s.name) !== revisions.get(s.name)) return
  mergeSource(s)
  if (busyOf()[s.name] === "check") setBusy(s.name, null)
})

export async function refreshSources(): Promise<void> {
  const generation = ++readGeneration
  const before = new Map(revisions)
  try {
    const list = await api<Source[]>("upstream_versions")
    if (generation !== readGeneration) return
    for (const s of list ?? []) {
      if (before.get(s.name) !== revisions.get(s.name) || busyOf()[s.name] || confirming.has(s.name) ||
          (allTokens?.has(s.name) && allTokens.get(s.name) === revisions.get(s.name))) continue
      const previous = store.get<Source[]>(SOURCES_KEY)?.find(x => x.name === s.name)
      const sameVersion = previous && (previous.version ?? previous.current) === (s.version ?? s.current)
      mergeSource(sameVersion ? { ...previous, ...s } : s)
      revise(s.name)
    }
  } catch (e) {
    if (generation === readGeneration) notify.error(t("settings.src.readFailed"), errMsg(e))
  }
}

export async function checkOne(name: string) {
  if (busyOf()[name] || confirming.has(name)) return
  revise(name)
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
    revise(name)
    setBusy(name, null)
  }
}

export function checkAll(): Promise<void> {
  if (checking) return checking
  const list = store.get<Source[]>(SOURCES_KEY)
  if (!list?.length) return Promise.resolve()
  const tokens = new Map<string, number>()
  for (const s of list) {
    if (busyOf()[s.name] || confirming.has(s.name)) continue
    tokens.set(s.name, revise(s.name))
    setBusy(s.name, "check")
  }
  if (!tokens.size) return Promise.resolve()
  allTokens = tokens
  const requestId = `${Date.now()}-${++requestSequence}`
  allRequest = requestId
  setGroup({ checking: true })
  checking = Promise.resolve().then(async () => {
    try {
      const res = await api<Source[]>("upstream_check_updates", requestId)
      for (const s of res ?? [])
        if (tokens.has(s.name) && tokens.get(s.name) === revisions.get(s.name)) mergeSource(s)
      sourcesChecked = !!res
      const n = (store.get<Source[]>(SOURCES_KEY) ?? []).filter((s) => s.update).length
      if (n) notify.info(t("settings.src.updatesCount", { count: n }))
      else notify.success(t("settings.src.allLatest"))
    } catch (e) {
      notify.error(t("settings.src.checkFailed"), errMsg(e))
    } finally {
      for (const [name, token] of tokens) {
        if (revisions.get(name) !== token) continue
        revise(name)
        setBusy(name, null)
      }
      allTokens = null
      allRequest = null
      checking = null
      setGroup({ checking: false })
    }
  })
  return checking
}

async function updateSource(name: string, quiet?: boolean): Promise<boolean> {
  if (busyOf()[name]) return false
  revise(name)
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
    revise(name)
    setBusy(name, null)
  }
}

export async function updateOneConfirm(name: string) {
  if (busyOf()[name] || confirming.has(name)) return
  confirming.add(name)
  try {
    const strategies = store.get<Source[]>(SOURCES_KEY)?.find(s => s.name === name)?.repo ===
      "https://github.com/Flowseal/zapret-discord-youtube"
    const ok = await confirmDialog({
      title: t("settings.src.confirmTitle", { name }),
      description: t("settings.src.confirmDesc") + (strategies ? " " + t("settings.src.confirmStrategies") : ""),
      confirmText: t("settings.src.confirm"),
    })
    if (ok) await updateSource(name)
  } finally {
    confirming.delete(name)
  }
}

export async function updateAllConfirm() {
  if (store.get<SourceGroup>(GROUP_KEY)?.updating) return
  setGroup({ updating: true })
  let names: string[] = []
  try {
    if (checking) await checking
    else if (!sourcesChecked) await checkAll()
    names = (store.get<Source[]>(SOURCES_KEY) ?? [])
      .filter((s) => s.update && s.updatable && !busyOf()[s.name] && !confirming.has(s.name)).map((s) => s.name)
    if (!names.length) {
      notify.info(t("settings.src.nothing"))
      return
    }
    for (const name of names) confirming.add(name)
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
  } finally {
    for (const name of names) confirming.delete(name)
    setGroup({ updating: false })
  }
}
