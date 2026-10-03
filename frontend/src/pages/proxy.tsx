/* Прокси — sing-box по VLESS/Trojan/SS/VMess-ссылке в трёх режимах: системный прокси
   (PAC) по спискам доменов, выборочный TUN (выбранные приложения + списки) и полный TUN.
   Состояние — стор "proxy" (хаб опрашивает его всегда), своих опросов у страницы нет. */

import { useEffect, useRef, useState } from "react"
import {
  ArrowRightIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  DownloadIcon,
  FilterIcon,
  GitBranchIcon,
  ListIcon,
  NetworkIcon,
  PlusIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react"

import { LogView } from "@/components/app/log-view"
import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { TrialButton } from "@/components/app/trial"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api } from "@/lib/bridge"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { router } from "@/lib/router"
import { optimistic, store, useStore } from "@/lib/store"
import { setTransport } from "@/pages/lists-data"
import type { AppInfo } from "@/lib/types"
import { AppsPickerDialog, type RunningApp } from "@/pages/proxy-apps-dialog"

type Mode = "pac" | "split" | "tun"

interface ProxyView {
  running?: boolean
  external?: boolean
  link?: string
  parsed?: { label?: string; protocol?: string; server?: string; security?: string; transport?: string } | null
  lists?: string[]
  apps?: string[]
  domains?: number
  ips?: number
  all_lists?: string[]
  core?: { present?: boolean; version?: string }
  autostart?: boolean
  mode?: Mode
  needs_admin?: boolean
  error?: string
}

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))
const modeOf = (st: ProxyView) => st.mode || "pac"
const targets = (st: ProxyView) => (st.domains || 0) + (st.ips || 0)

// --- статус и пуск/стоп ---------------------------------------------------------

// Почему не запустить — первое, что мешает; показывается прямо в строке статуса.
function reasonOf(st: ProxyView, admin: boolean): string {
  if (st.running) return ""
  const mode = modeOf(st)
  const hasScope = mode === "tun" || targets(st) > 0 || (mode === "split" && (st.apps ?? []).length > 0)
  if (!st.core?.present) return t("proxy.reason.noCore")
  if (!st.link) return t("proxy.reason.noLink")
  if (!st.parsed) return t("proxy.reason.badLink")
  if (!hasScope) return t(mode === "split" ? "proxy.reason.noScopeSplit" : "proxy.reason.noScope")
  if (st.needs_admin && !admin) return t("proxy.reason.needAdmin")
  return ""
}

