/* Автонастройка: проверить сервисы, подобрать способ обхода и применить его. Сессия идёт
   у владельца модулей (приложение или служба), страница только запускает её и рисует
   состояние из хаба (ключ autotune). Диагноз и каталог — в сторе, переживают уход. */

import { useEffect, useState } from "react"
import {
  ChevronDownIcon,
  CircleAlertIcon,
  GaugeIcon,
  RotateCcwIcon,
  SearchCheckIcon,
  Share2Icon,
  SparklesIcon,
  WandSparklesIcon,
  WrenchIcon,
  ZapIcon,
} from "lucide-react"

import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Checkbox } from "@/components/ui/checkbox"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field"
import { Progress } from "@/components/ui/progress"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/bridge"
import { copyText } from "@/lib/clipboard"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { optimistic, store, useStore } from "@/lib/store"
import type { AppInfo } from "@/lib/types"
import { SettingRow } from "@/pages/settings/general"
import { CONFIG_KEY, refreshConfig, setConfig, useConfig, usePending, type AppConfig } from "@/pages/settings/state"
import {
  CATALOG_KEY,
  absorbReport,
  DIAGNOSIS_KEY,
  NAMES_KEY,
  candidateText,
  currentText,
  diagnose,
  fixText,
  loadCatalog,
  loadNames,
  progressPercent,
  reasonText,
  statusOf,
  type AutotuneState,
  type CatalogItem,
  type DiagnosisView,
  type LogEvent,
  type Mode,
  type ReportRow,
  type ServiceCheck,
  type Session,
} from "@/pages/autotune-data"

const MODE_KEY = "autotune.mode"
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

interface WinwsView {
  strategies?: { id: string; name?: string }[]
}

function useLabels() {
  const strategies = useStore<WinwsView>("winws")?.strategies ?? []
  const names = useStore<Record<string, string>>(NAMES_KEY) ?? {}
  return { strategies, names }
}

async function act(method: string, args: unknown[], failKey: string) {
  try {
    await api(method, ...args)
  } catch (e) {
    notify.error(t(failKey), errText(e))
  }
}

// Отчёт уходит только формой обсуждения в браузере: публикует его сам человек
async function share() {
  try {
    const report = await api<{ url: string | null; form: string; text: string }>("autotune_share")
    if (report.url) {
      await api("open_url", report.url)
      return
    }
    await copyText(report.text)
    await api("open_url", report.form)
  } catch (e) {
    notify.error(t("autotune.shareFailed"), errText(e))
  }
}

function startFix(services: string[] | null) {
  const mode = store.get<Mode>(MODE_KEY) ?? "fast"
  void act("autotune_start", [services, mode], "autotune.startFailed")
}

function CheckDot({ check }: { check: ServiceCheck | null }) {
  if (!check || check.ok === null) return <StatusDot tone="off" />
  return <StatusDot tone={check.ok ? "ok" : "err"} />
}

function checkText(check: ServiceCheck | null): string {
  if (!check || check.ok === null) return t("autotune.status.unknown")
  if (check.ok) return check.ms != null ? t("autotune.status.okMs", { ms: fmtNum(check.ms) }) : t("autotune.status.ok")
  return reasonText(check) || t("autotune.reason.error")
}

// --- запуск ----------------------------------------------------------------------------

