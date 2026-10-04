/* Проверка: одно поле — один ответ по каждому сайту. Внутри две проверки идут
   параллельно — есть ли сайт в реестре РКН (cheburcheck) и открывается ли он прямо сейчас
   с этой машины с учётом обхода (blockcheck), — а в таблице они сведены в итог словами:
   «Открывается», «Работает через обход», «Заблокирован» и т.п.

   Поле заодно и поиск: по набранному предлагаются списки, где такой домен есть, и сами
   домены — выбор подсказки запускает проверку списка или сайта.

   Состояние живёт вне компонента (как у прежней страницы): проверка не прерывается,
   если уйти на другую страницу, а результаты ждут возвращения. Списки стримятся пушами,
   поэтому перерисовка таблицы сгруппирована по времени, а строки мемоизированы. */

import { memo, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import { Autocomplete } from "@base-ui/react/autocomplete"
import { CircleCheckIcon, GlobeIcon, ListIcon, SearchIcon, TriangleAlertIcon } from "lucide-react"
import { cn } from "cn"

import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api, onPush } from "@/lib/bridge"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"

// --- данные --------------------------------------------------------------------

interface RknResult {
  _request_id?: string
  target?: string
  status?: string
  blocked?: boolean
  rkn_domain?: boolean | string | null
  subnets?: string[]
  cdn?: string[]
}

interface ReachResult {
  _request_id?: string
  target?: string
  status?: string
  ip?: string | null
  ms?: number | null
  reason?: string | null
}

interface Row {
  rkn: RknResult | null
  reach: ReachResult | null
}

interface RunState {
  requestId: string | null
  starting?: boolean
  reachFinished?: boolean
  rknFinished?: boolean
  total: number
  rknDone: number
  reachDone: number
}

interface ListIndex {
  name: string
  count: number
  entries: string[]
}

interface View {
  results: Map<string, Row>
  run: RunState | null
  input: string
  onlyProblems: boolean
  registryDown: string | null
  lists: ListIndex[] | null
}

const PARALLEL = 4 // для введённых вручную: реестр публичный, не долбим его

// изменяемое состояние страницы и его неизменяемый снимок для React
const s: View = {
  results: new Map(),
  run: null,
  input: "",
  onlyProblems: false,
  registryDown: null,
  lists: null,
}
let snap: View = { ...s }
const listeners = new Set<() => void>()
let timer = 0

function emit(): void {
  clearTimeout(timer)
  timer = 0
  snap = { ...s }
  for (const fn of listeners) fn()
}

// поток пушей может быть в сотни в секунду — сливаем их в одну перерисовку
function emitSoon(): void {
  if (!timer) timer = window.setTimeout(emit, 60)
}

function useView(): View {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => snap
  )
}

// --- разбор ввода: ссылки, несколько сайтов через пробел/запятую -----------------------

