/* Провайдеры DNS и hosts — одно место настройки: добавить, изменить, скрыть, удалить,
   проверить. Вкладки DNS и Hosts только выбирают из этого списка (modules/provider_registry.py). */

import { useCallback, useEffect, useState } from "react"
import {
  CircleCheckIcon,
  CircleXIcon,
  CopyIcon,
  EyeIcon,
  EyeOffIcon,
  LockIcon,
  PackageIcon,
  PencilIcon,
  PlusIcon,
  ScanSearchIcon,
  ServerIcon,
  SlidersHorizontalIcon,
  Trash2Icon,
} from "lucide-react"

import { Fold } from "@/components/app/fold"
import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/bridge"
import { confirmDialog } from "@/lib/dialogs"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { useStore } from "@/lib/store"
import { useDebounced } from "@/lib/use-autosave"
import { PROBE_KEY, editProbeConfig, loadProbeConfig, saveProbeConfig, type ProbeFields, type ProbeState } from "@/pages/dns-probe"

export interface RegistryProvider {
  id: string
  name: string
  kind: "dns" | "static"
  servers?: string[]
  ipv6?: string[]
  doh?: string
  dot?: string
  builtin?: boolean
  unblock?: boolean
  filter?: boolean
  hidden?: boolean
  hosts_lists?: number
}

interface Ping {
  ok: boolean
  ms?: number | null
}

interface ProbeResult {
  error?: string
  reachable?: boolean
  dnssec?: boolean | null
  unblock?: boolean | null
  filter?: boolean | null
  unblock_detail?: Record<string, unknown>
}

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
// DNS и Hosts берут провайдеров из своих источников хаба — после правки обновляем и их
const refreshTabs = () => void api("hub_refresh", ["dns", "hosts"]).catch(() => {})

// --- проверка провайдера -----------------------------------------------------------------

function ProbeMark({ v }: { v: boolean | null | undefined }) {
  if (v === true) return <CircleCheckIcon className="size-3.5 text-success" aria-label={t("dns.probe.yes")} />
  if (v === false) return <CircleXIcon className="size-3.5 text-destructive" aria-label={t("dns.probe.no")} />
  return <span>—</span>
}

function ProbeView({ id, busy, result }: { id: string; busy: boolean; result: ProbeResult | undefined }) {
  if (busy)
    return (
      <div data-testid={`providers-probe-result-${id}`} className="mt-1.5 text-xs text-muted-foreground">
        {t("dns.probe.running")}
      </div>
    )
  if (!result) return null
  const fail = (text: string) => (
    <div data-testid={`providers-probe-result-${id}`} className="mt-1.5 flex items-center gap-1 text-xs text-destructive">
      <CircleXIcon className="size-3.5" />
      {text}
    </div>
  )
  if (result.error) return fail(result.error)
  if (!result.reachable) return fail(t("dns.probe.silent"))
  const doms = Object.keys(result.unblock_detail ?? {}).join(", ")
  return (
    <div data-testid={`providers-probe-result-${id}`} className="mt-1.5 flex flex-wrap gap-x-3.5 gap-y-1 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1">
        DNSSEC <ProbeMark v={result.dnssec} />
      </span>
      <span className="inline-flex items-center gap-1">
        {t("dns.probe.bypass")}
        {doms ? ` (${doms})` : ""} <ProbeMark v={result.unblock} />
      </span>
      <span className="inline-flex items-center gap-1">
        {t("dns.probe.ads")} <ProbeMark v={result.filter} />
      </span>
    </div>
  )
}

function PingCell({ ping, kind }: { ping: Ping | undefined; kind: RegistryProvider["kind"] }) {
  if (!ping) return <span className="text-muted-foreground">…</span>
  if (!ping.ok)
    return (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <StatusDot tone="err" />
        {t("dns.ping.none")}
      </span>
    )
  // у готового набора адресов сети нет — «доступен» значит «файл на месте»
  if (kind === "static" || ping.ms == null)
    return (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <StatusDot tone="ok" />
        {t("providers.available")}
      </span>
    )
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <StatusDot tone={ping.ms < 60 ? "ok" : ping.ms < 200 ? "warn" : "err"} />
      {t("dns.ping.ms", { ms: fmtNum(ping.ms) })}
    </span>
  )
}

