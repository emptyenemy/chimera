/* Hosts — разблокировка сервисов подменой IP в системном hosts-файле.

   Провайдеры бывают двух типов: dns (резолвит домены из списков через свой DoH/UDP на
   лету) и static (готовый набор host -> IP из файла: домены не выбираются, набор
   применяется целиком или не применяется вовсе). Модель выбора одна: провайдер слева,
   справа — что через него разблокировать (списки доменов для dns, переключатель для
   static). Лёгкое состояние приходит из хаба (стор "hosts"), тяжёлое — hosts_overview. */

import { useEffect, useRef, useState } from "react"
import {
  CircleAlertIcon,
  CopyIcon,
  EyeOffIcon,
  ListChecksIcon,
  LockIcon,
  PackageIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  ServerIcon,
  Trash2Icon,
} from "lucide-react"
import { cn } from "cn"

import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { TrialButton } from "@/components/app/trial"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldContent, FieldGroup, FieldLabel, FieldSet, FieldLegend } from "@/components/ui/field"
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from "@/components/ui/item"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/bridge"
import { confirmDialog } from "@/lib/dialogs"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { optimistic, useStore } from "@/lib/store"
import type { AppInfo } from "@/lib/types"
import { AddProviderDialog } from "@/pages/hosts-add-dialog"
import { AdvancedCard } from "@/pages/hosts-advanced"
import {
  OVERVIEW_KEY,
  isDns,
  isUnavailable,
  loadOverview,
  saveAssignments,
  toneClass,
  type Assignments,
  type HostsView,
  type Overview,
  type Ping,
  type Provider,
} from "@/pages/hosts-data"

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

// метки времени бэкенда — unix-секунды (time.time())
function fmtDuration(sec: number): string {
  sec = Math.max(0, Math.floor(sec || 0))
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (d) return t("hosts.dur.dh", { d, h })
  if (h) return t("hosts.dur.hm", { h, m })
  if (m) return t("hosts.dur.ms", { m, s })
  return t("hosts.dur.s", { s })
}

function agoText(mark: number | undefined): string {
  if (mark == null) return ""
  const sec = Math.max(0, Math.round(Date.now() / 1000 - mark))
  return sec < 30 ? t("hosts.ago.now") : t("hosts.ago", { time: fmtDuration(sec) })
}

const dnsAssigned = (a: Assignments, pid: string): string[] => {
  const v = a[pid]
  return Array.isArray(v) ? v : []
}

function listOwner(name: string, assignments: Assignments): string | null {
  for (const pid of Object.keys(assignments)) if (dnsAssigned(assignments, pid).includes(name)) return pid
  return null
}

// --- привязки ----------------------------------------------------------------------

// Привязка списка к dns-провайдеру: список у одного провайдера за раз, применяется сразу.
function toggleListAssignment(provider: string, name: string, checked: boolean) {
  return saveAssignments((assignments) => {
    const mapping: Assignments = {}
    for (const [pid, v] of Object.entries(assignments)) mapping[pid] = Array.isArray(v) ? v.filter((x) => x !== name) : v
    if (checked) mapping[provider] = [...dnsAssigned(mapping, provider), name]
    for (const pid of Object.keys(mapping)) if (Array.isArray(mapping[pid]) && !(mapping[pid] as string[]).length) delete mapping[pid]
    return mapping
  }, t("hosts.assign.failed"))
}

// static ничего не выбирает списками — привязка это просто «включён/нет» (true в assignments)
function toggleStaticAssignment(id: string, checked: boolean) {
  return saveAssignments((assignments) => {
    const mapping: Assignments = { ...assignments }
    if (checked) mapping[id] = true
    else delete mapping[id]
    return mapping
  }, t("hosts.static.failed"))
}

async function setHidden(id: string, hidden: boolean) {
  try {
    await api("hosts_hide_provider", id, hidden)
    notify.success(t(hidden ? "hosts.hide.done" : "hosts.unhide.done"))
    await loadOverview()
  } catch (e) {
    notify.error(t("hosts.hide.failed"), msg(e))
  }
}

