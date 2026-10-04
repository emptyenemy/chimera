/* Данные страницы «Проверка»: разбор ввода, подсказки по спискам, итог двух проверок и
   состояние проверки. Состояние живёт вне компонента: проверка не прерывается, если уйти
   на другую страницу, а результаты ждут возвращения. Списки стримятся пушами, поэтому
   перерисовка сгруппирована по времени. Отрисовка — pages/checks.tsx. */

import { useSyncExternalStore } from "react"

import { api, onPush } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"

// --- данные --------------------------------------------------------------------

export interface RknResult {
  _request_id?: string
  target?: string
  status?: string
  blocked?: boolean
  rkn_domain?: boolean | string | null
  subnets?: string[]
  cdn?: string[]
}

export interface ReachResult {
  _request_id?: string
  target?: string
  status?: string
  ip?: string | null
  ms?: number | null
  reason?: string | null
  cdn?: string | null   // "cloudflare" — адрес из его сетей (встроенный список cloudflare)
}

export interface Row {
  rkn: RknResult | null
  reach: ReachResult | null
}

export interface RunState {
  requestId: string | null
  starting?: boolean
  reachFinished?: boolean
  rknFinished?: boolean
  total: number
  rknDone: number
  reachDone: number
}

export interface ListIndex {
  name: string
  count: number
  entries: string[]
}

export interface View {
  results: Map<string, Row>
  run: RunState | null
  input: string
  onlyProblems: boolean
  registryDown: string | null
  lists: ListIndex[] | null
}

export const PARALLEL = 4 // для введённых вручную: реестр публичный, не долбим его

// изменяемое состояние страницы и его неизменяемый снимок для React
export const s: View = {
  results: new Map(),
  run: null,
  input: "",
  onlyProblems: false,
  registryDown: null,
  lists: null,
}
export let snap: View = { ...s }
export const listeners = new Set<() => void>()
export let timer = 0

export function emit(): void {
  clearTimeout(timer)
  timer = 0
  snap = { ...s }
  for (const fn of listeners) fn()
}

// поток пушей может быть в сотни в секунду — сливаем их в одну перерисовку
export function emitSoon(): void {
  if (!timer) timer = window.setTimeout(emit, 60)
}

export function useView(): View {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => snap
  )
}

// --- разбор ввода: ссылки, несколько сайтов через пробел/запятую -----------------------

export function parseTargets(text: string): string[] {
  const seen = new Set<string>()
  for (const part of text.split(/[\s,;]+/).filter(Boolean)) {
    try {
      const bareIpv6 = /^[a-f\d:.]+$/i.test(part) && part.split(":").length > 2
      const address = bareIpv6 ? `[${part}]` : part
      const link = new URL(/^[a-z][a-z\d+.-]*:\/\//i.test(part) ? part : `https://${address}`)
      if (!['http:', 'https:'].includes(link.protocol) || link.username || link.password) continue
      const host = link.hostname.toLowerCase()
      if (host.startsWith("[") && host.endsWith("]")) {
        seen.add(host.slice(1, -1))
        continue
      }
      if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
        seen.add(host)
        continue
      }
      const name = host.replace(/^www\./, "").replace(/\.$/, "")
      const labels = name.split(".")
      if (name.length > 253 || labels.length < 2 ||
          !labels.every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)) ||
          !/^(?:[a-z]{2,63}|xn--[a-z0-9-]+)$/.test(labels.at(-1)!)) continue
      seen.add(name)
    } catch {
      continue
    }
  }
  return [...seen]
}

// --- подсказки: списки и домены по набранному ---------------------------------------------

export type Suggestion =
  | { kind: "list"; name: string; count: number; hits: string[]; byName: boolean }
  | { kind: "site"; domain: string }

export interface SuggestionGroup {
  value: string
  items: Suggestion[]
}

export const MAX_LISTS = 8
export const MAX_SITES = 6
export const IP_LIKE = /^[\d.:a-f]+(\/\d+)?$/i

export const lastToken = (text: string) => text.split(/[\s,;]+/).at(-1) ?? ""