// --- строка -------------------------------------------------------------------------------

function IconButton({ label, testId, onClick, disabled, children }: {
  label: string
  testId: string
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger render={<Button variant="ghost" size="icon-sm" data-testid={testId} aria-label={label} disabled={disabled} onClick={onClick} />}>
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function ProviderRow({
  p,
  ping,
  probing,
  probe,
  onProbe,
  onEdit,
  onHide,
  onDelete,
}: {
  p: RegistryProvider
  ping: Ping | undefined
  probing: boolean
  probe: ProbeResult | undefined
  onProbe: () => void
  onEdit: () => void
  onHide: (hidden: boolean) => void
  onDelete: () => void
}) {
  const isStatic = p.kind === "static"
  const all = [...(p.servers ?? []), ...(p.ipv6 ?? []), p.doh ? `DoH ${p.doh}` : "", p.dot ? `DoT ${p.dot}` : ""].filter(Boolean)
  const main = isStatic ? t("providers.static") : (p.servers ?? []).slice(0, 2).join(" · ") || p.doh || p.dot || ""
  const Icon = isStatic ? PackageIcon : p.doh ? LockIcon : ServerIcon
  return (
    <TableRow data-testid={`providers-row-${p.id}`} className={p.hidden ? "opacity-60" : undefined}>
      <TableCell className="w-px pr-0 align-top text-muted-foreground [&_svg]:mt-0.5 [&_svg]:size-4">
        <Icon />
      </TableCell>
      <TableCell className="whitespace-normal">
        <div className="flex flex-wrap items-center gap-1.5 leading-5 font-medium">
          {p.name}
          {p.unblock && <Badge variant="outline">{t("dns.badge.bypass")}</Badge>}
          {p.filter && <Badge variant="secondary">{t("dns.badge.protect")}</Badge>}
          {!p.builtin && <Badge variant="outline">{t("providers.own")}</Badge>}
          {!!p.hosts_lists && <Badge variant="secondary">{t("providers.inHosts", { count: p.hosts_lists })}</Badge>}
        </div>
        <Tooltip>
          <TooltipTrigger render={<div className="w-fit text-[13px] text-muted-foreground" />}>{main}</TooltipTrigger>
          {all.length > 0 && <TooltipContent className="whitespace-pre-line">{all.join("\n")}</TooltipContent>}
        </Tooltip>
        <ProbeView id={p.id} busy={probing} result={probe} />
      </TableCell>
      <TableCell className="w-28 text-[13px]" data-testid={`providers-ping-${p.id}`}>
        {!p.hidden && <PingCell ping={ping} kind={p.kind} />}
      </TableCell>
      <TableCell className="w-px">
        <div className="flex items-center justify-end gap-0.5">
          {!isStatic && !p.hidden && (
            <IconButton label={t("dns.probe.hint")} testId={`providers-probe-${p.id}`} disabled={probing} onClick={onProbe}>
              {probing ? <Spinner /> : <ScanSearchIcon />}
            </IconButton>
          )}
          {!isStatic && (
            <IconButton label={t(p.builtin ? "dns.copy" : "dns.edit")} testId={`providers-edit-${p.id}`} onClick={onEdit}>
              {p.builtin ? <CopyIcon /> : <PencilIcon />}
            </IconButton>
          )}
          {p.builtin ? (
            <IconButton label={t(p.hidden ? "dns.unhide" : "dns.hide")} testId={`providers-hide-${p.id}`} onClick={() => onHide(!p.hidden)}>
              {p.hidden ? <EyeIcon /> : <EyeOffIcon />}
            </IconButton>
          ) : (
            <IconButton label={t("dns.delete")} testId={`providers-delete-${p.id}`} onClick={onDelete}>
              <Trash2Icon />
            </IconButton>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

// --- диалог провайдера ------------------------------------------------------------------------

const EMPTY_FORM = { name: "", ip1: "", ip2: "", ip6: "", doh: "", dot: "", unblock: false, filter: false }

function formOf(p: RegistryProvider | null, copy: boolean): typeof EMPTY_FORM {
  if (!p) return EMPTY_FORM
  return {
    name: copy ? `${p.name} (${t("dns.copy.suffix")})` : p.name,
    ip1: p.servers?.[0] ?? "",
    ip2: p.servers?.slice(1).join(", ") ?? "",
    ip6: (p.ipv6 ?? []).join(", "),
    doh: p.doh ?? "",
    dot: p.dot ?? "",
    unblock: !!p.unblock,
    filter: !!p.filter,
  }
}

function ProviderDialog({
  provider,
  copy,
  onClose,
  onSaved,
}: {
  provider: RegistryProvider | null
  copy: boolean
  onClose: () => void
  onSaved: () => void
}) {
  // правка своего; копия встроенного сохраняется как новый
  const editing = !!provider && !copy
  const [form, setForm] = useState(() => formOf(provider, copy))
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof typeof EMPTY_FORM>(k: K, v: (typeof EMPTY_FORM)[K]) => setForm((f) => ({ ...f, [k]: v }))
  const submit = async () => {
    setBusy(true)
    try {
      const v = (x: string) => x.trim()
      const fields = [v(form.name), [v(form.ip1), v(form.ip2)], v(form.ip6), v(form.doh), v(form.dot), form.unblock, form.filter] as const
      if (editing && provider) await api("providers_update", provider.id, ...fields)
      else await api("providers_add", ...fields)
      notify.success(t(editing ? "dns.edit.done" : "dns.add.done"))
      onSaved()
      onClose()
    } catch (e) {
      notify.error(t(editing ? "dns.edit.failed" : "dns.add.failed"), errText(e))
      setBusy(false)
    }
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="providers-dialog" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(editing ? "dns.edit.title" : "dns.add.title")}</DialogTitle>
          <DialogDescription>{t("providers.dialog.desc")}</DialogDescription>
        </DialogHeader>
        <FieldGroup className="gap-4">
          <Field>
            <FieldLabel htmlFor="providers-f-name">{t("dns.add.name")}</FieldLabel>
            <Input id="providers-f-name" data-testid="providers-f-name" autoFocus placeholder={t("dns.add.namePh")} value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="providers-f-ip1">{t("dns.add.ip1")}</FieldLabel>
              <Input id="providers-f-ip1" data-testid="providers-f-ip1" className="font-mono" placeholder="1.1.1.1" value={form.ip1} onChange={(e) => set("ip1", e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="providers-f-ip2">{t("dns.add.ip2")}</FieldLabel>
              <Input id="providers-f-ip2" data-testid="providers-f-ip2" className="font-mono" placeholder={t("dns.add.optional")} value={form.ip2} onChange={(e) => set("ip2", e.target.value)} />
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="providers-f-ip6">IPv6</FieldLabel>
            <Input id="providers-f-ip6" data-testid="providers-f-ip6" className="font-mono" placeholder={t("dns.add.ip6Ph")} value={form.ip6} onChange={(e) => set("ip6", e.target.value)} />
          </Field>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="providers-f-doh">DoH</FieldLabel>
              <Input id="providers-f-doh" data-testid="providers-f-doh" className="font-mono" placeholder="https://…/dns-query" value={form.doh} onChange={(e) => set("doh", e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="providers-f-dot">DoT</FieldLabel>
              <Input id="providers-f-dot" data-testid="providers-f-dot" className="font-mono" placeholder="dns.example.com" value={form.dot} onChange={(e) => set("dot", e.target.value)} />
            </Field>
          </div>
          <Field orientation="horizontal">
            <Checkbox id="providers-f-unblock" data-testid="providers-f-unblock" checked={form.unblock} onCheckedChange={(v) => set("unblock", v === true)} />
            <FieldLabel htmlFor="providers-f-unblock" className="font-normal">
              {t("dns.add.unblock")}
            </FieldLabel>
          </Field>
          <Field orientation="horizontal">
            <Checkbox id="providers-f-filter" data-testid="providers-f-filter" checked={form.filter} onCheckedChange={(v) => set("filter", v === true)} />
            <FieldLabel htmlFor="providers-f-filter" className="font-normal">
              {t("dns.add.filter")}
            </FieldLabel>
          </Field>
        </FieldGroup>
        <DialogFooter>
          <Button variant="outline" data-testid="providers-cancel" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button data-testid="providers-save" disabled={busy} onClick={() => void submit()}>
            {busy && <Spinner data-icon="inline-start" />}
            {t(editing ? "dns.edit.save" : "dns.add.ok")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- настройки проверки --------------------------------------------------------------------

function ProbeSettings() {
  const state = useStore<ProbeState>(PROBE_KEY)
  const cfg = state?.draft ?? state?.value
  const debounce = useDebounced(() => void saveProbeConfig())
  useEffect(() => { void loadProbeConfig() }, [])

  const edit = (part: Partial<ProbeFields>) => {
    editProbeConfig(part)
    debounce.schedule()
  }
  const flush = () => {
    debounce.flush()
    void saveProbeConfig()
  }
  const commitOnEnter = (event: { key: string; preventDefault: () => void }) => {
    if (event.key !== "Enter") return
    event.preventDefault()
    flush()
  }
  const error = state?.draft?.error ?? state?.error
  return (
    <FieldGroup className="gap-4" aria-busy={state?.busy}>
      {error && (
        <Alert variant="destructive" data-testid="dns-probe-error">
          <AlertTitle>{t(state?.draft ? "dns.probeCfg.failed" : "dns.probeCfg.readFailed")}</AlertTitle>
          <AlertDescription>
            <p>{error}</p>
            <Button variant="outline" size="sm" disabled={state?.busy} data-testid="dns-probe-retry"
              onClick={() => state?.draft ? flush() : void loadProbeConfig()}>
              {t("common.retry")}
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {!cfg ? !error && <>
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </> : <>
        <Field>
          <FieldLabel htmlFor="dns-probe-bypass">{t("dns.probeCfg.bypass")}</FieldLabel>
          <Input
            id="dns-probe-bypass"
            data-testid="dns-probe-bypass"
            className="font-mono"
            placeholder="rutracker.org"
            value={cfg.bypass}
            onChange={(e) => edit({ bypass: e.target.value })}
            onBlur={flush}
            onKeyDown={commitOnEnter}
          />
          <FieldDescription>{t("dns.probeCfg.bypassHint")}</FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="dns-probe-ad">{t("dns.probeCfg.ad")}</FieldLabel>
          <Input
            id="dns-probe-ad"
            data-testid="dns-probe-ad"
            className="font-mono"
            placeholder="doubleclick.net"
            value={cfg.ad}
            onChange={(e) => edit({ ad: e.target.value })}
            onBlur={flush}
            onKeyDown={commitOnEnter}
          />
        </Field>
      </>}
    </FieldGroup>
  )
}

// --- страница -------------------------------------------------------------------------------------

export function ProvidersPage() {
  const [items, setItems] = useState<RegistryProvider[] | null>(null)
  const [pings, setPings] = useState<Record<string, Ping>>({})
  const [probing, setProbing] = useState<Record<string, boolean>>({})
  const [probes, setProbes] = useState<Record<string, ProbeResult>>({})
  const [dialog, setDialog] = useState<{ provider: RegistryProvider | null; copy: boolean } | null>(null)

  const load = useCallback(async () => {
    try {
      setItems(await api<RegistryProvider[]>("providers_list"))
    } catch (e) {
      setItems([])
      notify.error(t("providers.loadFailed"), errText(e))
    }
  }, [])
  useEffect(() => { void load() }, [load])

  // пинг один раз при открытии: каждого отдельно, медленный не держит остальных
  useEffect(() => {
    if (!items) return
    let stopped = false
    for (const p of items) {
      if (p.hidden || pings[p.id]) continue
      void api<Ping>("hosts_ping_one", p.id)
        .catch(() => ({ ok: false }))
        .then((r) => { if (!stopped) setPings((m) => ({ ...m, [p.id]: r })) })
    }
    return () => { stopped = true }
    // pings в зависимостях перезапускали бы замер на каждый ответ
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items])

  const changed = () => {
    void load()
    refreshTabs()
  }

  const onProbe = async (id: string) => {
    setProbing((m) => ({ ...m, [id]: true }))
    try {
      const r = await api<ProbeResult>("dns_probe", id)
      setProbes((m) => ({ ...m, [id]: r }))
    } catch (e) {
      setProbes((m) => ({ ...m, [id]: { error: errText(e) } }))
    } finally {
      setProbing((m) => { const next = { ...m }; delete next[id]; return next })
    }
  }

  const onHide = async (p: RegistryProvider, hidden: boolean) => {
    try {
      await api("providers_hide", p.id, hidden)
      notify.success(t(hidden ? "providers.hidden.done" : "dns.unhide.done"))
      changed()
    } catch (e) {
      notify.error(t("dns.hide.failed"), errText(e))
    }
  }

  const onDelete = async (p: RegistryProvider) => {
    const ok = await confirmDialog({
      title: t("dns.delete.title"),
      description: t("providers.delete.desc", { name: p.name || p.id }),
      confirmText: t("dns.delete.confirm"),
      destructive: true,
    })
    if (!ok) return
    try {
      await api("providers_delete", p.id)
      notify.success(t("dns.delete.done"))
      changed()
    } catch (e) {
      notify.error(t("dns.delete.failed"), errText(e))
    }
  }

  const visible = (items ?? []).filter((p) => !p.hidden)
  const hidden = (items ?? []).filter((p) => p.hidden)
  const rows = (list: RegistryProvider[]) => list.map((p) => (
    <ProviderRow
      key={p.id}
      p={p}
      ping={pings[p.id]}
      probing={!!probing[p.id]}
      probe={probes[p.id]}
      onProbe={() => void onProbe(p.id)}
      onEdit={() => setDialog({ provider: p, copy: !!p.builtin })}
      onHide={(value) => void onHide(p, value)}
      onDelete={() => void onDelete(p)}
    />
  ))

  return (
    <Page id="providers" title={t("nav.providers")}>
      <Card data-testid="providers-card">
        <CardHeader>
          <CardTitle>{t("providers.title")}</CardTitle>
          <CardAction>
            <Button variant="ghost" size="sm" data-testid="providers-add" onClick={() => setDialog({ provider: null, copy: false })}>
              <PlusIcon data-icon="inline-start" />
              {t("dns.add")}
            </Button>
          </CardAction>
          <FieldDescription className="col-span-full">{t("providers.desc")}</FieldDescription>
        </CardHeader>
        <CardContent>
          {!items ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-12 w-full" />)}
            </div>
          ) : (
            <Table data-testid="providers-list">
              <TableBody>{rows(visible)}</TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {hidden.length > 0 && (
        <Fold icon={EyeOffIcon} title={t("dns.hidden", { count: hidden.length })} testId="providers-hidden">
          <Table>
            <TableBody>{rows(hidden)}</TableBody>
          </Table>
        </Fold>
      )}
      <Fold icon={SlidersHorizontalIcon} title={t("providers.probeSettings")} testId="providers-probe-settings">
        <ProbeSettings />
      </Fold>
      {dialog && <ProviderDialog provider={dialog.provider} copy={dialog.copy} onClose={() => setDialog(null)} onSaved={changed} />}
    </Page>
  )
}
