/* DNS — переключатель системного DNS (аналог DNS Jumper).

   Источник "dns" в хабе ленивый (dns_state гоняет системные вызовы — секунды), поэтому
   его включает useHubWatch, пока страница открыта. Пока данных нет — скелетон, остальное
   рисуется сразу. Проба возможностей и её настройки в хаб не входят — грузятся при заходе. */

import { useEffect, useMemo, useRef, useState } from "react"
import {
  CheckIcon,
  ClockIcon,
  NetworkIcon,
  RotateCcwIcon,
  SlidersHorizontalIcon,
  WifiIcon,
  WifiOffIcon,
} from "lucide-react"

import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field } from "@/components/ui/field"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/bridge"
import { fmtNum } from "@/lib/format"
import { useHubWatch } from "@/lib/hub-watch"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { router } from "@/lib/router"
import { store, useStore } from "@/lib/store"
import type { AppInfo } from "@/lib/types"

// --- данные --------------------------------------------------------------------

interface Adapter {
  index: number
  name: string
  desc?: string
  status?: string
  physical?: boolean
  ipv4?: string[]
  dns?: string[]
  speed?: string | null
}

interface Provider {
  id: string
  name: string
  servers?: string[]
  ipv6?: string[]
  doh?: string
  dot?: string
  builtin?: boolean
  unblock?: boolean
  filter?: boolean
}

interface Trial {
  adapter: number
  provider: string
  deadline: number
  seconds_left: number
}

interface DnsState {
  adapters?: Adapter[]
  providers?: Provider[]
  trial?: Trial | null
}

interface PingResult {
  servers?: { server: string; ok: boolean; ms: number | null }[]
}

const TRIAL_SECONDS = 15 // сколько даём на «Оставить» после смены DNS
const PING_EVERY = 2500

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const refreshDns = () => void api("hub_refresh", ["dns"]).catch(() => {})

function without<T>(map: Record<string, T>, key: string): Record<string, T> {
  const rest = { ...map }
  delete rest[key]
  return rest
}

function isActiveProvider(p: Provider, a: Adapter | null): boolean {
  const cur = a?.dns ?? []
  if (!cur.length) return false
  const set = new Set(p.servers ?? [])
  return cur.every((ip) => set.has(ip))
}

function adapterLabel(a: Adapter): string {
  const desc = a.desc && a.desc !== a.name ? ` — ${a.desc}` : ""
  const tags = [a.physical ? "" : t("dns.adapter.virtual"), a.status === "Up" ? "" : t("dns.adapter.down")].filter(Boolean)
  return a.name + desc + tags.map((x) => ` · ${x}`).join("")
}

// лучший (наименьший) пинг из серверов провайдера; null — ни один не ответил
function bestMs(r: PingResult | undefined): number | null {
  const ok = (r?.servers ?? []).filter((s) => s.ok && s.ms != null).map((s) => s.ms as number)
  return ok.length ? Math.min(...ok) : null
}

// --- карточка адаптера ---------------------------------------------------------------