function parseTargets(text: string): string[] {
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

type Suggestion =
  | { kind: "list"; name: string; count: number; hits: string[]; byName: boolean }
  | { kind: "site"; domain: string }

interface SuggestionGroup {
  value: string
  items: Suggestion[]
}

const MAX_LISTS = 8
const MAX_SITES = 6
const IP_LIKE = /^[\d.:a-f]+(\/\d+)?$/i

const lastToken = (text: string) => text.split(/[\s,;]+/).at(-1) ?? ""

// что сейчас набирается: последний адрес в поле, без схемы, www и пути
function query(text: string): string {
  return lastToken(text)
    .toLowerCase()
    .replace(/^[a-z][a-z\d+.-]*:\/\//, "")
    .replace(/^www\./, "")
    .split(/[/?#]/)[0]
}

function suggest(lists: ListIndex[] | null, text: string): SuggestionGroup[] {
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

const suggestionText = (it: Suggestion) => (it.kind === "list" ? it.name : it.domain)

// --- итог по двум проверкам --------------------------------------------------------------

// Реестр различает две вещи: в него внесён сам домен — или только адрес/подсеть, где сайт
// живёт (часто общая CDN вроде Akamai). Для пользователя разный смысл: первое — сайт
// блокируют, второе — он может открываться и сам по себе.
const inRegistry = (r: RknResult | null) => r?.blocked === true && !!r.rkn_domain
const ipInRegistry = (r: RknResult | null) => r?.blocked === true && !r.rkn_domain

type Tone = "success" | "danger" | "warning" | "muted"

interface Verdict {
  label: string
  tone: Tone
  note: string
  pending?: boolean
}

function verdict(rkn: RknResult | null, reach: ReachResult | null): Verdict {
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

const isProblem = (r: Row) => verdict(r.rkn, r.reach).tone !== "success" && !!r.reach

// --- проверка ----------------------------------------------------------------------------

function put(site: string, key: "rkn" | "reach", value: RknResult | ReachResult): boolean {
  const cur = s.results.get(site) ?? { rkn: null, reach: null }
  s.results.set(site, { ...cur, [key]: value })
  return cur[key] === null
}

function step(kind: "rknDone" | "reachDone"): void {
  if (s.run) s.run = { ...s.run, [kind]: s.run[kind] + 1 }
}

function finishIfDone(): void {
  const r = s.run
  if (r && !r.starting && r.rknDone >= r.total && r.reachDone >= r.total) {
    s.run = null
    emit()
  } else emitSoon()
}

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

// введённые вручную: обе проверки на каждый сайт, по PARALLEL сайтов разом
async function checkTyped(): Promise<void> {
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
async function checkList(name: string): Promise<void> {
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

function fillRegistryErrors(): void {
  for (const site of s.results.keys()) put(site, "rkn", { status: "error" })
  if (s.run) s.run = { ...s.run, rknDone: s.run.total, rknFinished: true }
}

function isCurrentStream(p: { _request_id?: string } | null | undefined): boolean {
  return !!s.run?.requestId && p?._request_id === s.run.requestId
}

function acceptResult(kind: "rkn" | "reach", r: RknResult | ReachResult): void {
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

interface StreamDone {
  _request_id?: string
  results?: (RknResult | ReachResult)[]
}

function acceptDone(kind: "rkn" | "reach", p: StreamDone): void {
  if (!isCurrentStream(p)) return
  for (const r of p.results ?? []) acceptResult(kind, r)
  if (s.run) s.run = kind === "reach"
    ? { ...s.run, reachDone: s.run.total, reachFinished: true }
    : { ...s.run, rknDone: s.run.total, rknFinished: true }
  finishIfDone()
}
onPush("blockDone", (p) => acceptDone("reach", p as StreamDone))
onPush("cheburDone", (p) => acceptDone("rkn", p as StreamDone))

let listReadGeneration = 0
async function loadLists(): Promise<void> {
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
function pickSuggestion(it: Suggestion): void {
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

let registryReadGeneration = 0
async function loadRegistryStatus(): Promise<void> {
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

// --- отображение -------------------------------------------------------------------------

const DOT_TONE = { success: "ok", danger: "err", warning: "warn", muted: "off" } as const
const TEXT_TONE: Record<Tone, string> = {
  success: "",
  danger: "text-destructive",
  warning: "text-warning",
  muted: "text-muted-foreground",
}

function RegistryCell({ rkn, down }: { rkn: RknResult | null; down: boolean }) {
  if (!rkn) return <span className="text-muted-foreground">{down ? "—" : "…"}</span>
  if (rkn.status === "rate" || rkn.status === "error")
    return (
      <Tooltip>
        <TooltipTrigger render={<span className="text-muted-foreground" />}>—</TooltipTrigger>
        <TooltipContent>{t("checks.reg.noAnswer")}</TooltipContent>
      </Tooltip>
    )
  if (inRegistry(rkn)) return <Badge variant="secondary">{t("checks.reg.domain")}</Badge>
  if (ipInRegistry(rkn)) {
    const nets = [...(rkn.subnets ?? []), ...(rkn.cdn ?? [])].join(", ")
    return (
      <Tooltip>
        <TooltipTrigger render={<Badge variant="outline" />}>{t("checks.reg.ip")}</TooltipTrigger>
        {nets && <TooltipContent>{nets}</TooltipContent>}
      </Tooltip>
    )
  }
  return <span className="text-muted-foreground">{t("checks.reg.none")}</span>
}

const SiteRow = memo(function SiteRow({ site, row, down }: { site: string; row: Row; down: boolean }) {
  const v = verdict(row.rkn, row.reach)
  const reach = row.reach
  const ms = reach?.ms != null && (reach.status === "ok" || reach.status === "challenge") ? t("checks.ms", { ms: fmtNum(reach.ms) }) : ""
  return (
    <TableRow data-testid={`checks-row-${site}`} data-tone={v.tone}>
      <TableCell className="align-top font-mono text-[13px]">
        {reach?.ip ? (
          <Tooltip>
            <TooltipTrigger render={<span />}>{site}</TooltipTrigger>
            <TooltipContent>{t("checks.ip", { ip: reach.ip })}</TooltipContent>
          </Tooltip>
        ) : (
          site
        )}
      </TableCell>
      <TableCell className="align-top whitespace-normal">
        <div className={cn("flex items-center gap-2 font-medium", TEXT_TONE[v.tone])}>
          {v.pending ? <Spinner className="size-3" /> : <StatusDot tone={DOT_TONE[v.tone]} />}
          {v.label}
        </div>
        {v.note && <div className="mt-0.5 pl-4 text-xs text-muted-foreground">{v.note}</div>}
      </TableCell>
      <TableCell className="align-top">
        <RegistryCell rkn={row.rkn} down={down} />
      </TableCell>
      <TableCell className="align-top text-right text-muted-foreground tabular-nums">{ms}</TableCell>
    </TableRow>
  )
})

function Summary({ view }: { view: View }) {
  const { run, results } = view
  if (run) return <span>{t("checks.summary.running", { done: Math.min(run.reachDone, run.total), total: run.total })}</span>
  const all = [...results.values()]
  if (!all.length) return null
  const open = all.filter((r) => verdict(r.rkn, r.reach).tone === "success").length
  const reg = all.filter((r) => inRegistry(r.rkn)).length
  return (
    <span data-testid="checks-summary">
      {t("checks.summary.open")} <b className="font-semibold text-foreground">{t("checks.summary.ofTotal", { n: open, total: all.length })}</b>
      {reg > 0 && (
        <>
          {" · "}
          {t("checks.summary.registry")} <b className="font-semibold text-foreground">{reg}</b>
        </>
      )}
    </span>
  )
}

function Results({ view }: { view: View }) {
  const { results, run, onlyProblems, registryDown } = view
  const rows = [...results.entries()].filter(([, r]) => !onlyProblems || isProblem(r))
  const progress = run && run.total ? Math.min(100, ((run.rknDone + run.reachDone) / (run.total * 2)) * 100) : 0
  return (
    <Card data-testid="checks-results">
      <CardHeader>
        <CardTitle className="font-normal text-muted-foreground">
          <Summary view={view} />
        </CardTitle>
        <CardAction>
          <Field orientation="horizontal">
            <Checkbox
              id="checks-only-problems"
              data-testid="checks-only-problems"
              checked={onlyProblems}
              onCheckedChange={(v) => {
                s.onlyProblems = v === true
                emit()
              }}
            />
            <FieldLabel htmlFor="checks-only-problems" className="font-normal">
              {t("checks.onlyProblems")}
            </FieldLabel>
          </Field>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {run && <Progress value={progress} data-testid="checks-progress" />}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("checks.col.site")}</TableHead>
              <TableHead>{t("checks.col.verdict")}</TableHead>
              <TableHead>{t("checks.col.registry")}</TableHead>
              <TableHead className="text-right">{t("checks.col.answer")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([site, row]) => (
              <SiteRow key={site} site={site} row={row} down={!!registryDown} />
            ))}
            {!rows.length && run && (
              <TableRow>
                <TableCell colSpan={4}>
                  <div className="flex flex-col gap-2">
                    <Skeleton className="h-5 w-full" />
                    <Skeleton className="h-5 w-full" />
                    <Skeleton className="h-5 w-full" />
                  </div>
                </TableCell>
              </TableRow>
            )}
            {!rows.length && !run && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={4}>
                  <Empty className="p-6">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <CircleCheckIcon />
                      </EmptyMedia>
                      <EmptyTitle>{t("checks.empty.noProblems")}</EmptyTitle>
                    </EmptyHeader>
                  </Empty>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

// совпавшая с запросом часть — жирным
function Match({ text, q }: { text: string; q: string }) {
  const i = q ? text.toLowerCase().indexOf(q) : -1
  if (i < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <b className="font-semibold text-foreground">{text.slice(i, i + q.length)}</b>
      {text.slice(i + q.length)}
    </>
  )
}

function SuggestionBody({ it, q }: { it: Suggestion; q: string }) {
  if (it.kind === "site")
    return (
      <>
        <GlobeIcon className="text-muted-foreground" />
        <span className="truncate font-mono text-[13px] text-muted-foreground">
          <Match text={it.domain} q={q} />
        </span>
      </>
    )
  const more = it.hits.length - 3
  return (
    <>
      <ListIcon className="mt-0.5 self-start text-muted-foreground" />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-baseline gap-2">
          <span className="font-medium">
            <Match text={it.name} q={q} />
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">{fmtNum(it.count)}</span>
        </span>
        {it.hits.length > 0 && (
          <span className="truncate text-xs text-muted-foreground">
            {it.hits.slice(0, 3).join(", ")}
            {more > 0 && ` +${fmtNum(more)}`}
          </span>
        )}
      </div>
    </>
  )
}

function CheckForm({ view }: { view: View }) {
  const { run, input, lists, registryDown } = view
  const groups = useMemo(() => suggest(lists, input), [lists, input])
  const [open, setOpen] = useState(false)
  const highlighted = useRef<Suggestion | undefined>(undefined)
  const anchor = useRef<HTMLDivElement>(null)
  const shown = open && groups.length > 0 && !run
  const q = query(input)
  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <Autocomplete.Root
          items={groups}
          filter={null}
          value={input}
          open={shown}
          itemToStringValue={suggestionText}
          onOpenChange={(next) => {
            setOpen(next)
            if (!next) highlighted.current = undefined
          }}
          onItemHighlighted={(it) => {
            highlighted.current = it
          }}
          onValueChange={(value, details) => {
            if (details.reason === "item-press") return // выбор подсказки обрабатывает сам пункт
            s.input = value
            emit()
          }}
        >
          <FieldGroup>
            <Field orientation="horizontal" className="flex-wrap">
              <InputGroup ref={anchor} className="min-w-60 flex-1">
                <InputGroupAddon>
                  <SearchIcon />
                </InputGroupAddon>
                <Autocomplete.Input
                  render={<InputGroupInput />}
                  data-testid="checks-input"
                  aria-label={t("checks.input.label")}
                  placeholder={t("checks.input.placeholder")}
                  autoComplete="off"
                  spellCheck={false}
                  onKeyDown={(e) => {
                    // Enter по подсвеченной подсказке выбирает её, иначе проверяет набранное
                    if (e.key === "Enter" && !(shown && highlighted.current)) void checkTyped()
                  }}
                />
              </InputGroup>
              <Button data-testid="checks-run" disabled={!!run} onClick={() => void checkTyped()}>
                {run && <Spinner data-icon="inline-start" />}
                {t("checks.run")}
              </Button>
            </Field>
          </FieldGroup>
          <Autocomplete.Portal>
            <Autocomplete.Positioner anchor={anchor} sideOffset={4} className="isolate z-50">
              <Autocomplete.Popup
                data-testid="checks-suggestions"
                className="max-h-[min(var(--available-height),24rem)] w-(--anchor-width) overflow-y-auto rounded-md bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95"
              >
                <Autocomplete.List className="p-1">
                  {(group: SuggestionGroup) => (
                    <Autocomplete.Group key={group.value} items={group.items}>
                      <Autocomplete.GroupLabel className="px-2 py-1.5 text-xs text-muted-foreground">
                        {t(group.value === "lists" ? "checks.suggest.lists" : "checks.suggest.sites")}
                      </Autocomplete.GroupLabel>
                      <Autocomplete.Collection>
                        {(it: Suggestion) => (
                          <Autocomplete.Item
                            key={`${it.kind}:${suggestionText(it)}`}
                            value={it}
                            data-testid={`checks-suggest-${it.kind}-${suggestionText(it)}`}
                            onClick={() => pickSuggestion(it)}
                            className="flex w-full cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
                          >
                            <SuggestionBody it={it} q={q} />
                          </Autocomplete.Item>
                        )}
                      </Autocomplete.Collection>
                    </Autocomplete.Group>
                  )}
                </Autocomplete.List>
              </Autocomplete.Popup>
            </Autocomplete.Positioner>
          </Autocomplete.Portal>
        </Autocomplete.Root>
        {registryDown && (
          <Alert data-testid="checks-registry-down">
            <TriangleAlertIcon />
            <AlertDescription>{t("checks.registryDown")}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}

export function ChecksPage() {
  const view = useView()
  useEffect(() => {
    void loadLists()
    void loadRegistryStatus()
  }, [])
  return (
    <Page id="checks" title={t("nav.checks")}>
      <CheckForm view={view} />
      {(view.results.size > 0 || view.run) && <Results view={view} />}
    </Page>
  )
}
