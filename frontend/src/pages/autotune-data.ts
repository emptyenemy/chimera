/* Данные страницы «Автонастройка»: состояние сессии (пушит хаб, ключ autotune), диагноз и
   каталог сервисов (живут в сторе и переживают уход со страницы), прогресс и подписи способов.
   Устройство подбора — docs/AUTOTUNE.md. */

import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { store } from "@/lib/store"

export type Mode = "fast" | "smart"
export type Reason = "dpi" | "dns" | "geo" | "error"
export type FixKind = "strategy" | "hosts" | "dns" | "proxy"
export type Phase =
  | "running" | "done" | "cancelled" | "failed" | "reverted" | "kept" | "interrupted" | "rollback_failed" | "invalid"

export interface Fix {
  kind: FixKind
  id: string
}

export interface ServiceCheck {
  ok: boolean | null
  covered?: number
  total?: number
  reasons?: Reason[]
  ms?: number | null
  skipped?: string
}

export interface ReportRow {
  name: string
  before?: ServiceCheck
  after?: ServiceCheck
  fix?: Fix | null
  hint?: string
  skipped?: string
}

export interface Report {
  mode: Mode
  offline: boolean
  services: ReportRow[]
  fixes: Record<string, Fix>
}

export interface Current {
  step: FixKind
  candidate: string
  index: number
  total: number
}

export interface LogEvent {
  type: "result"
  step: FixKind
  candidate: string
  fixed?: string[]
  covered?: number
  ms?: number | null
  rejected?: "canary" | "protected" | null
  error?: string
}

export interface Session {
  id: string | null
  phase: Phase
  mode: Mode
  trigger?: "user" | "watch"
  services: string[]
  stage: string | null
  current: Current | null
  log: LogEvent[]
  report: Report | null
  error: string | null
  reason: string | null
  cancelling?: boolean | null
}

export interface AutotuneState {
  active: Session | null
  last: Session | null
}

export interface CatalogItem {
  name: string
  targets: string[]
}

export interface TargetCheck {
  domain: string
  status: string
  ms: number | null
}

export interface Diagnosis {
  services: (ServiceCheck & { name: string; targets?: TargetCheck[] })[]
  offline: boolean
}

export interface DiagnosisView {
  busy: boolean
  result: Diagnosis | null
  error: string | null
}

export const CATALOG_KEY = "autotune.catalog"
export const DIAGNOSIS_KEY = "autotune.diagnosis"
export const NAMES_KEY = "autotune.names"

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

export async function loadCatalog(): Promise<void> {
  try {
    store.set(CATALOG_KEY, await api<CatalogItem[]>("autotune_catalog"))
  } catch {
    store.set(CATALOG_KEY, store.get<CatalogItem[]>(CATALOG_KEY) ?? [])
  }
}

// человеческие имена провайдеров для отчёта: «hosts через Comss DNS», а не через comss
export async function loadNames(): Promise<void> {
  try {
    const items = await api<{ id: string; name?: string }[]>("providers_list")
    store.set(NAMES_KEY, Object.fromEntries(items.map((p) => [p.id, p.name || p.id])))
  } catch {
    /* без имён отчёт покажет идентификаторы */
  }
}

export async function diagnose(services: string[] | null = null): Promise<void> {
  const prev = store.get<DiagnosisView>(DIAGNOSIS_KEY)
  store.set(DIAGNOSIS_KEY, { busy: true, result: prev?.result ?? null, error: null })
  try {
    const result = await api<Diagnosis>("autotune_diagnose", services)
    // точечная проверка обновляет только свои строки
    const merged = services && prev?.result
      ? { ...result, services: prev.result.services.map((row) => result.services.find((r) => r.name === row.name) ?? row) }
      : result
    store.set(DIAGNOSIS_KEY, { busy: false, result: merged, error: null })
  } catch (e) {
    store.set(DIAGNOSIS_KEY, { busy: false, result: prev?.result ?? null, error: errText(e) })
  }
}

let absorbed: string | null = null

// Итог подбора — самый свежий диагноз: после «Готово» список не должен откатиться к старому,
// а после «Вернуть как было» — показывать починенным то, что снова не работает.
// Один раз на переход: хаб присылает одно и то же состояние, пока его не закроют.
export function absorbReport(session: Session | null): void {
  const side = session?.phase === "done" ? "after" : session?.phase === "reverted" ? "before" : null
  const report = side ? session?.report : null
  const key = `${session?.id}:${side}`
  if (!report || !side || !session?.id || key === absorbed) return
  absorbed = key
  const fresh = report.services.filter((r) => r[side]).map((r) => ({ name: r.name, ...r[side]! }))
  const prev = store.get<DiagnosisView>(DIAGNOSIS_KEY)?.result
  const services = prev
    ? [...prev.services.map((row) => fresh.find((r) => r.name === row.name) ?? row),
       ...fresh.filter((r) => !prev.services.some((row) => row.name === r.name))]
    : fresh
  store.set(DIAGNOSIS_KEY, { busy: false, error: null, result: { services, offline: report.offline } })
}

// Доля пути: шаги неравные — стратегий десятки, а прокси один.
const SPANS: Record<string, [number, number]> = {
  diagnose: [0, 5],
  strategy: [5, 70],
  hosts: [70, 85],
  dns: [85, 93],
  proxy: [93, 97],
  verify: [97, 100],
}

export function progressPercent(session: Session | null): number {
  if (!session || session.phase !== "running") return 0
  const [start, end] = SPANS[session.stage ?? "diagnose"] ?? [0, 5]
  const cur = session.current
  const part = cur && cur.total ? (cur.index + 1) / cur.total : 0
  return Math.round(start + (end - start) * part)
}

export function statusOf(name: string, diagnosis: Diagnosis | null, session: Session | null): ServiceCheck | null {
  // итог свежей сессии точнее старого диагноза
  const row = session?.report?.services.find((r) => r.name === name)
  if (row?.after) return row.after
  return diagnosis?.services.find((r) => r.name === name) ?? null
}

export function broken(diagnosis: Diagnosis | null): string[] {
  return (diagnosis?.services ?? []).filter((r) => r.ok === false).map((r) => r.name)
}

export function reasonText(check: ServiceCheck | null): string {
  if (!check?.reasons?.length) return ""
  return check.reasons.map((r) => t(`autotune.reason.${r}`)).join(", ")
}

export function fixText(fix: Fix, strategies: { id: string; name?: string }[], names: Record<string, string>): string {
  if (fix.kind === "strategy") {
    const name = strategies.find((s) => s.id === fix.id)?.name ?? fix.id
    return t("autotune.via.strategy", { name })
  }
  if (fix.kind === "proxy") return t("autotune.via.proxy")
  return t(`autotune.via.${fix.kind}`, { name: names[fix.id] ?? fix.id })
}

export function candidateText(step: FixKind, candidate: string, strategies: { id: string; name?: string }[],
                              names: Record<string, string>): string {
  if (step === "strategy") return strategies.find((s) => s.id === candidate)?.name ?? candidate
  if (step === "proxy") return t("autotune.via.proxy")
  return names[candidate] ?? candidate
}
