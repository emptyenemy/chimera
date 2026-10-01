import { useStore } from "@/lib/store"

export type TrialKind = "strategy" | "hosts" | "tun"
export interface Trial {
  id: string | null
  kind: TrialKind | null
  target: string
  phase: string
  checks_done: boolean
  checks: { domain: string; status: string }[]
  seconds_left: number
  reason?: string
  error?: string
}
export interface TrialState {
  active: Trial | null
  last: Trial | null
}

export function useTrialPending() {
  const state = useStore<TrialState>("trial")
  return (
    state?.active?.phase === "pending" || state?.active?.phase === "applying"
  )
}