function AdapterCard({
  st,
  adapter,
  onSelect,
}: {
  st: DnsState | undefined
  adapter: Adapter | null
  onSelect: (index: number) => void
}) {
  const list = st?.adapters ?? []
  const reset = async () => {
    if (!adapter) return notify.error(t("dns.noAdapter"))
    try {
      await api("dns_reset", adapter.index)
      notify.success(t("dns.reset.done"))
      refreshDns()
    } catch (e) {
      notify.error(t("dns.reset.failed"), errText(e))
    }
  }
  const info = adapter
    ? [
        adapter.ipv4?.length ? t("dns.info.ip", { ip: adapter.ipv4.join(", ") }) : null,
        adapter.dns?.length ? t("dns.info.dns", { dns: adapter.dns.join(", ") }) : t("dns.info.dhcp"),
        adapter.speed || null,
      ]
        .filter(Boolean)
        .join(" · ")
    : ""
  const items = list.map((a) => ({ label: adapterLabel(a), value: String(a.index) }))

  return (
    <Card data-testid="dns-adapter-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <WifiIcon className="size-4" />
          {t("dns.adapter.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!st ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : !list.length ? (
          <Empty className="p-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <WifiOffIcon />
              </EmptyMedia>
              <EmptyTitle>{t("dns.adapter.none")}</EmptyTitle>
            </EmptyHeader>
          </Empty>
        ) : (
          <>
            <Field orientation="horizontal">
              <Select items={items} value={adapter ? String(adapter.index) : null} onValueChange={(v) => v && onSelect(Number(v))}>
                <SelectTrigger data-testid="dns-adapter" aria-label={t("dns.adapter.title")} className="min-w-0 flex-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent alignItemWithTrigger={false} className="w-auto">
                  <SelectGroup>
                    {items.map((it) => (
                      <SelectItem key={it.value} value={it.value} data-testid={`dns-adapter-${it.value}`}>
                        {it.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Button variant="outline" data-testid="dns-reset" onClick={() => void reset()}>
                <RotateCcwIcon data-icon="inline-start" />
                {t("dns.reset")}
              </Button>
            </Field>
            <p data-testid="dns-current" className="text-[13px] text-muted-foreground">
              {info}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// --- пробное применение ----------------------------------------------------------------

// Плашка с обратным отсчётом. Откат делает бэкенд по таймеру, плашка только показывает,
// сколько осталось, и даёт решить раньше.
function TrialAlert({ st }: { st: DnsState }) {
  const trial = st.trial
  const [now, setNow] = useState(() => Date.now())
  const notified = useRef(new Set<number>())
  const deadline = trial?.deadline
  useEffect(() => {
    if (deadline == null) return
    const id = window.setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [deadline])
  const left = trial ? Math.max(0, Math.ceil(trial.deadline - now / 1000)) : 0
  useEffect(() => {
    if (deadline == null || left > 0 || notified.current.has(deadline)) return
    notified.current.add(deadline) // сервер откатит сам; здесь только освежаем состояние
    notify.info(t("dns.trial.reverted"), t("dns.trial.revertedDesc"))
    const id = window.setTimeout(refreshDns, 1500)
    return () => clearTimeout(id)
  }, [left, deadline])

  if (!trial) return null
  const provider = st.providers?.find((p) => p.id === trial.provider)
  const adapter = st.adapters?.find((a) => a.index === trial.adapter)
  const decide = async (keep: boolean) => {
    try {
      await api(keep ? "dns_trial_confirm" : "dns_trial_revert", Number(trial.adapter))
      notify.success(t(keep ? "dns.trial.kept" : "dns.trial.revertedNow"))
    } catch (e) {
      notify.error(t(keep ? "dns.trial.keepFailed" : "dns.trial.revertFailed"), errText(e))
    } finally {
      refreshDns()
    }
  }
  return (
    <Alert data-testid="dns-trial">
      <ClockIcon />
      <AlertTitle>{t("dns.trial.title", { provider: provider?.name || trial.provider, adapter: adapter?.name || trial.adapter })}</AlertTitle>
      <AlertDescription>
        <p>
          {t("dns.trial.desc")} <b data-testid="dns-trial-left">{left}</b> {t("dns.trial.seconds")}
        </p>
        <div className="mt-2 flex gap-2">
          <Button size="sm" data-testid="dns-trial-keep" onClick={() => void decide(true)}>
            {t("dns.trial.keep")}
          </Button>
          <Button size="sm" variant="outline" data-testid="dns-trial-revert" onClick={() => void decide(false)}>
            {t("dns.trial.revert")}
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  )
}

// --- строка провайдера -----------------------------------------------------------------------

function PingCell({ result }: { result: PingResult | undefined }) {
  if (!result) return <span className="text-muted-foreground">…</span>
  const ms = bestMs(result)
  if (ms == null)
    return (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <StatusDot tone="err" />
        {t("dns.ping.none")}
      </span>
    )
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <StatusDot tone={ms < 60 ? "ok" : ms < 200 ? "warn" : "err"} />
      {t("dns.ping.ms", { ms: fmtNum(ms) })}
    </span>
  )
}

function ProviderRow({
  p,
  adapter,
  ping,
  applying,
  noAdmin,
  onApply,
}: {
  p: Provider
  adapter: Adapter | null
  ping: PingResult | undefined
  applying: boolean
  noAdmin: boolean
  onApply: (id: string) => void
}) {
  const active = isActiveProvider(p, adapter)
  // все адреса (IPv6, DoH, DoT) — в подсказке: в строке хватает основного
  const all = [...(p.servers ?? []), ...(p.ipv6 ?? []), p.doh ? `DoH ${p.doh}` : "", p.dot ? `DoT ${p.dot}` : ""].filter(Boolean)
  const main = (p.servers ?? []).slice(0, 2).join(" · ") || p.doh || p.dot || ""
  return (
    <TableRow data-testid={`dns-row-${p.id}`} data-state={active ? "selected" : undefined}>
      <TableCell className="whitespace-normal">
        <div className="flex flex-wrap items-center gap-1.5 leading-5 font-medium">
          {p.name}
          {p.unblock && <Badge variant="outline">{t("dns.badge.bypass")}</Badge>}
          {p.filter && <Badge variant="secondary">{t("dns.badge.protect")}</Badge>}
        </div>
        <Tooltip>
          <TooltipTrigger render={<div className="w-fit text-[13px] text-muted-foreground" />}>{main}</TooltipTrigger>
          <TooltipContent className="whitespace-pre-line">{all.join("\n")}</TooltipContent>
        </Tooltip>
      </TableCell>
      <TableCell className="w-24 text-[13px]" data-testid={`dns-ping-${p.id}`}>
        <PingCell result={ping} />
      </TableCell>
      <TableCell className="w-px">
        <div className="flex items-center justify-end gap-1">
          {active ? (
            <Button variant="secondary" size="sm" disabled data-testid={`dns-active-${p.id}`}>
              <CheckIcon data-icon="inline-start" />
              {t("dns.active")}
            </Button>
          ) : (
            <Tooltip>
              <TooltipTrigger render={<span />}>
                <Button
                  variant="outline"
                  size="sm"
                  data-testid={`dns-use-${p.id}`}
                  disabled={applying || noAdmin}
                  onClick={() => onApply(p.id)}
                >
                  {applying && <Spinner data-icon="inline-start" />}
                  {t("dns.apply")}
                </Button>
              </TooltipTrigger>
              {noAdmin && <TooltipContent>{t("dns.needAdmin")}</TooltipContent>}
            </Tooltip>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

// --- страница ----------------------------------------------------------------------------------------

export function DnsPage() {
  useHubWatch(["dns"])
  const st = useStore<DnsState>("dns")
  const app = useStore<AppInfo>("app")
  const noAdmin = app?.admin === false

  const [selected, setSelected] = useState<number | null>(null)
  const [pings, setPings] = useState<Record<string, PingResult>>({})
  const [order, setOrder] = useState<string[] | null>(null)
  const [applying, setApplying] = useState<Record<string, boolean>>({})

  const adapters = st?.adapters
  const adapter = useMemo<Adapter | null>(() => {
    const list = adapters ?? []
    if (!list.length) return null
    return list.find((a) => a.index === selected) ?? list[0]
  }, [adapters, selected])

  // Автопинг: все провайдеры параллельно на каждый проход, проходы не накладываются.
  // Результат рисуется сразу по приходу: недоступный сервер отвечает таймаутом в секунды
  // и не должен держать «…» у остальных.
  useEffect(() => {
    let stopped = false
    let timer = 0
    const pass = async () => {
      // провайдеры берём прямо из стора: цикл живёт дольше одного рендера
      const list = store.get<DnsState>("dns")?.providers ?? []
      if (list.length) {
        const best = new Map<string, number>()
        await Promise.allSettled(
          list.map(async (p) => {
            let r: PingResult
            try {
              r = await api<PingResult>("dns_ping_one", p.id)
            } catch {
              r = { servers: (p.servers ?? []).map((server) => ({ server, ok: false, ms: null })) }
            }
            best.set(p.id, bestMs(r) ?? Infinity)
            if (!stopped) setPings((prev) => ({ ...prev, [p.id]: r }))
          })
        )
        // Порядок по скорости фиксируется один раз — после первого полного прохода.
        // Пересортировка на каждом тике двигала бы строки под курсором, и клик по
        // «Применить» попадал бы в соседнего провайдера.
        if (!stopped) {
          const sorted = list.map((p) => p.id).sort((a, b) => (best.get(a) ?? Infinity) - (best.get(b) ?? Infinity))
          setOrder((prev) => (prev && prev.length === sorted.length ? prev : sorted))
        }
      }
      if (!stopped) timer = window.setTimeout(pass, PING_EVERY)
    }
    void pass()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [])

  const providers = useMemo(() => {
    const list = (st?.providers ?? []).slice()
    if (!order) return list
    const pos = (id: string) => {
      const i = order.indexOf(id)
      return i < 0 ? Infinity : i
    }
    return list.sort((a, b) => pos(a.id) - pos(b.id))
  }, [st?.providers, order])

  const onApply = async (id: string) => {
    if (!adapter) return notify.error(t("dns.noAdapter"))
    setApplying((m) => ({ ...m, [id]: true }))
    try {
      // с автооткатом: если интернет пропал после смены, «Оставить» нажать некому — через
      // TRIAL_SECONDS бэкенд сам вернёт прежний DNS
      const p = await api<{ name?: string; encrypted?: boolean } | null>("dns_set_trial", adapter.index, id, TRIAL_SECONDS)
      notify.success(
        t("dns.applied.title", { name: p?.name || id }),
        [p?.encrypted ? t("dns.applied.doh") : "", t("dns.applied.trial", { seconds: TRIAL_SECONDS })].filter(Boolean).join(" ")
      )
    } catch (e) {
      notify.error(t("dns.applied.failed"), errText(e))
    } finally {
      setApplying((m) => without(m, id))
      refreshDns()
    }
  }

  return (
    <Page id="dns" title={t("nav.dns")}>
      {st?.trial && <TrialAlert st={st} />}
      <AdapterCard st={st} adapter={adapter} onSelect={setSelected} />
      <Card data-testid="dns-providers-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <NetworkIcon className="size-4" />
            {t("dns.providers.title")}
          </CardTitle>
          <CardAction>
            <Button variant="ghost" size="sm" data-testid="dns-manage" onClick={() => router.go("providers")}>
              <SlidersHorizontalIcon data-icon="inline-start" />
              {t("providers.manage")}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {!st ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : !providers.length ? (
            <Empty className="p-6">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <NetworkIcon />
                </EmptyMedia>
                <EmptyTitle>{t("dns.providers.none")}</EmptyTitle>
                <EmptyDescription>{t("dns.providers.noneDesc")}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <Table data-testid="dns-list">
              <TableBody>
                {providers.map((p) => (
                  <ProviderRow
                    key={p.id}
                    p={p}
                    adapter={adapter}
                    ping={pings[p.id]}
                    applying={!!applying[p.id]}
                    noAdmin={noAdmin}
                    onApply={(id) => void onApply(id)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </Page>
  )
}
