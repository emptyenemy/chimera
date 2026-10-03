import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { optimistic, store } from "@/lib/store"

export type GameMode = "off" | "all" | "tcp" | "udp"
export type IpsetMode = "none" | "any" | "loaded"
export type Proto = "tcp" | "udp"

export interface FiltersState {
  game: GameMode
  game_ranges?: Record<Proto, string>
  ipset: IpsetMode
  ipset_count?: number
  ipset_stored?: number
  fakes?: { slots: Record<string, { label: string; present?: boolean; current?: string | null }>; candidates: string[] }
  apply_error?: string
}

interface RangeDraft {
  value: string
  revision: number
  status: "dirty" | "saving" | "error"
  error?: string
}

export type RangeDrafts = Partial<Record<Proto, RangeDraft>>
export const RANGE_DRAFTS_KEY = "strategies.rangeDrafts"
export const RANGE_RESET_KEY = "strategies.rangeReset"
export const GAME_RANGE_DEFAULT = "1024-65535"
const DEFAULT_RANGES = { tcp: GAME_RANGE_DEFAULT, udp: GAME_RANGE_DEFAULT }
const protocols: Proto[] = ["tcp", "udp"]
const message = (error: unknown) => error instanceof Error ? error.message : String(error)
let revision = 0

const drafts = () => store.get<RangeDrafts>(RANGE_DRAFTS_KEY) ?? {}

export function validateGameRange(value: string): string | null {
  const normalized = value.replace(/\s+/g, "")
  if (!normalized) return t("strat.range.empty")
  for (const item of normalized.split(",")) {
    if (!/^[1-9][0-9]{0,4}(-[1-9][0-9]{0,4})?$/.test(item)) return t("strat.range.format", { item })
    const [startText, endText] = item.split("-")
    const start = Number(startText), end = Number(endText ?? startText)
    if (start > 65535 || end > 65535) return t("strat.range.outside", { item })
    if (start > end) return t("strat.range.reversed", { item })
  }
  return null
}

export function reportFilterApply(label: string, result: FiltersState | undefined): void {
  if (result?.apply_error) notify.error(t("strat.applyFailed", { label }), result.apply_error)
  else if (store.get<{ running?: boolean }>("winws")?.running) notify.success(t("strat.applied", { label }))
}

export function editRange(which: Proto, value: string): void {
  store.set(RANGE_DRAFTS_KEY, { ...drafts(), [which]: { value, revision: ++revision, status: "dirty" } })
}

export function discardRange(which: Proto): void {
  const next = { ...drafts() }
  delete next[which]
  store.set(RANGE_DRAFTS_KEY, next)
}

function updateSubmitted(which: Proto, submitted: RangeDraft, error?: string): void {
  if (drafts()[which]?.revision !== submitted.revision) return
  if (error) store.set(RANGE_DRAFTS_KEY, { ...drafts(), [which]: { ...submitted, status: "error", error } })
  else discardRange(which)
}

function writeRanges(patch: Partial<Record<Proto, string>>): Promise<FiltersState> {
  return optimistic("filters", (value) => ({
    game_ranges: { ...DEFAULT_RANGES, ...(value as FiltersState | undefined)?.game_ranges, ...patch },
  }), () => {
    const mode = store.confirmed<FiltersState>("filters")?.game ?? "off"
    return api<FiltersState>("game_filter_set", mode, patch.tcp ?? null, patch.udp ?? null)
  }, { notifyError: false })
}

export async function commitRange(which: Proto): Promise<FiltersState | undefined> {
  const submitted = drafts()[which]
  if (!submitted || submitted.status === "saving") return
  const error = validateGameRange(submitted.value)
  if (error) {
    updateSubmitted(which, submitted, error)
    return
  }
  const value = submitted.value.replace(/\s+/g, "")
  const confirmed = store.confirmed<FiltersState>("filters")?.game_ranges?.[which] ?? GAME_RANGE_DEFAULT
  if (!store.pending("filters") && value === confirmed) {
    updateSubmitted(which, submitted)
    return
  }
  store.set(RANGE_DRAFTS_KEY, { ...drafts(), [which]: { ...submitted, status: "saving" } })
  try {
    const result = await writeRanges({ [which]: value })
    updateSubmitted(which, submitted)
    reportFilterApply(t(which === "tcp" ? "strat.range.tcpLabel" : "strat.range.udpLabel"), result)
    return result
  } catch (error) {
    updateSubmitted(which, submitted, message(error))
  }
}

export async function resetRanges(): Promise<FiltersState | undefined> {
  if (store.get<boolean>(RANGE_RESET_KEY)) return
  store.set(RANGE_RESET_KEY, true)
  const submitted: RangeDrafts = {}
  for (const which of protocols) submitted[which] = { value: GAME_RANGE_DEFAULT, revision: ++revision, status: "saving" }
  store.set(RANGE_DRAFTS_KEY, submitted)
  try {
    const result = await writeRanges(DEFAULT_RANGES)
    for (const which of protocols) updateSubmitted(which, submitted[which]!)
    reportFilterApply(t("strat.range.resetLabel"), result)
    return result
  } catch (error) {
    for (const which of protocols) updateSubmitted(which, submitted[which]!, message(error))
    notify.error(t("strat.range.resetFailed"), message(error))
  } finally {
    store.set(RANGE_RESET_KEY, false)
  }
}

export async function flushRanges(): Promise<void> {
  await Promise.all(protocols.filter(which => drafts()[which]?.status === "dirty").map(commitRange))
}