async function deleteProvider(p: Provider): Promise<boolean> {
  const ok = await confirmDialog({
    title: t("hosts.delete.title"),
    description: t("hosts.delete.desc", { name: p.name }),
    confirmText: t("hosts.delete.confirm"),
    destructive: true,
  })
  if (!ok) return false
  try {
    await api("hosts_delete_provider", p.id)
    notify.success(t("hosts.delete.done"))
    await loadOverview()
    return true
  } catch (e) {
    notify.error(t("hosts.delete.failed"), msg(e))
    return false
  }
}

// --- статус --------------------------------------------------------------------------

function LastSwitch({ st, providers }: { st: HostsView; providers: Provider[] | undefined }) {
  const sw = st.last_switch
  if (!sw) return null
  const name = (id: string) => providers?.find((p) => p.id === id)?.name || id
  const ago = agoText(sw.when)
  return (
    <Alert data-testid="hosts-last-switch">
      <RefreshCwIcon />
      <AlertTitle>{t("hosts.switch.title")}</AlertTitle>
      <AlertDescription>
        {name(sw.from)} → {name(sw.to)} — {sw.reason}
        {ago && ` · ${ago}`}
      </AlertDescription>
    </Alert>
  )
}

function StatusCard({ st }: { st: HostsView }) {
  const app = useStore<AppInfo>("app")
  const [busy, setBusy] = useState(false)
  const on = !!st.applied
  const bound = Object.values(st.assignments ?? {}).some((v) => (Array.isArray(v) ? v.length : v))
  const noAdmin = app?.admin === false
  const count = st.count ?? 0
  const pct = st.health?.total ? Math.round((st.health.ratio || 0) * 100) : null

  let title
  if (on) {
    title = (
      <>
        {t("hosts.status.on", { count, n: fmtNum(count) })}
        {pct !== null && (
          <>
            {" · "}
            <span className={cn("font-medium", toneClass(pct))} title={t("hosts.status.aliveTip")} data-testid="hosts-alive">
              {t("hosts.status.alive", { pct })}
            </span>
          </>
        )}
      </>
    )
  } else if (noAdmin) title = <span className="text-warning">{t("hosts.status.noAdmin")}</span>
  else if (!bound) title = <span className="text-warning">{t("hosts.status.noBound")}</span>
  else title = t("hosts.status.off")

  const toggle = async () => {
    setBusy(true)
    const target = !on
    try {
      await optimistic("hosts", { applied: target }, () => api("hosts_set_enabled", target), {
        errorTitle: t(target ? "hosts.toggle.failedOn" : "hosts.toggle.failedOff"),
      })
    } catch {
      /* тост уже показан */
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card size="sm" data-testid="hosts-status" data-state={on ? "on" : "off"} className={on ? "ring-primary/40" : undefined}>
      <CardContent className="flex flex-row items-center gap-4">
        <StatusDot tone={on ? "on" : "off"} />
        <div className="min-w-0 grow truncate font-semibold" data-testid="hosts-status-title">
          {title}
        </div>
        <TrialButton kind="hosts" target={on ? "off" : "on"} disabled={busy || noAdmin || (!on && !bound)} />
        <Button
          size="sm"
          variant={on ? "destructive" : "default"}
          data-testid="hosts-toggle"
          disabled={busy || (!on && (noAdmin || !bound))}
          onClick={() => void toggle()}
        >
          {busy && <Spinner data-icon="inline-start" />}
          {on ? t("hosts.status.disable") : t("hosts.status.enable")}
        </Button>
      </CardContent>
    </Card>
  )
}

// --- провайдеры -----------------------------------------------------------------------

function PingView({ ping }: { ping: Ping | undefined }) {
  if (!ping)
    return (
      <>
        <StatusDot />
        <span className="text-muted-foreground">…</span>
      </>
    )
  if (!ping.ok)
    return (
      <>
        <StatusDot tone="err" />
        <span className="text-muted-foreground">{t("hosts.ping.none")}</span>
      </>
    )
  if (ping.ms == null)
    return (
      <>
        <StatusDot tone="ok" />
        <span className="text-muted-foreground">{t("hosts.ping.up")}</span>
      </>
    )
  return (
    <>
      <StatusDot tone={ping.ms < 80 ? "ok" : ping.ms < 250 ? "warn" : "err"} />
      <span className="tabular-nums">{t("hosts.ping.ms", { ms: fmtNum(ping.ms) })}</span>
    </>
  )
}

function ProviderRow({
  p,
  st,
  selected,
  ping,
  onSelect,
  onEdit,
}: {
  p: Provider
  st: HostsView
  selected: boolean
  ping: Ping | undefined
  onSelect: () => void
  onEdit: (p: Provider) => void
}) {
  const stat = !isDns(p)
  const unavailable = isUnavailable(p)
  const assigned = st.assignments?.[p.id]
  const boundCount = stat ? (assigned ? 1 : 0) : Array.isArray(assigned) ? assigned.length : 0
  const canDelete = isDns(p) && !p.builtin
  const health = st.health?.providers?.[p.id]
  const pct = health?.total ? Math.round((health.ratio || 0) * 100) : null

  let desc: string
  if (unavailable) desc = p.reason ?? ""
  else if (stat) desc = t("hosts.provider.builtin")
  else desc = p.servers?.length ? p.servers.join(" · ") : p.doh || "—"

  return (
    <Item
      variant="outline"
      size="sm"
      role="radio"
      aria-checked={selected}
      aria-disabled={unavailable}
      tabIndex={unavailable ? -1 : 0}
      data-testid={`hosts-provider-${p.id}`}
      data-state={selected ? "selected" : undefined}
      title={unavailable ? p.reason : undefined}
      className={cn(
        "cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        selected && "border-primary/40 bg-muted",
        unavailable && "cursor-not-allowed opacity-60"
      )}
      onClick={() => !unavailable && onSelect()}
      onKeyDown={(e) => {
        if (!unavailable && e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault()
          onSelect()
        }
      }}
    >
      <ItemMedia variant="icon">{stat ? <PackageIcon /> : p.doh ? <LockIcon /> : <ServerIcon />}</ItemMedia>
      <ItemContent>
        <ItemTitle>
          {p.name}
          {boundCount > 0 && <Badge variant="secondary">{stat ? t("hosts.provider.on") : boundCount}</Badge>}
          {pct !== null && (
            <Badge variant="outline" className={toneClass(pct)}>
              {pct}%
            </Badge>
          )}
        </ItemTitle>
        <ItemDescription className={cn(unavailable && "text-destructive")}>{desc}</ItemDescription>
      </ItemContent>
      <ItemActions>
        <div className="flex items-center gap-1.5 whitespace-nowrap">
          {unavailable ? <span className="text-muted-foreground">—</span> : <PingView ping={ping} />}
        </div>
        {isDns(p) && (
          <Button
            variant="ghost"
            size="icon-xs"
            data-testid={`hosts-provider-edit-${p.id}`}
            aria-label={t(p.builtin ? "hosts.provider.copy" : "hosts.provider.edit")}
            title={t(p.builtin ? "hosts.provider.copy" : "hosts.provider.edit")}
            onClick={(e) => {
              e.stopPropagation()
              onEdit(p)
            }}
          >
            {p.builtin ? <CopyIcon /> : <PencilIcon />}
          </Button>
        )}
        {canDelete ? (
          <Button
            variant="ghost"
            size="icon-xs"
            data-testid={`hosts-provider-delete-${p.id}`}
            aria-label={t("hosts.provider.delete", { name: p.name })}
            title={t("hosts.provider.deleteTip")}
            onClick={(e) => {
              e.stopPropagation()
              void deleteProvider(p)
            }}
          >
            <Trash2Icon />
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="icon-xs"
            data-testid={`hosts-provider-hide-${p.id}`}
            aria-label={t("hosts.provider.hide")}
            title={t("hosts.provider.hide")}
            onClick={(e) => {
              e.stopPropagation()
              void setHidden(p.id, true)
            }}
          >
            <EyeOffIcon />
          </Button>
        )}
      </ItemActions>
    </Item>
  )
}

function ProvidersCard({
  providers,
  hidden,
  st,
  selected,
  pings,
  onSelect,
}: {
  providers: Provider[] | undefined
  hidden: { id: string; name: string }[]
  st: HostsView
  selected: string | null
  pings: Record<string, Ping>
  onSelect: (id: string) => void
}) {
  // null — диалог закрыт; provider: null — новый, иначе правка своего или копия встроенного
  const [dialog, setDialog] = useState<{ provider: Provider | null; copy: boolean } | null>(null)
  let body
  if (!providers) {
    body = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    )
  } else if (!providers.length) {
    body = (
      <Empty className="p-6">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ServerIcon />
          </EmptyMedia>
          <EmptyTitle>{t("hosts.provider.empty.title")}</EmptyTitle>
          <EmptyDescription>{t("hosts.provider.empty.desc")}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  } else {
    body = (
      <ItemGroup className="gap-2" role="radiogroup" aria-label={t("hosts.provider.title")} data-testid="hosts-providers">
        {providers.map((p) => (
          <ProviderRow
            key={p.id}
            p={p}
            st={st}
            selected={p.id === selected}
            ping={pings[p.id]}
            onSelect={() => onSelect(p.id)}
            onEdit={(item) => setDialog({ provider: item, copy: !!item.builtin })}
          />
        ))}
      </ItemGroup>
    )
  }
  return (
    <Card size="sm" className="min-w-0" data-testid="hosts-providers-card">
      <CardHeader>
        <CardTitle>{t("hosts.provider.title")}</CardTitle>
        <CardAction>
          <Button variant="ghost" size="sm" data-testid="hosts-add" onClick={() => setDialog({ provider: null, copy: false })}>
            <PlusIcon data-icon="inline-start" />
            {t("hosts.provider.add")}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {body}
        {hidden.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="sm" className="mt-2 text-muted-foreground" data-testid="hosts-hidden" />}>
              <EyeOffIcon data-icon="inline-start" />
              {t("hosts.hidden", { count: hidden.length })}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {hidden.map((h) => (
                <DropdownMenuItem key={h.id} data-testid={`hosts-unhide-${h.id}`} onClick={() => void setHidden(h.id, false)}>
                  {h.name} — {t("hosts.unhide")}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </CardContent>
      {dialog && <AddProviderDialog provider={dialog.provider} copy={dialog.copy} onClose={() => setDialog(null)} />}
    </Card>
  )
}

// --- правая карточка: что разблокировать через выбранного провайдера ------------------------

function SitesCard({ overview, st, provider }: { overview: Overview | undefined; st: HostsView; provider: Provider | undefined }) {
  if (provider && !isDns(provider)) {
    const on = !!st.assignments?.[provider.id]
    return (
      <Card size="sm" className="min-w-0" data-testid="hosts-sites">
        <CardHeader>
          <CardTitle>{provider.name}</CardTitle>
        </CardHeader>
        <CardContent>
          <Field orientation="horizontal">
            <FieldLabel htmlFor="hosts-static-switch" className="font-normal">
              {t("hosts.static.apply", { name: provider.name })}
            </FieldLabel>
            <Switch
              id="hosts-static-switch"
              data-testid="hosts-static-toggle"
              checked={on}
              onCheckedChange={(v) => void toggleStaticAssignment(provider.id, v)}
            />
          </Field>
        </CardContent>
      </Card>
    )
  }

  const assignments = st.assignments ?? {}
  const nameOf = (id: string) => overview?.providers.find((p) => p.id === id)?.name || id
  let body
  if (!overview) {
    body = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    )
  } else if (!overview.lists.length) {
    body = (
      <Empty className="p-6">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ListChecksIcon />
          </EmptyMedia>
          <EmptyTitle>{t("hosts.sites.empty.title")}</EmptyTitle>
          <EmptyDescription>{t("hosts.sites.empty.desc")}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  } else {
    body = (
      <FieldSet>
        <FieldLegend className="sr-only">{t("hosts.sites.title")}</FieldLegend>
        <FieldGroup className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-x-4 gap-y-3" data-slot="checkbox-group">
          {overview.lists.map((l) => {
            const owner = listOwner(l.name, assignments)
            const mine = !!provider && owner === provider.id
            const elsewhere = !!owner && !mine
            return (
              <Field key={l.name} orientation="horizontal" data-disabled={!provider || elsewhere ? true : undefined}>
                <Checkbox
                  id={`hosts-list-${l.name}`}
                  data-testid={`hosts-list-${l.name}`}
                  checked={mine}
                  disabled={!provider || elsewhere}
                  onCheckedChange={(on) => provider && void toggleListAssignment(provider.id, l.name, on)}
                />
                <FieldContent className="min-w-0 flex-row items-center justify-between gap-2">
                  <FieldLabel htmlFor={`hosts-list-${l.name}`} className="font-normal">
                    {l.name}
                  </FieldLabel>
                  {elsewhere ? (
                    <span className="truncate text-xs text-muted-foreground">→ {nameOf(owner)}</span>
                  ) : (
                    <span className="text-xs text-muted-foreground tabular-nums">{fmtNum(l.count)}</span>
                  )}
                </FieldContent>
              </Field>
            )
          })}
        </FieldGroup>
      </FieldSet>
    )
  }
  return (
    <Card size="sm" className="min-w-0" data-testid="hosts-sites">
      <CardHeader>
        <CardTitle>{provider ? t("hosts.sites.via", { name: provider.name }) : t("hosts.sites.title")}</CardTitle>
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  )
}

// --- страница ---------------------------------------------------------------------------

export function HostsPage() {
  const st = useStore<HostsView>("hosts")
  const overview = useStore<Overview>(OVERVIEW_KEY)
  const [chosen, setChosen] = useState<string | null>(null)
  const [pings, setPings] = useState<Record<string, Ping>>({})
  const pinging = useRef(false)
  const providers = overview?.providers

  useEffect(() => {
    void loadOverview()
  }, [])

  // Автопинг: свой цикл на тик, все провайдеры параллельно, без наложения. Результат
  // рисуется сразу по приходу: недоступный провайдер отвечает таймаутом в секунды и не
  // должен держать «…» у остальных.
  useEffect(() => {
    // недоступный встроенный набор пинговать нечего — причина уже показана в строке
    const targets = (providers ?? []).filter((p) => !isUnavailable(p))
    if (!targets.length) return
    let stopped = false
    const run = async () => {
      if (pinging.current) return
      pinging.current = true
      try {
        await Promise.allSettled(
          targets.map(async (p) => {
            let r: Ping
            try {
              r = (await api<Ping | null>("hosts_ping_one", p.id)) ?? { ok: false, ms: null }
            } catch {
              r = { ok: false, ms: null }
            }
            if (!stopped) setPings((prev) => ({ ...prev, [p.id]: r }))
          })
        )
      } finally {
        pinging.current = false
      }
    }
    void run()
    const id = window.setInterval(() => void run(), 2500)
    return () => {
      stopped = true
      window.clearInterval(id)
    }
  }, [providers])

  // выбранный провайдер: явный выбор, а пока его нет (или провайдера удалили) — первый доступный
  const selected =
    (chosen && providers?.some((p) => p.id === chosen) ? chosen : providers?.find((p) => !isUnavailable(p))?.id) ?? null
  const provider = providers?.find((p) => p.id === selected)
  const state = st ?? {}

  return (
    <Page id="hosts" title={t("nav.hosts")}>
      {st?.error && (
        <Alert variant="destructive" data-testid="hosts-error">
          <CircleAlertIcon />
          <AlertDescription>{st.error}</AlertDescription>
        </Alert>
      )}
      <LastSwitch st={state} providers={providers} />
      {st ? <StatusCard st={st} /> : <Skeleton className="h-14 w-full" data-testid="hosts-loading" />}
      <div className="@container">
        <div className="grid grid-cols-1 items-start gap-4 @2xl:grid-cols-2">
          <ProvidersCard providers={providers} hidden={overview?.hidden ?? []} st={state} selected={selected} pings={pings} onSelect={setChosen} />
          <SitesCard overview={overview} st={state} provider={provider} />
        </div>
      </div>
      <AdvancedCard st={state} providers={providers} />
    </Page>
  )
}
