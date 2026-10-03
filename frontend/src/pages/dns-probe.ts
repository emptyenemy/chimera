import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { store } from "@/lib/store"

interface ProbeConfig { bypass?: string[]; ad?: string }
export interface ProbeFields { bypass: string; ad: string }
interface ProbeDraft extends ProbeFields { error: string | null }
export interface ProbeState {
  value: ProbeFields | null
  draft: ProbeDraft | null
  busy: boolean
  error: string | null
}

export const PROBE_KEY = "dns.probeConfig"
const state = (): ProbeState => store.get<ProbeState>(PROBE_KEY) ?? { value: null, draft: null, busy: false, error: null }
const fields = (config: ProbeConfig): ProbeFields => ({ bypass: (config?.bypass ?? []).join(" "), ad: config?.ad ?? "" })
const message = (error: unknown) => error instanceof Error ? error.message : String(error)
let revision = 0
let readGeneration = 0
let queued = 0
let tail: Promise<unknown> = Promise.resolve()
const submissions = new WeakMap<ProbeDraft, Promise<boolean>>()

export async function loadProbeConfig(): Promise<void> {
  if (state().busy || state().draft) return
  const before = revision
  const generation = ++readGeneration
  try {
    const config = await api<ProbeConfig>("dns_probe_config")
    if (generation === readGeneration && before === revision && !state().busy && !state().draft)
      store.set(PROBE_KEY, { ...state(), value: fields(config), error: null })
  } catch (error) {
    if (generation === readGeneration && before === revision && !state().draft)
      store.set(PROBE_KEY, { ...state(), error: message(error) })
  }
}

export function editProbeConfig(part: Partial<ProbeFields>): void {
  const current = state()
  if (!current.value && !current.draft) return
  ++revision
  store.set(PROBE_KEY, { ...current, draft: { ...current.value, ...current.draft, ...part, error: null } })
}

export function saveProbeConfig(): Promise<boolean> {
  const draft = state().draft
  if (!draft) return Promise.resolve(true)
  const previous = submissions.get(draft)
  if (previous) return previous
  ++queued
  ++revision
  store.set(PROBE_KEY, { ...state(), busy: true })
  const saving = tail.then(async () => {
    try {
      const config = await api<ProbeConfig>("dns_set_probe_config", draft.bypass, draft.ad)
      const current = state()
      store.set(PROBE_KEY, { ...current, value: fields(config), draft: current.draft === draft ? null : current.draft, error: null })
      return true
    } catch (error) {
      const current = state()
      if (current.draft === draft)
        store.set(PROBE_KEY, { ...current, draft: { ...draft, error: message(error) } })
      notify.error(t("dns.probeCfg.failed"), message(error))
      return false
    } finally {
      --queued
      ++revision
      store.set(PROBE_KEY, { ...state(), busy: queued > 0 })
    }
  })
  submissions.set(draft, saving)
  tail = saving
  return saving
}