function StatusCard({ st }: { st: ProxyView }) {
  const app = useStore<AppInfo>("app")
  const [working, setWorking] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const on = !!st.running
  const reason = reasonOf(st, app?.admin !== false)

  let title
  if (st.external) title = t("proxy.status.external")
  else if (on) title = t("proxy.status.on", { server: st.parsed?.server ?? "" })
  else if (reason) title = <span className="text-warning">{reason}</span>
  else title = t("proxy.status.off")

  const toggle = async () => {
    setWorking(true)
    try {
      if (on) {
        await optimistic("proxy", { running: false }, () => api("proxy_stop"), { errorTitle: t("proxy.stop.failed") })
        notify.success(t("proxy.stop.done"))
      } else {
        await optimistic("proxy", { running: true }, () => api("proxy_start"), { errorTitle: t("proxy.start.failed") })
        notify.success(t("proxy.start.done"))
      }
    } catch {
      /* тост уже показан, стор откатен */
    } finally {
      setWorking(false)
    }
  }

  const download = async () => {
    setDownloading(true)
    try {
      const r = await api<{ restart_required?: boolean; message?: string; version?: string } | null>("proxy_download_core")
      if (r?.restart_required) notify.warning(t("proxy.core.updated"), r.message)
      else notify.success(t("proxy.core.installed"), r?.version ? t("proxy.core.version", { version: r.version }) : undefined)
    } catch (e) {
      notify.error(t("proxy.core.failed"), msg(e))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Card size="sm" data-testid="proxy-status" data-state={on ? "on" : "off"} className={on ? "ring-success/30" : undefined}>
      <CardContent className="flex flex-row flex-wrap items-center gap-x-4 gap-y-3">
        <StatusDot tone={on ? "on" : "off"} />
        <div className="min-w-0 grow truncate font-semibold" data-testid="proxy-status-title">
          {title}
        </div>
        <Field orientation="horizontal" className="w-auto">
          <FieldLabel htmlFor="proxy-autostart" className="font-normal text-muted-foreground">
            {t("proxy.autostart")}
          </FieldLabel>
          <Switch
            id="proxy-autostart"
            data-testid="proxy-autostart"
            checked={!!st.autostart}
            onCheckedChange={(v) =>
              void optimistic("proxy", { autostart: v }, () => api("proxy_set_autostart", v), {
                errorTitle: t("proxy.autostart.failed"),
              }).catch(() => {})
            }
          />
        </Field>
        {!st.core?.present && (
          <Button variant="outline" size="sm" data-testid="proxy-download" disabled={downloading} onClick={() => void download()}>
            {downloading ? <Spinner data-icon="inline-start" /> : <DownloadIcon data-icon="inline-start" />}
            {downloading ? t("proxy.core.downloading") : t("proxy.core.download")}
          </Button>
        )}
        <Button
          size="sm"
          variant={on ? "destructive" : "default"}
          data-testid="proxy-toggle"
          disabled={working || (!on && !!reason)}
          onClick={() => void toggle()}
        >
          {working && <Spinner data-icon="inline-start" />}
          {on ? t("proxy.stop") : t("proxy.start")}
        </Button>
      </CardContent>
      {st.error && (
        <CardContent>
          <Alert variant="destructive" data-testid="proxy-error">
            <CircleAlertIcon />
            <AlertDescription>{st.error}</AlertDescription>
          </Alert>
        </CardContent>
      )}
    </Card>
  )
}

// --- режим ----------------------------------------------------------------------

const MODES: { id: Mode; icon: LucideIcon; labelKey: string; hintKey: string }[] = [
  { id: "pac", icon: FilterIcon, labelKey: "proxy.mode.pac", hintKey: "proxy.mode.pac.hint" },
  { id: "split", icon: GitBranchIcon, labelKey: "proxy.mode.split", hintKey: "proxy.mode.split.hint" },
  { id: "tun", icon: NetworkIcon, labelKey: "proxy.mode.tun", hintKey: "proxy.mode.tun.hint" },
]

function ModeCard({ st }: { st: ProxyView }) {
  const mode = modeOf(st)
  const cur = MODES.find((m) => m.id === mode) ?? MODES[0]
  return (
    <Card size="sm" data-testid="proxy-mode">
      <CardHeader>
        <CardTitle>{t("proxy.mode.title")}</CardTitle>
        <CardAction><TrialButton kind="tun" target={mode === "split" ? "split" : "tun"} disabled={!st.parsed || !st.core?.present || !!st.external} label={t("trial.tryTun")} /></CardAction>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-3">
          <ToggleGroup
            variant="outline"
            spacing={1}
            className="max-w-full flex-wrap"
            aria-label={t("proxy.mode.title")}
            value={[cur.id]}
            onValueChange={(v) => {
              // повторный клик по активному режиму снимает нажатие — режим при этом не меняется
              const next = v[0] as Mode | undefined
              if (next && next !== mode)
                void optimistic("proxy", { mode: next }, () => api("proxy_set_mode", next), {
                  errorTitle: t("proxy.mode.failed"),
                }).catch(() => {})
            }}
          >
            {MODES.map((m) => (
              <ToggleGroupItem key={m.id} value={m.id} data-testid={`proxy-mode-${m.id}`}>
                <m.icon data-icon="inline-start" />
                {t(m.labelKey)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <FieldDescription data-testid="proxy-mode-hint">{t(cur.hintKey)}</FieldDescription>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

// --- ссылка сервера -------------------------------------------------------------

function ParsedInfo({ st }: { st: ProxyView }) {
  const p = st.parsed
  if (!p) {
    return (
      <FieldDescription data-testid="proxy-parsed">
        {st.link ? t("proxy.link.unparsed") : t("proxy.link.hint")}
      </FieldDescription>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="proxy-parsed">
      <Badge variant="secondary">{(p.protocol ?? "").toUpperCase()}</Badge>
      <Badge variant="outline">{(p.transport ?? "tcp").toUpperCase()}</Badge>
      <Badge variant="outline">{p.server}</Badge>
      <Badge variant="outline">{p.security === "none" ? t("proxy.link.noTls") : p.security}</Badge>
      <span className="text-muted-foreground">«{p.label}»</span>
    </div>
  )
}

function ServerCard({ st }: { st: ProxyView }) {
  // текст, пока его печатают; null — показываем то, что сохранено в сторе
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef(0)
  const latest = useRef<string | null>(null)
  const submitted = useRef<{ raw: string } | null>(null)

  const save = async (raw: string) => {
    if (submitted.current?.raw === raw) return
    const value = raw.trim()
    if (!store.pending("proxy") && value === (store.get<ProxyView>("proxy")?.link ?? "")) {
      if (latest.current === raw) {
        latest.current = null
        setDraft(null)
        setError(null)
      }
      return
    }
    const submission = { raw }
    submitted.current = submission
    try {
      await optimistic("proxy", null, () => api<Partial<ProxyView> | null>("proxy_set_link", value), { notifyError: false })
      if (latest.current === raw && submitted.current === submission) {
        latest.current = null
        setError(null)
        setDraft(null)
        notify.success(t(value ? "proxy.link.saved" : "proxy.link.cleared"))
      }
    } catch (e) {
      // тост на каждую паузу посреди набора был бы навязчив: ошибка — надписью под полем
      if (latest.current === raw && submitted.current === submission) setError(msg(e))
    } finally {
      if (submitted.current === submission) submitted.current = null
    }
  }

  const flush = () => {
    window.clearTimeout(timer.current)
    timer.current = 0
    if (latest.current !== null) void save(latest.current)
  }

  // ушли со страницы, не дождавшись паузы, — ссылка всё равно сохранится
  useEffect(
    () => () => {
      if (timer.current) {
        window.clearTimeout(timer.current)
        if (latest.current !== null) void save(latest.current)
      }
    },
    // save берёт всё нужное из стора и ref-ов, пересоздавать эффект незачем
    []
  )

  return (
    <Card size="sm" data-testid="proxy-server">
      <CardHeader>
        <CardTitle>{t("proxy.server.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-3">
          <Field data-invalid={error ? true : undefined}>
            <FieldLabel htmlFor="proxy-link" className="sr-only">
              {t("proxy.server.title")}
            </FieldLabel>
            <Textarea
              id="proxy-link"
              data-testid="proxy-link"
              className="max-h-40 min-h-20 font-mono"
              spellCheck={false}
              aria-invalid={error ? true : undefined}
              placeholder={t("proxy.link.placeholder")}
              value={draft ?? st.link ?? ""}
              onChange={(e) => {
                latest.current = e.target.value
                setDraft(e.target.value)
                window.clearTimeout(timer.current)
                timer.current = window.setTimeout(flush, 500)
              }}
              onBlur={flush}
            />
          </Field>
          {error ? (
            <Alert variant="destructive" data-testid="proxy-link-error">
              <CircleAlertIcon />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : (
            <ParsedInfo st={st} />
          )}
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

// --- приложения выборочного TUN -------------------------------------------------
// Выбор — только из запущенных программ: имя процесса берётся из системы как есть,
// без угадывания. Выбранные, но сейчас не запущенные остаются в списке.

function saveApps(selection: string[] | string) {
  const change = (value: unknown) => ({
    apps: typeof selection === "string" ? ((value as ProxyView | undefined)?.apps ?? []).filter(name => name !== selection) : selection,
  })
  return optimistic("proxy", change, () => api("proxy_set_apps", change(store.confirmed("proxy")).apps), {
    errorTitle: t("proxy.apps.failed"),
  }).catch(() => {})
}

function AppsCard({ st }: { st: ProxyView }) {
  const [picking, setPicking] = useState(false)
  const [running, setRunning] = useState<RunningApp[] | null>(null)
  const apps = st.apps ?? []

  const openPicker = async () => {
    setPicking(true)
    try {
      setRunning((await api<RunningApp[]>("proxy_apps_snapshot")) ?? [])
    } catch (e) {
      notify.error(t("proxy.apps.snapshotFailed"), msg(e))
    } finally {
      setPicking(false)
    }
  }

  return (
    <Card size="sm" data-testid="proxy-apps">
      <CardHeader>
        <CardTitle>{t("proxy.apps.title")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {apps.length > 0 && (
          <div className="flex flex-wrap gap-2" data-testid="proxy-apps-list">
            {apps.map((a) => (
              <Badge key={a} variant="outline" className="h-6 gap-1 pr-0.5">
                <span className="font-mono">{a}</span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="size-5"
                  data-testid={`proxy-app-remove-${a}`}
                  aria-label={t("proxy.apps.remove", { name: a })}
                  title={t("proxy.apps.removeTip")}
                  onClick={() => void saveApps(a)}
                >
                  <XIcon />
                </Button>
              </Badge>
            ))}
          </div>
        )}
        <div>
          <Button variant="outline" size="sm" data-testid="proxy-apps-add" disabled={picking} onClick={() => void openPicker()}>
            {picking ? <Spinner data-icon="inline-start" /> : <PlusIcon data-icon="inline-start" />}
            {t("proxy.apps.add")}
          </Button>
        </div>
        <FieldDescription>{t("proxy.apps.webview")}</FieldDescription>
      </CardContent>
      {running && (
        <AppsPickerDialog
          running={running}
          selected={apps}
          onClose={() => setRunning(null)}
          onSave={(names) => {
            setRunning(null)
            void saveApps(names)
          }}
        />
      )}
    </Card>
  )
}

// --- списки для маршрутизации через прокси --------------------------------------

function ListsCard({ st }: { st: ProxyView }) {
  const all = st.all_lists ?? []
  const sel = new Set(st.lists ?? [])

  const toggle = (name: string, on: boolean) => {
    void setTransport(name, "proxy", on, { notifyInfo: false, errorTitle: t("proxy.lists.failed") })
  }

  return (
    <Card size="sm" data-testid="proxy-lists">
      <CardHeader>
        <CardTitle>{t("proxy.lists.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {all.length === 0 ? (
          <Empty className="p-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ListIcon />
              </EmptyMedia>
              <EmptyTitle>{t("proxy.lists.empty.title")}</EmptyTitle>
              <EmptyDescription>{t("proxy.lists.empty.desc")}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button variant="outline" size="sm" data-testid="proxy-go-lists" onClick={() => router.go("lists")}>
                {t("proxy.lists.empty.go")}
                <ArrowRightIcon data-icon="inline-end" />
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <FieldSet>
            <FieldLegend className="sr-only">{t("proxy.lists.title")}</FieldLegend>
            <FieldGroup className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-4 gap-y-3">
              {all.map((name) => (
                <Field key={name} orientation="horizontal">
                  <Checkbox
                    id={`proxy-list-${name}`}
                    data-testid={`proxy-list-${name}`}
                    checked={sel.has(name)}
                    onCheckedChange={(on) => toggle(name, on)}
                  />
                  <FieldLabel htmlFor={`proxy-list-${name}`} className="font-normal">
                    {name}
                  </FieldLabel>
                </Field>
              ))}
            </FieldGroup>
          </FieldSet>
        )}
      </CardContent>
    </Card>
  )
}

function LogCard() {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card size="sm" data-testid="proxy-log">
        <CardHeader>
          <CollapsibleTrigger
            render={<Button variant="ghost" className="w-full justify-between" data-testid="proxy-log-toggle" />}
          >
            {t("proxy.log.title")}
            <ChevronDownIcon data-icon="inline-end" className={open ? "rotate-180" : undefined} />
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent>
          <CardContent>{open && <LogView method="proxy_log" />}</CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}

export function ProxyPage() {
  const st = useStore<ProxyView>("proxy")
  return (
    <Page id="proxy" title={t("nav.proxy")}>
      {!st ? (
        <div className="flex flex-col gap-4" data-testid="proxy-loading">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-36 w-full" />
        </div>
      ) : (
        <>
          <StatusCard st={st} />
          <ModeCard st={st} />
          <ServerCard st={st} />
          {modeOf(st) === "split" && <AppsCard st={st} />}
          {modeOf(st) !== "tun" && <ListsCard st={st} />}
        </>
      )}
      <LogCard />
    </Page>
  )
}