function StartCard({ busy }: { busy: boolean }) {
  const app = useStore<AppInfo>("app")
  const diag = useStore<DiagnosisView>(DIAGNOSIS_KEY)
  const mode = useStore<Mode>(MODE_KEY) ?? "fast"
  const noAdmin = app?.admin === false
  return (
    <Card data-testid="autotune-start-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <WandSparklesIcon className="size-4" />
          {t("autotune.start.title")}
        </CardTitle>
        <CardDescription>{t("autotune.start.desc")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <FieldGroup className="gap-2">
          <ToggleGroup
            variant="outline"
            spacing={1}
            className="max-w-full flex-wrap"
            aria-label={t("autotune.mode.title")}
            value={[mode]}
            onValueChange={(v) => v[0] && store.set(MODE_KEY, v[0] as Mode)}
          >
            <ToggleGroupItem value="fast" data-testid="autotune-mode-fast">
              <ZapIcon data-icon="inline-start" />
              {t("autotune.mode.fast")}
            </ToggleGroupItem>
            <ToggleGroupItem value="smart" data-testid="autotune-mode-smart">
              <GaugeIcon data-icon="inline-start" />
              {t("autotune.mode.smart")}
            </ToggleGroupItem>
          </ToggleGroup>
          <FieldDescription data-testid="autotune-mode-hint">{t(`autotune.mode.${mode}Hint`)}</FieldDescription>
        </FieldGroup>
        {noAdmin && (
          <Alert data-testid="autotune-admin">
            <CircleAlertIcon />
            <AlertDescription>{t("autotune.needAdmin")}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap gap-2">
          <Button data-testid="autotune-start" disabled={busy || noAdmin} onClick={() => startFix(null)}>
            <SparklesIcon data-icon="inline-start" />
            {t("autotune.start.all")}
          </Button>
          <Button variant="outline" data-testid="autotune-check" disabled={busy || diag?.busy}
            onClick={() => void diagnose()}>
            {diag?.busy ? <Spinner data-icon="inline-start" /> : <SearchCheckIcon data-icon="inline-start" />}
            {t("autotune.start.check")}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// Самолечение в фоне: чинить снова то, что автонастройка уже чинила в этой сети
function WatchCard() {
  const config = useConfig()
  const pending = usePending()
  return (
    <Card size="sm" data-testid="autotune-watch-card">
      <CardContent>
        <SettingRow id="autotune-watch" title={t("autotune.watch.title")} hint={t("autotune.watch.hint")}>
          <Switch
            id="autotune-watch"
            data-testid="autotune-watch"
            checked={!!config?.autotune_watch}
            disabled={!config || !!pending.autotune_watch}
            onCheckedChange={(v) => void setConfig("autotune_watch", v)}
          />
        </SettingRow>
      </CardContent>
    </Card>
  )
}

// --- что пробовать: способы и варианты --------------------------------------------------------
// Человек знает, что DNS у него не поможет или что прокси режет скорость и пинг, — и не ждёт
// перебора там, где перспективы нет. Те же настройки у самолечения.

const STEPS = ["strategy", "hosts", "dns", "proxy"] as const
type Step = (typeof STEPS)[number]
type OptionStep = Exclude<Step, "proxy">

interface Methods {
  candidates: Record<OptionStep, { id: string; name: string }[]>
}

// очередь правок config.json: быстрые клики по галочкам не теряются, каждая строится от подтверждённого
function saveMethods(key: "autotune_steps" | "autotune_exclude", change: (config: AppConfig) => Partial<AppConfig>) {
  const patch = (value: unknown) => change((value ?? {}) as AppConfig)
  return optimistic(CONFIG_KEY, patch, () => {
    const next = patch(store.confirmed(CONFIG_KEY))
    return api<AppConfig>("config_set", key, next[key])
  }, { errorTitle: t("autotune.methods.failed") }).catch(() => {})
}

const stepsOf = (config: AppConfig | undefined): string[] => config?.autotune_steps ?? [...STEPS]

function toggleStep(step: Step, on: boolean) {
  void saveMethods("autotune_steps", (config) => {
    const steps = stepsOf(config).filter((s) => s !== step)
    return { autotune_steps: STEPS.filter((s) => s === step ? on : steps.includes(s)) }
  })
}

function toggleOption(step: OptionStep, id: string, tried: boolean) {
  void saveMethods("autotune_exclude", (config) => {
    const exclude = { ...(config.autotune_exclude ?? {}) }
    const ids = (exclude[step] ?? []).filter((x) => x !== id)
    exclude[step] = tried ? ids : [...ids, id]
    return { autotune_exclude: exclude }
  })
}

function MethodsCard() {
  const config = useConfig()
  const [open, setOpen] = useState(false)
  const [methods, setMethods] = useState<Methods | null>(null)
  const steps = stepsOf(config)
  const exclude = config?.autotune_exclude ?? {}

  const expand = async (next: boolean) => {
    setOpen(next)
    if (!next || methods) return
    try {
      setMethods(await api<Methods>("autotune_methods"))
    } catch (e) {
      notify.error(t("autotune.methods.loadFailed"), errText(e))
    }
  }

  return (
    <Card size="sm" data-testid="autotune-methods">
      <CardHeader>
        <CardTitle>{t("autotune.methods.title")}</CardTitle>
        <CardDescription>{t("autotune.methods.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FieldGroup className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-4 gap-y-3">
          {STEPS.map((step) => {
            const on = steps.includes(step)
            return (
              <Field key={step} orientation="horizontal">
                <Checkbox
                  id={`autotune-method-${step}`}
                  data-testid={`autotune-method-${step}`}
                  checked={on}
                  disabled={!config || (on && steps.length === 1)}
                  onCheckedChange={(v) => toggleStep(step, v === true)}
                />
                <FieldLabel htmlFor={`autotune-method-${step}`} className="font-normal">
                  {t(`autotune.methods.step.${step}`)}
                </FieldLabel>
              </Field>
            )
          })}
        </FieldGroup>
        {steps.includes("proxy") && <FieldDescription>{t("autotune.methods.proxyHint")}</FieldDescription>}
        <Collapsible open={open} onOpenChange={(next) => void expand(next)}>
          <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="w-fit" data-testid="autotune-options-toggle" />}>
            {t("autotune.methods.options")}
            <ChevronDownIcon data-icon="inline-end" className={open ? "rotate-180" : undefined} />
          </CollapsibleTrigger>
          <CollapsibleContent className="flex flex-col gap-4 pt-2">
            <FieldDescription>{t("autotune.methods.optionsHint")}</FieldDescription>
            {!methods && <Spinner />}
            {methods && (["strategy", "hosts", "dns"] as const).filter((step) => steps.includes(step)).map((step) => (
              <FieldSet key={step} data-testid={`autotune-options-${step}`}>
                <FieldLegend variant="label">{t(`autotune.methods.step.${step}`)}</FieldLegend>
                <FieldGroup className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-4 gap-y-2">
                  {methods.candidates[step].map((option) => (
                    <Field key={option.id} orientation="horizontal">
                      <Checkbox
                        id={`autotune-option-${step}-${option.id}`}
                        data-testid={`autotune-option-${step}-${option.id}`}
                        checked={!(exclude[step] ?? []).includes(option.id)}
                        onCheckedChange={(v) => toggleOption(step, option.id, v === true)}
                      />
                      <FieldLabel htmlFor={`autotune-option-${step}-${option.id}`} className="font-normal">
                        {option.name}
                      </FieldLabel>
                    </Field>
                  ))}
                </FieldGroup>
              </FieldSet>
            ))}
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}

// --- ход подбора ---------------------------------------------------------------------------

function logText(e: LogEvent, labels: ReturnType<typeof useLabels>): string {
  const who = candidateText(e.step, e.candidate, labels.strategies, labels.names)
  if (e.error) return t("autotune.log.error", { who })
  if (e.rejected) return t(`autotune.log.rejected.${e.rejected}`, { who })
  if (e.fixed?.length) return t("autotune.log.fixed", { who, services: e.fixed.join(", ") })
  return t("autotune.log.nothing", { who })
}

function RunningCard({ session }: { session: Session }) {
  const labels = useLabels()
  const cur = session.current
  const percent = progressPercent(session)
  const results = session.log.filter((e) => e.type === "result").slice(-5).reverse()
  return (
    <Card data-testid="autotune-running">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Spinner className="size-4" />
          {t("autotune.running.title")}
        </CardTitle>
        <CardAction>
          <Badge variant="secondary">{t(`autotune.mode.${session.mode}`)}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Progress value={percent} data-testid="autotune-progress" />
        <p data-testid="autotune-current" className="text-sm">
          {cur
            ? currentText(cur, labels.strategies, labels.names)
            : t(`autotune.stage.${session.stage ?? "diagnose"}`)}
        </p>
        {results.length > 0 && (
          <ul data-testid="autotune-log" className="flex flex-col gap-1 text-[13px] text-muted-foreground">
            {results.map((e, i) => (
              <li key={`${e.step}-${e.candidate}-${i}`}>{logText(e, labels)}</li>
            ))}
          </ul>
        )}
        <div>
          <Button variant="outline" data-testid="autotune-cancel" disabled={!!session.cancelling}
            onClick={() => void act("autotune_cancel", [], "autotune.cancelFailed")}>
            {session.cancelling && <Spinner data-icon="inline-start" />}
            {t("autotune.running.cancel")}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// --- итог --------------------------------------------------------------------------------------

function ResultRow({ row }: { row: ReportRow }) {
  const labels = useLabels()
  const after = row.after ?? null
  const method = row.fix && after?.ok
    ? fixText(row.fix, labels.strategies, labels.names)
    : after?.ok
      ? t("autotune.result.already")
      : t(`autotune.hint.${row.hint ?? "nothing_helped"}`)
  return (
    <TableRow data-testid={`autotune-result-${row.name}`} data-ok={after?.ok ? "true" : "false"}>
      <TableCell className="font-medium">{row.name}</TableCell>
      <TableCell>
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <CheckDot check={after} />
          {checkText(after)}
        </span>
      </TableCell>
      <TableCell className="whitespace-normal text-muted-foreground">{method}</TableCell>
    </TableRow>
  )
}

function ResultCard({ session }: { session: Session }) {
  const [sharing, setSharing] = useState(false)
  const report = session.report
  const rows = (report?.services ?? []).filter((r) => !r.skipped)
  const fixed = rows.filter((r) => r.fix && r.after?.ok).length
  const open = rows.filter((r) => r.after?.ok).length
  return (
    <Card data-testid="autotune-result">
      <CardHeader>
        <CardTitle>{t("autotune.result.title")}</CardTitle>
        <CardDescription data-testid="autotune-summary">
          {session.trigger === "watch" && <span className="block">{t("autotune.result.byWatch")}</span>}
          {t("autotune.result.summary", { open, total: rows.length, fixed })}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {report?.offline && (
          <Alert variant="destructive" data-testid="autotune-offline">
            <CircleAlertIcon />
            <AlertDescription>{t("autotune.offline")}</AlertDescription>
          </Alert>
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("autotune.col.service")}</TableHead>
              <TableHead>{t("autotune.col.status")}</TableHead>
              <TableHead>{t("autotune.col.method")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => <ResultRow key={row.name} row={row} />)}
          </TableBody>
        </Table>
        <div className="flex flex-wrap gap-2">
          <Button data-testid="autotune-keep" onClick={() => void act("autotune_keep", [], "autotune.keepFailed")}>
            {t("autotune.result.keep")}
          </Button>
          {fixed > 0 && (
            <Button variant="outline" data-testid="autotune-revert"
              onClick={() => void act("autotune_revert", [], "autotune.revertFailed")}>
              <RotateCcwIcon data-icon="inline-start" />
              {t("autotune.result.revert")}
            </Button>
          )}
          {rows.length > 0 && !report?.offline && (
            <Button variant="outline" data-testid="autotune-share" disabled={sharing}
              onClick={() => { setSharing(true); void share().finally(() => setSharing(false)) }}>
              {sharing ? <Spinner data-icon="inline-start" /> : <Share2Icon data-icon="inline-start" />}
              {t("autotune.result.share")}
            </Button>
          )}
        </div>
        {rows.length > 0 && !report?.offline && <FieldDescription>{t("autotune.result.shareHint")}</FieldDescription>}
      </CardContent>
    </Card>
  )
}

// Сессия закончилась без результата или её нужно довести до конца
function SessionAlert({ session, recoverable }: { session: Session; recoverable: boolean }) {
  const destructive = recoverable || session.phase === "failed"
  return (
    <Alert variant={destructive ? "destructive" : "default"} data-testid="autotune-last" data-phase={session.phase}>
      <CircleAlertIcon />
      <AlertTitle>{t(`autotune.phase.${session.phase}`)}</AlertTitle>
      {(session.error || recoverable) && (
        <AlertDescription>
          {session.error && <p>{session.error.startsWith("err.") ? t(session.error) : session.error}</p>}
          {recoverable && (
            <Button size="sm" variant="outline" className="mt-2" data-testid="autotune-recover"
              onClick={() => void act("autotune_revert", [], "autotune.revertFailed")}>
              <RotateCcwIcon data-icon="inline-start" />
              {t("autotune.result.revert")}
            </Button>
          )}
        </AlertDescription>
      )}
    </Alert>
  )
}

// --- сервисы ------------------------------------------------------------------------------------

function ServiceRow({ item, busy, session }: { item: CatalogItem; busy: boolean; session: Session | null }) {
  const diag = useStore<DiagnosisView>(DIAGNOSIS_KEY)
  const app = useStore<AppInfo>("app")
  const check = statusOf(item.name, diag?.result ?? null, session)
  return (
    <TableRow data-testid={`autotune-row-${item.name}`} data-ok={check?.ok === true ? "true" : check?.ok === false ? "false" : ""}>
      <TableCell className="font-medium">
        <Tooltip>
          <TooltipTrigger render={<span />}>{item.name}</TooltipTrigger>
          <TooltipContent className="whitespace-pre-line">
            {item.targets.length ? item.targets.join("\n") : t("autotune.noTargets")}
          </TooltipContent>
        </Tooltip>
      </TableCell>
      <TableCell data-testid={`autotune-status-${item.name}`}>
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <CheckDot check={check} />
          {checkText(check)}
        </span>
      </TableCell>
      <TableCell className="w-px">
        {check?.ok !== true && item.targets.length > 0 && (
          <Button size="sm" variant="outline" data-testid={`autotune-fix-${item.name}`}
            disabled={busy || app?.admin === false} onClick={() => startFix([item.name])}>
            <WrenchIcon data-icon="inline-start" />
            {t("autotune.fix")}
          </Button>
        )}
      </TableCell>
    </TableRow>
  )
}

function ServicesCard({ busy, session }: { busy: boolean; session: Session | null }) {
  const catalog = useStore<CatalogItem[]>(CATALOG_KEY)
  const diag = useStore<DiagnosisView>(DIAGNOSIS_KEY)
  return (
    <Card data-testid="autotune-services">
      <CardHeader>
        <CardTitle>{t("autotune.services.title")}</CardTitle>
        <CardDescription>
          {diag?.result?.offline ? t("autotune.offline") : t("autotune.services.desc")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {diag?.error && (
          <Alert variant="destructive" className="mb-3">
            <CircleAlertIcon />
            <AlertDescription>{diag.error}</AlertDescription>
          </Alert>
        )}
        {catalog && !catalog.length ? (
          <Empty className="p-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <WandSparklesIcon />
              </EmptyMedia>
              <EmptyTitle>{t("autotune.services.none")}</EmptyTitle>
              <EmptyDescription>{t("autotune.services.noneDesc")}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table data-testid="autotune-service-list">
            <TableBody>
              {(catalog ?? []).map((item) => (
                <ServiceRow key={item.name} item={item} busy={busy} session={session} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

// --- страница ------------------------------------------------------------------------------------

export function AutotunePage() {
  const st = useStore<AutotuneState>("autotune")
  const active = st?.active ?? null
  const last = st?.last ?? null
  const running = active?.phase === "running"
  const recoverable = !!active && ["interrupted", "rollback_failed", "invalid"].includes(active.phase)

  useEffect(() => {
    void loadCatalog()
    void loadNames()
    void refreshConfig()
  }, [])

  // закончилась сессия — её итог становится диагнозом: список сервисов показывает новое положение дел
  useEffect(() => absorbReport(active ?? last), [active, last])

  return (
    <Page id="autotune" title={t("nav.autotune")}>
      {recoverable && active && <SessionAlert session={active} recoverable />}
      {running && active ? <RunningCard session={active} /> : <StartCard busy={recoverable} />}
      {active?.phase === "done" && <ResultCard session={active} />}
      <MethodsCard />
      <WatchCard />
      {!active && last && ["cancelled", "failed", "reverted", "interrupted"].includes(last.phase) && (
        <SessionAlert session={last} recoverable={false} />
      )}
      <ServicesCard busy={running || recoverable} session={active?.phase === "done" ? active : null} />
    </Page>
  )
}
