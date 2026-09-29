/* Telegram: локальный MTProto-прокси (tg-ws-proxy). Telegram Desktop подключается к нему
   по host:port, а он заворачивает трафик в WebSocket до дата-центров. Состояние — ключ
   хаба tg, живая статистика — ленивый tgStats (только пока страница открыта). */

import { useState } from "react"
import {
  ChevronDownIcon,
  CircleAlertIcon,
  CopyIcon,
  ExternalLinkIcon,
  EyeIcon,
  EyeOffIcon,
  GaugeIcon,
  QrCodeIcon,
  RefreshCwIcon,
  SettingsIcon,
  TerminalIcon,
} from "lucide-react"

import { LogView } from "@/components/app/log-view"
import { Page } from "@/components/app/page"
import { StatusDot } from "@/components/app/status-dot"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/bridge"
import { copyText } from "@/lib/clipboard"
import { confirmDialog } from "@/lib/dialogs"
import { fmtNum } from "@/lib/format"
import { useHubWatch } from "@/lib/hub-watch"
import { t } from "@/lib/i18n"
import { notify } from "@/lib/notify"
import { optimistic, store, useStore } from "@/lib/store"
import { useDebounced, useDraft } from "@/lib/use-autosave"
import { TgAdvanced } from "@/pages/telegram/advanced"
import { TgQrDialog } from "@/pages/telegram/qr-dialog"
import type { TgFull, TgStats } from "@/pages/telegram/types"

const PENDING_KEY = "tg.pending"

async function toggleRunning(target: boolean) {
  store.set(PENDING_KEY, true)
  try {
    await optimistic("tg", { running: target }, () => api(target ? "tg_start" : "tg_stop"), {
      errorTitle: t(target ? "tg.start.failed" : "tg.stop.failed"),
    })
  } catch {
    /* тост уже показан */
  } finally {
    store.set(PENDING_KEY, false)
  }
}

async function toggleAutostart(st: TgFull, target: boolean) {
  try {
    await optimistic("tg", { autostart: target }, () => api("tg_set_config", st.host, st.port, st.secret, target), {
      errorTitle: t("tg.autostart.failed"),
    })
  } catch {
    /* тост уже показан */
  }
}

function Hero({ st, onQr }: { st: TgFull | undefined; onQr: () => void }) {
  const pending = !!useStore<boolean>(PENDING_KEY)
  const [opening, setOpening] = useState(false)
  if (!st) {
    return (
      <Card>
        <CardContent>
          <Skeleton className="h-8 w-full" />
        </CardContent>
      </Card>
    )
  }
  const on = !!st.running
  const noLink = !st.link
  return (
    <Card data-testid="tg-hero" data-state={on ? "on" : "off"} className={on ? "ring-success/30" : undefined}>
      <CardContent className="flex-row items-center gap-3">
        <StatusDot tone={on ? "on" : "off"} />
        <div className="grow truncate font-semibold" data-testid="tg-status">
          {on ? t("tg.status.on", { addr: `${st.host}:${st.port}` }) : t("tg.status.off")}
        </div>
        <Field orientation="horizontal" className="w-auto">
          <FieldLabel htmlFor="tg-autostart" className="font-normal text-muted-foreground">
            {t("tg.autostart")}
          </FieldLabel>
          <Switch
            id="tg-autostart"
            data-testid="tg-autostart"
            checked={!!st.autostart}
            onCheckedChange={(v) => void toggleAutostart(st, v)}
          />
        </Field>
        <Button
          size="sm"
          variant={on ? "destructive" : "default"}
          data-testid="tg-toggle"
          disabled={pending}
          onClick={() => void toggleRunning(!on)}
        >
          {pending && <Spinner data-icon="inline-start" />}
          {on ? t("tg.stop") : t("tg.start")}
        </Button>
      </CardContent>
      <CardContent className="flex-row flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          data-testid="tg-open-link"
          disabled={noLink || opening}
          onClick={async () => {
            setOpening(true)
            try {
              await api("tg_open_link")
            } catch (e) {
              notify.error(t("tg.openFailed"), e instanceof Error ? e.message : String(e))
            } finally {
              setOpening(false)
            }
          }}
        >
          {opening ? <Spinner data-icon="inline-start" /> : <ExternalLinkIcon data-icon="inline-start" />}
          {t("tg.openLink")}
        </Button>
        <Button variant="ghost" size="sm" data-testid="tg-copy-link" disabled={noLink} onClick={() => void copyText(st.link ?? "")}>
          <CopyIcon data-icon="inline-start" />
          {t("tg.copyLink")}
        </Button>
        <Button variant="ghost" size="sm" data-testid="tg-show-qr" disabled={noLink} onClick={onQr}>
          <QrCodeIcon data-icon="inline-start" />
          {t("tg.qr.button")}
        </Button>
      </CardContent>
      {st.error && (
        <CardContent>
          <Alert variant="destructive" data-testid="tg-error">
            <CircleAlertIcon />
            <AlertDescription>{st.error}</AlertDescription>
          </Alert>
        </CardContent>
      )}
    </Card>
  )
}