// что сейчас набирается: последний адрес в поле, без схемы, www и пути
export function query(text: string): string {
  return lastToken(text)
    .toLowerCase()
    .replace(/^[a-z][a-z\d+.-]*:\/\//, "")
    .replace(/^www\./, "")
    .split(/[/?#]/)[0]
}

export function suggest(lists: ListIndex[] | null, text: string): SuggestionGroup[] {
  const q = query(text)
  if (q.length < 2 || !lists) return []
  const found: Extract<Suggestion, { kind: "list" }>[] = []
  const sites = new Set<string>()
  for (const l of lists) {
    const hits = l.entries.map((e) => e.toLowerCase().replace(/^\./, "")).filter((e) => e.includes(q))
    const byName = l.name.toLowerCase().includes(q)
    if (!byName && !hits.length) continue
    found.push({ kind: "list", name: l.name, count: l.count, hits, byName })
    for (const h of hits) if (!IP_LIKE.test(h)) sites.add(h)
  }
  // совпало имя — список про это и есть; дальше — где совпадений больше
  found.sort((a, b) => Number(b.byName) - Number(a.byName) || b.hits.length - a.hits.length || a.name.localeCompare(b.name))
  const domains = [...sites]
    .sort((a, b) => Number(!a.startsWith(q)) - Number(!b.startsWith(q)) || a.length - b.length || a.localeCompare(b))
    .slice(0, MAX_SITES)
    .map((domain): Suggestion => ({ kind: "site", domain }))
  const groups: SuggestionGroup[] = []
  if (found.length) groups.push({ value: "lists", items: found.slice(0, MAX_LISTS) })
  if (domains.length) groups.push({ value: "sites", items: domains })
  return groups
}

export const suggestionText = (it: Suggestion) => (it.kind === "list" ? it.name : it.domain)

// --- итог по двум проверкам --------------------------------------------------------------

// Реестр различает две вещи: в него внесён сам домен — или только адрес/подсеть, где сайт
// живёт (часто общая CDN вроде Akamai). Для пользователя разный смысл: первое — сайт
// блокируют, второе — он может открываться и сам по себе.
export const inRegistry = (r: RknResult | null) => r?.blocked === true && !!r.rkn_domain
export const ipInRegistry = (r: RknResult | null) => r?.blocked === true && !r.rkn_domain

export type Tone = "success" | "danger" | "warning" | "muted"

export interface Verdict {
  label: string
  tone: Tone
  note: string
  pending?: boolean
}

export function verdict(rkn: RknResult | null, reach: ReachResult | null): Verdict {
  if (!reach) return { label: t("checks.v.pending"), tone: "muted", note: "", pending: true }
  const st = reach.status
  if (st === "ok" || st === "challenge") {
    const cf = st === "challenge" ? t("checks.n.cloudflare") : ""
    return inRegistry(rkn)
      ? {
          label: t("checks.v.viaBypass"),
          tone: "success",
          note: [t("checks.n.registry"), cf].filter(Boolean).join(" · "),
        }
      : { label: t("checks.v.open"), tone: "success", note: cf }
  }
  if (inRegistry(rkn)) return { label: t("checks.v.blocked"), tone: "danger", note: t("checks.n.blocked") }
  if (ipInRegistry(rkn)) return { label: t("checks.v.blockedIp"), tone: "danger", note: t("checks.n.blockedIp") }
  if (st === "denied") return { label: t("checks.v.denied"), tone: "warning", note: reach.reason || t("checks.n.denied") }
  if (st === "dns") return { label: t("checks.v.noDns"), tone: "warning", note: t("checks.n.noDns") }
  if (st === "blocked") return { label: t("checks.v.unreachable"), tone: "danger", note: reach.reason || t("checks.n.unreachable") }
  return { label: t("checks.v.error"), tone: "muted", note: reach.reason || "" }
}

export const isProblem = (r: Row) => verdict(r.rkn, r.reach).tone !== "success" && !!r.reach

/** За Cloudflare: адрес из его сетей по нашему списку или по ответу реестра (cdn_providers). */
export const behindCloudflare = (r: Row) =>
  r.reach?.cdn === "cloudflare" || !!r.rkn?.cdn?.some((name) => /cloudflare/i.test(name))

/** Не открывающиеся сайты за Cloudflare: их чинит один список у прокси, а не каждый отдельно. */
export const cloudflareProblems = (results: Map<string, Row>): string[] =>
  [...results].filter(([, r]) => isProblem(r) && behindCloudflare(r)).map(([site]) => site)

// --- проверка ----------------------------------------------------------------------------

export function put(site: string, key: "rkn" | "reach", value: RknResult | ReachResult): boolean {
  const cur = s.results.get(site) ?? { rkn: null, reach: null }
  s.results.set(site, { ...cur, [key]: value })
  return cur[key] === null
}

export function step(kind: "rknDone" | "reachDone"): void {
  if (s.run) s.run = { ...s.run, [kind]: s.run[kind] + 1 }
}

export function finishIfDone(): void {
  const r = s.run
  if (r && !r.starting && r.rknDone >= r.total && r.reachDone >= r.total) {
    s.run = null
    emit()
  } else emitSoon()
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

// введённые вручную: обе проверки на каждый сайт, по PARALLEL сайтов разом
export async function checkTyped(): Promise<void> {
  if (s.run) return
  const sites = parseTargets(s.input)
  if (!sites.length) {
    notify.warning(t("checks.badTarget.title"), t("checks.badTarget.desc"))
    return
  }
  s.results = new Map(sites.map((site) => [site, { rkn: null, reach: null }]))
  s.run = { requestId: null, total: sites.length, rknDone: 0, reachDone: 0 }
  emit()
  const registryDown = !!s.registryDown
  const one = async (site: string) => {
    await Promise.all([
      api<ReachResult>("block_check_one", site)
        .then(
          (r) => put(site, "reach", r),
          (e) => put(site, "reach", { status: "error", reason: errText(e) })
        )
        .finally(() => step("reachDone")),
      (registryDown ? Promise.resolve<RknResult>({ status: "error" }) : api<RknResult>("chebur_check_one", site))
        .then(
          (r) => put(site, "rkn", r),
          () => put(site, "rkn", { status: "error" })
        )
        .finally(() => step("rknDone")),
    ])
    finishIfDone()
  }
  const queue = [...sites]
  await Promise.all(
    Array.from({ length: Math.min(PARALLEL, queue.length) }, async () => {
      while (queue.length) await one(queue.shift()!)
    })
  )
}

// список: обе проверки идут на бэкенде и стримятся пушами
export async function checkList(name: string): Promise<void> {
  if (!name || s.run) return
  const requestId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
  const registryDown = !!s.registryDown
  s.results = new Map()
  s.run = { requestId, total: 0, rknDone: 0, reachDone: 0, starting: true }
  emit()
  try {
    const reach = await api<{ total?: number; targets?: string[] }>("block_check_start", name, requestId)
    const targets = reach?.targets
    const total = targets?.length ?? reach?.total ?? 0
    if (targets) s.results = new Map(targets.map(site => [site, s.results.get(site) ?? { rkn: null, reach: null }]))
    s.run = s.run && { ...s.run, total, reachDone: s.run.reachFinished ? total : s.run.reachDone }
    if (!registryDown) {
      try {
        await api("chebur_check_start", name, requestId, targets)
      } catch {
        fillRegistryErrors()
      }
    } else fillRegistryErrors()
    if (s.run) {
      s.run = { ...s.run, starting: false, rknDone: s.run.rknFinished ? total : s.run.rknDone }
      finishIfDone()
    }
  } catch (e) {
    s.run = null
    notify.error(t("checks.listFailed"), errText(e))
  }
  emit()
}

export function fillRegistryErrors(): void {
  for (const site of s.results.keys()) put(site, "rkn", { status: "error" })
  if (s.run) s.run = { ...s.run, rknDone: s.run.total, rknFinished: true }
}

export function isCurrentStream(p: { _request_id?: string } | null | undefined): boolean {
  return !!s.run?.requestId && p?._request_id === s.run.requestId
}

export function acceptResult(kind: "rkn" | "reach", r: RknResult | ReachResult): void {
  if (!s.run || !r?.target || (!s.run.starting && !s.results.has(r.target))) return
  if (put(r.target, kind, r)) step(kind === "rkn" ? "rknDone" : "reachDone")
}

onPush("blockResult", (p) => {
  const r = p as ReachResult
  if (!isCurrentStream(r)) return
  acceptResult("reach", r)
  finishIfDone()
})
onPush("cheburResult", (p) => {
  const r = p as RknResult
  if (!isCurrentStream(r)) return
  acceptResult("rkn", r)
  finishIfDone()
})

export interface StreamDone {
  _request_id?: string
  results?: (RknResult | ReachResult)[]
}

export function acceptDone(kind: "rkn" | "reach", p: StreamDone): void {
  if (!isCurrentStream(p)) return
  for (const r of p.results ?? []) acceptResult(kind, r)
  if (s.run) s.run = kind === "reach"
    ? { ...s.run, reachDone: s.run.total, reachFinished: true }
    : { ...s.run, rknDone: s.run.total, rknFinished: true }
  finishIfDone()
}
onPush("blockDone", (p) => acceptDone("reach", p as StreamDone))
onPush("cheburDone", (p) => acceptDone("rkn", p as StreamDone))

export let listReadGeneration = 0
export async function loadLists(): Promise<void> {
  const generation = ++listReadGeneration
  try {
    const lists = await api<ListIndex[]>("lists_index")
    if (generation !== listReadGeneration) return
    s.lists = lists
  } catch {
    if (generation !== listReadGeneration) return
    s.lists = s.lists ?? []
  }
  emit()
}

// выбранный из подсказок домен встаёт вместо недописанного адреса
export function pickSuggestion(it: Suggestion): void {
  if (s.run) return
  if (it.kind === "list") {
    void checkList(it.name)
    return
  }
  const token = lastToken(s.input)
  s.input = (token ? s.input.slice(0, -token.length) : s.input) + it.domain
  emit()
  void checkTyped()
}

export let registryReadGeneration = 0
export async function loadRegistryStatus(): Promise<void> {
  const generation = ++registryReadGeneration
  try {
    await api("chebur_status")
    if (generation !== registryReadGeneration) return
    s.registryDown = null
  } catch (e) {
    if (generation !== registryReadGeneration) return
    s.registryDown = errText(e)
  }
  emit()
}