interface CfgDraft {
  host: string
  port: string
  secret: string
}

function ConnectionCard({ st }: { st: TgFull | undefined }) {
  const [secretVisible, setSecretVisible] = useState(false)
  const draft = useDraft<CfgDraft>()

  const save = async () => {
    const cur = store.get<TgFull>("tg")
    const snap = draft.read()
    if (!cur || !snap) return
    const host = snap.host ?? cur.host
    const port = Number(snap.port ?? cur.port)
    const secret = snap.secret ?? cur.secret
    try {
      await optimistic("tg", { host, port, secret }, () => api("tg_set_config", host, port, secret, !!cur.autostart), {
        errorTitle: t("tg.config.saveFailed"),
      })
      draft.clearIf(snap) // сохранилось — дальше рисуем из стора
    } catch {
      /* тост уже показан, черновик остаётся, чтобы не потерять правку */
    }
  }
  const { schedule, flush } = useDebounced(() => void save())

  const regen = async () => {
    const ok = await confirmDialog({
      title: t("tg.regen.title"),
      description: t("tg.regen.desc"),
      confirmText: t("tg.regen.confirm"),
      destructive: true,
    })
    if (!ok) return
    try {
      await optimistic("tg", {}, () => api("tg_regen_secret"), { errorTitle: t("tg.regen.failed") })
      notify.success(t("tg.regen.done"))
    } catch {
      /* тост уже показан */
    }
  }

  if (!st) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("tg.config.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    )
  }
  const d = draft.value
  const edit = (part: Partial<CfgDraft>) => {
    draft.update(part)
    schedule()
  }
  const commitOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && e.currentTarget.blur()
  return (
    <Card data-testid="tg-config" onBlur={flush}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SettingsIcon className="size-4 text-muted-foreground" />
          {t("tg.config.title")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="tg-host">{t("tg.host")}</FieldLabel>
              <FieldDescription>{t("tg.host.hint")}</FieldDescription>
            </FieldContent>
            <Input
              id="tg-host"
              data-testid="tg-host"
              className="w-[400px] flex-none"
              spellCheck={false}
              value={d?.host ?? st.host ?? ""}
              onChange={(e) => edit({ host: e.target.value })}
              onKeyDown={commitOnEnter}
            />
          </Field>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="tg-port">{t("tg.port")}</FieldLabel>
            </FieldContent>
            <Input
              id="tg-port"
              data-testid="tg-port"
              className="w-[400px] flex-none"
              type="number"
              min={1}
              max={65535}
              value={d?.port ?? String(st.port ?? "")}
              onChange={(e) => edit({ port: e.target.value })}
              onKeyDown={commitOnEnter}
            />
          </Field>
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="tg-secret">{t("tg.secret")}</FieldLabel>
            </FieldContent>
            <InputGroup className="w-[400px] flex-none">
              <InputGroupInput
                id="tg-secret"
                data-testid="tg-secret"
                className="font-mono"
                type={secretVisible ? "text" : "password"}
                spellCheck={false}
                autoComplete="off"
                value={d?.secret ?? st.secret ?? ""}
                onChange={(e) => edit({ secret: e.target.value })}
                onKeyDown={commitOnEnter}
              />
              <InputGroupAddon align="inline-end">
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <InputGroupButton
                        size="icon-xs"
                        data-testid="tg-secret-toggle"
                        aria-label={t(secretVisible ? "tg.secret.hide" : "tg.secret.show")}
                        onClick={() => setSecretVisible((v) => !v)}
                      />
                    }
                  >
                    {secretVisible ? <EyeOffIcon /> : <EyeIcon />}
                  </TooltipTrigger>
                  <TooltipContent>{t(secretVisible ? "tg.secret.hide" : "tg.secret.show")}</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <InputGroupButton
                        size="icon-xs"
                        data-testid="tg-secret-regen"
                        aria-label={t("tg.secret.regen")}
                        onClick={() => void regen()}
                      />
                    }
                  >
                    <RefreshCwIcon />
                  </TooltipTrigger>
                  <TooltipContent>{t("tg.secret.regen")}</TooltipContent>
                </Tooltip>
              </InputGroupAddon>
            </InputGroup>
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

const STAT_TILES: { key: keyof TgStats; label: string; num: boolean }[] = [
  { key: "active", label: "tg.stats.active", num: true },
  { key: "total", label: "tg.stats.total", num: true },
  { key: "ws", label: "tg.stats.ws", num: true },
  { key: "tcp_fallback", label: "tg.stats.tcp", num: true },
  { key: "cfproxy", label: "tg.stats.cf", num: true },
  { key: "up", label: "tg.stats.up", num: false },
  { key: "down", label: "tg.stats.down", num: false },
]

// статистика есть только у работающего прокси — у остановленного карточки нет вовсе
function StatsCard({ st }: { st: TgFull | undefined }) {
  const stats = useStore<TgStats>("tgStats")
  if (!st?.running) return null
  return (
    <Card data-testid="tg-stats">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GaugeIcon className="size-4 text-muted-foreground" />
          {t("tg.stats.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {STAT_TILES.map((tile) => (
          <Card key={tile.key} size="sm" data-testid={`tg-stat-${tile.key}`}>
            <CardContent>
              <span className="text-muted-foreground">{t(tile.label)}</span>
              {stats ? (
                <span className="text-lg font-semibold tabular-nums">
                  {tile.num ? fmtNum(stats[tile.key] as number) : String(stats[tile.key])}
                </span>
              ) : (
                <Skeleton className="h-7 w-16" />
              )}
            </CardContent>
          </Card>
        ))}
      </CardContent>
    </Card>
  )
}

function LogCard() {
  return (
    <Collapsible>
      <Card data-testid="tg-log-card">
        <CollapsibleTrigger
          data-testid="tg-log-toggle"
          className="group/trigger w-full text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TerminalIcon className="size-4 text-muted-foreground" />
              {t("tg.log.title")}
              <ChevronDownIcon className="ml-auto size-4 text-muted-foreground transition-transform group-data-[panel-open]/trigger:rotate-180" />
            </CardTitle>
          </CardHeader>
        </CollapsibleTrigger>
        {/* лог опрашивается, только пока панель раскрыта */}
        <CollapsibleContent>
          <CardContent>
            <LogView method="tg_log" />
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}

export function TelegramPage() {
  const st = useStore<TgFull>("tg")
  const [qrOpen, setQrOpen] = useState(false)
  useHubWatch(["tgStats"])
  return (
    <Page id="telegram" title={t("tg.title")}>
      <Hero st={st} onQr={() => setQrOpen(true)} />
      <StatsCard st={st} />
      <ConnectionCard st={st} />
      <TgAdvanced />
      <LogCard />
      <TgQrDialog open={qrOpen} onOpenChange={setQrOpen} />
    </Page>
  )
}
